"""Per-layer image generation and final compositing (run inside Celery workers)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

from .. import imagegen, llm
from ..brand import guard
from ..brand.compliance import check_image, correction
from ..brand.policy import IMAGE_RULES
from ..brand.kit import load_kit
from ..config import get_settings
from .compose import render
from .layouts import place_image
from .spec import DesignSpec, Layer

log = logging.getLogger(__name__)

BRAND_STYLE_PROMPT = (
    "Create a NEW {what} in exactly the same visual style as the reference images: the same glossy 3D vector "
    "rendering, rounded chunky forms, soft shading and highlights, and the same palette (navy #000856, blue "
    "#1F65D6, sky #3ECCFF with mint, yellow, pink and lilac accents). Subject: {prompt}. One cohesive composition, "
    "centred, generous padding, transparent background, no text, no letters, no logos."
)
CUTOUT_STYLE = ("Isolated subject on a fully transparent background, clean edges, natural soft light, "
                "photographic, no text, no logos.")


def _job_dir(job_id: str) -> Path:
    d = get_settings().jobs_dir / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _full_prompt(layer: Layer) -> str:
    prompt = (layer.prompt or "").strip()
    if layer.role == "photo":
        return f"{prompt}. {imagegen.PHOTO_STYLE} Keep the main subject fully in frame and centred, with the face in the upper-middle and generous headroom. No logos on clothing."
    if layer.role == "cutout":
        return f"{prompt}. {CUTOUT_STYLE}"
    return prompt


def _render(layer: Layer, size: imagegen.Size, extra: str = "") -> Image.Image:
    s = get_settings()
    if layer.gen_mode == "brand_style":
        kit = load_kit()
        refs = [kit.path(a) for a in (kit.get(i) for i in layer.style_refs or []) if a]
        what = "brand charm icon" if layer.role == "charm" else "brand illustration"
        prompt = BRAND_STYLE_PROMPT.format(what=what, prompt=layer.prompt or "") + " " + extra
        return imagegen.edit(prompt, refs, size=size, transparent=True) if refs else \
            imagegen.generate(prompt, size=size, transparent=True)
    if layer.gen_mode == "edit":
        if not layer.file or not (s.data_dir / layer.file).exists():
            raise ValueError("edit requested without a source image")
        prompt = (f"{layer.prompt or ''}. Keep everything else identical (same person, pose, framing, lighting). "
                  f"{IMAGE_RULES} {extra}")
        return imagegen.edit(prompt, [s.data_dir / layer.file], size=size, transparent=layer.transparent)
    return imagegen.generate(f"{_full_prompt(layer)} {IMAGE_RULES} {extra}", size=size, transparent=layer.transparent)


def generate_layer_image(job_id: str, layer_data: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
    """Generate one layer's pixels, verified against the brand image policy.

    Every image is reviewed by a vision model; text, logos, watermarks, competitor
    branding or (for illustrations) off-palette colours trigger a regeneration with a
    targeted correction. Returns file/src, final geometry and the compliance verdict.
    """
    s = get_settings()
    layer = Layer.model_validate(layer_data)
    size = imagegen.best_size(layer.w, layer.h)
    extra, verdict, img, fixed = "", {}, None, []
    for attempt in range(1, max_attempts + 1):
        img = _render(layer, size, extra)
        verdict = check_image(img, layer.role)
        verdict["attempts"] = attempt
        verdict["fixed"] = list(dict.fromkeys(fixed))
        if verdict["ok"]:
            break
        fixed.extend(verdict.get("blocking", []))
        log.info("layer %s attempt %d non-compliant: %s", layer.id, attempt, verdict.get("blocking"))
        extra = "STRICT CORRECTION: " + correction(verdict.get("blocking", []))
    assert img is not None
    if layer.transparent:
        img = imagegen.trim_transparent(img)
    version = layer_data.get("version", 0)
    path = _job_dir(job_id) / f"{layer.id}-{version}.png"
    (img if layer.transparent else img.convert("RGB")).save(path, optimize=True)
    rel = str(path.relative_to(s.data_dir))
    place_image(layer, img.width, img.height)
    return {"id": layer.id, "file": rel, "src": f"{s.public_api_url}/files/{rel}", "iw": img.width, "ih": img.height,
            "x": layer.x, "y": layer.y, "w": layer.w, "h": layer.h, "compliance": verdict}


def compose_and_audit(job_id: str, spec: DesignSpec) -> dict[str, Any]:
    """Final pass: brand-guard fixes, flattened PNG + thumbnail, vision QA."""
    s = get_settings()
    checks = guard.audit(spec, fix=True)
    out_dir = _job_dir(job_id)
    final = render(spec, 1.0).convert("RGB")
    final_path = out_dir / f"{spec.id}-final.png"
    final.save(final_path, optimize=True)
    thumb = final.copy()
    thumb.thumbnail((540, 540))
    thumb_path = out_dir / f"{spec.id}-thumb.jpg"
    thumb.save(thumb_path, quality=86)
    spec.preview_url = f"{s.public_api_url}/files/{thumb_path.relative_to(s.data_dir)}"
    spec.checks = checks
    qa = review(thumb_path.read_bytes())
    return {"spec": spec.model_dump(), "checks": checks, "summary": guard.summarize(checks), "qa": qa,
            "final_url": f"{s.public_api_url}/files/{final_path.relative_to(s.data_dir)}",
            "thumb_url": spec.preview_url}


def review(image: bytes) -> dict[str, Any]:
    """Art-director QA of the composite (vision). Never blocks delivery."""
    system = "You are a strict brand art director reviewing a Xero social ad. Return JSON only."
    user = [
        {"type": "text", "text": (
            "Rate this ad 1-10 for on-brand quality (Xero: navy/blue/sky palette, condensed bold headline, "
            "wordmark, blooms, authentic imagery) and visual polish (hierarchy, spacing, legibility). "
            "Return {\"score\": n, \"strengths\": [max 2 short items], \"issues\": [max 2 short, actionable items]}.")},
        llm.image_part(image, "image/jpeg"),
    ]
    try:
        out = llm.complete_json(system, user, tier="flash", temperature=0.1, max_tokens=500, attempts=2, timeout=25)
        return {"score": out.get("score"), "strengths": out.get("strengths", [])[:2], "issues": out.get("issues", [])[:2]}
    except Exception as e:  # QA is advisory
        log.warning("qa review failed: %s", e)
        return {"score": None, "strengths": [], "issues": []}
