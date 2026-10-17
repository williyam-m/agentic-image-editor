"""Brand guard: audit a design against the brand rules and auto-fix what is safe to fix.

Checks are measured, not guessed: contrast and logo colourway are decided by
sampling the actual composited pixels behind each element.
"""
from __future__ import annotations

from typing import Any

from PIL import Image

from ..design.spec import DesignSpec, Layer
from .kit import FONTS, PALETTE, STORY_SAFE
from .policy import LEGAL_LINE, copy_issues, is_approved_logo_color, needs_legal_line

BRAND_FAMILIES = {f["family"] for f in FONTS.values()}
_PALETTE_RGB = {name: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for name, h in PALETTE.items()}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(rgb: tuple[float, float, float]) -> float:
    def ch(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def nearest_palette(hex_color: str) -> tuple[str, str]:
    r, g, b = _rgb(hex_color)
    name = min(_PALETTE_RGB, key=lambda n: sum((x - y) ** 2 for x, y in zip(_PALETTE_RGB[n], (r, g, b))))
    return name, PALETTE[name]


def is_palette(hex_color: str | None) -> bool:
    return bool(hex_color) and hex_color.upper() in {v.upper() for v in PALETTE.values()}


def _sample(img: Image.Image, layer: Layer, k: float) -> tuple[float, float, float]:
    x0, y0 = max(0, int(layer.x * k)), max(0, int(layer.y * k))
    x1, y1 = min(img.width, int((layer.x + layer.w) * k) + 1), min(img.height, int((layer.y + layer.h) * k) + 1)
    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255)
    region = img.crop((x0, y0, x1, y1)).convert("RGB").resize((1, 1), Image.BOX)
    return region.getpixel((0, 0))  # type: ignore[return-value]


def best_text_color(bg: tuple[float, float, float]) -> str:
    return PALETTE["navy"] if contrast(_rgb(PALETTE["navy"]), bg) >= contrast(_rgb(PALETTE["white"]), bg) \
        else PALETTE["white"]


def audit(spec: DesignSpec, fix: bool = True, only: set[str] | None = None) -> list[dict[str, Any]]:
    """Run all checks; mutate ``spec`` with safe fixes when ``fix``. ``only`` limits to layer ids."""
    from ..design.compose import render

    checks: list[dict[str, Any]] = []

    def report(rule: str, status: str, detail: str, layer: Layer | None = None) -> None:
        checks.append({"rule": rule, "status": status, "detail": detail, "layer": layer.id if layer else None})

    layers = [l for l in spec.all_layers() if not only or l.id in only]
    W, H = spec.width, spec.height

    # 1) Palette — every solid colour must come from the brand palette.
    snapped = 0
    for l in layers:
        for attr in ("fill", "color", "stroke"):
            val = getattr(l, attr)
            if val and not is_palette(val) and l.role not in ("photo",):
                name, hexv = nearest_palette(val)
                if fix:
                    setattr(l, attr, hexv)
                snapped += 1
                report("palette", "fixed" if fix else "warn", f"{l.name}: {val} → brand {name} {hexv}", l)
    if not snapped:
        report("palette", "pass", "All colours are from the Xero palette")

    # 2) Typography — brand families only.
    bad_fonts = [l for l in layers if l.kind == "text" and l.font_family not in BRAND_FAMILIES]
    for l in bad_fonts:
        key = "headline" if l.role in ("headline", "stat_value", "pill_text") else "body"
        if fix:
            l.font, l.font_family, l.font_weight = key, FONTS[key]["family"], FONTS[key]["weight"]
        report("typography", "fixed" if fix else "warn", f"{l.name}: switched to {FONTS[key]['family']}", l)
    if not bad_fonts:
        report("typography", "pass", "Brand typefaces (condensed headline, clean body)")

    # 3a) Legal — offers need a "Terms apply." line; unapproved claims/competitors are flagged.
    texts_all = [l.text or "" for l in spec.all_layers() if l.kind == "text"]
    if not only:
        if needs_legal_line(texts_all):
            if fix:
                legal = _legal_layer(spec)
                if legal:
                    spec.layers.append(legal)
                    report("legal", "fixed", f"Offer detected — added “{LEGAL_LINE}”", legal)
            else:
                report("legal", "warn", f"Offer copy without “{LEGAL_LINE}”")
        else:
            report("legal", "pass", "No offer copy without terms")
        issues = copy_issues(texts_all)
        for i in issues:
            report("legal", "warn", i.detail)

    # Contrast-sensitive checks sample a render without the element being checked.
    k = 0.25
    texts = [l for l in spec.all_layers() if l.kind == "text" and (not only or l.id in only)]
    logos = [l for l in spec.all_layers() if l.role == "logo"]
    base = render(spec, k, skip={l.id for l in texts} | {l.id for l in logos})

    # 3) Logo — present once, correct colourway for what is behind it, legible size.
    if not only:
        if len(logos) == 0:
            report("logo", "warn", "No Xero wordmark on the design")
        elif len(logos) > 1:
            report("logo", "warn", f"{len(logos)} wordmarks; use one")
    for logo in logos:
        if only and logo.id not in only:
            continue
        bg = _sample(base, logo, k)
        want = best_text_color(bg)
        if want == PALETTE["white"] and logo.fill and logo.fill.upper() == PALETTE["sky"].upper() \
                and contrast(_rgb(PALETTE["sky"]), bg) >= 3:
            want = PALETTE["sky"]  # sky on navy is an approved colourway
        if (logo.fill or "").upper() != want.upper():
            if fix:
                logo.fill = want
            report("logo", "fixed" if fix else "warn",
                   f"Wordmark recoloured to {'navy' if want == PALETTE['navy'] else 'white/sky'} for its background", logo)
        else:
            report("logo", "pass", "Wordmark colourway matches its background", logo)
        if logo.w < 0.12 * W:
            report("logo", "warn", "Wordmark is small; keep it ≥12% of the width", logo)
        if not is_approved_logo_color(logo.fill):
            report("logo", "warn", "Wordmark colour is outside the approved colourways", logo)
        pad = logo.h * 0.3
        crowding = [o for o in spec.all_layers() if o.role in ("headline", "subhead", "cta", "charm", "stat", "legal")
                    and o.x < logo.x + logo.w + pad and o.x + o.w > logo.x - pad
                    and o.y < logo.y + logo.h + pad and o.y + o.h > logo.y - pad]
        if crowding:
            report("logo", "warn", f"Clear space around the wordmark is broken by {crowding[0].name}", logo)

    # 4) Contrast — WCAG AA (4.5:1) for all copy.
    worst = 99.0
    for l in texts:
        if not l.color:
            continue
        bg = _sample(base, l, k)
        ratio = contrast(_rgb(l.color), bg)
        if ratio < 4.5:
            new = best_text_color(bg)
            new_ratio = contrast(_rgb(new), bg)
            if fix and new_ratio > ratio:
                l.color = new
                ratio = new_ratio
            report("contrast", "fixed" if fix else "warn", f"{l.name}: contrast raised to {ratio:.1f}:1", l)
        worst = min(worst, ratio)
    if texts and worst >= 4.5:
        report("contrast", "pass", f"All copy ≥ 4.5:1 (lowest {worst:.1f}:1)")

    # 5) Layout — copy inside the canvas and, for stories, inside Meta safe zones.
    for l in layers:
        if l.role in ("headline", "subhead", "cta", "logo") and l.kind in ("text", "vector", "group"):
            if l.x < -1 or l.y < -1 or l.x + l.w > W + 1 or l.y + l.h > H + 1:
                report("layout", "warn", f"{l.name} extends beyond the canvas", l)
            if spec.format == "story" and (l.y < STORY_SAFE["top"] * H - 1 or l.y + l.h > (1 - STORY_SAFE["bottom"]) * H + 1):
                report("safe_zone", "warn", f"{l.name} is outside the 9:16 safe zone", l)

    # 6) Imagery — every AI image verified against the image policy.
    gen = [l for l in spec.all_layers() if l.kind == "image" and l.compliance]
    if gen and not only:
        bad = [l for l in gen if not l.compliance.get("ok")]
        if bad:
            for l in bad:
                report("imagery", "warn", f"{l.name}: {', '.join(l.compliance.get('blocking', []))}", l)
        else:
            regen = sum(max(0, (l.compliance.get("attempts") or 1) - 1) for l in gen)
            report("imagery", "pass", f"{len(gen)} AI image(s) policy-verified (no text/logos)"
                   + (f"; {regen} auto-regenerated" if regen else ""))

    # 7) Copy discipline.
    brief = spec.brief or {}
    head = brief.get("headline") or next((l.text for l in texts if l.role == "headline"), "") or ""
    if not only:
        words = len(head.split())
        report("copy", "pass" if words <= 10 else "warn",
               f"Headline {words} words" + ("" if words <= 10 else " — keep it under 10"))
        charms = [l for l in spec.all_layers() if l.role == "charm"]
        report("charms", "pass" if len(charms) <= 2 else "warn", f"{len(charms)} charm(s) (max 2)")
    return checks


