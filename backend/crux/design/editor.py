"""Targeted layer editing: instruction + selected/pinned layers → precise canvas operations.

The LLM produces *intent* ops; :func:`compile_ops` turns them into exact,
brand-safe operations (text re-fitted with real font metrics, colours snapped
to the palette, images regenerated per layer).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .. import llm
from ..brand.guard import nearest_palette
from ..brand.policy import LEGAL_LINE, copy_issues, is_approved_logo_color, needs_legal_line
from ..brand.kit import FONTS, PALETTE, RULES_TEXT, BrandKit
from ..config import get_settings
from . import fonts
from .layouts import Box, contain
from .spec import Layer, new_id

log = logging.getLogger(__name__)

COLOR_NAMES = {**{k: v for k, v in PALETTE.items()}, "light blue": PALETTE["sky_soft"], "light_blue": PALETTE["sky_soft"],
               "dark blue": PALETTE["navy"], "off-white": PALETTE["paper"], "purple": PALETTE["lilac"]}

EDIT_SCHEMA = """Return ONLY JSON: {"message": "one friendly sentence describing what you changed",
 "ops": [ ... ]} where each op is one of:
 {"target": id, "action": "set_text", "text": "new copy"}
 {"target": id, "action": "style_text", "color": "palette name", "font_size": number|null, "weight": "bold|semibold|regular"|null}
 {"target": id, "action": "set_fill", "color": "palette name"}
 {"target": id, "action": "transform", "dx": px, "dy": px, "scale": factor, "rotation": deg, "opacity": 0-1}  (all optional)
 {"target": id, "action": "edit_image", "mode": "edit|replace", "prompt": "for edit: the change to make to the existing image; for replace: a full description of the new image"}
 {"target": id, "action": "swap_asset", "asset_id": "catalog id"}
 {"target": id, "action": "remove"}
 {"target": id, "action": "arrange", "to": "front|back"}
 {"action": "add_charm", "asset_id": "charm id" | null, "prompt": "new charm subject if no catalog charm fits" | null, "x": px, "y": px, "size": px}
 {"action": "add_text", "role": "subhead|legal|label", "text": "...", "x": px, "y": px, "w": px, "color": "palette name", "font_size": px}
