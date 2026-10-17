"""Enterprise brand & legal policy — the non-negotiable rules every output must pass.

Used at generation time (planner, layout, image generation), edit time and audit
time (brand guard, Brand DNA). Deterministic where possible so it is auditable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .kit import FONTS, PALETTE

APPROVED_LOGO_COLORS = {PALETTE["navy"], PALETTE["white"], PALETTE["sky"]}
BRAND_FONT_FAMILIES = {f["family"] for f in FONTS.values()}
LEGAL_LINE = "Terms apply."

# Claims legal must approve case-by-case — never generated automatically.
BANNED_CLAIMS = (
    r"\bguarantee(d|s)?\b", r"\b#\s?1\b", r"\bnumber\s+one\b", r"\bbest\b", r"\brisk[- ]free\b",
    r"\bfree forever\b", r"\b100\s?%", r"\bno\.?\s?1\b", r"\bcheapest\b", r"\bunlimited\b",
)
COMPETITORS = ("quickbooks", "intuit", "myob", "sage", "freshbooks", "wave apps", "zoho books", "netsuite")
OFFER = re.compile(r"(\bfree\b|\d+\s?%|£\s?\d|\$\s?\d|€\s?\d|\bvoucher\b|\bdiscount\b|\btrial\b|\bper month\b)", re.I)

IMAGE_RULES = (
    "No text, letters, numbers, signage, logos, brand marks, watermarks or readable screens anywhere in the image. "
    "No competitor products or third-party branding. Wardrobe and key props in Xero blues (navy, blue, sky) or "
    "neutral whites/greys/denim; avoid dominant red, orange, purple or neon tones. Authentic, inclusive, "
    "optimistic small-business people; nothing unsafe, sexualised or political."
)


@dataclass
class CopyIssue:
    rule: str
    detail: str
    severity: str = "high"


def copy_issues(texts: list[str]) -> list[CopyIssue]:
    """Legal/copy violations in a set of on-canvas strings."""
    issues: list[CopyIssue] = []
    joined = " ".join(t for t in texts if t)
    low = joined.lower()
    for pat in BANNED_CLAIMS:
        m = re.search(pat, low)
        if m:
            issues.append(CopyIssue("legal_claim", f"Unapproved claim “{m.group(0).strip()}” needs legal sign-off"))
    for c in COMPETITORS:
        if c in low:
            issues.append(CopyIssue("competitor", f"Mentions competitor “{c}”"))
    return issues


def needs_legal_line(texts: list[str]) -> bool:
    joined = " ".join(t for t in texts if t)
    return bool(OFFER.search(joined)) and LEGAL_LINE.lower().rstrip(".") not in joined.lower()


def is_approved_logo_color(hex_color: str | None) -> bool:
    return bool(hex_color) and hex_color.upper() in {c.upper() for c in APPROVED_LOGO_COLORS}
