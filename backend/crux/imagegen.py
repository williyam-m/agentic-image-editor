"""Image generation with OpenAI GPT Image (Flare).

Layers are generated independently so each can be re-edited on its own:
cut-out subjects use a transparent background, full-bleed photos do not.
"""
from __future__ import annotations

import base64
import io
import logging
import random
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

import openai
from openai import OpenAI
from PIL import Image

from .config import get_settings

log = logging.getLogger(__name__)

Size = Literal["1024x1024", "1024x1536", "1536x1024"]

PHOTO_STYLE = (
    "Authentic editorial photograph, natural warm daylight, real small-business setting, "
    "candid genuine expression, shallow depth of field, crisp focus on the subject, "
    "true-to-life skin tones, no text, no logos, no watermarks."
)


@lru_cache
def _client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.openai_api_key.get_secret_value(), timeout=180, max_retries=0)


def best_size(width: float, height: float) -> Size:
    ratio = width / max(height, 1)
    if ratio > 1.2:
        return "1536x1024"
    if ratio < 0.83:
        return "1024x1536"
    return "1024x1024"


def _retry(fn, what: str, attempts: int = 4):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError,
                openai.InternalServerError) as e:
            last = e
            delay = min(10.0, 1.5 * 2**i) + random.random()
            log.warning("%s attempt %d failed (%s); retrying in %.1fs", what, i + 1, type(e).__name__, delay)
            time.sleep(delay)
    raise RuntimeError(f"{what} failed: {last}")


def _decode(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


def generate(prompt: str, *, size: Size = "1024x1024", transparent: bool = False,
             quality: str | None = None) -> Image.Image:
    s = get_settings()
    kwargs: dict = {"model": s.image_model, "prompt": prompt, "size": size, "n": 1,
                    "quality": quality or s.image_quality}
    if transparent:
        kwargs.update(background="transparent", output_format="png")
    started = time.perf_counter()
    resp = _retry(lambda: _client().images.generate(**kwargs), "image.generate")
    log.info("image generated in %.1fs (%s)", time.perf_counter() - started, size)
    return _decode(resp.data[0].b64_json)


def edit(prompt: str, images: list[Path | bytes], *, size: Size = "1024x1024",
         transparent: bool = False, quality: str | None = None) -> Image.Image:
    """Edit / restyle using one or more input images (first image is the primary)."""
    s = get_settings()
    files = []
    for i, img in enumerate(images[:8]):
        data = img if isinstance(img, bytes) else Path(img).read_bytes()
        files.append((f"input_{i}.png", _to_png(data), "image/png"))
    kwargs: dict = {"model": s.image_model, "prompt": prompt, "image": files, "size": size, "n": 1,
                    "quality": quality or s.image_quality}
    if transparent:
        kwargs.update(background="transparent", output_format="png")
    started = time.perf_counter()
    resp = _retry(lambda: _client().images.edit(**kwargs), "image.edit")
    log.info("image edited in %.1fs (%s)", time.perf_counter() - started, size)
    return _decode(resp.data[0].b64_json)


def _to_png(data: bytes) -> bytes:
    im = Image.open(io.BytesIO(data))
    if im.format == "PNG":
        return data
    buf = io.BytesIO()
    im.convert("RGBA").save(buf, format="PNG")
    return buf.getvalue()


def trim_transparent(im: Image.Image, pad: int = 4) -> Image.Image:
    """Crop empty margins so cut-out layers hug their content."""
    if im.mode != "RGBA":
        return im
    bbox = im.split()[-1].point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        return im
    l, t, r, b = bbox
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))
