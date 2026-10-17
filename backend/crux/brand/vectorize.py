"""Bitmap → clean SVG path tracing (potrace) for blooms, waves and the wordmark.

Vector brand shapes become real, recolourable editor paths instead of flat
bitmaps. Potrace emits a flipped, 10x-scaled coordinate system; we bake that
transform into the path so the SVG is a plain ``viewBox="0 0 w h"`` path.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

_TRANSFORM = re.compile(r'translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([-\d.]+),([-\d.]+)\)')
_PATH = re.compile(r'<path d="([^"]+)"', re.S)
_TOKEN = re.compile(r"[MmLlCcZz]|-?\d*\.?\d+(?:e[-+]?\d+)?")


def potrace_available() -> bool:
    return shutil.which("potrace") is not None


def _transform_path(d: str, sx: float, sy: float, tx: float, ty: float, k: float) -> str:
    out: list[str] = []
    cmd = ""
    nums: list[float] = []

    def flush() -> None:
        if not cmd:
            return
        if cmd in "Zz":
            out.append("Z")
            return
        absolute = cmd.isupper()
        pts = []
        for i in range(0, len(nums) - 1, 2):
            x, y = nums[i], nums[i + 1]
            if absolute:
                x, y = (x * sx + tx) * k, (y * sy + ty) * k
            else:
                x, y = x * sx * k, y * sy * k
            pts.append(f"{x:.1f} {y:.1f}")
        out.append(cmd + " ".join(pts))

    for tok in _TOKEN.findall(d):
        if tok.isalpha():
            flush()
            cmd, nums = tok, []
            if tok in "Zz":
                flush()
                cmd = ""
        else:
            nums.append(float(tok))
    flush()
    return " ".join(out)


def trace_mask(mask: Image.Image, upscale: int = 1) -> tuple[str, int, int]:
    """Trace a binary mask (255 = shape). Returns (path d, width, height) in mask pixels."""
    if not potrace_available():
        raise RuntimeError("potrace is not installed (brew install potrace)")
    w, h = mask.size
    if upscale > 1:
        mask = mask.resize((w * upscale, h * upscale), Image.LANCZOS)
    bmp = mask.point(lambda v: 0 if v > 127 else 255).convert("1")
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.bmp", Path(tmp) / "out.svg"
        bmp.save(src)
        subprocess.run(["potrace", "-s", "--flat", "-a", "1.0", "-O", "0.4", "-t", "6",
                        "-o", str(dst), str(src)], check=True, capture_output=True)
        svg = dst.read_text()
    m = _TRANSFORM.search(svg)
    if not m:
        raise RuntimeError("unexpected potrace output")
    tx, ty, sx, sy = map(float, m.groups())
    paths = [_transform_path(d, sx, sy, tx, ty, 1.0 / upscale) for d in _PATH.findall(svg)]
    return " ".join(paths), w, h


def svg_document(d: str, width: int, height: int, fill: str = "#000856") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><path d="{d}" fill="{fill}"/></svg>')