Policy (enterprise, legal): the wordmark must stay (only navy, white or sky; never rotated, distorted, removed or
replaced); only palette colours; only brand fonts; no unapproved claims (guaranteed, best, #1, risk-free, free forever,
100%, cheapest, unlimited) or competitor names. If the request breaks policy, make the closest compliant change and
say so in "message".
Rules: change ONLY what the instruction asks; prefer the targeted layers; coordinates are board pixels;
colours must be palette names (navy, blue, sky, sky_soft, white, paper, mint, green, yellow, pink, lilac);
keep copy short and on-voice; image prompts must never ask for text, logos or brand marks inside the image; for photos of people use edit_image mode=edit to keep the same person unless asked to replace."""


def _resolve_color(value: str | None) -> tuple[str | None, str | None]:
    """Return (hex, note). Names map to the palette; hex snaps to the nearest brand colour."""
    if not value:
        return None, None
    v = value.strip().lower()
    if v in COLOR_NAMES:
        return COLOR_NAMES[v], None
    if v.startswith("#") and len(v) in (4, 7):
        name, hexv = nearest_palette(v if len(v) == 7 else "#" + "".join(c * 2 for c in v[1:]))
        note = None if hexv.lower() == v else f"{value} snapped to brand {name} {hexv}"
        return hexv, note
    return None, f"Ignored unknown colour '{value}'"


def plan_edit(req: dict[str, Any], kit: BrandKit) -> dict[str, Any]:
    targets = [{k: t.get(k) for k in ("id", "name", "type", "role", "x", "y", "w", "h", "text", "font_size",
                                      "color", "fill", "asset_id") if t.get(k) not in (None, "")}
               | ({"image_prompt": (t.get("image") or {}).get("prompt")} if t.get("image") else {})
               for t in req.get("targets", [])]
    context = [{k: c.get(k) for k in ("id", "name", "role", "type", "x", "y", "w", "h", "text") if c.get(k) not in (None, "")}
               for c in req.get("context", [])][:40]
    board = req.get("board") or {}
    system = "\n\n".join([
        "You are the Crux design copilot editing layers of an on-brand Xero ad in the Crux Studio editor.",
        RULES_TEXT,
        "Charm catalog (ids): " + ", ".join(f"{a.id}={a.name}" for a in kit.by_category("charm")[:120]),
        "Illustrations/devices: " + ", ".join(f"{a.id}={a.name}" for a in kit.by_category("illustration") + kit.by_category("device")),
        EDIT_SCHEMA,
    ])
    user = json.dumps({
        "instruction": req.get("instruction", ""),
        "board": {k: board.get(k) for k in ("name", "width", "height", "background")},
        "brief": {k: (board.get("brief") or {}).get(k) for k in ("headline", "cta", "archetype", "colorway")},
        "targets": targets,
        "other_layers": context,
        "pinned_point": req.get("pointer"),
    }, ensure_ascii=False)
    return llm.complete_json(system, user, tier="pro", temperature=0.4, max_tokens=1800)


def _target(req: dict[str, Any], tid: str | None) -> dict[str, Any] | None:
    pool = req.get("targets", []) + req.get("context", [])
    t = next((t for t in pool if t.get("id") == tid), None)
    if t is None and len(req.get("targets", [])) == 1 and tid is None:
        t = req["targets"][0]
    return t


def compile_ops(req: dict[str, Any], plan: dict[str, Any], kit: BrandKit) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Returns (ops, image_jobs, notes). Image jobs are generated by the workflow then merged into ops."""
    s = get_settings()
    ops: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    notes: list[str] = []
    W = float((req.get("board") or {}).get("width") or 1080)
    for raw in plan.get("ops", [])[:12]:
        action = raw.get("action")
        t = _target(req, raw.get("target"))
        if action not in ("add_charm", "add_text") and t is None:
            notes.append(f"Skipped '{action}': unknown layer")
            continue
        blocked = _policy_block(action, raw, t)
        if blocked:
            notes.append(f"Blocked by brand policy: {blocked}")
            continue
        if action == "set_text":
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            props: dict[str, Any] = {"text": text}
            role = (t.get("role") or "").lower()
            size = float(t.get("font_size") or 0) or None
            if role in ("headline", "subhead", "cta_label", "pill_text", "stat_value") and t.get("w") and size:
                key = {"headline": "headline", "subhead": "body_medium", "cta_label": "cta",
                       "pill_text": "headline", "stat_value": "headline_bold"}[role]
                max_lines = 3 if role == "headline" else (2 if role == "subhead" else 1)
                max_h = max(float(t.get("h") or 0) * 1.35, size * FONTS[key]["line_height"] * max_lines)
                if role == "headline":
                    ft = fonts.fit_headline(text, key, float(t["w"]), max_h, size, max(16.0, size * 0.6), max_lines)
                else:
                    ft = fonts.fit(text, key, float(t["w"]), max_h, size, max(16.0, size * 0.6), max_lines)
                props.update(text=ft.text, font_size=round(ft.size))
            if role == "cta_label":
                bg_op, label_geo = _fit_cta(req, t, text)
                if bg_op:
                    ops.append(bg_op)
                props.update(label_geo)
            ops.append({"op": "update", "target": t["id"], "props": props})
        elif action == "style_text":
            props = {}
            color, note = _resolve_color(raw.get("color"))
            if color:
                props["color"] = color
            if note:
                notes.append(note)
            if raw.get("font_size"):
                props["font_size"] = max(10, min(240, round(float(raw["font_size"]))))
            weight = (raw.get("weight") or "").lower()
            if weight:
                key = {"bold": "headline_bold", "semibold": "headline", "regular": "body"}.get(weight)
                if key:
                    if (t.get("role") or "") not in ("headline", "stat_value", "pill_text") and weight != "regular":
                        key = "cta"
                    props.update(font_family=FONTS[key]["family"], font_weight=FONTS[key]["weight"])
            if props:
                ops.append({"op": "update", "target": t["id"], "props": props})
        elif action == "set_fill":
            color, note = _resolve_color(raw.get("color"))
            if note:
                notes.append(note)
            if color:
                ops.append({"op": "update", "target": t["id"], "props": {"fill": color}})
        elif action == "transform":
            x, y, w, h = (float(t.get(k) or 0) for k in ("x", "y", "w", "h"))
            props = {}
            scale = float(raw.get("scale") or 1)
            if scale != 1 and w and h:
                cx, cy = x + w / 2, y + h / 2
                w, h = w * scale, h * scale
                x, y = cx - w / 2, cy - h / 2
                props.update(w=round(w, 1), h=round(h, 1))
            x += float(raw.get("dx") or 0)
            y += float(raw.get("dy") or 0)
            props.update(x=round(x, 1), y=round(y, 1))
            for k in ("rotation", "opacity"):
                if raw.get(k) is not None:
                    props[k] = float(raw[k])
            ops.append({"op": "update", "target": t["id"], "props": props})
        elif action == "edit_image":
            image = t.get("image") or {}
            mode = "edit" if raw.get("mode") != "replace" and image.get("file") else "generate"
            role = t.get("role") or "photo"
            transparent = bool(image.get("transparent")) or role in ("charm", "illustration", "cutout")
            layer = Layer(id=new_id("img"), name=t.get("name") or "Image", kind="image", role=role,
                          x=float(t.get("x") or 0), y=float(t.get("y") or 0), w=float(t.get("w") or 512),
                          h=float(t.get("h") or 512), prompt=str(raw.get("prompt") or ""),
                          transparent=transparent, fit="cover" if not transparent else "contain",
                          status="pending", gen_mode=mode, file=image.get("file"))  # type: ignore[arg-type]
            jobs.append({"target": t["id"], "layer": layer.model_dump(), "keep_geometry": not transparent})
        elif action == "swap_asset":
            asset = kit.get(raw.get("asset_id"))
            if not asset:
                notes.append(f"Unknown asset {raw.get('asset_id')}")
                continue
            box = contain(Box(float(t["x"]), float(t["y"]), float(t["w"]), float(t["h"])), asset.width, asset.height)
            geo = {"x": round(box.x, 1), "y": round(box.y, 1), "w": round(box.w, 1), "h": round(box.h, 1)}
            if asset.vector:
                ops.append({"op": "vector", "target": t["id"], "svg_url": f"{s.public_api_url}/files/brand/{asset.vector}",
                            "fill": t.get("fill") or PALETTE["blue"], "asset_id": asset.id, **geo})
            else:
                ops.append({"op": "image", "target": t["id"], "src": f"{s.public_api_url}/files/brand/{asset.file}",
                            "file": f"brand/{asset.file}", "asset_id": asset.id, "name": asset.name, **geo})
        elif action == "remove":
            ops.append({"op": "remove", "target": t["id"]})
        elif action == "arrange":
            ops.append({"op": "arrange", "target": t["id"], "to": "back" if raw.get("to") == "back" else "front"})
        elif action == "add_charm":
            size = float(raw.get("size") or 120)
            x, y = float(raw.get("x") or W * 0.7), float(raw.get("y") or 120)
            asset = kit.get(raw.get("asset_id"))
            if asset:
                b = contain(Box(x, y, size, size), asset.width, asset.height)
                layer = Layer(name=f"Charm · {asset.name}", kind="image", role="charm", x=b.x, y=b.y, w=b.w, h=b.h,
                              asset_id=asset.id, src=f"{s.public_api_url}/files/brand/{asset.file}",
                              file=f"brand/{asset.file}", transparent=True, fit="contain")
                ops.append({"op": "add", "layer": layer.model_dump(exclude_none=True)})
            elif raw.get("prompt"):
                refs = [a.id for a in kit.by_category("charm") if a.width >= 70][:3]
                layer = Layer(id=new_id("charm"), name="Charm", kind="image", role="charm", x=x, y=y, w=size, h=size,
                              prompt=str(raw["prompt"]), transparent=True, fit="contain", status="pending",
                              gen_mode="brand_style", style_refs=refs)
                jobs.append({"target": None, "layer": layer.model_dump(), "add": True})
        elif action == "add_text":
            key = "body_medium" if raw.get("role") != "label" else "cta"
            size = float(raw.get("font_size") or 28)
            w = float(raw.get("w") or W * 0.6)
            ft = fonts.fit(str(raw.get("text") or ""), key, w, size * 4, size, 14, 3)
            color, _ = _resolve_color(raw.get("color") or "navy")
            layer = Layer(name=str(raw.get("role") or "Text").title(), kind="text", role=str(raw.get("role") or "label"),
                          x=float(raw.get("x") or 64), y=float(raw.get("y") or 64), w=w, h=ft.height, text=ft.text,
                          font=key, font_family=FONTS[key]["family"], font_weight=FONTS[key]["weight"],
                          font_size=ft.size, line_height=FONTS[key]["line_height"], color=color or PALETTE["navy"])
            ops.append({"op": "add", "layer": layer.model_dump(exclude_none=True)})
    _ensure_legal_line(req, ops, notes)
    return ops, jobs, notes


