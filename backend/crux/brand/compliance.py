"""Generated-image compliance: every AI image is verified by a vision model before it
reaches the canvas, and regenerated when it breaks a rule (text, logos, off-palette…)."""
from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image

from .. import llm
from .policy import IMAGE_RULES

log = logging.getLogger(__name__)

# Violations that block delivery (trigger a regeneration).
BLOCKING = ("text", "logos", "watermark", "competitor", "unsafe")


def check_image(img: Image.Image, role: str) -> dict[str, Any]:
    """Return {"ok", "violations", "blocking", "notes", "verified"}. If the reviewer itself is
    unavailable the image passes but is marked unverified (rules are also in every prompt)."""
    thumb = img.copy()
    if thumb.mode == "RGBA":
        bg = Image.new("RGBA", thumb.size, (236, 236, 236, 255))
        bg.alpha_composite(thumb)
        thumb = bg
    thumb = thumb.convert("RGB")
    thumb.thumbnail((640, 640))
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=85)
    kind = "photograph" if role == "photo" else "illustration/icon"
    system = "You are a brand-compliance reviewer for an enterprise. Be strict and literal. Return JSON only."
    user = [
        {"type": "text", "text": (
            f"Review this AI-generated {kind} for a Xero ad against these rules: {IMAGE_RULES}\n"
            "Return JSON: {\"text\": bool (any visible letters/numbers/signage/readable screen), "
            "\"logos\": bool (any logo or brand mark), \"watermark\": bool, \"competitor\": bool, "
            "\"unsafe\": bool, \"off_palette\": bool (dominant colours clash with navy/blue/sky/white), "
            "\"notes\": \"max 20 words\"}")},
        llm.image_part(buf.getvalue(), "image/jpeg"),
    ]
    try:
        # Advisory and on the critical path of every image: fail fast, never block delivery.
        out = llm.complete_json(system, user, tier="flash", temperature=0.0, max_tokens=300, attempts=2, timeout=20)
    except Exception as e:  # noqa: BLE001
        log.warning("compliance review unavailable: %s", e)
        return {"ok": True, "violations": [], "blocking": [], "notes": "unverified (reviewer unavailable)",
                "verified": False}
    violations = [k for k in (*BLOCKING, "off_palette") if out.get(k) is True]
    blocking = [v for v in violations if v in BLOCKING or (v == "off_palette" and role != "photo")]
    return {"ok": not blocking, "violations": violations, "blocking": blocking,
            "notes": str(out.get("notes", ""))[:160], "verified": True}


def correction(blocking: list[str]) -> str:
    fixes = {
        "text": "There must be absolutely NO text, letters, numbers, signs, labels or readable screens.",
        "logos": "There must be NO logos or brand marks on clothing, devices, packaging or walls.",
        "watermark": "No watermark.",
        "competitor": "No third-party or competitor products or branding.",
        "unsafe": "Keep the scene wholesome and professional.",
        "off_palette": "Use only navy, blue, sky-blue and white tones with small accents.",
    }
    return " ".join(fixes[b] for b in blocking if b in fixes)