def _legal_layer(spec: DesignSpec) -> Layer | None:
    """“Terms apply.” beside the CTA (or under it / bottom-left) wherever it collides with nothing."""
    from ..design import fonts
    from ..design.spec import new_id

    u = spec.width / 1080
    cta = next((l for l in spec.all_layers() if l.role == "cta"), None)
    size = round(18 * u)
    ft = fonts.fit(LEGAL_LINE, "body", 400 * u, 40 * u, size, size, 1)
    w, h = ft.width + 8, ft.height
    candidates = []
    if cta:
        candidates += [(cta.x + cta.w + 16 * u, cta.y + (cta.h - h) / 2), (cta.x, cta.y + cta.h + 10 * u)]
    candidates.append((64 * u, spec.height - 64 * u - h))
    obstacles = [l for l in spec.all_layers() if l.role in ("charm", "logo", "headline", "subhead", "stat", "bloom", "cta", "photo_group")]

    def clear(x: float, y: float) -> bool:
        if x + w > spec.width - 24 * u or y + h > spec.height - 8 * u:
            return False
        return not any(o.x < x + w and o.x + o.w > x and o.y < y + h and o.y + o.h > y for o in obstacles)

    x, y = next(((cx, cy) for cx, cy in candidates if clear(cx, cy)), candidates[0])
    f = FONTS["body"]
    return Layer(id=new_id(), name="Legal · Terms apply", kind="text", role="legal", x=x, y=y, w=w, h=h, text=ft.text,
                 font="body", font_family=f["family"], font_weight=f["weight"], font_size=ft.size,
                 line_height=f["line_height"], letter_spacing=0, color=PALETTE["navy"], align="left")


def summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    fixed = sum(c["status"] == "fixed" for c in checks)
    warns = sum(c["status"] == "warn" for c in checks)
    passed = sum(c["status"] == "pass" for c in checks)
    score = max(0, 100 - warns * 8 - fixed * 2)
    return {"score": score, "passed": passed, "fixed": fixed, "warnings": warns}
