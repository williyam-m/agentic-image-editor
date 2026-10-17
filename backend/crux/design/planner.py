"""Creative planner: user intent (+ brand knowledge, + optional reference) → validated Brief."""
from __future__ import annotations

import json
import logging
import zlib
from typing import Any

from .. import llm
from ..brand.kit import BLOOM_NAMES, FORMATS, RULES_TEXT, BrandKit
from ..brand.policy import copy_issues
from .brief import ARCHETYPE_GUIDE, DEFAULT_COLORWAY, Brief

log = logging.getLogger(__name__)

# Four deliberately different directions for "create 4 like this". Diversity is enforced in
# code (each variant gets its own layout archetype) rather than hoped for from the LLM.
VARIATION_DIRECTIONS = (
    "Stay closest to the inspiration: same layout and colourway, a fresh headline built on a different "
    "headline formula, and a new visual subject.",
    "Same message, different layout (given below); new copy angle.",
    "Different mood: the layout given below with a contrasting colourway and a different bloom; new visual.",
    "Bold and minimal: the layout given below, 2-4 word headline, one strong visual, no subhead, at most one charm.",
)
ARCHETYPE_ROTATION = ("card_photo", "photo_bloom", "navy_illustration", "device_showcase", "checklist")
ALT_COLORWAY = {"sky": "navy", "navy": "blue", "blue": "sky", "white": "navy"}


def variation_plan(base: dict[str, Any] | None, count: int) -> list[dict[str, Any]]:
    """Directions + forced archetype/colourway per variant so the set is visibly different."""
    base = base or {}
    first = base.get("archetype") if base.get("archetype") in ARCHETYPE_ROTATION else "card_photo"
    others = [a for a in ARCHETYPE_ROTATION if a != first]
    plans = [{"direction": VARIATION_DIRECTIONS[0], "archetype": first, "colorway": base.get("colorway")}]
    used = {base.get("bloom")}
    for i in range(1, count):
        arche = others[i - 1]
        colorway = None
        if i == 2:
            colorway = ALT_COLORWAY.get(DEFAULT_COLORWAY[arche], "navy")
        plans.append({"direction": VARIATION_DIRECTIONS[i], "archetype": arche, "colorway": colorway})
    # Give each variant its own bloom so a set never repeats the same brand shape.
    pool = [b for b in BLOOM_NAMES if b not in used]
    for i, p in enumerate(plans):
        p["bloom"] = pool[(zlib.crc32(str(base.get("headline")).encode()) + i * 5) % len(pool)]
    return plans[:count]


SCHEMA = """Return ONLY a JSON object:
{
 "name": "3-5 word design name",
 "archetype": "card_photo|navy_illustration|photo_bloom|device_showcase|checklist",
 "colorway": "sky|navy|blue|white",
 "headline": "2-8 words, sentence case, may be two short sentences",
 "subhead": "max 9 words or null",
 "cta": "2-4 words",
 "checklist": ["≤3 words", "...", "..."]  (exactly 3 items for checklist, else []),
 "visual": {"source": "asset|generate", "kind": "photo|illustration|device|cutout",
            "asset_id": "id from catalog or null", "prompt": "image prompt when source=generate, else null"},
 "bloom": "one of: %s",
 "wave": true|false,
 "charms": [{"asset_id": "charm id from catalog"}]  (0-2),
 "stat": {"label": "2-3 words", "value": "short figure e.g. £12,500"} or null,
 "rationale": "one sentence on why this works"
}""" % ", ".join(BLOOM_NAMES)

