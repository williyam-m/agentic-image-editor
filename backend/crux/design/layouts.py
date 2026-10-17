"""Deterministic layout engine: Brief → layered DesignSpec.

The LLM chooses *what* to say and show; this module decides *where*, using
measured text (real font files), brand spacing and the five layout archetypes
distilled from the reference ads. Doing geometry in code (not in the LLM) is
what keeps output consistently clean: no overlaps, no overflowing text, safe
zones respected.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..brand.kit import COLORWAYS, FONTS, FORMATS, PALETTE, STORY_SAFE, Asset, BrandKit
from ..config import get_settings
from . import fonts
from .brief import Brief
from .spec import DesignSpec, Layer, new_id

# Blooms with a solid centre (a logo or photo reads well on/in them).
# Full-bodied blooms: a wordmark or a face reads well inside them.
SOLID_BLOOMS = ("harmony", "peace")


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def right(self) -> float:
        return self.x + self.w


def contain(box: Box, iw: float, ih: float, anchor: str = "center") -> Box:
    s = min(box.w / iw, box.h / ih)
    w, h = iw * s, ih * s
    x = box.x + (box.w - w) / 2
    y = {"bottom": box.bottom - h, "top": box.y}.get(anchor, box.y + (box.h - h) / 2)
    return Box(x, y, w, h)


def cover(box: Box, iw: float, ih: float, anchor: str = "center") -> Box:
    s = max(box.w / iw, box.h / ih)
    w, h = iw * s, ih * s
    x = box.x + (box.w - w) / 2
    y = {"bottom": box.bottom - h, "top": box.y}.get(anchor, box.y + (box.h - h) / 2)
    return Box(x, y, w, h)


def place_image(layer: Layer, iw: int, ih: int) -> None:
    """Final geometry for a generated image once its pixel size is known."""
    region = Box(layer.x, layer.y, layer.w, layer.h)
    b = cover(region, iw, ih, layer.anchor) if layer.fit == "cover" else contain(region, iw, ih, layer.anchor)
    layer.x, layer.y, layer.w, layer.h = round(b.x, 1), round(b.y, 1), round(b.w, 1), round(b.h, 1)


class Builder:
    def __init__(self, brief: Brief, kit: BrandKit, variant: int = 0):
        fmt = FORMATS[brief.format]
        self.brief, self.kit = brief, kit
        self.W, self.H = fmt["w"], fmt["h"]
        self.wide = self.W > self.H * 1.3
        self.story = brief.format == "story"
        self.u = min(self.W / 1080, self.H * 1.6 / 1080)
        self.cw = COLORWAYS[brief.colorway]
        self.rng = random.Random(f"{brief.headline}-{variant}")
        self.m = 64 * self.u if not self.wide else 48 * self.u
        self.top = STORY_SAFE["top"] * self.H if self.story else self.m
        self.text_bottom = (1 - STORY_SAFE["bottom"]) * self.H if self.story else self.H - self.m
        self.layers: list[Layer] = []
        self.api = get_settings().public_api_url

    # ---- primitives ---------------------------------------------------------------
    def add(self, layer: Layer) -> Layer:
        self.layers.append(layer)
        return layer

    def rect(self, name: str, role: str, b: Box, fill: str, radius: float = 0, shadow: bool = False) -> Layer:
        return Layer(name=name, kind="rect", role=role, x=b.x, y=b.y, w=b.w, h=b.h, fill=fill,
                     radius=radius, shadow=shadow)

    def text(self, name: str, role: str, ft: fonts.FittedText, x: float, y: float, w: float, color: str,
             key: str, align: str = "left") -> Layer:
        f = FONTS[key]
        return Layer(name=name, kind="text", role=role, x=x, y=y, w=w, h=ft.height, text=ft.text, font=key,
                     font_family=f["family"], font_weight=f["weight"], font_size=ft.size,
                     line_height=f["line_height"], letter_spacing=f["letter_spacing"], color=color,
                     align=align)  # type: ignore[arg-type]

    def vector(self, name: str, role: str, asset: Asset, b: Box, fill: str, keep_aspect: bool = True) -> Layer:
        if keep_aspect:
            b = contain(b, asset.width, asset.height)
        return Layer(name=name, kind="vector", role=role, x=b.x, y=b.y, w=b.w, h=b.h, fill=fill,
                     asset_id=asset.id, svg_url=f"{self.api}/files/brand/{asset.vector}")

    def asset_image(self, name: str, role: str, asset: Asset, region: Box, anchor: str = "center",
                    fit: str = "contain") -> Layer:
        b = contain(region, asset.width, asset.height, anchor) if fit == "contain" else \
            cover(region, asset.width, asset.height, anchor)
        return Layer(name=name, kind="image", role=role, x=b.x, y=b.y, w=b.w, h=b.h, asset_id=asset.id,
                     src=f"{self.api}/files/brand/{asset.file}", file=f"brand/{asset.file}",
                     transparent=asset.has_alpha, fit=fit, anchor=anchor)  # type: ignore[arg-type]

    def gen_image(self, name: str, role: str, region: Box, prompt: str, *, transparent: bool,
                  fit: str, anchor: str = "center", mode: str = "generate",
                  style_refs: list[str] | None = None) -> Layer:
        return Layer(name=name, kind="image", role=role, x=region.x, y=region.y, w=region.w, h=region.h,
                     prompt=prompt, transparent=transparent, fit=fit, anchor=anchor,  # type: ignore[arg-type]
                     status="pending", gen_mode=mode, style_refs=style_refs)  # type: ignore[arg-type]

    def group(self, name: str, role: str, children: list[Layer], kind: str = "group") -> Layer:
        if kind == "mask":  # children[0] is the mask shape and defines the bounds
            m = children[0]
            return Layer(name=name, kind="mask", role=role, x=m.x, y=m.y, w=m.w, h=m.h, children=children)
        x0 = min(c.x for c in children)
        y0 = min(c.y for c in children)
        x1 = max(c.x + c.w for c in children)
        y1 = max(c.y + c.h for c in children)
        return Layer(name=name, kind="group", role=role, x=x0, y=y0, w=x1 - x0, h=y1 - y0,  # type: ignore[arg-type]
                     children=children)

    # ---- brand components -----------------------------------------------------------
    def logo(self, x: float, y: float, width: float, color: str | None = None, align: str = "left") -> Layer | None:
        asset = self.kit.logo()
        if not asset:
            return None
        h = width * asset.height / asset.width
        if align == "right":
            x -= width
        return self.add(self.vector("Xero logo", "logo", asset, Box(x, y, width, h), color or self.cw["logo"]))

    def mask_body_top(self, asset: Asset, threshold: float = 0.45) -> float:
        """Fraction of the shape's height where its rows first become substantially filled."""
        import numpy as np
        from PIL import Image

        if not asset.mask:
            return 0.0
        m = np.asarray(Image.open(get_settings().brand_dir / asset.mask).convert("L").resize((64, 64))) / 255.0
        rows = m.mean(axis=1)
        full = rows.max() or 1.0
        idx = next((i for i, v in enumerate(rows) if v >= threshold * full), 0)
        return idx / 64

    def spot_in_mask(self, asset: Asset, box: Box, w: float, h: float) -> tuple[float, float]:
        """Top-left of the w×h spot inside ``asset``'s shape (drawn at ``box``) that the shape covers best."""
        import numpy as np
        from PIL import Image

        if not asset.mask:
            return box.x + (box.w - w) / 2, box.y + (box.h - h) / 2
        k = 4.0  # work at 1/4 resolution
        mw, mh = max(1, int(box.w / k)), max(1, int(box.h / k))
        m = np.asarray(Image.open(get_settings().brand_dir / asset.mask).convert("L").resize((mw, mh))) / 255.0
        # Only consider spots inside the canvas.
        bw, bh = max(1, int(w / k)), max(1, int(h / k))
        ii = np.pad(m.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        best, best_xy = -1.0, (box.x + (box.w - w) / 2, box.y + (box.h - h) / 2)
        cx, cy = mw / 2, mh / 2
        for y in range(0, max(1, mh - bh + 1)):
            for x in range(0, max(1, mw - bw + 1)):
                ax, ay = box.x + x * k, box.y + y * k
                if ax < self.m * 0.5 or ax + w > self.W - self.m * 0.5 or ay + h > self.H:
                    continue
                cov = (ii[y + bh, x + bw] - ii[y, x + bw] - ii[y + bh, x] + ii[y, x]) / (bw * bh)
                score = cov - 0.0005 * ((x + bw / 2 - cx) ** 2 + (y + bh / 2 - cy) ** 2) ** 0.5
                if score > best:
                    best, best_xy = score, (ax, ay)
        return best_xy

    def logo_size(self) -> tuple[float, float]:
        asset = self.kit.logo()
        w = (0.2 if not self.wide else 0.13) * self.W
        return w, (w * asset.height / asset.width if asset else w * 0.29)

    def cta(self, x: float, y: float, bg: str | None = None, fg: str | None = None, size: float | None = None) -> Layer:
        size = size or 30 * self.u
        label = self.brief.cta.strip() or "Find out more"
        ft = fonts.fit(label, "cta", 2000, 400, size, size, 1)
        pad_x, h = 32 * self.u, 72 * self.u
        w = ft.width + 2 * pad_x + 4
        box = self.rect("CTA button", "cta_bg", Box(x, y, w, h), bg or self.cw["cta_bg"], radius=10 * self.u)
        label_layer = self.text("CTA label", "cta_label", ft, x, y + (h - ft.height) / 2, w,
                                fg or self.cw["cta_text"], "cta", "center")
        return self.add(self.group("CTA", "cta", [box, label_layer]))

    def headline(self, x: float, y: float, w: float, max_h: float, color: str, max_size: float,
                 align: str = "left", max_lines: int = 3) -> Layer:
        key = "headline"
        ft = fonts.fit_headline(self.brief.headline, key, w, max_h, max_size, 44 * self.u, max_lines)
        return self.add(self.text("Headline", "headline", ft, x, y, w, color, key, align))

    def subhead(self, x: float, y: float, w: float, color: str, align: str = "left") -> Layer | None:
        if not self.brief.subhead:
            return None
        ft = fonts.fit(self.brief.subhead, "body_medium", w, 140 * self.u, 32 * self.u, 22 * self.u, 2)
        return self.add(self.text("Subhead", "subhead", ft, x, y, w, color, "body_medium", align))

    def wave(self) -> None:
        """Request a background wave; it is chosen after layout so it can avoid the copy."""
        self.want_wave = self.brief.wave

    def _place_wave(self) -> None:
        """Pick the wave whose blue mass overlaps headline/CTA/logo the least (keeps contrast clean)."""
        if not getattr(self, "want_wave", False):
            return
        import numpy as np
        from PIL import Image

        clear_roles = {"headline", "subhead", "cta"}  # the logo adapts its colour; copy needs calm ground
        boxes = [l for l in self.layers if l.role in clear_roles]
        sw, sh = max(1, self.W // 8), max(1, self.H // 8)
        shape = "portrait" if self.H > self.W * 1.5 else "square"
        scored: list[tuple[float, str, int, Asset]] = []
        for a in self.kit.by_category("background"):
            if not a.mask:
                continue
            base = np.asarray(Image.open(get_settings().brand_dir / a.mask).convert("L").resize((sw, sh))) / 255.0
            if base.mean() < 0.15:
                continue
            for rot in (0, 180):  # a wave turned upside-down is still the same brand shape
                m = base if rot == 0 else base[::-1, ::-1]
                overlap = 0.0
                for b in boxes:
                    x0, y0 = int(b.x / 8), int(b.y / 8)
                    x1, y1 = max(x0 + 1, int((b.x + b.w) / 8)), max(y0 + 1, int((b.y + b.h) / 8))
                    overlap += float(m[max(0, y0):y1, max(0, x0):x1].mean() or 0) * (b.w * b.h)
                penalty = 0.0 if shape in a.tags else 0.01
                scored.append((overlap / (self.W * self.H) + penalty, a.id, rot, a))
        if not scored:
            return
        scored.sort(key=lambda t: (t[0], t[1], t[2]))
        best = scored[0][0]
        _, _, rot, asset = self.rng.choice([t for t in scored if t[0] <= best + 0.004])
        layer = self.vector("Background wave", "wave", asset, Box(0, 0, self.W, self.H), self.cw["wave"],
                            keep_aspect=False)
        layer.rotation = rot
        self.layers.insert(1, layer)

    def charm(self, idx: int, cx: float, cy: float, size: float, rotation: float = 0) -> None:
        if idx >= len(self.brief.charms):
            return
        pick = self.brief.charms[idx]
        asset = self.kit.get(pick.asset_id)
        b = Box(cx - size / 2, cy - size / 2, size, size)
        if asset and asset.category in ("charm", "illustration"):
            layer = self.asset_image(f"Charm · {asset.name}", "charm", asset, b)
        elif pick.prompt:
            layer = self.gen_image("Charm", "charm", b, pick.prompt, transparent=True, fit="contain",
                                   mode="brand_style", style_refs=self._style_refs("charm", 3))
        else:
            return
        layer.rotation = rotation
        self.add(layer)

    def stat_card(self, x: float, y: float) -> None:
        stat = self.brief.stat
        if not stat:
            return
        u = self.u
        w, h = 300 * u, 156 * u
        card = self.rect("Stat card", "stat_bg", Box(x, y, w, h), PALETTE["white"], radius=18 * u, shadow=True)
        lab = fonts.fit(stat.label, "body_medium", w - 48 * u, 40 * u, 24 * u, 18 * u, 1)
        val = fonts.fit(stat.value, "headline_bold", w - 48 * u, 70 * u, 56 * u, 30 * u, 1)
        label = self.text("Stat label", "stat_label", lab, x + 24 * u, y + 20 * u, w - 48 * u, PALETTE["navy"], "body_medium")
        value = self.text("Stat value", "stat_value", val, x + 24 * u, y + 20 * u + lab.height + 4 * u, w - 48 * u,
                          PALETTE["navy"], "headline_bold")
        # A tiny upward sparkline drawn as an inline vector.
        sw, sh = 110 * u, 44 * u
        sx, sy = x + w - sw - 20 * u, y + h - sh - 20 * u
        pts = [(0, 0.75), (0.2, 0.62), (0.38, 0.7), (0.55, 0.42), (0.72, 0.5), (1.0, 0.08)]
        d = "M " + " L ".join(f"{px * sw:.1f} {py * sh:.1f}" for px, py in pts)
        spark = Layer(name="Sparkline", kind="vector", role="sparkline", x=sx, y=sy, w=sw, h=sh,
                      stroke=PALETTE["blue"], stroke_width=4 * u,
                      svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="{sw:.0f}" height="{sh:.0f}" '
                           f'viewBox="0 0 {sw:.1f} {sh:.1f}"><path d="{d}" fill="none" stroke="{PALETTE["blue"]}" '
                           f'stroke-width="{4 * u:.1f}" stroke-linecap="round" stroke-linejoin="round"/></svg>'))
        self.add(self.group("Stat card", "stat", [card, label, value, spark]))

    def _style_refs(self, category: str, n: int) -> list[str]:
        items = sorted(self.kit.by_category(category), key=lambda a: a.id)
        if category == "charm":
            items = [a for a in items if a.width >= 70]
        self.rng.shuffle(items)
        return [a.id for a in items[:n]]

    def visual_layer(self, region: Box, *, anchor: str = "center", mask_bloom: str | None = None) -> None:
        """The hero visual: brand asset or generated image, optionally cropped in a bloom/rect mask."""
        v = self.brief.visual
        asset = self.kit.get(v.asset_id) if v.source == "asset" else None
        if asset and asset.category in ("illustration", "device"):
            self.add(self.asset_image(asset.name, v.kind if v.kind != "cutout" else "illustration", asset, region,
                                      anchor=anchor))
            return
        prompt = v.prompt or "a smiling small business owner at work in their shop"
        if v.kind == "photo":
            photo = self.gen_image("Photo", "photo", region, prompt, transparent=False, fit="cover", anchor="center")
            if mask_bloom:
                bloom = self.kit.bloom(mask_bloom)
                if bloom:
                    mb = cover(region, bloom.width, bloom.height)
                    mb.x, mb.y = region.x, region.y  # bleed right/down, never into the copy column
                    mask = self.vector(f"{bloom.name} mask", "mask_shape", bloom, mb, PALETTE["blue"], keep_aspect=False)
                    # Fit the photo to the bloom's *body* (skip thin curls) and anchor it to the top,
                    # so faces land inside the shape rather than in an empty corner of its box.
                    body_top = self.mask_body_top(bloom)
                    photo.x, photo.y = mb.x, mb.y + body_top * mb.h - 0.04 * mb.h
                    photo.w, photo.h = mb.w, mb.y + mb.h - photo.y
                    photo.anchor = "top"
                    self.add(self.group("Photo in bloom", "photo_group", [mask, photo], kind="mask"))
                    return
            mask = self.rect("Photo frame", "mask_shape", region, PALETTE["blue"])
            self.add(self.group("Photo", "photo_group", [mask, photo], kind="mask"))
        elif v.kind == "illustration":
            self.add(self.gen_image("Illustration", "illustration", region, prompt, transparent=True,
                                    fit="contain", anchor=anchor, mode="brand_style",
                                    style_refs=self._style_refs("illustration", 3)))
        else:  # cutout subject / device without asset
            self.add(self.gen_image("Cut-out", "cutout", region, prompt, transparent=True, fit="contain",
                                    anchor="bottom"))

    # ---- archetypes ------------------------------------------------------------------
    def build(self) -> DesignSpec:
        getattr(self, f"_{self.brief.archetype}")()
        self._place_wave()
        return DesignSpec(name=self.brief.name, format=self.brief.format, width=self.W, height=self.H,
                          background=self.cw["bg"], layers=self.layers, brief=self.brief.model_dump())

    def _background(self) -> None:
        self.add(self.rect("Background", "background", Box(0, 0, self.W, self.H), self.cw["bg"]))

    def _text_stack(self, x: float, y: float, w: float, max_h: float, color: str, max_size: float,
                    align: str = "left", cta_colors: tuple[str, str] | None = None, gap: float = 36) -> float:
        """Headline + subhead + CTA; returns the bottom y."""
        u = self.u
        hl = self.headline(x, y, w, max_h, color, max_size, align)
        bottom = hl.y + hl.h
        sub = self.subhead(x, bottom + 18 * u, w, color, align)
        if sub:
            bottom = sub.y + sub.h
        cta_y = bottom + gap * u
        bg, fg = cta_colors or (self.cw["cta_bg"], self.cw["cta_text"])
        c = self.cta(x, cta_y, bg, fg)
        if align == "center":
            dx = x + (w - c.w) / 2 - c.x
            for ch in [c, *(c.children or [])]:
                ch.x += dx
        return c.y + c.h

    def _card_photo(self) -> None:
        u, W, H, m = self.u, self.W, self.H, self.m
        self._background()
        if self.wide:
            card = Box(m, m, W * 0.5 - 1.5 * m, H - 2 * m)
            self.visual_layer(Box(W * 0.5 - m, 0, W * 0.5 + m, H))
            self.add(self.rect("Card", "card", card, self.cw["card"], radius=28 * u, shadow=True))
            p = 44 * u
            lw, lh = self.logo_size()
            self._text_stack(card.x + p, card.y + p, card.w - 2 * p, card.h - 2 * p - lh - 140 * u, PALETTE["navy"],
                             84 * u, cta_colors=(PALETTE["navy"], PALETTE["white"]))
            self.logo(card.x + p, card.bottom - p - lh, lw, PALETTE["navy"])
            self.charm(0, card.right, card.y + 40 * u, 110 * u, 8)
            return

        card_x, card_w, p = 48 * u, W - 96 * u, 60 * u
        card_y = self.top if self.story else 48 * u
        inner_w = card_w - 2 * p
        # Measure the card content first, then draw bottom-up (photo, accents, card, text).
        hl = fonts.fit_headline(self.brief.headline, "headline", inner_w, 0.3 * H, 100 * u, 44 * u, 3)
        sub_h = 0
        if self.brief.subhead:
            sub_h = 18 * u + fonts.fit(self.brief.subhead, "body_medium", inner_w, 140 * u, 32 * u, 22 * u, 2).height
        card_h = p + hl.height + sub_h + 40 * u + 72 * u + p
        photo_top = card_y + card_h - 70 * u
        self.visual_layer(Box(0, photo_top, W, H - photo_top))
        lw, lh = self.logo_size()
        bloom = self.kit.bloom(self.brief.bloom if self.brief.bloom in SOLID_BLOOMS else "harmony")
        if bloom:
            bw = 0.52 * W
            bb = contain(Box(W - 0.4 * W, card_y + card_h - 30 * u, bw, bw * 0.8), bloom.width, bloom.height)
            self.add(self.vector(f"{bloom.name} accent", "bloom", bloom, bb, PALETTE["blue"]))
            lw, lh = lw * 0.85, lh * 0.85
            lx, ly = self.spot_in_mask(bloom, bb, lw * 1.3, lh * 1.9)
            self.logo(lx + lw * 0.15, ly + lh * 0.45, lw, PALETTE["white"])
        else:
            self.logo(W - m, card_y + card_h + 30 * u, lw, PALETTE["white"], align="right")
        self.add(self.rect("Card", "card", Box(card_x, card_y, card_w, card_h), self.cw["card"], radius=32 * u,
                           shadow=True))
        self._text_stack(card_x + p, card_y + p, inner_w, 0.3 * H, PALETTE["navy"], 100 * u,
                         cta_colors=(PALETTE["sky_soft"], PALETTE["navy"]), gap=40)
        self.charm(0, card_x + 70 * u, card_y + card_h + 10 * u, 120 * u, -10)
        self.charm(1, card_x + card_w - 60 * u, card_y + 50 * u, 100 * u, 12)
        stat_y = min(H - 48 * u - 156 * u, self.text_bottom - 156 * u) if self.story else H - 48 * u - 156 * u
        self.stat_card(48 * u, max(photo_top + 160 * u, stat_y))

    def _navy_illustration(self) -> None:
        u, W, H, m = self.u, self.W, self.H, self.m
        self._background()
        self.wave()
        lw, lh = self.logo_size()
        if self.wide:
            col = W * 0.5 - m
            self._text_stack(m, m, col, H - 2 * m - lh - 160 * u, self.cw["text"], 88 * u)
            self.logo(m, H - m - lh, lw)
            self.visual_layer(Box(W * 0.5, m * 0.5, W * 0.5 - m * 0.5, H - m))
            self.charm(0, W - 1.5 * m, 1.5 * m, 90 * u, 10)
            return
        hl = self.headline(m, self.top, W - 2 * m, 0.28 * H, self.cw["text"], 124 * u, align="center")
        bottom = hl.y + hl.h
        sub = self.subhead(m, bottom + 18 * u, W - 2 * m, self.cw["text"], align="center")
        if sub:
            bottom = sub.y + sub.h
        cta_h = 72 * u
        foot_y = self.text_bottom - cta_h
        self.visual_layer(Box(m, bottom + 30 * u, W - 2 * m, foot_y - bottom - 60 * u))
        self.cta(m, foot_y)  # colourway colours keep the button off the wave tone
        self.logo(W - m, foot_y + (cta_h - lh) / 2, lw, align="right")
        self.charm(0, W - 1.6 * m, bottom + 90 * u, 110 * u, 12)
        self.charm(1, 1.6 * m, foot_y - 120 * u, 90 * u, -12)

    def _photo_bloom(self) -> None:
        u, W, H, m = self.u, self.W, self.H, self.m
        self._background()
        lw, lh = self.logo_size()
        bloom = self.brief.bloom if self.brief.bloom in SOLID_BLOOMS else "harmony"
        if self.wide:
            self._text_stack(m, m, W * 0.46 - m, H - 2 * m - lh - 160 * u, self.cw["text"], 84 * u)
            self.logo(m, H - m - lh, lw)
            self.visual_layer(Box(W * 0.46, -0.05 * H, W * 0.58, H * 1.1), mask_bloom=bloom)
            self.stat_card(W * 0.44, H - m - 156 * u)
            return
        text_bottom = self._text_stack(m, self.top, W - 2 * m, 0.3 * H, self.cw["text"], 116 * u,
                                       cta_colors=(PALETTE["sky_soft"], PALETTE["navy"]))
        region_top = text_bottom + 40 * u
        self.visual_layer(Box(0.26 * W, region_top, 0.82 * W, H - region_top + 0.04 * H), mask_bloom=bloom)
        logo_y = (self.text_bottom if self.story else H - m) - lh
        self.logo(m, logo_y, lw)
        self.stat_card(m, region_top + (logo_y - region_top) * 0.35)
        self.charm(0, 0.3 * W, region_top + 40 * u, 110 * u, -8)

    def _device_showcase(self) -> None:
        u, W, H, m = self.u, self.W, self.H, self.m
        self._background()
        self.wave()
        lw, lh = self.logo_size()
        if not (self.brief.visual.source == "asset" and self.kit.get(self.brief.visual.asset_id)):
            devices = sorted(self.kit.by_category("device"), key=lambda a: a.id)
            if devices:
                self.brief.visual.source, self.brief.visual.asset_id = "asset", self.rng.choice(devices).id
                self.brief.visual.kind = "device"
        if self.wide:
            self._text_stack(m, m, W * 0.48 - m, H - 2 * m - lh - 160 * u, self.cw["text"], 84 * u)
            self.logo(m, H - m - lh, lw)
            self.visual_layer(Box(W * 0.5, m * 0.5, W * 0.5 - m * 0.5, H - m * 0.5), anchor="bottom")
            return
        text_bottom = self._text_stack(m, self.top, W - 2 * m, 0.3 * H, self.cw["text"], 112 * u)
        region = Box(0.2 * W, text_bottom + 30 * u, 0.8 * W, H - text_bottom - 30 * u)
        self.visual_layer(region, anchor="bottom")
        logo_y = (self.text_bottom if self.story else H - m) - lh
        self.logo(m, logo_y, lw, PALETTE["white"])
        self.charm(0, 0.2 * W, text_bottom + 140 * u, 120 * u, -10)
        self.charm(1, W - 1.4 * m, text_bottom + 60 * u, 90 * u, 12)

    def _checklist(self) -> None:
        u, W, H, m = self.u, self.W, self.H, self.m
        self._background()
        self.wave()
        lw, lh = self.logo_size()
        items = self.brief.checklist or ["Invoices", "Payroll", "Tax time"]
        check = next((a for a in self.kit.by_category("charm")
                      if "check" in a.name.lower() and "green" in a.name.lower()), None)
        if self.wide:
            self._text_stack(m, m, W * 0.46 - m, H - 2 * m - lh - 160 * u, self.cw["text"], 84 * u)
            self.logo(m, H - m - lh, lw)
            self._pills(items, Box(W * 0.5, m, W * 0.5 - m, H - 2 * m), check)
            return
        hl = self.headline(m, self.top, W - 2 * m, 0.26 * H, self.cw["text"], 112 * u)
        bottom = hl.y + hl.h
        sub = self.subhead(m, bottom + 18 * u, W - 2 * m, self.cw["text"])
        if sub:
            bottom = sub.y + sub.h
        cta_h = 72 * u
        foot_y = self.text_bottom - cta_h
        self._pills(items, Box(m, bottom + 56 * u, W - 2 * m, foot_y - bottom - 100 * u), check)
        self.cta(m, foot_y)  # colourway colours keep the button off the wave tone
        self.logo(W - m, foot_y + (cta_h - lh) / 2, lw, align="right")
        self.charm(0, W - 1.8 * m, foot_y - 150 * u, 130 * u, 8)

    def _pills(self, items: list[str], region: Box, check: Asset | None) -> None:
        u = self.u
        n = len(items)
        ph = min(104 * u, region.h / (n * 1.3))
        gap = min(30 * u, (region.h - n * ph) / max(n, 1))
        pw = min(region.w * 0.78, 700 * u)
        stagger = (region.w - pw) / max(n - 1, 1) * 0.5
        y = region.y
        for i, item in enumerate(items):
            x = region.x + i * stagger
            pill = self.rect("Pill", "pill_bg", Box(x, y, pw, ph), PALETTE["white"], radius=ph / 2, shadow=True)
            children = [pill]
            icon = 0.68 * ph
            tx = x + 0.3 * ph
            if check:
                children.append(self.asset_image("Check", "pill_icon", check,
                                                 Box(x + 0.18 * ph, y + (ph - icon) / 2, icon, icon)))
                tx = x + 0.18 * ph + icon + 0.22 * ph
            ft = fonts.fit(item, "headline", pw - (tx - x) - 0.4 * ph, ph * 0.8, 0.5 * ph, 0.3 * ph, 1)
            children.append(self.text("Pill text", "pill_text", ft, tx, y + (ph - ft.height) / 2,
                                      pw - (tx - x) - 0.3 * ph, PALETTE["navy"], "headline"))
            self.add(self.group(f"Checklist · {item}", "checklist_item", children))
            y += ph + gap


def build_spec(brief: Brief, kit: BrandKit, variant: int = 0) -> DesignSpec:
    spec = Builder(brief, kit, variant).build()
    spec.variant = variant
    for layer in spec.all_layers():
        for attr in ("x", "y", "w", "h"):
            setattr(layer, attr, round(getattr(layer, attr), 1))
        if layer.font_size:
            layer.font_size = round(layer.font_size)
        if not layer.id:
            layer.id = new_id()
    return spec
