"""Browser E2E for Crux Studio (Playwright).

Every scenario runs in the real editor; the render-fidelity check compares the live canvas
pixels with the server compositor's PNG of the same board (they must match).
Usage: .venv/bin/python tests/e2e_studio.py [create|edit|photo|comment|comment-ui|variations|upload|dna|manual|voice|intel|all]
The voice scenario feeds tests/fixtures/voice_edit_headline.wav through Chromium's fake microphone.
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "e2e"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8787"
# Tests never touch the designer's own document: each run uses a throwaway one.
DOC = f"e2e-{int(time.time())}"


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"))
    print(f"   screenshot {name}.png")


def ask(page: Page, text: str) -> None:
    page.fill("[data-testid=chat-input]", text)
    page.press("[data-testid=chat-input]", "Enter")


def wait_count(page: Page, selector: str, n: int, timeout: float = 240) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if page.locator(selector).count() >= n:
            return time.time() - t0
        err = page.locator(".error-note")
        if err.count():
            raise RuntimeError(err.last.inner_text())
        time.sleep(0.5)
    raise TimeoutError(selector)


def state(page: Page) -> dict:
    return page.evaluate("() => { const s = window.__crux.getState(); return {doc: s.doc, active: s.activeBoardId, selection: s.selection}; }")


def active_board(page: Page) -> dict:
    s = state(page)
    return next(b for b in s["doc"]["boards"] if b["id"] == s["active"])


def fidelity(page: Page, name: str) -> float:
    """Mean per-channel difference (0-255) between canvas pixels and the server composite."""
    board = active_board(page)
    page.evaluate("() => window.__crux.setUi({ selection: null, openComment: null, commentDraft: null, tool: 'select' })")
    page.mouse.move(2, 2)  # no hover outline over the board
    page.wait_for_timeout(1200)
    canvas = Image.open(io.BytesIO(page.locator(".board-frame").screenshot())).convert("RGB")
    url = httpx.post(f"{URL}/api/render", json={"spec": board, "scale": 1}, timeout=60).json()["url"]
    server = Image.open(io.BytesIO(httpx.get(url).content)).convert("RGB")
    size = (270, round(270 * board["height"] / board["width"]))
    a, b = canvas.resize(size, Image.LANCZOS), server.resize(size, Image.LANCZOS)
    diff = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
    side = Image.new("RGB", (size[0] * 2 + 10, size[1]), "white")
    side.paste(a, (0, 0)); side.paste(b, (size[0] + 10, 0))
    side.save(OUT / f"{name}-fidelity.png")
    return diff


def main(what: str) -> None:
    with sync_playwright() as p:
        voice_wav = ROOT / "tests" / "fixtures" / "voice_edit_headline.wav"
        browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                          f"--use-file-for-fake-audio-capture={voice_wav}"])
        page = browser.new_context(viewport={"width": 1680, "height": 1000}, permissions=["microphone"]).new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{URL}/studio?doc={DOC}")
        page.wait_for_selector("[data-testid=chat-input]")
        print("✓ studio loaded")

        ask(page, "Feed ad: tradies get paid faster with Xero invoicing")
        dt = wait_count(page, ".design-card .dot.done", 1)
        print(f"✓ create finished in {dt:.1f}s")
        board = active_board(page)
        imgs = [l for l in _walk(board["layers"]) if l["kind"] == "image"]
        assert imgs and all(l.get("status") == "ready" and l.get("src") for l in imgs), "image layers not ready"
        loaded = page.evaluate("""() => Promise.all([...document.querySelectorAll('.board-frame image')].map(i => new Promise(r => {
            const im = new Image(); im.onload = () => r(im.naturalWidth); im.onerror = () => r(0); im.src = i.getAttribute('href'); })))""")
        print(f"✓ {len(loaded)} image layers rendered on canvas, all loaded: {all(w > 0 for w in loaded)}")
        assert loaded and all(w > 0 for w in loaded)
        d = fidelity(page, "create")
        print(f"✓ canvas vs server render: mean pixel diff {d:.1f}/255")
        assert d < 12, f"canvas does not match the composite ({d:.1f})"
        shot(page, "s01-created")

        if what in ("edit", "all"):
            head = next(l for l in _walk(active_board(page)["layers"]) if l["role"] == "headline")
            page.evaluate(f"() => window.__crux.setUi({{ selection: '{head['id']}' }})")
            n = page.locator(".edit-card .dot.done").count() + 1
            ask(page, "Make this headline about getting paid in days, not weeks")
            dt = wait_count(page, ".edit-card .dot.done", n, 120)
            new = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == head["id"])
            print(f"✓ layer edit in {dt:.1f}s: “{head['text']}” → “{new['text']}”")
            assert new["text"] != head["text"]
            shot(page, "s02-edited")

        if what in ("voice", "all"):
            if not httpx.get(f"{URL}/api/voice/status").json().get("enabled"):
                print("- voice skipped: add ELEVENLABS_API_KEY to .env and restart to test speak-to-edit")
            else:
                head = next(l for l in _walk(active_board(page)["layers"]) if l["role"] == "headline")
                # Start from a known headline so the spoken change is unambiguous.
                page.evaluate("""(id) => window.__crux.mutate(d => { for (const b of d.boards) for (const l of b.layers)
                    if (l.id === id) l.text = "Placeholder headline."; })""", head["id"])
                head["text"] = "Placeholder headline."
                page.evaluate(f"() => window.__crux.setUi({{ selection: '{head['id']}' }})")
                n = page.locator(".edit-card .dot.done").count() + 1
                page.click("[data-testid=voice-btn]")  # then speak: "Make the headline say get paid in days, not weeks."
                page.wait_for_selector(".voice-strip.listening", timeout=8000)
                dt = wait_count(page, ".edit-card .dot.done", n, 120)
                heard = page.locator(".msg.user .bubble").last.inner_text()
                new = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == head["id"])
                print(f"✓ voice edit in {dt:.1f}s · heard “{heard}” · headline now “{new['text']}”")
                assert "day" in new["text"].lower() and new["text"] != head["text"]

        if what in ("photo", "all"):
            photo = next(l for l in _walk(active_board(page)["layers"]) if l["role"] == "photo")
            page.evaluate(f"() => window.__crux.setUi({{ selection: '{photo['id']}' }})")
            n = page.locator(".edit-card .dot.done").count() + 1
            ask(page, "Change the lighting to warm golden-hour sunset light")
            dt = wait_count(page, ".edit-card .dot.done", n, 180)
            new = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == photo["id"])
            print(f"✓ photo edit in {dt:.1f}s, new pixels: {new['src'] != photo['src']}")
            assert new["src"] != photo["src"]
            print(f"✓ fidelity after photo edit: {fidelity(page, 'photo'):.1f}/255")
            shot(page, "s03-photo")

        if what in ("comment", "all"):
            cta = next(l for l in _walk(active_board(page)["layers"]) if l["role"] == "cta_label")
            page.click("[data-testid=tool-comment]")
            frame = page.locator(".board-frame").bounding_box()
            b = active_board(page)
            z = frame["width"] / b["width"]
            page.mouse.click(frame["x"] + (cta["x"] + cta["w"] / 2) * z, frame["y"] + (cta["y"] + cta["h"] / 2) * z)
            page.fill("[data-testid=comment-input]", "change this button to say Start your free trial")
            n = page.locator(".edit-card .dot.done").count() + 1
            page.press("[data-testid=comment-input]", "Enter")
            dt = wait_count(page, ".edit-card .dot.done", n, 120)
            new = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == cta["id"])
            c = state(page)["doc"]["comments"][-1]
            print(f"✓ comment edit in {dt:.1f}s on “{cta['name']}”: “{new['text']}” · thread: {c['status']} · {c['thread'][-1]['text'][:70]}")
            assert new["text"] != cta["text"] and c["status"] == "resolved" and c["layerId"] == cta["id"]
            page.keyboard.press("v")
            shot(page, "s04-comment")

        if what in ("comment-ui", "all"):
            frame = page.locator(".board-frame").bounding_box()
            page.click("[data-testid=tool-comment]")
            page.mouse.click(frame["x"] + frame["width"] * 0.5, frame["y"] + frame["height"] * 0.6)
            page.wait_for_selector("[data-testid=comment-input]")
            page.click("[data-testid=tool-text]")
            gone_on_tool = page.locator(".comment-pop").count() == 0
            page.click("[data-testid=tool-comment]")
            page.mouse.click(frame["x"] + frame["width"] * 0.4, frame["y"] + frame["height"] * 0.5)
            page.wait_for_selector("[data-testid=comment-close]")
            page.click("[data-testid=comment-close]")
            gone_on_close = page.locator(".comment-pop").count() == 0
            page.mouse.click(frame["x"] + frame["width"] * 0.4, frame["y"] + frame["height"] * 0.5)
            page.wait_for_selector("[data-testid=comment-input]")
            page.keyboard.press("Escape")
            gone_on_esc = page.locator(".comment-pop").count() == 0
            print(f"✓ comment box closes on tool switch: {gone_on_tool} · × button: {gone_on_close} · Esc: {gone_on_esc}")
            assert gone_on_tool and gone_on_close and gone_on_esc
            page.click("[data-testid=tool-select]")

        if what in ("manual", "all"):
            head = next(l for l in _walk(active_board(page)["layers"]) if l["role"] == "headline")
            frame = page.locator(".board-frame").bounding_box()
            z = frame["width"] / active_board(page)["width"]
            cx, cy = frame["x"] + (head["x"] + 20) * z, frame["y"] + (head["y"] + 20) * z
            page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 40, cy + 30, steps=8); page.mouse.up()
            moved = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == head["id"])
            print(f"✓ drag moved headline by ({moved['x'] - head['x']:.0f}, {moved['y'] - head['y']:.0f}) board px")
            assert moved["x"] > head["x"] + 20
            page.keyboard.press("Meta+z")
            back = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == head["id"])
            print(f"✓ undo restored position: {abs(back['x'] - head['x']) < 0.5}")
            assert abs(back["x"] - head["x"]) < 0.5
            page.mouse.dblclick(cx, cy)
            page.wait_for_selector(".inline-text")
            page.fill(".inline-text", "Typed by hand.")
            page.keyboard.press("Escape")
            typed = next(l for l in _walk(active_board(page)["layers"]) if l["id"] == head["id"])
            print(f"✓ inline text edit: “{typed['text']}”")
            assert typed["text"] == "Typed by hand."
            print(f"✓ fidelity after manual edits: {fidelity(page, 'manual'):.1f}/255")

        if what in ("variations", "all"):
            page.evaluate("() => window.__crux.setUi({ selection: null })")
            n = page.locator(".design-card .dot.done").count() + 1
            before = len(state(page)["doc"]["boards"])
            ask(page, "Create 4 different images like this")
            dt = wait_count(page, ".design-card .dot.done", n, 300)
            boards = state(page)["doc"]["boards"]
            print(f"✓ variations in {dt:.1f}s: {len(boards) - before} new boards · "
                  + ", ".join(sorted({b['brief'].get('archetype', '?') for b in boards[before:]})))
            assert len(boards) - before == 4
            print(f"✓ fidelity of a variation: {fidelity(page, 'variation'):.1f}/255")
            shot(page, "s05-variations")

        if what in ("upload", "all"):
            ref = sorted((ROOT / "Candidate-resources" / "Image_Ad_References").glob("*.png"))[0]
            page.evaluate("() => window.__crux.setUi({ selection: null })")
            layers_before = sum(len(list(_walk(b["layers"]))) for b in state(page)["doc"]["boards"])
            # Dropping an image on the composer attaches it as a reference (not as a canvas layer).
            page.evaluate("""async (url) => {
                const blob = await (await fetch(url)).blob();
                const dt = new DataTransfer();
                dt.items.add(new File([blob], 'dropped.png', { type: 'image/png' }));
                const el = document.querySelector('.composer');
                for (const type of ['dragenter', 'dragover', 'drop'])
                    el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
            }""", f"{URL}/favicon.png")
            page.wait_for_selector("[data-testid=ref-attach]", timeout=10_000)
            assert sum(len(list(_walk(b["layers"]))) for b in state(page)["doc"]["boards"]) == layers_before, \
                "dropping on the composer added a canvas layer"
            page.click("[data-testid=ref-remove]")
            assert page.locator("[data-testid=ref-attach]").count() == 0
            print("✓ drop on composer attaches a reference (no canvas layer added); remove works")

            page.set_input_files("[data-testid=ref-file]", str(ref))
            page.wait_for_selector("[data-testid=ref-attach]", timeout=10_000)
            assert "4 variations of your image" in page.locator(".context-chip").text_content()
            page.click("[data-testid=ref-count-2]")
            assert "2 variations of your image" in page.locator(".context-chip").text_content()
            n = page.locator(".design-card .dot.done").count() + 1
            before = len(state(page)["doc"]["boards"])
            page.click(".send")
            dt = wait_count(page, ".design-card .dot.done", n, 300)
            boards = state(page)["doc"]["boards"][before:]
            print(f"✓ uploaded-image variations in {dt:.1f}s: {len(boards)} new boards · "
                  + ", ".join(f"{b['brief'].get('archetype')}/{b['brief'].get('colorway')}" for b in boards))
            assert len(boards) == 2
            assert page.locator(".msg.user .ref-sent").count() >= 1, "reference thumbnail missing from the chat"
            assert page.locator("[data-testid=ref-attach]").count() == 0, "attachment not cleared after sending"
            print(f"✓ fidelity of an image variation: {fidelity(page, 'upload'):.1f}/255")
            shot(page, "s05b-upload-variations")

        if what in ("dna", "all"):
            sys.path.insert(0, str(Path(__file__).parent))
            from dna_fixture import off_brand_spec

            spec = off_brand_spec()
            page.evaluate("(spec) => { window.__crux.mutate(d => { d.boards.push(spec); }); window.__crux.setUi({ activeBoardId: spec.id, selection: null }); }", spec)
            page.wait_for_timeout(800)
            n = page.locator(".dna-card .ring").count()
            page.click(".dna-btn")
            page.wait_for_function(f"document.querySelectorAll('.dna-card .ring').length > {n}", timeout=120_000)
            before = int(page.locator(".dna-card").last.locator(".ring text").text_content())
            print(f"✓ Brand DNA on off-brand board: {before}/100 · {page.locator('.dna-card').last.locator('.findings li').count()} findings")
            page.locator(".dna-card").last.locator("button:has-text('Pin issues')").click()
            page.wait_for_timeout(600)
            pins = page.locator(".pin.dna").count()
            page.locator(".dna-card").last.locator("button:has-text('automatically')").click()
            page.wait_for_function(f"document.querySelectorAll('.dna-card .ring').length > {n + 1}", timeout=120_000)
            after = int(page.locator(".dna-card").last.locator(".ring text").text_content())
            left = page.locator(".pin.dna").count()
            print(f"✓ {pins} issues pinned on canvas · after Fix all: {after}/100 · stale pins left: {left}")
            assert after > before and left == 0
            shot(page, "s06-dna")

        if what in ("intel", "all"):
            page.click("[data-testid=tab-intel]")
            page.fill("[data-testid=intel-query]", "accounting software")
            page.click("[data-testid=intel-scan]")
            t0 = time.time()
            page.wait_for_selector("[data-testid=intel-idea]", timeout=240_000)
            ads = page.locator("[data-testid=intel-ad]").count()
            ideas = page.locator("[data-testid=intel-idea]").count()
            rep = httpx.get(f"{URL}/api/competitors/latest", params={"query": "accounting software", "country": "ALL"}).json()
            dated = sum(1 for a in rep["ads"] if a.get("started") and a.get("days_active") is not None)
            media = sum(1 for a in rep["ads"] if a.get("thumb_file") or a.get("video_url"))
            days = [a["days_active"] for a in rep["ads"]]
            print(f"✓ Meta Ad Library scan in {time.time() - t0:.1f}s: {len(rep['ads'])} ads ({dated} dated, {media} with creative), "
                  f"{ads} on-topic shown, {ideas} ideas · longest-running {max(days)} days")
            assert len(rep["ads"]) >= 15 and dated == len(rep["ads"]) and ideas >= 3 and days == sorted(days, reverse=True)
            shot(page, "s07-intel")
            idea_head = page.locator(".idea-head").first.inner_text()
            n = page.locator(".design-card .dot.done").count() + 1
            page.locator("[data-testid=intel-idea] button:has-text('Create this')").first.click()
            wait_count(page, ".design-card .dot.done", n, 240)
            made = active_board(page)
            print(f"✓ idea → board “{made['brief'].get('headline')}” (idea: “{idea_head}”) · {made['brief'].get('archetype')}")
            page.click("[data-testid=tab-intel]")
            n += 1
            page.locator("[data-testid=intel-ad] button:has-text('Remix on-brand')").first.click()
            wait_count(page, ".design-card .dot.done", n, 240)
            print(f"✓ remix of a competitor ad → board “{active_board(page)['brief'].get('headline')}”")
            shot(page, "s08-intel-made")

        errs = [e for e in errors if "favicon" not in e]
        if errs:
            print("console errors:", *errs[:8], sep="\n  ")
        browser.close()


def _walk(layers):
    for l in layers:
        yield l
        yield from _walk(l.get("children") or [])


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "create")
    finally:
        (ROOT / "data" / "docs" / f"{DOC}.json").unlink(missing_ok=True)  # throwaway test document
