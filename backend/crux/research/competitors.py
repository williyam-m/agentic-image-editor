"""Competitor analysis: what long-running ads in the category have in common, and on-brand ideas for us.

Longevity tiers (days active as the performance proxy):
  proven ≥ 90 days · testing 30–89 · new < 30.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .. import llm
from ..brand.kit import RULES_TEXT
from ..brand.policy import COMPETITORS, copy_issues
from ..config import get_settings
from ..design.brief import ARCHETYPE_GUIDE

log = logging.getLogger(__name__)


def tier(days: int | None) -> str:
    if days is None:
        return "unknown"
    return "proven" if days >= 90 else "testing" if days >= 30 else "new"


def analyze_ad(ad: dict[str, Any], category: str) -> dict[str, Any]:
    """Vision + copy read of one ad. Never blocks the run: failures return a minimal analysis."""
    s = get_settings()
    prompt = (
        f"You are a performance-creative strategist studying competitor ads in the “{category}” category.\n"
        f"Advertiser: {ad['advertiser']}. Format: {ad['media_type']}. Days running: {ad.get('days_active')}.\n"
        f"Ad copy: {ad.get('body', '')[:700]}\nCTA: {ad.get('cta')}\n"
        "Return JSON: {\"relevance\": 0-10 (how relevant to the category and to small-business finance software), "
        "\"hook\": \"the opening hook in max 10 words\", \"angle\": \"persuasion angle in max 8 words\", "
        "\"visual\": \"what the creative shows, max 14 words\", \"style\": \"visual style, max 8 words\", "
        "\"offer\": \"offer or null\", \"why_it_works\": \"max 18 words\", "
        "\"tags\": [3-5 lowercase tags e.g. ugc, testimonial, product-ui, stat, offer, founder, meme]}")
    content: str | list[dict[str, Any]] = prompt
    if ad.get("thumb_file"):
        content = [{"type": "text", "text": prompt}, llm.image_part((s.data_dir / ad["thumb_file"]).read_bytes(), "image/jpeg")]
    try:
        out = llm.complete_json("Return JSON only.", content, tier="flash", temperature=0.2, max_tokens=500,
                                attempts=2, timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("ad analysis failed for %s: %s", ad.get("library_id"), e)
        out = {"relevance": 5, "hook": (ad.get("body") or "")[:60], "angle": "", "visual": "", "style": "",
               "offer": None, "why_it_works": "", "tags": []}
    try:
        out["relevance"] = max(0, min(10, int(out.get("relevance", 5))))
    except (TypeError, ValueError):
        out["relevance"] = 5
    out["tags"] = [str(t)[:20] for t in (out.get("tags") or [])][:5]
    return out


def synthesize(category: str, ads: list[dict[str, Any]], kit_insights: dict[str, Any]) -> dict[str, Any]:
    relevant = [a for a in ads if (a.get("analysis") or {}).get("relevance", 5) >= 4] or ads
    relevant = sorted(relevant, key=lambda a: -(a.get("days_active") or 0))
    evidence = [{
        "id": a["library_id"], "advertiser": a["advertiser"], "days_active": a.get("days_active"),
        "tier": tier(a.get("days_active")), "variants": a.get("variants"), "format": a["media_type"],
        **{k: (a.get("analysis") or {}).get(k) for k in ("hook", "angle", "visual", "style", "offer", "tags")},
    } for a in relevant[:20]]
    banned = "guaranteed, best, #1, number one, risk-free, free forever, 100%, cheapest, unlimited"
    system = "\n\n".join([
        "You are Xero's head of creative strategy turning competitor research into original, on-brand ad ideas.",
        RULES_TEXT,
        "Xero copy voice: " + "; ".join((kit_insights or {}).get("voice", [])[:5]),
        "Layout archetypes you can use: " + "; ".join(f"{k}: {v}" for k, v in ARCHETYPE_GUIDE.items()),
        "Rules: ideas must be ORIGINAL for Xero — never copy a competitor's copy, claims, characters or branding; never "
        f"name competitors ({', '.join(COMPETITORS)} or any advertiser in the data); never use: {banned}. "
        "Weight patterns by longevity: 'proven' ads (90+ days live) are the strongest signal.",
    ])
    user = (f"Category: {category}\nCompetitor ads (sorted by days active):\n{json.dumps(evidence, ensure_ascii=False)}\n\n"
            "Return JSON: {\"summary\": \"2 sentences on what is working in this category\", "
            "\"patterns\": [{\"pattern\": \"max 8 words\", \"evidence\": \"which ads / how long they ran, max 18 words\", "
            "\"strength\": \"strong|medium|weak\"}] (4-6), "
            "\"whitespace\": [2-3 short opportunities nobody is owning], "
            "\"ideas\": [{\"title\": \"3-6 words\", \"headline\": \"2-8 words, Xero voice\", \"subhead\": \"max 9 words or null\", "
            "\"cta\": \"2-4 words\", \"archetype\": one of the archetypes, \"visual\": \"what to show, max 18 words\", "
            "\"why\": \"which pattern it borrows and why it will work, max 25 words\", \"inspired_by\": [ad ids]}] (5)}")
    out = llm.complete_json(system, user, tier="pro", temperature=0.6, max_tokens=3000)
    ideas = []
    for idea in out.get("ideas", []):
        if idea.get("archetype") not in ARCHETYPE_GUIDE:
            idea["archetype"] = "card_photo"
        if copy_issues([str(idea.get(k) or "") for k in ("headline", "subhead", "cta")]):
            continue  # legal policy: unapproved claims never reach the designer
        ideas.append(idea)
    out["ideas"] = ideas
    return out
