"""Brand DNA: explain everything in a design that violates the brand guidelines.

Two complementary audits run in parallel and are merged:

* **measured** (deterministic) — from the real editor layers: fonts, palette, WCAG contrast
  sampled from the exported pixels, logo colourway/size/clear space, legal copy, safe zones.
  These findings carry ready-to-apply fixes.
* **visual** (vision model) — from the exported image: catches what layers can't express
  (flattened/raster ads, imagery off-brand, text inside photos, layout and tone issues),
  each located with a normalised bounding box.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any

from PIL import Image

from .. import llm
from ..design import fonts
from .guard import best_text_color, contrast, nearest_palette, is_palette
from .kit import FONTS, PALETTE, PRIMARY_COLORS, RULES_TEXT, STORY_SAFE
from .policy import (BRAND_FONT_FAMILIES, IMAGE_RULES, LEGAL_LINE, copy_issues, is_approved_logo_color,
                     needs_legal_line)

log = logging.getLogger(__name__)

DIMENSIONS = ("color", "typography", "logo", "imagery", "layout", "copy")
SEVERITY_COST = {"high": 18, "medium": 9, "low": 4}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _ring_color(img: Image.Image, x: float, y: float, w: float, h: float, pad: int = 8) -> tuple[float, float, float]:
    """Average colour of a thin band just outside a box (the background behind a text)."""
    W, H = img.size
    rgb = img.convert("RGB")
    samples = []
    for (x0, y0, x1, y1) in ((x - pad, y - pad, x + w + pad, y), (x - pad, y + h, x + w + pad, y + h + pad),
                             (x - pad, y, x, y + h), (x + w, y, x + w + pad, y + h)):
        box = (max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1)))
        if box[2] > box[0] and box[3] > box[1]:
            samples.append(rgb.crop(box).resize((1, 1), Image.BOX).getpixel((0, 0)))
    if not samples:
        return (255, 255, 255)
    return tuple(sum(c[i] for c in samples) / len(samples) for i in range(3))  # type: ignore[return-value]


def _finding(dimension: str, severity: str, issue: str, suggestion: str, *, layer: dict[str, Any] | None = None,
             box: list[float] | None = None, fix: dict[str, Any] | None = None, source: str = "measured") -> dict[str, Any]:
    return {"dimension": dimension, "severity": severity, "issue": issue, "suggestion": suggestion,
            "layer_id": (layer or {}).get("id"), "layer_name": (layer or {}).get("name"), "box": box,
            "fix": fix, "source": source}


STRUCTURAL_ROLES = ("background", "card", "cta_bg", "pill_bg", "stat_bg", "wave", "bloom")
PRIMARY_HEX = {PALETTE[k] for k in PRIMARY_COLORS}


def _nearest(hex_color: str, names: tuple[str, ...]) -> tuple[str, str]:
    r, g, b = _rgb(hex_color)
    name = min(names, key=lambda n: sum((x - y) ** 2 for x, y in zip(_rgb(PALETTE[n]), (r, g, b))))
    return name, PALETTE[name]


def _contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    cx = float(inner.get("x", 0)) + float(inner.get("w", 0)) / 2
    cy = float(inner.get("y", 0)) + float(inner.get("h", 0)) / 2
    return (float(outer.get("x", 0)) <= cx <= float(outer.get("x", 0)) + float(outer.get("w", 0))
            and float(outer.get("y", 0)) <= cy <= float(outer.get("y", 0)) + float(outer.get("h", 0)))


def rewrite_copy(texts: list[dict[str, Any]], issues: list[str]) -> dict[str, str]:
    """Compliant rewrites (same meaning and length) for copy that breaks the legal policy."""
    system = ("You are Xero's senior copywriter working with legal. Rewrite copy so it complies, keeping meaning, "
              "tone and length. Return JSON only.")
    user = ("Policy problems: " + "; ".join(issues) + ". Never use: guaranteed, best, #1, number one, risk-free, "
            "free forever, 100%, cheapest, unlimited, competitor names.\nTexts: "
            + json.dumps([{"id": t["id"], "text": t.get("text")} for t in texts], ensure_ascii=False)
            + '\nReturn {"rewrites": [{"id": ..., "text": ...}]} only for texts that need changing.')
    try:
        out = llm.complete_json(system, user, tier="pro", temperature=0.4, max_tokens=800, attempts=2)
    except Exception as e:  # noqa: BLE001
        log.warning("copy rewrite failed: %s", e)
        return {}
    return {r["id"]: str(r["text"]) for r in out.get("rewrites", []) if r.get("id") and r.get("text")
            and not copy_issues([str(r["text"])])}


def layer_audit(board: dict[str, Any], layers: list[dict[str, Any]], image: Image.Image | None) -> list[dict[str, Any]]:
    """Deterministic findings with *coherent* fixes: structural fills snap to primary colours first,
    then text/logo colours are chosen against the background they will actually sit on."""
    W = float(board.get("width") or (image.width if image else 1080))
    H = float(board.get("height") or (image.height if image else 1350))
    sx = (image.width / W) if image else 1.0
    out: list[dict[str, Any]] = []

    def norm(l: dict[str, Any]) -> list[float]:
        return [round(float(l.get("x", 0)) / W, 4), round(float(l.get("y", 0)) / H, 4),
                round(float(l.get("w", 0)) / W, 4), round(float(l.get("h", 0)) / H, 4)]

    is_logo = lambda l: l.get("role") == "logo" or "logo" in str(l.get("name", "")).lower()  # noqa: E731
    # The wordmark is audited as one unit: drop the vector paths nested inside it.
    logo_ids = {l["id"] for l in layers if is_logo(l)}
    changed = True
    while changed:
        inner = {l["id"] for l in layers if l.get("parent_id") in logo_ids} - logo_ids
        changed = bool(inner)
        logo_ids |= inner
    layers = [l for l in layers if is_logo(l) or l["id"] not in logo_ids]
    texts = [l for l in layers if l.get("type") == "text"]

    def fitted(l: dict[str, Any], text: str, key: str) -> dict[str, Any]:
        """Font size so ``text`` fits the layer's box in brand font ``key`` (real metrics)."""
        size = float(l.get("font_size") or 32)
        w, h = float(l.get("w") or 400), float(l.get("h") or size * 1.2)
        lines = 3 if key.startswith("headline") else 2
        ft = (fonts.fit_headline if key.startswith("headline") else fonts.fit)(
            text, key, w, max(h, size * FONTS[key]["line_height"]), size, max(14.0, size * 0.5), lines)
        return {"text": ft.text, "font_size": round(ft.size)}

    def brand_key(l: dict[str, Any]) -> str:
        fam = l.get("font_family")
        if fam == FONTS["headline"]["family"] or (fam not in BRAND_FONT_FAMILIES and (l.get("font_size") or 0) >= 48):
            return "headline"
        return "body"

    # 1) Fills (non-text, non-logo). Large/structural shapes: primary palette only.
    fixed_fill: dict[str, str] = {}
    board_bg = board.get("background")
    for l in layers:
        val = l.get("fill")
        if l.get("type") in ("text", "image") or is_logo(l) or not (isinstance(val, str) and val.startswith("#")):
            continue
        area = float(l.get("w", 0)) * float(l.get("h", 0)) / max(W * H, 1)
        structural = l.get("role") in STRUCTURAL_ROLES or area > 0.12 or l.get("type") == "rect" and area > 0.04
        allowed = PRIMARY_HEX if structural else {v for v in PALETTE.values()}
        if val.upper() not in {a.upper() for a in allowed}:
            name, hexv = _nearest(val, PRIMARY_COLORS if structural else tuple(PALETTE))
            fixed_fill[l["id"]] = hexv
            why = "an accent colour on a large shape" if is_palette(val) else "off-palette"
            out.append(_finding("color", "high" if structural else "medium", f"“{l.get('name')}” is {val} — {why}",
                                f"Use brand {name.replace('_', ' ')} {hexv}", layer=l, box=norm(l),
                                fix={"op": "update", "target": l["id"], "props": {"fill": hexv}}))

    def bg_under(t: dict[str, Any]) -> tuple[float, float, float]:
        """Colour directly behind ``t`` after fills are fixed (falls back to sampled pixels)."""
        idx = layers.index(t)
        for o in reversed(layers[:idx]):
            if o.get("type") == "text" or is_logo(o) or not _contains(o, t):
                continue
            col = fixed_fill.get(o["id"]) or o.get("fill")
            if isinstance(col, str) and col.startswith("#") and o.get("type") != "image":
                return _rgb(col)
            if image and (o.get("type") == "image" or o.get("image")):
                return _ring_color(image, float(t["x"]) * sx, float(t["y"]) * sx, float(t["w"]) * sx, float(t["h"]) * sx)
        if isinstance(board_bg, str) and board_bg.startswith("#"):
            return _rgb(fixed_fill.get(board.get("id", ""), board_bg))
        return _ring_color(image, float(t["x"]) * sx, float(t["y"]) * sx, float(t["w"]) * sx, float(t["h"]) * sx) \
            if image else (255, 255, 255)

    # Board background itself
    if isinstance(board_bg, str) and board_bg.startswith("#") and board_bg.upper() not in {h.upper() for h in PRIMARY_HEX}:
        name, hexv = _nearest(board_bg, PRIMARY_COLORS)
        fixed_fill[board.get("id", "")] = hexv
        out.append(_finding("color", "high", f"Board background {board_bg} is not a primary brand colour",
                            f"Use brand {name.replace('_', ' ')} {hexv}", box=[0, 0, 1, 1],
                            fix={"op": "update", "target": board.get("id"), "props": {"fill": hexv}}))

    # 2) Typography
    for l in texts:
        fam = l.get("font_family")
        if fam and fam not in BRAND_FONT_FAMILIES:
            key = "headline" if (l.get("font_size") or 0) >= 48 else "body"
            out.append(_finding("typography", "high", f"“{l.get('name')}” uses {fam}, not a brand typeface",
                                f"Use {FONTS[key]['family']} ({'headlines' if key == 'headline' else 'body copy'})",
                                layer=l, box=norm(l),
                                fix={"op": "update", "target": l["id"],
                                     "props": {"font_family": FONTS[key]["family"], "font_weight": FONTS[key]["weight"],
                                               **fitted(l, str(l.get("text") or ""), key)}}))

    # 3) Text colour: primary palette + ≥4.5:1 against the (fixed) background beneath it
    for l in texts:
        col = l.get("color")
        if not (isinstance(col, str) and col.startswith("#")):
            continue
        bg = bg_under(l)
        ratio = contrast(_rgb(col), bg)
        on_palette = col.upper() in {h.upper() for h in PRIMARY_HEX}
        if ratio < 4.5 or not on_palette:
            better = best_text_color(bg)
            issue = (f"“{l.get('name')}” contrast is {ratio:.1f}:1 (needs 4.5:1)" if ratio < 4.5
                     else f"“{l.get('name')}” uses {col}, not a brand text colour")
            out.append(_finding("color", "high" if ratio < 4.5 else "medium", issue,
                                f"Use {'navy' if better == PALETTE['navy'] else 'white'} text on this background",
                                layer=l, box=norm(l), fix={"op": "update", "target": l["id"], "props": {"color": better}}))

    # 4) Logo
    logos = [l for l in layers if is_logo(l)]
    if not logos:
        out.append(_finding("logo", "high", "No Xero wordmark layer found",
                            "Add the official wordmark (Brand kit → Logo)", box=None))
    for lg in logos:
        fill = lg.get("fill")
        bg = bg_under(lg)
        want = best_text_color(bg)
        ok_color = is_approved_logo_color(fill) and contrast(_rgb(fill), bg) >= 3 if fill else True
        if not ok_color:
            out.append(_finding("logo", "high", f"Wordmark is {fill} — outside approved colourways or unreadable",
                                "Navy on light backgrounds; white or sky on navy/blue", layer=lg, box=norm(lg),
                                fix={"op": "update", "target": lg["id"], "props": {"fill": want}}))
        if float(lg.get("w", 0)) < 0.12 * W:
            grow = 0.18 * W / max(float(lg.get("w", 1)), 1)
            nw, nh = float(lg["w"]) * grow, float(lg["h"]) * grow
            out.append(_finding("logo", "medium", "Wordmark is too small to read",
                                "Scale the wordmark to ~18% of the canvas width", layer=lg, box=norm(lg),
                                fix={"op": "update", "target": lg["id"], "props": {
                                    "w": round(nw, 1), "h": round(nh, 1),
                                    "x": round(min(float(lg["x"]), W - nw - 0.06 * W), 1),
                                    "y": round(min(float(lg["y"]), H - nh - 0.05 * H), 1)}}))
        pad = float(lg.get("h", 0)) * 0.3
        for o in layers:
            if o is lg or o.get("role") not in ("headline", "subhead", "cta", "charm", "stat", "legal"):
                continue
            if float(o["x"]) < float(lg["x"]) + float(lg["w"]) + pad and float(o["x"]) + float(o["w"]) > float(lg["x"]) - pad and \
                    float(o["y"]) < float(lg["y"]) + float(lg["h"]) + pad and float(o["y"]) + float(o["h"]) > float(lg["y"]) - pad:
                out.append(_finding("logo", "medium", f"“{o.get('name')}” crowds the wordmark's clear space",
                                    "Keep clear space of ~⅓ the wordmark height on every side", layer=o, box=norm(o)))
                break

    # 5) Copy & legal (with compliant AI rewrites as fixes)
    all_text = [str(l.get("text") or "") for l in texts]
    bad = [(l, copy_issues([str(l.get("text") or "")])) for l in texts]
    bad = [(l, i) for l, i in bad if i]
    rewrites = rewrite_copy([l for l, _ in bad], [x.detail for _, i in bad for x in i]) if bad else {}
    for l, issues in bad:
        new = rewrites.get(l["id"])
        out.append(_finding("copy", "high", f"“{l.get('name')}”: " + "; ".join(i.detail for i in issues),
                            f"Rewrite: “{new}”" if new else "Remove the claim or get legal sign-off",
                            layer=l, box=norm(l),
                            fix={"op": "update", "target": l["id"], "props": fitted(l, new, brand_key(l))} if new else None))
    if needs_legal_line(all_text) and not any(l.get("role") == "legal" for l in layers):
        cta = next((l for l in layers if l.get("role") == "cta_bg"), None)
        u = W / 1080
        x, y = (float(cta["x"]), float(cta["y"]) + float(cta["h"]) + 10 * u) if cta else (64 * u, H - 90 * u)
        probe = {"x": x, "y": y, "w": 140 * u, "h": 24 * u}
        legal_color = best_text_color(_bg_at(layers, fixed_fill, probe, board, image, sx))
        out.append(_finding("copy", "high", "Offer copy without “Terms apply.”",
                            f"Add “{LEGAL_LINE}” near the offer", box=[x / W, y / H, 0.12, 0.02],
                            fix={"op": "add", "layer": {
                                "id": "legal_dna", "name": "Legal · Terms apply", "kind": "text", "role": "legal",
                                "x": x, "y": y, "w": 140 * u, "h": 24 * u, "text": LEGAL_LINE, "font": "body",
                                "font_family": FONTS["body"]["family"], "font_weight": FONTS["body"]["weight"],
                                "font_size": round(18 * u), "line_height": 1.3, "letter_spacing": 0,
                                "color": legal_color}}))
    for l in texts:
        if l.get("role") == "headline" and len(str(l.get("text") or "").split()) > 10:
            out.append(_finding("copy", "low", "Headline is longer than 10 words",
                                "Cut to a punchy 2–8 word line (e.g. “Data in. Doubt out.”)", layer=l, box=norm(l)))
    # 6) Layout: story safe zones (9:16 only)
    if abs(W / max(H, 1) - 9 / 16) < 0.02:
        for l in layers:
            if l.get("type") == "text" or is_logo(l) or l.get("role") == "cta":
                top, bottom = float(l["y"]) / H, (float(l["y"]) + float(l["h"])) / H
                if top < STORY_SAFE["top"] or bottom > 1 - STORY_SAFE["bottom"]:
                    out.append(_finding("layout", "medium", f"“{l.get('name')}” sits in the 9:16 UI-overlay zone",
                                        "Keep copy and logo between 14% from the top and 35% from the bottom",
                                        layer=l, box=norm(l)))
    return out


