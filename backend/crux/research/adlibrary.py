"""Meta Ad Library scraper (public, logged-out search) for competitor research.

Pulls ~15-20 ads for a category keyword and, for each, the creative (image, carousel frames or
video + poster), copy, advertiser and the "Started running on" date. Days active is used as a
rough performance proxy: advertisers tend to keep winning ads live and kill losers fast.

One browser session per scan, gentle scrolling, results cached — research use of a public tool.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")
LIBRARY = "https://www.facebook.com/ads/library/"

# Runs inside the page: one entry per ad card (anchored on its "Library ID: …" line).
EXTRACT_JS = r"""
() => {
  const leaves = [...document.querySelectorAll('span,div')]
    .filter(e => e.childElementCount === 0 && /^Library ID: \d+$/.test(e.textContent.trim()));
  const cards = [];
  for (const leaf of leaves) {
    let n = leaf, depth = 0;
    while (n && depth < 16) {
      n = n.parentElement; depth++;
      if (!n) break;
      const ids = n.textContent.match(/Library ID/g) || [];
      if (ids.length > 1) { n = null; break; }
      if (n.textContent.includes('Sponsored') && n.querySelector('img, video')) break;
    }
    if (!n) continue;
    const imgs = [...n.querySelectorAll('img')]
      .map(i => ({ src: i.currentSrc || i.src, w: i.naturalWidth || i.width, h: i.naturalHeight || i.height }))
      .filter(i => i.src && i.src.startsWith('http'));
    const avatar = imgs.find(i => i.w <= 80);
    const creatives = imgs.filter(i => i.w > 80).map(i => i.src);
    const videos = [...n.querySelectorAll('video')].map(v => ({ src: v.currentSrc || v.src || '', poster: v.poster || '' }));
    const links = [...n.querySelectorAll('a[href]')].map(a => a.href);
    cards.push({ text: n.innerText, avatar: avatar ? avatar.src : null, creatives, videos, links });
  }
  return cards;
}
"""

_DATE_FORMATS = ("%d %b %Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y")


def _parse_date(s: str) -> date | None:
    s = s.strip().rstrip(".")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_card(raw: dict[str, Any], today: date) -> dict[str, Any] | None:
    lines = [l.strip() for l in raw["text"].replace("​", "").split("\n")]
    lines = [l for l in lines if l]
    text = "\n".join(lines)
    m = re.search(r"Library ID: (\d+)", text)
    if not m:
        return None
    lib_id = m.group(1)
    started = ended = None
    m = re.search(r"Started running on (.+)", text)
    if m:
        started = _parse_date(m.group(1))
    else:
        m = re.search(r"\n([0-9A-Za-z ,]+?\d{4}) - ([0-9A-Za-z ,]+?\d{4})\n", text)
        if m:
            started, ended = _parse_date(m.group(1)), _parse_date(m.group(2))
    status = "active" if lines and lines[0].lower() == "active" else "inactive" if "Inactive" in lines[:3] else "unknown"
    variants = 1
    m = re.search(r"(\d+) ads use this creative", text)
    if m:
        variants = int(m.group(1))
    try:
        sp = lines.index("Sponsored")
        advertiser = lines[sp - 1]
        body_lines = lines[sp + 1:]
    except ValueError:
        advertiser, body_lines = "Unknown advertiser", []
    # Trailing link/CTA lines (e.g. "HTTPS://WWW.SITE.COM", "Learn more") are not body copy.
    cta, domain = None, None
    tail = []
    for l in body_lines:
        if re.match(r"^https?://", l, re.I) or re.match(r"^[A-Z0-9.-]+\.[A-Z]{2,}$", l):
            domain = domain or re.sub(r"^https?://(www\.)?", "", l, flags=re.I).split("/")[0].lower()
        elif l in ("Learn more", "Sign up", "Shop now", "Download", "Get offer", "Apply now", "Sign Up", "Learn More",
                   "Install now", "Book now", "Subscribe", "Get quote", "Contact us", "Open link", "Watch more"):
            cta = cta or l
        else:
            tail.append(l)
    body = "\n".join(tail).strip()
    end = ended or today
    days = (end - started).days if started else None
    video = next((v for v in raw.get("videos", []) if v.get("src", "").startswith("http")), None)
    poster = video["poster"] if video and video.get("poster") else None
    creatives = list(dict.fromkeys(raw.get("creatives") or []))
    media_type = "video" if raw.get("videos") else "carousel" if len(creatives) > 1 else "image" if creatives else "text"
    return {
        "library_id": lib_id, "advertiser": advertiser, "avatar": raw.get("avatar"), "status": status,
        "started": started.isoformat() if started else None, "ended": ended.isoformat() if ended else None,
        "days_active": days, "variants": variants, "body": body[:1200], "cta": cta, "domain": domain,
        "media_type": media_type, "video_url": video["src"] if video else None, "poster_url": poster,
        "image_urls": creatives[:6], "ad_url": f"{LIBRARY}?id={lib_id}",
    }


def search_url(query: str, country: str = "ALL", active_only: bool = False) -> str:
    params = {"active_status": "active" if active_only else "all", "ad_type": "all", "country": country,
              "is_targeted_country": "false", "media_type": "all", "q": query,
              "search_type": "keyword_unordered"}
    return f"{LIBRARY}?{urllib.parse.urlencode(params)}"


def _dismiss_overlays(page) -> None:
    for label in ("Allow all cookies", "Decline optional cookies", "Only allow essential cookies", "Accept All", "Close"):
        try:
            btn = page.get_by_role("button", name=label).first
            if btn.is_visible(timeout=500):
                btn.click(timeout=1500)
                page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001 - overlay not present
            pass


def scrape(query: str, country: str = "ALL", limit: int = 20, active_only: bool = False,
           timeout_s: float = 75) -> list[dict[str, Any]]:
    """Return up to ``limit`` distinct ads for ``query`` from the public Meta Ad Library."""
    from playwright.sync_api import sync_playwright

    today = date.today()
    ads: dict[str, dict[str, Any]] = {}
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1100}, locale="en-US", user_agent=UA)
        page = ctx.new_page()
        page.goto(search_url(query, country, active_only), wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)
        _dismiss_overlays(page)
        stale = 0
        while len(ads) < limit and time.time() - t0 < timeout_s and stale < 4:
            before = len(ads)
            for raw in page.evaluate(EXTRACT_JS):
                ad = parse_card(raw, today)
                if ad and ad["library_id"] not in ads:
                    ads[ad["library_id"]] = ad
            if len(ads) >= limit:
                break
            stale = stale + 1 if len(ads) == before else 0
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(1800)
        body_text = page.inner_text("body")[:2000]
        browser.close()
    if not ads:
        hint = "login wall" if "Log in" in body_text and "Library ID" not in body_text else "no results"
        raise RuntimeError(f"Meta Ad Library returned no ads for “{query}” ({hint}).")
    log.info("ad library: %d ads for %r in %.1fs", len(ads), query, time.time() - t0)
    return list(ads.values())[:limit]


def cache_media(ads: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    """Download each ad's lead creative (image / video poster) so it outlives Meta's signed URLs."""
    s = get_settings()
    folder = s.data_dir / "competitors" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=20, headers={"User-Agent": UA, "Referer": "https://www.facebook.com/"},
                      follow_redirects=True) as client:
        for ad in ads:
            url = ad.get("poster_url") or (ad["image_urls"][0] if ad.get("image_urls") else None)
            if not url:
                continue
            try:
                r = client.get(url)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                    name = f"{ad['library_id']}-{hashlib.md5(url.encode()).hexdigest()[:6]}.jpg"
                    path = folder / name
                    path.write_bytes(r.content)
                    rel = str(path.relative_to(s.data_dir))
                    ad["thumb_file"] = rel
                    ad["thumb_url"] = f"{s.public_api_url}/files/{rel}"
            except httpx.HTTPError as e:
                log.warning("media download failed for %s: %s", ad["library_id"], e)
    return ads


def slug(query: str, country: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{query}-{country}".lower()).strip("-")[:60]


def results_path(query: str, country: str) -> Path:
    return get_settings().data_dir / "competitors" / f"{slug(query, country)}.json"