def _policy_block(action: str | None, raw: dict[str, Any], t: dict[str, Any] | None) -> str | None:
    """Enterprise rules the copilot will not break, whatever the instruction says."""
    role = ((t or {}).get("role") or "").lower()
    is_logo = role == "logo" or "logo" in ((t or {}).get("name") or "").lower()
    if is_logo:
        if action in ("remove", "swap_asset", "edit_image"):
            return "the Xero wordmark is mandatory and can't be removed, replaced or redrawn"
        if action in ("set_fill", "style_text"):
            color, _ = _resolve_color(raw.get("color"))
            if color and not is_approved_logo_color(color):
                return "the wordmark may only be navy, white or sky"
        if action == "transform" and raw.get("rotation"):
            return "the wordmark can't be rotated"
    if action in ("set_text", "add_text"):
        issues = copy_issues([str(raw.get("text") or "")])
        if issues:
            return "; ".join(i.detail for i in issues)
    return None


def _ensure_legal_line(req: dict[str, Any], ops: list[dict[str, Any]], notes: list[str]) -> None:
    """New offer copy must ship with “Terms apply.” (added under the CTA when missing)."""
    pool = req.get("targets", []) + req.get("context", [])
    new_texts = [str(o["props"]["text"]) for o in ops if o["op"] == "update" and "text" in o.get("props", {})]
    new_texts += [str(o["layer"].get("text") or "") for o in ops if o["op"] == "add"]
    if not new_texts:
        return
    texts = [str(c.get("text") or "") for c in pool] + new_texts
    if not needs_legal_line(texts) or any((c.get("role") == "legal") for c in pool):
        return
    cta = next((c for c in pool if c.get("role") == "cta_bg"), None)
    W = float((req.get("board") or {}).get("width") or 1080)
    u = W / 1080
    size = round(18 * u)
    ft = fonts.fit(LEGAL_LINE, "body", 400 * u, 40 * u, size, size, 1)
    x, y = (float(cta["x"]), float(cta["y"]) + float(cta["h"]) + 10 * u) if cta else (64 * u, 64 * u)
    layer = Layer(name="Legal · Terms apply", kind="text", role="legal", x=x, y=y, w=ft.width + 8, h=ft.height,
                  text=ft.text, font="body", font_family=FONTS["body"]["family"], font_weight=FONTS["body"]["weight"],
                  font_size=ft.size, line_height=FONTS["body"]["line_height"], letter_spacing=0, color=PALETTE["navy"])
    ops.append({"op": "add", "layer": layer.model_dump(exclude_none=True)})
    notes.append(f"Offer copy detected — added “{LEGAL_LINE}” as required by legal")