def _bg_at(layers: list[dict[str, Any]], fixed_fill: dict[str, str], probe: dict[str, Any], board: dict[str, Any],
           image: Image.Image | None, sx: float) -> tuple[float, float, float]:
    for o in reversed(layers):
        if o.get("type") == "text" or not _contains(o, probe):
            continue
        col = fixed_fill.get(o["id"]) or o.get("fill")
        if isinstance(col, str) and col.startswith("#") and o.get("type") != "image":
            return _rgb(col)
        break
    bg = fixed_fill.get(board.get("id", "")) or board.get("background")
    if isinstance(bg, str) and bg.startswith("#"):
        return _rgb(bg)
    return _ring_color(image, probe["x"] * sx, probe["y"] * sx, probe["w"] * sx, probe["h"] * sx) if image else (255, 255, 255)


def layer_facts(board: dict[str, Any], layers: list[dict[str, Any]], measured: list[dict[str, Any]] | None = None) -> str:
    """Ground truth from the file so the vision model doesn't second-guess what is measurable."""
    parts = []
    bg = board.get("background")
    if isinstance(bg, str) and bg.startswith("#"):
        name = next((k for k, v in PALETTE.items() if v.upper() == bg.upper()), None)
        parts.append(f"Board background is {bg}" + (f" (brand {name.replace('_', ' ')}, approved)." if name else "."))
    fams = sorted({f"{l.get('font_family')} {l.get('font_weight') or ''}".strip() for l in layers
                   if l.get("type") == "text" and l.get("font_family")})
    if fams:
        parts.append("Typefaces used: " + ", ".join(fams) + ". Barlow Condensed 700 IS the brand's condensed bold "
                     "headline face; Barlow is the body face.")
    logos = [l for l in layers if l.get("role") == "logo" or "logo" in str(l.get("name", "")).lower()]
    if logos:
        lg = logos[0]
        under = next((o for o in reversed(layers[:layers.index(lg)]) if o.get("type") != "text"
                      and o.get("role") not in (None, "logo") and _contains(o, lg)), None)
        backing = f" on a solid {under.get('fill')} {under.get('role')} shape" if under and under.get("fill") else ""
        parts.append(f"The official Xero wordmark is present ({lg.get('fill') or 'vector'}){backing}.")
    if measured is not None and not any(f["dimension"] == "color" for f in measured):
        parts.append("Every fill and text colour was measured and is an approved brand palette colour with ≥4.5:1 contrast.")
    return " ".join(parts)