PROMPT_RULES = """Visual rules:
- card_photo and photo_bloom need a PHOTO: source=generate, kind=photo. The prompt must describe one specific,
  authentic small-business person (age, ethnicity, wardrobe), their workplace, the action, the emotion and natural
  light. Vary people and settings; never include text, screens with text, or logos in the prompt.
- navy_illustration needs an ILLUSTRATION: prefer a catalog illustration (source=asset) when one fits the message;
  otherwise source=generate, kind=illustration with a prompt naming 2-4 playful finance objects.
- device_showcase needs a DEVICE asset from the catalog (source=asset, kind=device).
- checklist has no hero visual (source=asset, asset_id=null) and needs exactly 3 checklist items.
- stat cards suit card_photo and photo_bloom when a number strengthens the message.
- Choose charms that echo the message (e.g. sparkle = new/magic, check = done, heart = love, clock = time).
- Pick the bloom that matches the message's energy (all 12 are on-brand); don't default to Harmony — vary it.
- Write like Xero: confident, warm, benefit-first, short.

Legal & compliance (enterprise, non-negotiable):
- Never use unapproved claims: guaranteed, best, #1 / number one, risk-free, free forever, 100%, cheapest,
  unlimited. Never mention competitors. No invented statistics presented as facts about real customers;
  stat cards must be framed as illustrative ("Average time to pay", "Cash flow forecast").
- Offers (free, trial, %, prices, vouchers) are allowed only in neutral wording; a "Terms apply." line is added
  automatically.
- Image prompts must never ask for text, logos, signage or readable screens."""


def _system(kit: BrandKit) -> str:
    ins = kit.insights or {}
    guide = "\n".join(f"- {k}: {v}" for k, v in ARCHETYPE_GUIDE.items())
    refs = "\n".join(
        f"- {r.get('id')}: \"{(r.get('headline') or '').replace(chr(10), ' ')}\" | {r.get('archetype')} | "
        f"{r.get('colorway')} | CTA \"{r.get('cta')}\" | visual: {r.get('visual')}"
        for r in kit.references
    )
    return "\n\n".join([
        "You are the Crux design copilot: a senior brand designer and copywriter producing on-brand Xero social ads.",
        RULES_TEXT,
        "Copy voice:\n" + "\n".join(f"- {v}" for v in ins.get("voice", [])),
        "Headline formulas:\n" + "\n".join(f"- {v}" for v in ins.get("headline_formulas", [])),
        "Approved CTAs: " + ", ".join(ins.get("cta_bank", [])),
        "Layout archetypes:\n" + guide,
        "Reference ads (the bar for quality and tone):\n" + refs,
        "Asset catalog (use exact ids):\n" + kit.prompt_catalog(("illustration", "device", "charm")),
        PROMPT_RULES,
        SCHEMA,
    ])


def _normalize(raw: dict[str, Any], kit: BrandKit, fmt: str, archetype: str | None = None,
               colorway: str | None = None) -> Brief:
    raw = dict(raw)
    raw["format"] = fmt
    if archetype in ARCHETYPE_GUIDE:
        raw["archetype"] = archetype
    if colorway in ("sky", "navy", "blue", "white"):
        raw["colorway"] = colorway
    archetype = raw.get("archetype")
    if archetype not in ARCHETYPE_GUIDE:
        archetype = raw["archetype"] = "card_photo"
    if raw.get("colorway") not in ("sky", "navy", "blue", "white"):
        raw["colorway"] = DEFAULT_COLORWAY[archetype]
    if archetype == "card_photo" and raw["colorway"] == "navy":
        raw["colorway"] = "sky"  # white card + navy text reads best on light backgrounds
    visual = dict(raw.get("visual") or {})
    asset = kit.get(visual.get("asset_id"))
    if archetype in ("card_photo", "photo_bloom"):
        visual.update(source="generate", kind="photo", asset_id=None)
        visual["prompt"] = visual.get("prompt") or f"a cheerful small-business owner, {raw.get('headline', '')}"
    elif archetype == "navy_illustration":
        if asset and asset.category == "illustration":
            visual.update(source="asset", kind="illustration")
        else:
            visual.update(source="generate", kind="illustration", asset_id=None)
            visual["prompt"] = visual.get("prompt") or "a laptop, coins and a rising bar chart"
    elif archetype == "device_showcase":
        if not (asset and asset.category == "device"):
            devices = kit.by_category("device")
            visual["asset_id"] = devices[0].id if devices else None
        visual.update(source="asset", kind="device")
    else:  # checklist
        visual = {"source": "asset", "kind": "illustration", "asset_id": None, "prompt": None}
        items = [i for i in raw.get("checklist") or [] if i][:3]
        raw["checklist"] = items if len(items) >= 2 else ["Invoices", "Payroll", "Me time"]
    raw["visual"] = visual
    raw["charms"] = [c for c in (raw.get("charms") or []) if isinstance(c, dict) and kit.get(c.get("asset_id"))][:2]
    if raw.get("subhead") in ("", "null"):
        raw["subhead"] = None
    stat = raw.get("stat")
    if not (isinstance(stat, dict) and stat.get("label") and stat.get("value")):
        raw["stat"] = None
    for key in ("headline", "cta"):
        raw[key] = str(raw.get(key) or "").strip().strip('"') or ("Run your business, not your books." if key == "headline" else "Try Xero for free")
    return Brief.model_validate(raw)


