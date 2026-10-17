"""End-to-end smoke test of the Crux backend (no browser needed).

Usage: .venv/bin/python scripts/smoke_test.py [create|variations|edit|all]
"""
from __future__ import annotations

import json
import sys
import time

import httpx

API = "http://localhost:8787"


def wait(job_id: str, timeout: float = 240) -> dict:
    t0 = time.time()
    seen = 0
    while time.time() - t0 < timeout:
        r = httpx.get(f"{API}/api/jobs/{job_id}", timeout=30).json()
        events = (r.get("progress") or {}).get("events", [])
        for e in events[seen:]:
            print(f"  [{e['t']:>5}s] {e['text']}")
        seen = len(events)
        if r["status"] != "running":
            print(f"  -> {r['status']} in {time.time() - t0:.1f}s")
            return r
        time.sleep(1)
    raise TimeoutError(job_id)


def show(r: dict) -> list[dict]:
    res = r.get("result") or {}
    for i, (spec, out) in enumerate(zip(res.get("specs", []), res.get("results", []))):
        out = out or {}
        print(f"  variant {i + 1}: {spec['brief'].get('archetype')} / {spec['brief'].get('colorway')} — "
              f"“{spec['brief'].get('headline')}”  brand {out.get('summary')}  qa {out.get('qa', {}).get('score')}")
        print(f"     final: {out.get('final_url')}")
        for c in out.get("checks", []):
            if c["status"] != "pass":
                print(f"     {c['status']:>5} {c['rule']}: {c['detail']}")
    return res.get("specs", [])


def create(fmt: str = "feed", prompt: str = "Promote automatic bank reconciliation for busy cafe owners") -> list[dict]:
    print(f"\n== create ({fmt})")
    job = httpx.post(f"{API}/api/designs", json={"prompt": prompt, "format": fmt}, timeout=30).json()["job_id"]
    return show(wait(job))


def variations() -> list[dict]:
    print("\n== variations (4 like ref-04)")
    job = httpx.post(f"{API}/api/designs", json={"prompt": "Create 4 different images like this", "count": 4,
                                                  "reference_id": "ref-04-70ed"}, timeout=30).json()["job_id"]
    return show(wait(job, 300))


def edit(spec: dict) -> None:
    print("\n== edit headline + photo")
    layers = [l for l in _walk(spec["layers"])]
    head = next(l for l in layers if l["role"] == "headline")
    photo = next((l for l in layers if l["role"] == "photo"), None)
    targets = [{"id": head["id"], "name": head["name"], "type": "text", "role": "headline", "x": head["x"],
                "y": head["y"], "w": head["w"], "h": head["h"], "text": head["text"], "font_size": head["font_size"],
                "color": head["color"]}]
    if photo:
        targets.append({"id": photo["id"], "name": "Photo", "type": "rect", "role": "photo", "x": photo["x"],
                        "y": photo["y"], "w": photo["w"], "h": photo["h"],
                        "image": {"file": photo.get("file"), "prompt": photo.get("prompt")}})
    body = {"instruction": "Make the headline about saving 5 hours a week, and make the person in the photo wear a yellow apron",
            "board": {"name": spec["name"], "width": spec["width"], "height": spec["height"], "brief": spec["brief"]},
            "targets": targets}
    job = httpx.post(f"{API}/api/edits", json=body, timeout=30).json()["job_id"]
    r = wait(job)
    print(json.dumps(r.get("result"), indent=1)[:1500])


def _walk(layers):
    for l in layers:
        yield l
        yield from _walk(l.get("children") or [])


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    specs = []
    if what in ("create", "all", "edit"):
        specs = create()
    if what in ("formats", "all"):
        for fmt in ("story", "landscape", "square"):
            create(fmt)
    if what in ("variations", "all"):
        variations()
    if what in ("edit", "all") and specs:
        edit(specs[0])
