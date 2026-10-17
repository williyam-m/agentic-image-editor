"""Build docs/Crux-Studio-Technical-Presentation.pdf (16:9 slides) from HTML with headless Chromium.

Usage: .venv/bin/python scripts/build_presentation.py
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
IMG = (ROOT / "editor" / "public" / "landing").as_uri()
OUT = ROOT / "docs"

CSS = """
@page { size: 1280px 720px; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Geist", "Inter", Helvetica, Arial, sans-serif; color: #141414; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.slide { width: 1280px; height: 720px; position: relative; overflow: hidden; padding: 56px 64px; page-break-after: always;
  background: radial-gradient(45% 55% at 8% 0%, #ffd8c4 0%, rgba(255,216,196,0) 70%), radial-gradient(40% 50% at 100% 0%, #fbd3dd 0%, rgba(251,211,221,0) 70%),
  radial-gradient(40% 50% at 80% 110%, #ffe2c6 0%, rgba(255,226,198,0) 70%), #faf6f2; }
.slide.dark { color: #f4f1ee; background: radial-gradient(70% 80% at 0% 0%, rgba(255,111,8,.42) 0%, rgba(255,69,0,0) 55%),
  radial-gradient(60% 60% at 100% 100%, rgba(255,69,0,.22) 0%, rgba(255,69,0,0) 60%), #121212; }
.top { position: absolute; top: 26px; left: 64px; right: 64px; display: flex; justify-content: space-between; font-size: 12px; color: #8a817b; letter-spacing: .06em; text-transform: uppercase; }
.dark .top { color: #a8a29d; }
.logo { display: flex; align-items: center; gap: 0; font-weight: 700; color: #141414; text-transform: none; letter-spacing: -.03em; font-size: 15px; }
.dark .logo { color: #fff; }
.logo i { width: 14px; height: 14px; border-radius: 4px; background: linear-gradient(135deg,#ff8a3d,#ff4500); display: inline-block; transform: rotate(45deg); }
.logo span { color: #ff4500; }
.eyebrow { display: inline-block; font-size: 12px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: #ff4500; margin: 18px 0 10px; }
h1 { font-size: 64px; line-height: .98; letter-spacing: -.05em; text-transform: uppercase; font-weight: 700; }
h2 { font-size: 38px; line-height: 1.02; letter-spacing: -.045em; text-transform: uppercase; font-weight: 700; margin-bottom: 18px; }
.grad { background: linear-gradient(120deg,#ff8a3d 0%,#ff6f08 40%,#ff4500 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
p.lead { font-size: 18px; line-height: 1.5; color: #4a4542; max-width: 760px; }
.dark p.lead { color: #cfc9c4; }
.card { background: rgba(255,255,255,.62); border: 1px solid rgba(255,255,255,.9); border-radius: 16px; padding: 16px 18px;
  box-shadow: inset 0 1px 0 #fff, 0 18px 40px -26px rgba(255,69,0,.5); }
.dark .card { background: rgba(255,255,255,.05); border-color: rgba(255,255,255,.1); box-shadow: none; }
.card b { display: block; font-size: 15px; margin-bottom: 4px; }
.card span, .card li { font-size: 13px; line-height: 1.45; color: #5a534f; }
.dark .card span, .dark .card li { color: #bdb6b0; }
.grid { display: grid; gap: 12px; }
.g2 { grid-template-columns: 1fr 1fr; } .g3 { grid-template-columns: repeat(3,1fr); } .g4 { grid-template-columns: repeat(4,1fr); }
ul.clean { list-style: none; display: flex; flex-direction: column; gap: 7px; }
ul.clean li { font-size: 15px; line-height: 1.4; padding-left: 16px; position: relative; color: #3a3532; }
.dark ul.clean li { color: #ddd6d0; }
ul.clean li::before { content: ""; position: absolute; left: 0; top: 8px; width: 6px; height: 6px; border-radius: 50%; background: #ff4500; }
.pill { display: inline-block; font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 99px; background: rgba(255,111,8,.12); color: #c2410c; margin: 0 4px 4px 0; }
.dark .pill { background: rgba(255,111,8,.2); color: #ffb48a; }
.shot { border-radius: 12px; border: 1px solid rgba(255,255,255,.9); box-shadow: 0 30px 70px -30px rgba(255,69,0,.55), 0 10px 30px rgba(20,20,20,.12); width: 100%; display: block; }
.num { position: absolute; bottom: 24px; right: 64px; font-size: 12px; color: #a39b95; }
.mono { font-family: "Geist Mono", ui-monospace, monospace; font-size: 12px; }
table { width: 100%; border-collapse: separate; border-spacing: 0 6px; font-size: 13.5px; }
td { padding: 9px 12px; background: rgba(255,255,255,.62); vertical-align: top; line-height: 1.4; }
td:first-child { border-radius: 10px 0 0 10px; font-weight: 700; width: 210px; }
td:last-child { border-radius: 0 10px 10px 0; color: #5a534f; }
td.k { color: #c2410c; font-weight: 600; width: 230px; }
/* flow diagrams */
.flow { display: flex; align-items: stretch; gap: 0; }
.step { flex: 1; background: rgba(255,255,255,.66); border: 1px solid #fff; border-radius: 14px; padding: 12px 12px; font-size: 12.5px; line-height: 1.4; color: #5a534f; }
.dark .step { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.12); color: #c8c1bb; }
.step b { display: block; color: #141414; font-size: 14px; margin-bottom: 3px; }
.dark .step b { color: #fff; }
.step .t { display: inline-block; margin-top: 6px; font-family: "Geist Mono", monospace; font-size: 11px; color: #ff4500; }
.arrow { width: 26px; display: flex; align-items: center; justify-content: center; color: #ff6f08; font-size: 20px; font-weight: 700; }
.lane { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #8a817b; margin: 14px 0 6px; }
.box { border-radius: 14px; padding: 12px 14px; font-size: 12.5px; line-height: 1.4; }
.box b { display: block; font-size: 14px; margin-bottom: 2px; }
.b-ink { background: #141414; color: #ddd; } .b-ink b { color: #fff; }
.b-or { background: linear-gradient(135deg,#ff8a3d,#ff4500); color: #fff; }
.b-gl { background: rgba(255,255,255,.7); border: 1px solid #fff; color: #5a534f; } .b-gl b { color: #141414; }
.big { font-size: 46px; font-weight: 700; letter-spacing: -.04em; background: linear-gradient(120deg,#141414,#ff4500); -webkit-background-clip: text; background-clip: text; color: transparent; }
.dark .big { background: linear-gradient(120deg,#fff,#ff8a3d); -webkit-background-clip: text; background-clip: text; }
"""


def top(section: str) -> str:
    return f'<div class="top"><span class="logo"><i style="margin-right:7px"></i>crux<span>.</span>&nbsp;Studio</span><span>{section}</span></div>'


def slide(body: str, section: str = "", dark: bool = False, n: int = 0) -> str:
    return f'<section class="slide{" dark" if dark else ""}">{top(section)}{body}<div class="num">{n:02d}</div></section>'


def build() -> str:
    s: list[str] = []
    add = lambda body, section="", dark=False: s.append(slide(body, section, dark, len(s) + 1))  # noqa: E731

    # 1 — Title
    add(f"""
    <div style="display:grid;grid-template-columns:1.05fr .95fr;gap:40px;align-items:center;height:100%;padding-top:20px">
      <div>
        <span class="eyebrow">Technical presentation · GetCrux hackathon</span>
        <h1>Crux Studio<br><span class="grad">AI design copilot</span></h1>
        <p class="lead" style="margin-top:18px">A layered image editor where an AI copilot creates, edits and audits on-brand ads —
        by chat, voice or a comment on the canvas — orchestrated by Temporal and parallelised by Celery.</p>
        <div style="margin-top:22px"><span class="pill">Temporal</span><span class="pill">Celery + Redis</span><span class="pill">FastAPI</span>
        <span class="pill">React + SVG</span><span class="pill">DeepSeek V4</span><span class="pill">GPT Image Flare</span><span class="pill">ElevenLabs Scribe v2</span></div>
      </div>
      <img class="shot" src="{IMG}/create.jpg">
    </div>""", "Overview")

    # 2 — Problem & solution
    add("""
    <span class="eyebrow">The problem</span>
    <h2>Branded design is slow — and easy to get wrong</h2>
    <div class="grid g2" style="margin-top:8px">
      <div class="card"><b>Today</b><ul class="clean" style="margin-top:6px">
        <li>Designers hand-build every ad in an image editor</li><li>Fonts, colours, logo rules and approved assets must be remembered</li>
        <li>Legal rules (claims, “Terms apply.”) are easy to miss</li><li>Exploring variations or competitor ideas costs hours</li></ul></div>
      <div class="card"><b>Crux Studio</b><ul class="clean" style="margin-top:6px">
        <li>Describe an ad → a layered, editable board in ~20 s</li><li>Edit any single layer by chat, <b style="display:inline">voice</b> or a canvas comment</li>
        <li>Every output checked against brand &amp; legal policy — and auto-fixed</li><li>Variations, Brand DNA audits and competitor intel built in</li></ul></div>
    </div>
    <div class="grid g4" style="margin-top:16px">
      <div class="card"><div class="big">~20s</div><span>prompt → layered ad</span></div>
      <div class="card"><div class="big">10+</div><span>editable layers per design</span></div>
      <div class="card"><div class="big">323</div><span>brand assets analysed by AI</span></div>
      <div class="card"><div class="big">~3/255</div><span>canvas vs export pixel difference</span></div>
    </div>""", "Overview")

    # 3 — Architecture
    add("""
    <span class="eyebrow">Architecture</span>
    <h2>Who does what</h2>
    <div style="display:grid;grid-template-columns:1fr 34px 1fr 34px 1.1fr 34px 1.15fr;align-items:center;margin-top:4px">
      <div class="box b-gl"><b>Browser — Crux Studio</b>React + SVG canvas<br>layers · panels · copilot chat<br>voice capture · landing page</div>
      <div class="arrow">⇄</div>
      <div class="box b-ink"><b>FastAPI</b>HTTP API · documents<br>uploads · render/export<br>voice proxy · job status</div>
      <div class="arrow">→</div>
      <div class="box b-or"><b>Temporal</b>durable workflows:<br>design · edit · Brand DNA<br>competitors · brand ingest</div>
      <div class="arrow">→</div>
      <div class="box b-ink"><b>Celery workers + Redis</b>parallel heavy work:<br>image layers · compositing<br>vision checks · scraping</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;margin-top:22px">
      <div class="box b-gl"><b>DeepSeek V4 Pro</b>plans briefs &amp; copy, plans edits, synthesises insights</div>
      <div class="box b-gl"><b>DeepSeek V4.1 Flash</b>vision: asset tagging, image compliance, QA, Brand DNA, ad reading</div>
      <div class="box b-gl"><b>GPT Image 2.5 Flare</b>photos, transparent cut-outs, brand-style art, in-place photo edits</div>
      <div class="box b-gl"><b>ElevenLabs Scribe v2</b>speech → text for voice editing (server-side proxy)</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px">
      <div class="box b-gl"><b>Storage</b><span class="mono">data/</span> — documents (JSON), generated layers, exports, brand catalog</div>
      <div class="box b-gl"><b>Brand kit</b>Candidate-resources → vectors, charms, tags, insights</div>
      <div class="box b-gl"><b>Meta Ad Library</b>public competitor ads (headless Chromium)</div>
    </div>""", "Architecture")

    # 4 — Tech roles table
    add("""
    <span class="eyebrow">Tech stack</span>
    <h2>Each technology has one job</h2>
    <table>
      <tr><td>React + TypeScript + SVG</td><td>The editor. Draws each board as native SVG from the same layer model and font files as the server, so the canvas, previews and exports match.</td></tr>
      <tr><td>FastAPI (Python)</td><td>The front door: documents, uploads, server render, starts jobs and reports their progress, proxies voice so API keys never reach the browser.</td></tr>
      <tr><td>Temporal</td><td>The “project manager with a memory”: runs each multi-step job as a durable workflow — retries, timeouts, live progress, survives restarts.</td></tr>
      <tr><td>Celery + Redis</td><td>The “workforce”: a pool of workers that runs heavy, slow tasks in parallel (every image layer at once). Redis is the queue between them.</td></tr>
      <tr><td>DeepSeek V4 Pro / V4.1 Flash</td><td>Pro = thinking (copy, layout choices, edit plans, strategy). Flash = seeing (vision QA, compliance, tagging, ad analysis) — fast.</td></tr>
      <tr><td>GPT Image 2.5 Flare</td><td>Makes pixels: photos, transparent cut-outs, brand-style illustrations/charms from reference assets, and identity-preserving photo edits.</td></tr>
      <tr><td>ElevenLabs Scribe v2</td><td>Turns spoken edits into text (auto-stops on silence in the browser).</td></tr>
      <tr><td>Pillow · potrace · Playwright</td><td>Server compositor &amp; text metrics · brand shapes to vectors · Meta Ad Library scraping and browser tests.</td></tr>
    </table>""", "Tech stack")

    # 5 — Temporal vs Celery
    add("""
    <span class="eyebrow">Orchestration</span>
    <h2>Temporal is the brain. <span class="grad">Celery is the muscle.</span></h2>
    <div class="grid g2">
      <div class="card"><b>Temporal — decides and remembers</b><ul class="clean" style="margin-top:6px">
        <li>Each job is a <b style="display:inline">workflow</b>: a recipe of steps (plan → layout → generate → audit)</li>
        <li>Remembers where it is: if a worker crashes, it resumes from the last finished step</li>
        <li>Retries failed steps with back-off; timeouts &amp; heartbeats catch hangs</li>
        <li>Exposes a live <span class="mono">progress</span> query → the UI shows boards as soon as the layout exists</li>
        <li>Runs steps concurrently (4 variants, 20 ad analyses) with deadlines</li></ul></div>
      <div class="card"><b>Celery — does the heavy lifting</b><ul class="clean" style="margin-top:6px">
        <li>A pool of 24 worker threads pulling tasks from a Redis queue</li>
        <li>One task per image layer → all layers of all variants render at the same time</li>
        <li>Also: compositing + brand audit, AI vision checks, Ad Library scraping</li>
        <li>Scale out by adding workers — no workflow code changes</li>
        <li>Temporal activities hand a task to Celery and await it without blocking</li></ul></div>
    </div>
    <div class="card" style="margin-top:12px"><b>How they meet</b><span>Workflow step → <span class="mono">celery_task</span> activity sends the task to Redis → a Celery worker runs it →
      the activity polls the result (heartbeating) → Temporal records it and moves to the next step. Durability from Temporal, throughput from Celery.</span></div>""", "Temporal + Celery")

    # 6 — Image generation pipeline
    add("""
    <span class="eyebrow">Image generation</span>
    <h2>From a sentence to a layered ad</h2>
    <div class="flow">
      <div class="step"><b>1 · Plan</b>DeepSeek Pro writes the brief: archetype, colourway, headline, CTA, which brand assets, photo prompt — from brand rules, voice &amp; references. Legal re-plan if needed.<span class="t">~4s · Temporal activity</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>2 · Lay out</b>Code (not the AI) places every layer: text measured with the real font files, safe zones, waves kept off the copy. Brand guard runs.<span class="t">&lt;1s · deterministic</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>3 · Generate</b>Each image layer becomes a Celery task: GPT Image Flare photo / cut-out / brand-style art — all in parallel.<span class="t">~11–15s · Celery</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>4 · Verify</b>Vision AI checks each image for text, logos, watermarks, competitor branding → regenerates with a correction if it fails.<span class="t">~2–3s / image</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>5 · Compose &amp; audit</b>Server compositor flattens the layers; brand guard auto-fixes (contrast, logo colour, “Terms apply.”); art-director QA scores it.<span class="t">~3s · Celery</span></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><b>Progressive canvas</b><span>The board appears in the editor right after step 2 with placeholders; each photo drops in the moment its Celery task finishes. Total ≈ 20–25 s.</span></div>
      <div class="card"><b>Why layers, not one picture</b><span>Only photos/illustrations are generated images. Headline, CTA, card, bloom, logo and charms are real vector/text/brand-asset layers — so every element stays editable and on-brand.</span></div>
    </div>""", "Image generation")

    # 7 — Layer model + rendering
    add(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:34px;align-items:center;height:100%">
      <div>
        <span class="eyebrow">Layered design model</span>
        <h2>One model, three identical views</h2>
        <ul class="clean">
          <li><span class="mono">DesignSpec</span> = board + ordered layers: rect, text, image, vector, group, mask</li>
          <li>Editor canvas draws it as SVG; the server compositor (Pillow) draws it as PNG</li>
          <li>Same font files &amp; ascent/descent metrics, same wrap rules, same masks and shadows</li>
          <li>Measured in tests: canvas vs server render differ by ~2–4 / 255 per pixel</li>
          <li>Photos sit inside bloom masks; logo &amp; blooms are traced vectors (recolourable)</li>
          <li>Documents autosave as JSON; undo/redo, locks, visibility, reorder</li>
        </ul>
      </div>
      <img class="shot" src="{IMG}/photo.jpg">
    </div>""", "Rendering")

    # 8 — Brand ingestion
    add("""
    <span class="eyebrow">Brand kit ingestion</span>
    <h2>Teaching the AI the brand</h2>
    <div class="flow">
      <div class="step"><b>Scan</b>Candidate-resources: logo, blooms, background templates, illustrations, charms, product UI, 20 reference ads.</div>
      <div class="arrow">→</div>
      <div class="step"><b>Vectorise</b>potrace turns the wordmark, 12 named blooms and 18 wave templates into clean, recolourable SVG paths.</div>
      <div class="arrow">→</div>
      <div class="step"><b>Slice</b>The charm sprite sheet is cut into 251 individual charms (connected-component analysis).</div>
      <div class="arrow">→</div>
      <div class="step"><b>Tag with vision</b>Flash names &amp; tags every asset in numbered contact sheets; deconstructs each reference ad (archetype, copy angle).</div>
      <div class="arrow">→</div>
      <div class="step"><b>Synthesise</b>Pro distils brand voice, headline formulas, CTA bank and layout patterns → <span class="mono">catalog.json</span>.</div>
    </div>
    <div class="grid g3" style="margin-top:16px">
      <div class="card"><div class="big">323</div><span>assets catalogued (Temporal BrandIngestWorkflow, ~45s, cached by fingerprint)</span></div>
      <div class="card"><div class="big">5</div><span>layout archetypes learned from the references: card+photo, photo in bloom, navy illustration, device, checklist</span></div>
      <div class="card"><div class="big">11</div><span>palette colours — primary for large fills, accents only for charms</span></div>
    </div>""", "Brand kit")

    # 9 — Editing: chat, comment, voice
    add(f"""
    <span class="eyebrow">Editing</span>
    <h2>Three ways to change one layer</h2>
    <div class="grid g3">
      <div class="card"><b>💬 Chat</b><span>Select a layer → “make the photo golden hour”. EditWorkflow: Pro plans intent ops → compiler re-fits text with real font metrics, snaps colours, resizes CTA buttons → image edits run in Celery (same person &amp; scene) → ops apply to the document. <b style="display:inline">~3–8s text, ~20s photo</b></span></div>
      <div class="card"><b>📍 Comment</b><span>Comment tool → click anywhere. The layer under the pointer is hit-tested (deep-selects into groups and masked photos), the edit runs, Crux replies in the thread and resolves it. <b style="display:inline">~3s</b></span></div>
      <div class="card"><b>🎙 Voice</b><span>Press M → browser records (MediaRecorder) with a live level meter, auto-stops on 1.3s of silence → FastAPI proxies the audio to ElevenLabs Scribe v2 → the transcript runs as a chat edit. <b style="display:inline">~8s incl. speaking</b></span></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px">
      <img class="shot" style="height:300px;object-fit:cover;object-position:top" src="{IMG}/comment.jpg"><img class="shot" style="height:300px;object-fit:cover;object-position:top" src="{IMG}/voice.jpg">
    </div>""", "Editing")

    # 10 — Variations
    add(f"""
    <div style="display:grid;grid-template-columns:.9fr 1.1fr;gap:34px;align-items:center;height:100%">
      <div>
        <span class="eyebrow">Generate like this</span>
        <h2>1–4 real alternatives, in parallel</h2>
        <ul class="clean">
          <li>Pick a board (or a reference / competitor ad) → choose how many</li>
          <li>Diversity is enforced in code: each variant gets a different archetype; one gets a contrasting colourway</li>
          <li>Temporal plans all variants concurrently; Celery renders every image layer of every variant at once</li>
          <li>4 variants ≈ the time of one (~23–27s)</li>
          <li>Non-Crux boards: rendered and read by vision AI as the reference</li>
        </ul>
      </div>
      <img class="shot" src="{IMG}/variations.jpg">
    </div>""", "Variations")

    # 11 — Guardrails
    add("""
    <span class="eyebrow">Enterprise guardrails</span>
    <h2>Brand &amp; legal policy at every stage</h2>
    <table>
      <tr><td class="k">Planning</td><td>Unapproved claims (guaranteed, best, #1, risk-free, free forever, 100%…) and competitor names are rejected → the brief is re-planned with legal feedback.</td></tr>
      <tr><td class="k">Layout</td><td>Brand fonts only, measured to fit; story safe zones; logo in approved colourways with clear space; “Terms apply.” added for any offer.</td></tr>
      <tr><td class="k">Images</td><td>Every AI image is vision-checked for text, logos, watermarks, competitor branding, unsafe content (and off-palette art) → regenerated up to 3× with a targeted correction.</td></tr>
      <tr><td class="k">Composite</td><td>Brand guard samples the real pixels behind each text/logo: WCAG contrast ≥ 4.5:1 and logo colour are auto-fixed; palette snapping.</td></tr>
      <tr><td class="k">Editing</td><td>Off-policy requests (remove/recolour/rotate logo, unapproved claims) are blocked or turned into the closest compliant change, with an explanation.</td></tr>
      <tr><td class="k">Resilience</td><td>Reviewer AI calls have short timeouts — if a reviewer is down, delivery continues and the image is marked “unverified”.</td></tr>
    </table>""", "Guardrails")

    # 12 — Brand DNA
    add(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:34px;align-items:center;height:100%">
      <div>
        <span class="eyebrow">Brand DNA</span>
        <h2>Audit any design. Fix it in one click.</h2>
        <ul class="clean">
          <li><b style="display:inline">Measured audit</b> (deterministic): fonts, palette, contrast against the post-fix background, logo colour/size/clear space, legal copy with compliant AI rewrites, safe zones</li>
          <li><b style="display:inline">Visual audit</b> (Flash vision) grounded in the measured facts — imagery, layout, tone</li>
          <li>Score across 6 dimensions; every issue located (bounding box) and explained</li>
          <li>Fix all → re-check (off-brand test ad: ~10 → ~60–75); pins on the canvas</li>
          <li>BrandDnaWorkflow on Temporal, ~10s</li>
        </ul>
      </div>
      <img class="shot" src="{IMG}/dna.jpg">
    </div>""", "Brand DNA")

    # 13 — Competitor intel
    add(f"""
    <span class="eyebrow">Competitor intel</span>
    <h2>Learning from ads that kept running</h2>
    <div class="flow">
      <div class="step"><b>Scrape</b>Celery task drives headless Chromium on the public Meta Ad Library (no login): ~20 ads — creative, copy, advertiser, “started running on”.<span class="t">~6s</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>Rank</b>Days active = performance proxy (winners stay live). Tiers: proven ≥ 90d · testing · new. Creatives cached locally.</div>
      <div class="arrow">→</div>
      <div class="step"><b>Read</b>Flash vision reads every creative in parallel: hook, angle, format, relevance — with a 20s deadline.<span class="t">~5–20s</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>Synthesise</b>Pro weights patterns by longevity, finds whitespace and writes 5 original Xero ideas (legal-checked).<span class="t">~10s</span></div>
      <div class="arrow">→</div>
      <div class="step"><b>Create</b>“Create this →” or “Remix on-brand” runs the normal DesignWorkflow.</div>
    </div>
    <div style="display:grid;grid-template-columns:1.2fr .8fr;gap:16px;margin-top:14px;align-items:start">
      <img class="shot" style="height:330px;object-fit:cover;object-position:top" src="{IMG}/intel.jpg">
      <div class="card"><b>Measured</b><ul class="clean" style="margin-top:6px"><li>20 ads, all dated, all with creative</li><li>Longest-running: 657 days</li><li>Scan 21–36s end to end</li><li>Ideas never reuse competitor copy, claims or branding</li></ul></div>
    </div>""", "Competitor intel")

    # 14 — Performance & reliability
    add("""
    <span class="eyebrow">Performance &amp; reliability</span>
    <h2>Measured, not promised</h2>
    <div class="grid g4">
      <div class="card"><div class="big">~22s</div><span>new layered ad (plan 4s · images in parallel ~12s · compose + QA 3s)</span></div>
      <div class="card"><div class="big">~3s</div><span>layer text edit / comment edit</span></div>
      <div class="card"><div class="big">~25s</div><span>4 variations (same as one — parallel)</span></div>
      <div class="card"><div class="big">~8s</div><span>voice edit, incl. speaking &amp; transcription</span></div>
    </div>
    <div class="grid g3" style="margin-top:14px">
      <div class="card"><b>Durable</b><span>Every job is a Temporal workflow: retries with back-off, timeouts &amp; heartbeats; one failed layer degrades to a placeholder instead of failing the design.</span></div>
      <div class="card"><b>Fail fast where advisory</b><span>Compliance/QA reviewers time out in 15–25s; analysis deadlines cap slow vision calls; LLM rate-limits retried with jitter, Pro ↔ Flash fallback.</span></div>
      <div class="card"><b>Fast by design</b><span>Geometry is computed in code (no LLM round-trips per element); progressive canvas shows boards in ~4s; brand catalog cached by fingerprint.</span></div>
    </div>""", "Performance")

    # 15 — Testing & security
    add("""
    <span class="eyebrow">Quality &amp; security</span>
    <h2>Verified in a real browser</h2>
    <div class="grid g2">
      <div class="card"><b>Automated tests</b><ul class="clean" style="margin-top:6px">
        <li><span class="mono">scripts/smoke_test.py</span> — API: 4 formats, variations, edits</li>
        <li><span class="mono">tests/e2e_studio.py</span> — Playwright in Chromium: create, every image loaded, canvas-vs-server pixel diff, layer / photo / comment / voice edits (fake microphone), drag + undo + inline text, variations, Brand DNA fix-all, live Ad Library scan → idea → board</li>
        <li>Throwaway documents per run — the designer's work is never touched</li></ul></div>
      <div class="card"><b>Security</b><ul class="clean" style="margin-top:6px">
        <li>API keys only in <span class="mono">.env</span> (git-ignored, mode 600), loaded as secrets, never logged or sent to the browser</li>
        <li>Voice audio proxied server-side; Ad Library scraped with one gentle session</li>
        <li>Services bind to 127.0.0.1; CORS limited; uploads size-capped &amp; validated; ids and file paths validated</li></ul></div>
    </div>""", "Quality")

    # 16 — Run it
    add("""
    <span class="eyebrow">Run it</span>
    <h2>One command</h2>
    <div class="grid g2">
      <div class="card" style="background:#141414;color:#eee"><span class="mono" style="color:#ffb48a;font-size:14px;line-height:1.9">
        cp .env.example .env &nbsp;# add keys<br>./run.sh &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# start everything<br>./run.sh test &nbsp;&nbsp;&nbsp;# smoke + browser E2E<br>./run.sh stop</span>
        <span style="display:block;margin-top:10px;color:#bbb">Starts Redis, Temporal dev server, Celery workers, the Temporal worker and FastAPI; builds the editor; analyses the brand kit on first run. Landing: <span class="mono">localhost:8787</span> · Studio: <span class="mono">/studio</span></span></div>
      <div class="card"><b>Repository map</b><ul class="clean" style="margin-top:6px">
        <li><span class="mono">backend/crux/brand</span> — kit, ingestion, policy, guard, compliance, Brand DNA</li>
        <li><span class="mono">backend/crux/design</span> — spec, layout engine, compositor, planner, editor</li>
        <li><span class="mono">backend/crux/research</span> — Meta Ad Library + competitor analysis</li>
        <li><span class="mono">backend/crux/workflows · tasks · api</span> — Temporal, Celery, FastAPI</li>
        <li><span class="mono">editor/src</span> — model, SVG renderer, canvas, panels, copilot, voice, landing</li></ul></div>
    </div>""", "Run it")

    # 17 — Close
    add(f"""
    <div style="display:flex;flex-direction:column;justify-content:center;height:100%;align-items:flex-start">
      <span class="eyebrow">Crux Studio</span>
      <h1 style="color:#fff">Design on-brand,<br><span class="grad">layer by layer.</span></h1>
      <p class="lead" style="margin-top:18px">Temporal keeps every job durable. Celery makes every layer parallel. The AI writes, sees and checks —
      and the code keeps every pixel on-brand and editable.</p>
      <div style="display:flex;gap:10px;margin-top:26px">{"".join(f'<img src="{IMG}/ads/ad{i:02d}.jpg" style="width:118px;border-radius:10px;box-shadow:0 18px 40px -16px rgba(255,111,8,.7)">' for i in range(8))}</div>
    </div>""", "Thank you", dark=True)
    return "".join(s)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<link href='https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono&display=swap' rel='stylesheet'>"
            f"<style>{CSS}</style></head><body>{build()}</body></html>")
    html_path = OUT / "presentation.html"
    html_path.write_text(html)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(800)
        pdf = OUT / "Crux-Studio-Technical-Presentation.pdf"
        page.pdf(path=str(pdf), width="1280px", height="720px", print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        browser.close()
    print(pdf, f"{pdf.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
