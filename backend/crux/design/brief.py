"""Creative brief — what the planner LLM decides; the layout engine decides where things go."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..brand.kit import BLOOM_NAMES, FORMATS

Archetype = Literal["card_photo", "navy_illustration", "photo_bloom", "device_showcase", "checklist"]
Colorway = Literal["sky", "navy", "blue", "white"]

ARCHETYPE_GUIDE = {
    "card_photo": "White rounded card (headline, optional subhead, CTA) over a full-bleed lifestyle photo; "
                  "logo on a blue bloom accent. Best for human stories and relatable moments.",
    "navy_illustration": "Navy background with blue wave, big centred headline, central 3D brand illustration, "
                         "CTA bottom-left, logo bottom-right. Best for abstract benefits (all-in-one, growth).",
    "photo_bloom": "Solid navy/blue background, headline + CTA top-left, lifestyle photo cropped inside a large "
                   "organic bloom shape, optional floating stat card. Best for bold optimistic statements.",
    "device_showcase": "Light-blue background with blue wave, headline + CTA, a hand holding a phone/laptop/"
                       "tablet showing the Xero UI. Best for product features, ease of use, offers.",
    "checklist": "Navy background, headline, 3 white pill items with green checks (≤3 words each). Best for "
                 "listing jobs Xero handles (Payroll, Invoices, Tax).",
}

DEFAULT_COLORWAY: dict[str, str] = {
    "card_photo": "sky", "navy_illustration": "navy", "photo_bloom": "navy",
    "device_showcase": "sky", "checklist": "navy",
}


class Visual(BaseModel):
    source: Literal["asset", "generate"] = "generate"
    kind: Literal["photo", "illustration", "device", "cutout"] = "photo"
    asset_id: str | None = None
    prompt: str | None = None


class CharmPick(BaseModel):
    asset_id: str | None = None
    prompt: str | None = None


class Stat(BaseModel):
    label: str
    value: str


class Brief(BaseModel):
    name: str = "Xero ad"
    format: str = "feed"
    archetype: Archetype = "card_photo"
    colorway: Colorway = "sky"
    headline: str
    subhead: str | None = None
    cta: str = "Try Xero for free"
    checklist: list[str] = Field(default_factory=list)
    visual: Visual = Field(default_factory=Visual)
    bloom: str = "harmony"
    wave: bool = True
    charms: list[CharmPick] = Field(default_factory=list)
    stat: Stat | None = None
    rationale: str = ""

    @field_validator("format")
    @classmethod
    def _format(cls, v: str) -> str:
        return v if v in FORMATS else "feed"

    @field_validator("bloom")
    @classmethod
    def _bloom(cls, v: str) -> str:
        v = (v or "").lower().replace(" bloom", "").strip()
        return v if v in BLOOM_NAMES else "harmony"

    @field_validator("charms")
    @classmethod
    def _charms(cls, v: list[CharmPick]) -> list[CharmPick]:
        return v[:2]

    @field_validator("checklist")
    @classmethod
    def _checklist(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()][:4]
