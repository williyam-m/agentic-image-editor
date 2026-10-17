"""Brand-kit ingestion: turn the raw Candidate-resources folder into an analysed catalog.

Steps (each is pure and idempotent so it can run as a Celery task under a
Temporal workflow, see :mod:`crux.workflows.brand`):

1. :func:`prepare_assets` – deterministic processing: vectorise blooms, waves and the
   wordmark; slice the charm sprite sheet into individual charms; rasterise SVG
   illustrations; copy bitmaps; extract dominant colours.
2. :func:`describe_batch` – vision model names/tags a numbered contact sheet of assets.
3. :func:`analyze_reference` – vision model deconstructs one reference ad.
4. :func:`synthesize_insights` – reasoning model distils brand voice + layout patterns.
5. :func:`write_catalog` – merge everything into ``data/brand/catalog.json``.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from .. import llm
from ..config import get_settings
from .kit import PALETTE, RULES_TEXT
from .vectorize import svg_document, trace_mask

log = logging.getLogger(__name__)

# Representative file (by numeric prefix + uuid start) for each named bloom on the
# "Blooms" guideline board. Colour variants of the same shape are skipped:
# vectors are recoloured at design time.
BLOOM_FILES = {
    "peace": "10_ebd4", "energy": "09_17be", "x": "11_a077", "spark": "12_5947",
    "grow": "20_a716", "pulse": "14_64a3", "harmony": "16_eae9", "motion": "15_9adc",
    "balance": "13_0e5f", "ease": "19_dbe5", "surge": "17_eb16", "stride": "18_013f",
}

ARCHETYPES = ("card_photo", "navy_illustration", "photo_bloom", "device_showcase", "checklist")


def _rel(p: Path) -> str:
    return str(p.relative_to(get_settings().brand_dir))


def _hex(rgb: tuple[int, ...]) -> str:
    return "#%02X%02X%02X" % tuple(rgb[:3])


def dominant_colors(im: Image.Image, n: int = 4) -> list[str]:
    im = im.convert("RGBA")
    im.thumbnail((96, 96))
    arr = np.asarray(im).reshape(-1, 4)
    arr = arr[arr[:, 3] > 200][:, :3]
    if len(arr) == 0:
        return []
    q = (arr // 24) * 24 + 12  # coarse quantisation keeps families together
    counts = Counter(map(tuple, q))
    return [_hex(c) for c, _ in counts.most_common(n)]


def _save_png(im: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)


def _crop_to_alpha(im: Image.Image, pad: int = 2) -> Image.Image:
    bbox = im.split()[-1].point(lambda v: 255 if v > 16 else 0).getbbox()
    if not bbox:
        return im
    l, t, r, b = bbox
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))


def _vector_asset(asset_id: str, category: str, name: str, mask: Image.Image, upscale: int,
                  description: str, tags: list[str], fill: str) -> dict[str, Any]:
    s = get_settings()
    d, w, h = trace_mask(mask, upscale=upscale)
    vec = s.brand_dir / "vectors" / f"{asset_id}.svg"
    vec.parent.mkdir(parents=True, exist_ok=True)
    vec.write_text(svg_document(d, w, h, fill))
    mask_path = s.brand_dir / "masks" / f"{asset_id}.png"
    _save_png(mask.convert("L"), mask_path)
    preview = Image.new("RGBA", mask.size, fill)
    preview.putalpha(mask.convert("L"))
    png = s.brand_dir / "assets" / category / f"{asset_id}.png"
    _save_png(preview, png)
    return {"id": asset_id, "category": category, "name": name, "file": _rel(png), "width": w, "height": h,
            "has_alpha": True, "colors": [fill], "description": description, "tags": tags,
            "vector": _rel(vec), "mask": _rel(mask_path)}


def _bitmap_asset(asset_id: str, category: str, name: str, im: Image.Image, **extra: Any) -> dict[str, Any]:
    s = get_settings()
    png = s.brand_dir / "assets" / category / f"{asset_id}.png"
    _save_png(im, png)
    has_alpha = im.mode == "RGBA" and im.getextrema()[-1][0] < 250
    return {"id": asset_id, "category": category, "name": name, "file": _rel(png), "width": im.width,
            "height": im.height, "has_alpha": has_alpha, "colors": dominant_colors(im),
            "description": extra.pop("description", ""), "tags": extra.pop("tags", []), **extra}


def _slice_sheet(sheet: Image.Image, min_size: int = 40) -> list[Image.Image]:
    """Cut a sprite sheet into individual charms (connected blobs of opaque pixels)."""
    alpha = np.asarray(sheet.split()[-1]) > 40
    core = ndimage.binary_opening(alpha, structure=np.ones((5, 5)))  # drops dashed guide boxes
    grouped = ndimage.binary_dilation(core, iterations=10)          # merges sparkle + small sparkle
    labels, _ = ndimage.label(grouped)
    out: list[Image.Image] = []
    for sl in ndimage.find_objects(labels):
        if sl is None:
            continue
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if h < min_size or w < min_size or h > 400 or w > 400:
            continue
        piece = sheet.crop((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop))
        # Remove any guide-box dashes that fall inside the crop.
        pa = np.asarray(piece).copy()
        keep = ndimage.binary_dilation(core[sl], iterations=3)
        pa[..., 3] = np.where(keep, pa[..., 3], 0)
        piece = _crop_to_alpha(Image.fromarray(pa), pad=3)
        if piece.width >= min_size * 0.6 and piece.height >= min_size * 0.6:
            out.append(piece)
    return out


def _rasterize_svgs(svgs: list[Path], width: int = 900) -> list[Image.Image]:
    from playwright.sync_api import sync_playwright

    images: list[Image.Image] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": width})
        for svg in svgs:
            page.set_content(
                "<html><body style='margin:0;background:transparent'>"
                f"<img id='i' style='width:{width}px;display:block' src='data:image/svg+xml;base64,"
                + __import__("base64").b64encode(svg.read_bytes()).decode() + "'></body></html>")
            page.wait_for_selector("#i")
            png = page.locator("#i").screenshot(omit_background=True)
            images.append(_crop_to_alpha(Image.open(io.BytesIO(png)).convert("RGBA")))
        browser.close()
    return images


def _wave_profile(mask: np.ndarray) -> tuple[str, list[str]]:
    """Describe where a wave's mass sits so layouts can keep text on the free side."""
    h, w = mask.shape
    cov = mask.mean()
    zones = {"top": mask[: h // 3].mean(), "bottom": mask[-h // 3:].mean(),
             "left": mask[:, : w // 3].mean(), "right": mask[:, -w // 3:].mean()}
    heavy = [k for k, v in sorted(zones.items(), key=lambda kv: -kv[1]) if v > 0.35][:2]
    shape = "portrait" if h > w * 1.3 else "square"
    where = " and ".join(heavy) if heavy else "scattered"
    desc = f"{shape} background wave, blue shape weighted {where}, {cov:.0%} coverage; free space opposite"
    return desc, ["background", "wave", shape, f"cov{int(cov * 100)}", *[f"heavy-{z}" for z in heavy]]


def source_fingerprint() -> str:
    s = get_settings()
    h = hashlib.sha1()
    for root in (s.brand_kit_dir, s.references_dir):
        for p in sorted(root.rglob("*")):
            if p.is_file():
                h.update(f"{p.relative_to(root)}:{p.stat().st_size}".encode())
    h.update(b"v5")
    return h.hexdigest()


def prepare_assets() -> dict[str, Any]:
    """Deterministic processing. Returns the draft asset list and the vision work items."""
    s = get_settings()
    kit_dir = s.brand_kit_dir
    for sub in ("assets", "vectors", "masks"):
        shutil.rmtree(s.brand_dir / sub, ignore_errors=True)
    assets: list[dict[str, Any]] = []

    # 1) Wordmark → vector (traced from the navy master at 8x for smooth curves).
    logo = Image.open(next((kit_dir / "10_Logo").glob("02_*.png"))).convert("RGBA")
    assets.append(_vector_asset("logo-xero", "logo", "Xero wordmark", logo.split()[-1], 8,
                                "Official lowercase xero wordmark (navy/white/sky colourways)",
                                ["logo", "wordmark"], PALETTE["navy"]))

    # 2) Named blooms → vectors.
    bloom_dir = kit_dir / "06_Shapes_Cropping_Blooms"
    for name, prefix in BLOOM_FILES.items():
        f = next(bloom_dir.glob(f"{prefix}*.png"), None)
        if not f:
            continue
        im = _crop_to_alpha(Image.open(f).convert("RGBA"), pad=1)
        assets.append(_vector_asset(f"bloom-{name}", "bloom", f"{name.title()} Bloom", im.split()[-1], 2,
                                    f"{name.title()} Bloom organic brand shape (crop frame or accent)",
                                    ["bloom", name], PALETTE["blue"]))

    # 3) Background templates → wave vectors (blue region of each template).
    for i, f in enumerate(sorted((kit_dir / "24_Background_Templates").glob("*.png")), 1):
        rgb = np.asarray(Image.open(f).convert("RGB")).astype(int)
        mask = (np.abs(rgb - [31, 101, 214]).sum(-1) < 120)
        if mask.mean() < 0.05:
            continue
        m = Image.fromarray((mask * 255).astype("uint8"))
        desc, tags = _wave_profile(mask)
        assets.append(_vector_asset(f"bg-wave-{i:02d}", "background", f"Background wave {i:02d}", m, 2,
                                    desc, tags, PALETTE["blue"]))

    # 4) Illustrations: 3D bitmaps + SVG originals (rasterised for previews).
    vision: list[dict[str, str]] = []
    ill_dir = kit_dir / "07_Illustration"
    for f in sorted(ill_dir.glob("*.png")):
        im = Image.open(f).convert("RGBA")
        if im.height > 2 * im.width:  # the charm sprite sheet is duplicated here; sliced below
            continue
        a = _bitmap_asset(f"illus-{f.name[:2]}", "illustration", f"Illustration {f.name[:2]}", _crop_to_alpha(im))
        assets.append(a)
        vision.append({"id": a["id"], "file": a["file"]})
    svgs = sorted(ill_dir.glob("*.svg"))
    for f, im in zip(svgs, _rasterize_svgs(svgs)):
        label = f.stem.split("_", 2)[-1].replace("_", " ")
        a = _bitmap_asset(f"illus-{f.name[:2]}", "illustration", f"{label} illustration", im,
                          description=f"Flat spot illustration: {label.lower()}", tags=["illustration", "flat"])
        assets.append(a)
        vision.append({"id": a["id"], "file": a["file"]})

    # 5) Charms: individual files + sliced sprite sheet(s).
    charm_dir = kit_dir / "22_Charms"
    charms: list[Image.Image] = []
    sliced: set[str] = set()
    for f in sorted(charm_dir.glob("*.png")):
        im = Image.open(f).convert("RGBA")
        if im.height > 2 * im.width:
            digest = hashlib.md5(f.read_bytes()).hexdigest()
            if digest not in sliced:
                charms.extend(_slice_sheet(im))
                sliced.add(digest)
        else:
            charms.append(_crop_to_alpha(im))
    for i, im in enumerate(charms, 1):
        a = _bitmap_asset(f"charm-{i:03d}", "charm", f"Charm {i:03d}", im)
        assets.append(a)
    charm_ids = [a["id"] for a in assets if a["category"] == "charm"]

    # 6) Product UI device shots (hands holding phone / laptop / tablet with the Xero UI).
    for f in sorted((kit_dir / "11_Product_UI_References").glob("*.png")):
        im = _crop_to_alpha(Image.open(f).convert("RGBA"))
        im.thumbnail((1600, 1600))
        a = _bitmap_asset(f"device-{f.name[:2]}-{f.name[3:7]}", "device", f"Product UI {f.name[:2]}", im)
        assets.append(a)
        vision.append({"id": a["id"], "file": a["file"]})

    # 7) Reference ads (inspiration library).
    refs: list[dict[str, Any]] = []
    for f in sorted(s.references_dir.glob("*.png")):
        im = Image.open(f).convert("RGB")
        a = _bitmap_asset(f"ref-{f.name[:2]}-{f.name[3:7]}", "reference", f"Reference ad {f.name[:2]}", im)
        assets.append(a)
        refs.append({"id": a["id"], "file": a["file"]})

    return {"assets": assets, "vision": vision, "charm_ids": charm_ids, "references": refs}


# ---------------------------------------------------------------------------------
# Vision analysis
# ---------------------------------------------------------------------------------

def _contact_sheet(files: list[str], cell: int = 220) -> bytes:
    s = get_settings()
    cols = 6
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (236, 236, 236))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(s.fonts_dir / "Barlow-Bold.ttf"), 26)
    except OSError:
        font = ImageFont.load_default()
    for i, rel in enumerate(files):
        im = Image.open(s.brand_dir / rel).convert("RGBA")
        im.thumbnail((cell - 30, cell - 40))
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(im, (x + (cell - im.width) // 2, y + 34 + (cell - 40 - im.height) // 2), im)
        draw.text((x + 8, y + 4), str(i + 1), fill=(220, 30, 30), font=font)
    buf = io.BytesIO()
    sheet.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def describe_batch(items: list[dict[str, str]], kind: str) -> dict[str, dict[str, Any]]:
    """Name and tag a batch of assets using one numbered contact sheet (one vision call)."""
    sheet = _contact_sheet([it["file"] for it in items])
    system = ("You are a brand librarian cataloguing the Xero brand asset library. Be concrete and short. "
              "Return JSON only.")
    user = [
        {"type": "text", "text": (
            f"The image is a numbered contact sheet of {len(items)} {kind} assets (red numbers 1..{len(items)}). "
            "For EVERY number return: name (2-5 words, e.g. 'blue check mark charm'), "
            "description (max 18 words: subject, style, colours, best use in an ad), "
            "tags (3-6 lowercase keywords). Format: {\"items\":[{\"n\":1,\"name\":...,\"description\":...,\"tags\":[...]}]}")},
        llm.image_part(sheet, "image/jpeg"),
    ]
    out = llm.complete_json(system, user, tier="flash", temperature=0.2, max_tokens=6000)
    result: dict[str, dict[str, Any]] = {}
    for row in out.get("items", []):
        try:
            idx = int(row["n"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(items):
            result[items[idx]["id"]] = {
                "name": str(row.get("name", ""))[:60],
                "description": str(row.get("description", ""))[:200],
                "tags": [str(t)[:24] for t in row.get("tags", [])][:6],
            }
    return result


def analyze_reference(item: dict[str, str]) -> dict[str, Any]:
    s = get_settings()
    system = "You are a senior performance-ad designer deconstructing on-brand Xero social ads. Return JSON only."
    user = [
        {"type": "text", "text": (
            "Deconstruct this ad into JSON with keys: headline (exact text), subhead (exact or null), "
            "cta (exact button text or null), archetype (one of: " + ", ".join(ARCHETYPES) + "; "
            "card_photo = white rounded card with headline+CTA over a photo; navy_illustration = navy background, "
            "big headline + central 3D illustration; photo_bloom = headline over solid colour with a photo cropped "
            "in an organic bloom shape; device_showcase = hand holding phone/laptop with Xero UI; checklist = "
            "headline + list of pill items with check marks), colorway (sky|navy|blue|white = dominant background), "
            "visual (what the main image shows, max 15 words), elements (list of notable elements e.g. 'stat card', "
            "'sparkle charm', 'logo bottom-left'), copy_angle (the persuasion angle, max 10 words), "
            "layout_notes (max 30 words: positions of headline, visual, CTA, logo).")},
        llm.image_part(s.brand_dir / item["file"]),
    ]
    out = llm.complete_json(system, user, tier="flash", temperature=0.1, max_tokens=1500)
    out["id"] = item["id"]
    out["file"] = item["file"]
    if out.get("archetype") not in ARCHETYPES:
        out["archetype"] = "card_photo"
    return out


def synthesize_insights(references: list[dict[str, Any]]) -> dict[str, Any]:
    compact = [{k: r.get(k) for k in ("headline", "subhead", "cta", "archetype", "colorway", "copy_angle")}
               for r in references]
    system = "You are Xero's brand strategist. Distil practical creative guidance. Return JSON only."
    user = (RULES_TEXT + "\n\nAnalysed reference ads:\n" + json.dumps(compact, ensure_ascii=False) +
            "\n\nReturn JSON: {\"voice\": [4-6 short bullet rules for copy tone], "
            "\"headline_formulas\": [5 reusable patterns with an example each], "
            "\"cta_bank\": [8 on-brand CTA labels], "
            "\"layout_patterns\": [{\"archetype\":...,\"when_to_use\":...}], "
            "\"do\": [5 rules], \"dont\": [5 rules], \"summary\": \"2 sentences\"}")
    return llm.complete_json(system, user, tier="pro", temperature=0.3, max_tokens=3000)


def write_catalog(draft: dict[str, Any], descriptions: dict[str, dict[str, Any]],
                  references: list[dict[str, Any]], insights: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    assets = []
    for a in draft["assets"]:
        d = descriptions.get(a["id"])
        if d:
            a = {**a, "name": d.get("name") or a["name"], "description": d.get("description") or a["description"],
                 "tags": d.get("tags") or a["tags"]}
        assets.append(a)
    catalog = {"version": 1, "fingerprint": source_fingerprint(), "assets": assets,
               "references": references, "insights": insights}
    path = s.brand_dir / "catalog.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, indent=1, ensure_ascii=False))
    tmp.replace(path)
    log.info("catalog written: %d assets, %d references", len(assets), len(references))
    return {"assets": len(assets), "references": len(references)}


def catalog_is_fresh() -> bool:
    path = get_settings().brand_dir / "catalog.json"
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text()).get("fingerprint") == source_fingerprint()
    except (OSError, json.JSONDecodeError):
        return False


def batches(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def run_local(max_workers: int = 12) -> dict[str, Any]:
    """Run the full ingestion in-process (used when Temporal/Celery are not up yet)."""
    from concurrent.futures import ThreadPoolExecutor

    draft = prepare_assets()
    by_id = {a["id"]: a for a in draft["assets"]}
    charm_items = [{"id": i, "file": by_id[i]["file"]} for i in draft["charm_ids"]]
    jobs = [(b, "charm") for b in batches(charm_items, 30)] + [(b, "illustration/product") for b in batches(draft["vision"], 12)]
    descriptions: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers) as ex:
        for part in ex.map(lambda j: describe_batch(*j), jobs):
            descriptions.update(part)
        references = list(ex.map(analyze_reference, draft["references"]))
    insights = synthesize_insights(references)
    return write_catalog(draft, descriptions, references, insights)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run_local())