def vision_audit(png: bytes, width: int | None = None, height: int | None = None, facts: str = "") -> dict[str, Any]:
    system = ("You are Xero's brand guardian auditing a design for an enterprise brand-compliance review. "
              "Be specific, literal and actionable. Return JSON only.")
    context = [RULES_TEXT, "Imagery policy: " + IMAGE_RULES,
               "Accent colours (mint, green, yellow, pink, lilac) are only for charms/small details."]
    if width and height:
        context.append(f"Canvas: {width}x{height}px.")
        if abs(width / height - 9 / 16) > 0.02:
            context.append("This is NOT a 9:16 story: do not apply story safe zones.")
    if facts:
        context.append(f"Known facts (trust these over visual impression): {facts}")
    instructions = (
        "Audit the attached design. List EVERY guideline violation you can see (colour, typography, logo, "
        "imagery, layout, copy). For each give a normalised bounding box [x, y, w, h] (0-1) of where it is. "
        "Also score each DNA dimension 0-100 (100 = perfectly on-brand). Return JSON: "
        "{\"violations\": [{\"dimension\": \"color|typography|logo|imagery|layout|copy\", "
        "\"severity\": \"high|medium|low\", \"issue\": \"max 16 words\", \"suggestion\": \"max 18 words\", "
        "\"box\": [x, y, w, h]}], \"scores\": {\"color\": n, \"typography\": n, \"logo\": n, \"imagery\": n, "
        "\"layout\": n, \"copy\": n}, \"strengths\": [max 3 short items], \"summary\": \"max 25 words\"}")
    user = [
        {"type": "text", "text": "\n".join(context) + "\n\n" + instructions},
        llm.image_part(png),
    ]
    out = llm.complete_json(system, user, tier="flash", temperature=0.1, max_tokens=2500)
    vios = []
    for v in out.get("violations", [])[:14]:
        dim = v.get("dimension") if v.get("dimension") in DIMENSIONS else "layout"
        box = v.get("box") if isinstance(v.get("box"), list) and len(v.get("box")) == 4 else None
        if box:
            box = [max(0.0, min(1.0, float(b))) for b in box]
        vios.append(_finding(dim, v.get("severity") if v.get("severity") in SEVERITY_COST else "medium",
                             str(v.get("issue", ""))[:160], str(v.get("suggestion", ""))[:180], box=box,
                             source="visual"))
    return {"violations": vios, "scores": out.get("scores") or {}, "strengths": out.get("strengths", [])[:3],
            "summary": str(out.get("summary", ""))[:240]}