def _fit_cta(req: dict[str, Any], label: dict[str, Any], text: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resize the CTA button to its new label (same metrics as the layout engine).
    Returns (button op, label geometry props)."""
    size = float(label.get("font_size") or 30)
    width = round(fonts.text_width(text, "cta", size) + 2 * 32 * size / 30 + 4, 1)
    cx = float(label.get("x", 0)) + float(label.get("w", 0)) / 2
    cy = float(label.get("y", 0)) + float(label.get("h", 0)) / 2
    pool = req.get("targets", []) + req.get("context", [])
    bg = next((c for c in pool if c.get("role") == "cta_bg"
               and float(c["x"]) <= cx <= float(c["x"]) + float(c["w"])
               and float(c["y"]) <= cy <= float(c["y"]) + float(c["h"])), None)
    if not bg:
        return None, {}
    bg_op = {"op": "update", "target": bg["id"], "props": {"w": width, "h": float(bg["h"]), "x": float(bg["x"])}}
    return bg_op, {"w": width, "h": float(label["h"]), "x": float(bg["x"])}


def merge_image_results(ops: list[dict[str, Any]], jobs: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    for job, res in zip(jobs, results):
        if not res or res.get("error"):
            continue
        if job.get("add"):
            layer = dict(job["layer"])
            layer.update(status="ready", src=res["src"], file=res["file"],
                         **{k: res[k] for k in ("x", "y", "w", "h")})
            ops.append({"op": "add", "layer": {k: v for k, v in layer.items() if v is not None}})
            continue
        op = {"op": "image", "target": job["target"], "src": res["src"], "file": res["file"],
              "prompt": job["layer"].get("prompt")}
        if not job.get("keep_geometry"):
            op.update({k: res[k] for k in ("x", "y", "w", "h")})
        ops.append(op)
