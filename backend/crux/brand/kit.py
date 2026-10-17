"""The brand kit: rules distilled from the guideline pages plus the analysed asset catalog.

Static rules (palette, type, logo usage, safe zones) are transcribed from the
Brand-Kit guideline boards and colour-sampled from the official assets. The
asset catalog itself is produced by :mod:`crux.brand.ingest` and loaded lazily.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..config import get_settings

# --- Palette (sampled from logo / bloom / background / charm files) -----------------
PALETTE: dict[str, str] = {
    "navy": "#000856",      # primary: text on light, dark backgrounds (WCAG AAA)
    "blue": "#1F65D6",      # Xero blue: blooms, background waves
    "sky": "#3ECCFF",       # secondary: logo on navy, highlights
    "sky_soft": "#6BC9F9",  # light-blue ad backgrounds
    "white": "#FFFFFF",
    "paper": "#F9F8F6",     # warm off-white cards
    # Accents — charms and illustration details only, never large fills.
    "mint": "#ABFFD1",
    "green": "#2DB879",
    "yellow": "#FFEF9F",
    "pink": "#FFC4D2",
    "lilac": "#D598FE",
}
PRIMARY_COLORS = ("navy", "blue", "sky", "sky_soft", "white", "paper")
ACCENT_COLORS = ("mint", "green", "yellow", "pink", "lilac")

# Background colourways → what goes on top of them.
COLORWAYS: dict[str, dict[str, str]] = {
    "sky":   {"bg": PALETTE["sky_soft"], "wave": PALETTE["blue"], "text": PALETTE["navy"], "logo": PALETTE["navy"],
              "card": PALETTE["white"], "cta_bg": PALETTE["navy"], "cta_text": PALETTE["white"]},
    "navy":  {"bg": PALETTE["navy"], "wave": PALETTE["blue"], "text": PALETTE["white"], "logo": PALETTE["white"],
              "card": PALETTE["white"], "cta_bg": PALETTE["sky_soft"], "cta_text": PALETTE["navy"]},
    "blue":  {"bg": PALETTE["blue"], "wave": PALETTE["sky_soft"], "text": PALETTE["white"], "logo": PALETTE["white"],
              "card": PALETTE["white"], "cta_bg": PALETTE["navy"], "cta_text": PALETTE["white"]},
    "white": {"bg": PALETTE["paper"], "wave": PALETTE["sky_soft"], "text": PALETTE["navy"], "logo": PALETTE["navy"],
              "card": PALETTE["white"], "cta_bg": PALETTE["navy"], "cta_text": PALETTE["white"]},
}

# --- Typography (Barlow is the closest OFL match to Xero's National 2 family) --------
FONTS = {
    "headline": {"family": "Barlow Condensed", "weight": "700", "file": "BarlowCondensed-Bold.ttf",
                 "line_height": 1.0, "letter_spacing": -0.5},
    "headline_bold": {"family": "Barlow Condensed", "weight": "700", "file": "BarlowCondensed-Bold.ttf",
                      "line_height": 1.0, "letter_spacing": -0.5},
    "body": {"family": "Barlow", "weight": "400", "file": "Barlow-Regular.ttf", "line_height": 1.3, "letter_spacing": 0},
    "body_medium": {"family": "Barlow", "weight": "500", "file": "Barlow-Medium.ttf", "line_height": 1.3, "letter_spacing": 0},
    "cta": {"family": "Barlow", "weight": "600", "file": "Barlow-SemiBold.ttf", "line_height": 1.0, "letter_spacing": 0.2},
}

# --- Canvas formats ----------------------------------------------------------------
FORMATS: dict[str, dict[str, Any]] = {
    "feed":      {"w": 1080, "h": 1350, "label": "Feed 4:5"},
    "square":    {"w": 1080, "h": 1080, "label": "Square 1:1"},
    "story":     {"w": 1080, "h": 1920, "label": "Story 9:16"},
    "landscape": {"w": 1200, "h": 628, "label": "Landscape 1.91:1"},
}

# Meta safe zones for 9:16 (from 17_Meta_Asset_Safe_Zones): keep text/logo inside.
STORY_SAFE = {"top": 0.14, "bottom": 0.35, "side": 0.06}

BLOOM_NAMES = ("peace", "energy", "x", "spark", "grow", "pulse",
               "harmony", "motion", "balance", "ease", "surge", "stride")

RULES_TEXT = """\
XERO BRAND RULES (follow strictly)
Palette: navy #000856 (primary; text on light, dark backgrounds), blue #1F65D6 (blooms, waves),
sky #3ECCFF (logo/highlights on navy), light-blue #6BC9F9 (ad backgrounds), white, warm paper #F9F8F6.
Accents mint/green/yellow/pink/lilac are for charms and small details only.
Logo: lowercase "xero" wordmark. Navy on light backgrounds; white or sky on navy/blue. Never recolour
outside these, never stretch, never place on busy photography (use the pill only when unavoidable).
Typography: headlines in a condensed bold sans, sentence case, short and punchy (2–8 words, often two
short sentences like "Data in. Doubt out."). Body copy in a clean sans, one short line. CTA is a small
rounded button with 2–4 words ("Try Xero for free", "Find out more").
Shapes: "Blooms" (Peace, Energy, X, Spark, Grow, Pulse, Harmony, Motion, Balance, Ease, Surge, Stride) are
organic shapes used as backgrounds, crops for photography and accents. Background templates are bold
blue waves on white/light blue.
Photography: authentic small-business owners at work, natural light, warm and optimistic, often cropped
inside a bloom shape. Illustrations: glossy 3D blue loops with playful objects; charms (sparkles, checks,
hearts, thumbs-up) add delight — at most 2 per design.
Accessibility: text contrast ≥ 4.5:1 (navy on light, white on navy/blue).
Stories (9:16): keep text and logo out of the top 14% and bottom 35%, 6% side margins.
"""


@dataclass(frozen=True)
class Asset:
    id: str
    category: str
    name: str
    file: str               # path relative to data/brand (or absolute for originals)
    width: int
    height: int
    has_alpha: bool
    colors: list[str]
    description: str = ""
    tags: tuple[str, ...] = ()
    vector: str | None = None   # path to normalised SVG (blooms, waves, logo)
    mask: str | None = None     # PNG alpha mask used for preview rendering of vectors

    def to_public(self) -> dict[str, Any]:
        s = get_settings()
        return {
            "id": self.id, "category": self.category, "name": self.name,
            "width": self.width, "height": self.height, "hasAlpha": self.has_alpha,
            "colors": self.colors, "description": self.description, "tags": list(self.tags),
            "url": f"{s.public_api_url}/files/brand/{self.file}",
            "vectorUrl": f"{s.public_api_url}/files/brand/{self.vector}" if self.vector else None,
        }


class BrandKit:
    def __init__(self, catalog: dict[str, Any]):
        self.catalog = catalog
        self.assets: dict[str, Asset] = {}
        for a in catalog.get("assets", []):
            a = dict(a)
            a["tags"] = tuple(a.get("tags", ()))
            self.assets[a["id"]] = Asset(**a)
        self.insights: dict[str, Any] = catalog.get("insights", {})
        self.references: list[dict[str, Any]] = catalog.get("references", [])

    def by_category(self, category: str) -> list[Asset]:
        return [a for a in self.assets.values() if a.category == category]

    def get(self, asset_id: str | None) -> Asset | None:
        return self.assets.get(asset_id or "")

    def bloom(self, name: str) -> Asset | None:
        return self.assets.get(f"bloom-{name}") or next(iter(self.by_category("bloom")), None)

    def logo(self) -> Asset | None:
        return self.assets.get("logo-xero")

    def path(self, asset: Asset, vector: bool = False) -> Any:
        rel = asset.vector if vector else asset.file
        return get_settings().brand_dir / rel  # type: ignore[operator]

    def prompt_catalog(self, categories: tuple[str, ...] = ("illustration", "charm", "device", "background")) -> str:
        """Compact, LLM-readable asset listing used by the planner."""
        lines: list[str] = []
        for cat in categories:
            items = self.by_category(cat)
            if not items:
                continue
            lines.append(f"[{cat}]")
            for a in items:
                desc = (a.description or a.name)[:110]
                lines.append(f"- {a.id}: {desc}")
        return "\n".join(lines)


@lru_cache
def _load_catalog_cached(mtime: float) -> BrandKit:
    path = get_settings().brand_dir / "catalog.json"
    return BrandKit(json.loads(path.read_text()))


def load_kit() -> BrandKit:
    path = get_settings().brand_dir / "catalog.json"
    if not path.exists():
        return BrandKit({"assets": []})
    return _load_catalog_cached(path.stat().st_mtime)
