"""Text measurement with the same font files the Crux Studio editor renders, so layouts fit exactly."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageFont

from ..brand.kit import FONTS
from ..config import get_settings

# Browser and Pillow metrics differ by a hair; generated copy wraps against a narrower width.
WRAP_SAFETY = 0.93


@lru_cache(maxsize=256)
def font(key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(get_settings().fonts_dir / FONTS[key]["file"]), size)


def key_for(family: str | None, weight: str | int | None, fallback: str = "body") -> str:
    """Brand font key for a family/weight pair (edits change family/weight, not the key)."""
    w = str(weight or "")
    candidates = [k for k, f in FONTS.items() if f["family"] == family]
    exact = next((k for k in candidates if FONTS[k]["weight"] == w), None)
    return exact or (candidates[0] if candidates else fallback)


def metrics() -> dict[str, dict[str, float]]:
    """Ascent/descent ratios per font key — the editor uses them to place text exactly like the compositor."""
    out = {}
    for key in FONTS:
        asc, desc = font(key, 1000).getmetrics()
        out[key] = {"asc": asc / 1000, "desc": desc / 1000}
    return out


def text_width(text: str, key: str, size: float) -> float:
    return font(key, max(1, round(size))).getlength(text)


def wrap(text: str, key: str, size: float, max_w: float, safety: float = WRAP_SAFETY) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if text_width(trial, key, size) <= max_w * safety + 0.5:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


@dataclass
class FittedText:
    text: str          # with explicit line breaks so the editor wraps identically
    size: float
    lines: int
    width: float       # widest line
    height: float


def fit(text: str, key: str, max_w: float, max_h: float, max_size: float, min_size: float,
        max_lines: int = 4) -> FittedText:
    """Largest size (step 2px) at which ``text`` fits the box within ``max_lines``."""
    lh = FONTS[key]["line_height"]
    size = max_size
    while True:
        lines = wrap(text, key, size, max_w)
        height = len(lines) * size * lh
        if (len(lines) <= max_lines and height <= max_h) or size <= min_size:
            width = max((text_width(l, key, size) for l in lines), default=0)
            return FittedText("\n".join(lines), size, len(lines), width, height)
        size -= 2


def balance_lines(text: str, key: str, size: float, max_w: float) -> str:
    """Re-wrap so lines are visually balanced (avoids one-word last lines)."""
    lines = wrap(text, key, size, max_w)
    if len(lines) < 2:
        return "\n".join(lines)
    total = text_width(" ".join(lines), key, size)
    target = total / len(lines)
    best = lines
    lo, hi = target, max_w
    for _ in range(12):
        mid = (lo + hi) / 2
        trial = wrap(text, key, size, mid / WRAP_SAFETY)
        if len(trial) <= len(lines):
            best, hi = trial, mid
        else:
            lo = mid
    return "\n".join(best)


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=\S)")


def fit_headline(text: str, key: str, max_w: float, max_h: float, max_size: float, min_size: float,
                 max_lines: int = 3) -> FittedText:
    """Fit a headline the way designers set it: one sentence per line when that still reads
    big ("Data in. / Doubt out."), otherwise balanced wrapping without orphans."""
    lh = FONTS[key]["line_height"]
    flat = " ".join(text.split())
    wrapped = fit(flat, key, max_w, max_h, max_size, min_size, max_lines)
    if wrapped.lines > 1:
        wrapped.text = balance_lines(flat, key, wrapped.size, max_w)
    parts = [p.strip() for p in (text.split("\n") if "\n" in text else _SENTENCE.split(flat)) if p.strip()]
    if 2 <= len(parts) <= max_lines:
        size = max_size
        while size >= min_size:
            widest = max(text_width(p, key, size) for p in parts)
            if widest <= max_w * WRAP_SAFETY and len(parts) * size * lh <= max_h:
                break
            size -= 2
        if size >= min_size and size >= wrapped.size * 0.82:
            return FittedText("\n".join(parts), size, len(parts), max(text_width(p, key, size) for p in parts),
                              len(parts) * size * lh)
    return wrapped