def plan(prompt: str, kit: BrandKit, *, fmt: str = "feed", reference: dict[str, Any] | None = None,
         base: dict[str, Any] | None = None, direction: str | None = None, variant: int = 0,
         archetype: str | None = None, colorway: str | None = None, bloom: str | None = None) -> Brief:
    parts = [f"Designer request: {prompt.strip() or 'Create an on-brand Xero ad.'}",
             f"Format: {FORMATS[fmt]['label']} ({FORMATS[fmt]['w']}x{FORMATS[fmt]['h']})."]
    if reference:
        ref = {k: reference.get(k) for k in ("headline", "subhead", "cta", "archetype", "colorway", "visual",
                                             "elements", "copy_angle", "layout_notes") if reference.get(k)}
        parts.append("Inspiration (create something NEW in this spirit; do not copy the headline verbatim):\n"
                     + json.dumps(ref, ensure_ascii=False))
    if base:
        keep = {k: base.get(k) for k in ("archetype", "colorway", "headline", "subhead", "cta", "checklist",
                                         "visual", "bloom", "charms", "stat")}
        parts.append("Current design brief (the starting point):\n" + json.dumps(keep, ensure_ascii=False))
    if direction:
        parts.append(f"Direction for this variation (#{variant + 1}): {direction}")
    if archetype:
        parts.append(f"Use the {archetype} archetype" + (f" with the {colorway} colourway." if colorway else "."))
    if bloom:
        parts.append(f"Use the {bloom.title()} Bloom.")
    system, user = _system(kit), "\n\n".join(parts)
    raw = llm.complete_json(system, user, tier="pro", temperature=0.85 if direction else 0.7, max_tokens=1600)
    if bloom:
        raw["bloom"] = bloom
    brief = _normalize(raw, kit, fmt, archetype, colorway)
    issues = copy_issues([brief.headline, brief.subhead or "", brief.cta, *brief.checklist,
                          brief.stat.label if brief.stat else ""])
    if issues:  # one corrective pass: the copy must clear legal before anything is drawn
        log.info("copy failed policy (%s); re-planning", "; ".join(i.detail for i in issues))
        feedback = ("\n\nYour previous answer broke the legal policy: " + "; ".join(i.detail for i in issues)
                    + ". Rewrite the copy without these, keeping everything else.")
        raw = llm.complete_json(system, user + feedback, tier="pro", temperature=0.5, max_tokens=1600)
        if bloom:
            raw["bloom"] = bloom
        brief = _normalize(raw, kit, fmt, archetype, colorway)
    log.info("planned %s/%s: %s", brief.archetype, brief.colorway, brief.headline)
    return brief


def describe_design(image_png: bytes) -> dict[str, Any]:
    """Vision deconstruction of an arbitrary design (e.g. a board rendered from the editor)."""
    from ..brand.ingest import ARCHETYPES

    system = "You are a senior performance-ad designer. Deconstruct the ad. Return JSON only."
    user = [
        {"type": "text", "text": (
            "Return JSON keys: headline, subhead, cta, archetype (one of " + ", ".join(ARCHETYPES) + "), "
            "colorway (sky|navy|blue|white), visual (max 15 words), elements (list), copy_angle (max 10 words), "
            "layout_notes (max 30 words).")},
        llm.image_part(image_png),
    ]
    return llm.complete_json(system, user, tier="flash", temperature=0.1, max_tokens=1200)
