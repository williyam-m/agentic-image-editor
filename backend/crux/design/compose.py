"""Flatten a layered DesignSpec into a single PNG (the "combined final").

The editable result lives in Crux Studio; this renderer produces the server-side
composite used for chat previews, downloads, brand-guard contrast sampling and
vision QA. The editor's SVG renderer mirrors it exactly: rects, text with CSS-like line boxes,
images, recoloured vector masks and mask groups.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..brand.kit import FONTS
from ..config import get_settings
from . import fonts
from .spec import DesignSpec, Layer

_POINTS = re.compile(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)")


def _rgba(hex_color: str | None, opacity: float = 1.0) -> tuple[int, int, int, int]:
    h = (hex_color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(255 * max(0.0, min(1.0, opacity)))


def resolve_file(layer: Layer) -> Path | None:
    s = get_settings()
    if layer.file:
        return s.data_dir / layer.file
    if layer.src and layer.src.startswith(s.public_api_url + "/files/"):
        return s.data_dir / layer.src[len(s.public_api_url) + len("/files/"):]
    return None


@lru_cache(maxsize=64)
def _load_rgba(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


class Renderer:
    def __init__(self, spec: DesignSpec, scale: float = 1.0, skip: set[str] | None = None):
        self.spec, self.k = spec, scale
        self.skip = skip or set()

    def render(self) -> Image.Image:
        W, H = round(self.spec.width * self.k), round(self.spec.height * self.k)
        canvas = Image.new("RGBA", (W, H), _rgba(self.spec.background))
        for layer in self.spec.layers:
            self._draw(canvas, layer)
        return canvas

    def _box(self, l: Layer) -> tuple[int, int, int, int]:
        k = self.k
        return round(l.x * k), round(l.y * k), max(1, round(l.w * k)), max(1, round(l.h * k))

    def _paste(self, canvas: Image.Image, tile: Image.Image, x: int, y: int, l: Layer) -> None:
        if l.opacity < 1:
            a = tile.split()[-1].point(lambda v: int(v * l.opacity))
            tile.putalpha(a)
        if l.rotation:
            w0, h0 = tile.size
            tile = tile.rotate(-l.rotation, resample=Image.BICUBIC, expand=True)
            x -= (tile.width - w0) // 2
            y -= (tile.height - h0) // 2
        canvas.alpha_composite(tile, (x, y)) if x >= 0 and y >= 0 else self._paste_clipped(canvas, tile, x, y)

    @staticmethod
    def _paste_clipped(canvas: Image.Image, tile: Image.Image, x: int, y: int) -> None:
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(tile, (x, y), tile)
        canvas.alpha_composite(layer)

    def _draw(self, canvas: Image.Image, l: Layer) -> None:
        if l.id in self.skip or l.hidden:
            return
        fn = getattr(self, f"_{l.kind}")
        fn(canvas, l)

    def _rect(self, canvas: Image.Image, l: Layer) -> None:
        x, y, w, h = self._box(l)
        r = round(l.radius * self.k)
        if l.shadow:
            pad = round(30 * self.k)
            sh = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle((pad, pad + round(8 * self.k), pad + w, pad + h), r,
                                                 fill=(0, 8, 86, 46))
            sh = sh.filter(ImageFilter.GaussianBlur(round(14 * self.k) or 1))
            self._paste(canvas, sh, x - pad, y - pad, l)
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(tile).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=_rgba(l.fill))
        self._paste(canvas, tile, x, y, l)

    def _ellipse(self, canvas: Image.Image, l: Layer) -> None:
        x, y, w, h = self._box(l)
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(tile).ellipse((0, 0, w - 1, h - 1), fill=_rgba(l.fill))
        self._paste(canvas, tile, x, y, l)

    def _text(self, canvas: Image.Image, l: Layer) -> None:
        key = fonts.key_for(l.font_family, l.font_weight, l.font or "body") if l.font_family else (l.font or "body")
        size = (l.font_size or 24) * self.k
        f = fonts.font(key, max(1, round(size)))
        lh = (l.line_height or FONTS[key]["line_height"]) * size
        asc, desc = f.getmetrics()
        x, y, w, _ = self._box(l)
        draw = ImageDraw.Draw(canvas)
        # Same wrap the editor applies: explicit breaks, then the box width (exact, no safety margin).
        lines = fonts.wrap(l.text or "", key, l.font_size or 24, l.w, safety=1.0) if l.w else (l.text or "").split("\n")
        for i, line in enumerate(lines):
            lw = f.getlength(line)
            lx = {"center": x + (w - lw) / 2, "right": x + w - lw}.get(l.align or "left", x)
            baseline = y + i * lh + (lh - (asc + desc)) / 2 + asc
            draw.text((lx, baseline), line, font=f, fill=_rgba(l.color, l.opacity), anchor="ls")

    def _image(self, canvas: Image.Image, l: Layer) -> None:
        x, y, w, h = self._box(l)
        path = resolve_file(l)
        if l.status != "ready" or not path or not path.exists():
            tile = Image.new("RGBA", (w, h), (226, 232, 240, 255) if not l.transparent else (0, 0, 0, 0))
            self._paste(canvas, tile, x, y, l)
            return
        tile = _load_rgba(str(path)).resize((w, h), Image.LANCZOS)
        self._paste(canvas, tile.copy(), x, y, l)

    def _vector_alpha(self, l: Layer) -> Image.Image:
        x, y, w, h = self._box(l)
        if l.asset_id:
            from ..brand.kit import load_kit

            asset = load_kit().get(l.asset_id)
            if asset and asset.mask:
                return Image.open(get_settings().brand_dir / asset.mask).convert("L").resize((w, h), Image.LANCZOS)
        alpha = Image.new("L", (w, h), 0)
        if l.svg:
            m = re.search(r'd="([^"]+)"', l.svg)
            pts = [(float(a) * self.k, float(b) * self.k) for a, b in _POINTS.findall(m.group(1))] if m else []
            if len(pts) > 1:
                ImageDraw.Draw(alpha).line(pts, fill=255, width=max(1, round(l.stroke_width * self.k)),
                                           joint="curve")
        return alpha

    def _vector(self, canvas: Image.Image, l: Layer) -> None:
        x, y, w, h = self._box(l)
        alpha = self._vector_alpha(l)
        tile = Image.new("RGBA", (w, h), _rgba(l.fill or l.stroke))
        tile.putalpha(alpha)
        self._paste(canvas, tile, x, y, l)

    def _group(self, canvas: Image.Image, l: Layer) -> None:
        for c in l.children or []:
            self._draw(canvas, c)

    def _mask(self, canvas: Image.Image, l: Layer) -> None:
        children = l.children or []
        if not children:
            return
        mask_shape = children[0]
        content = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        for c in children[1:]:
            self._draw(content, c)
        x, y, w, h = self._box(mask_shape)
        alpha = Image.new("L", canvas.size, 0)
        if mask_shape.kind == "vector":
            alpha.paste(self._vector_alpha(mask_shape), (x, y))
        else:
            ImageDraw.Draw(alpha).rounded_rectangle((x, y, x + w - 1, y + h - 1), round(mask_shape.radius * self.k),
                                                   fill=255)
        content.putalpha(ImageChops.multiply(content.split()[-1], alpha))
        canvas.alpha_composite(content)


def render(spec: DesignSpec, scale: float = 1.0, skip: set[str] | None = None) -> Image.Image:
    return Renderer(spec, scale, skip).render()


def save_render(spec: DesignSpec, path: Path, scale: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    render(spec, scale).convert("RGB").save(path, "PNG", optimize=True)
    return path