def _iou(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def merge(measured: list[dict[str, Any]], visual: dict[str, Any]) -> dict[str, Any]:
    # Measured findings are precise and fixable; drop visual duplicates of the same problem.
    vis = [v for v in visual.get("violations", [])
           if not any(m["dimension"] == v["dimension"] and (_iou(m.get("box"), v.get("box")) > 0.25
                      or (m.get("box") == [0, 0, 1, 1] and v["dimension"] == "color" and "background" in v["issue"].lower()))
                      for m in measured)]
    findings = measured + vis
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3), f["source"] != "measured"))
    scores: dict[str, int] = {}
    vscores = visual.get("scores") or {}
    for d in DIMENSIONS:
        cost = sum(SEVERITY_COST[f["severity"]] for f in measured if f["dimension"] == d)
        v = vscores.get(d)
        base = int(v) if isinstance(v, (int, float)) else 100
        scores[d] = max(0, min(100, min(base, 100 - cost)))
    weights = {"color": 1.2, "typography": 1.0, "logo": 1.3, "imagery": 1.0, "layout": 0.8, "copy": 1.2}
    overall = round(sum(scores[d] * weights[d] for d in DIMENSIONS) / sum(weights.values()))
    for i, f in enumerate(findings):
        f["id"] = f"v{i + 1}"
    return {"score": overall, "scores": scores, "findings": findings,
            "fixable": sum(1 for f in findings if f.get("fix")), "strengths": visual.get("strengths", []),
            "summary": visual.get("summary", ""),
            "verdict": "On-brand" if overall >= 85 and not any(f["severity"] == "high" for f in findings)
            else "Needs fixes" if overall >= 60 else "Off-brand"}


def load_png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")
