# Crux Studio — layered AI image editor with a brand copilot

An image editor built for brand teams. Describe an ad, click any layer and say what to change, drop a
comment on an element, or ask for *“4 different images like this”*. Every headline, photo, bloom, charm,
CTA and logo is its **own editable layer** on the canvas, and everything follows the Xero brand kit in
`Candidate-resources/`.

```bash
cp .env.example .env     # add the OpenAI + DeepSeek keys (git-ignored)
./run.sh                 # one command: Redis + Temporal + Celery + worker + API/editor → http://localhost:8787
```

| Command | |
|---|---|
| `./run.sh` | start everything and open the studio (first run also analyses the brand kit, ~1 min) |
| `./run.sh status` | health of API, Temporal, Celery |
| `./run.sh test` | backend smoke tests + Playwright E2E of the editor (incl. pixel-fidelity checks) |
| `./run.sh stop` | stop all services |

Prerequisites (macOS): `brew install redis temporal potrace node python@3.13`. No Docker needed.
Voice editing needs a (free) ElevenLabs key: add `ELEVENLABS_API_KEY=...` to `.env` and restart; without it the
mic is disabled and everything else works. The key stays on the server (`/api/voice/transcribe` proxies the audio).

## The editor

* **Canvas** — zoom (⌘/Ctrl + wheel, `+`/`-`, `Shift+1` fit), pan (wheel, Space-drag, `H`), click to select the
  layer under the pointer (deep-selects into groups and masked photos), drag to move, 8 handles to resize
  (corner handles keep aspect for images/vectors), double-click text to edit inline, arrows to nudge,
  `⌘D` duplicate, `Delete`, `⌘Z` / `⇧⌘Z` undo/redo. Autosaves.
* **Tools** — Select `V`, Text `T`, Rectangle `R`, Comment `C`, Pan `H`, image upload (or drag & drop a file).
* **Panels** — Boards (live thumbnails, new blank board in 4 formats), Layers (tree, rename, show/hide, lock,
  reorder), Design inspector (geometry, rotation, opacity, brand palette with off-palette warning, brand fonts,
  image replace, policy verdict per AI image), Brand kit (323 AI-tagged assets, click to add), References.
* **Look & feel** — GetCrux visual language: animated peach/orange mesh-gradient backdrop, frosted-glass floating
  panels and a liquid-glass top bar, ink pill buttons, orange-gradient accents, a dark glowing Brand DNA card.
* **Rendering** — boards are drawn as native SVG from the same layer model and font files the server
  compositor uses (`backend/crux/design/compose.py`), so the canvas, the chat thumbnail and the exported PNG
  are the same picture. The E2E suite measures this: mean pixel difference canvas vs server ≈ 3/255.

## The copilot

| Feature | How | What happens |
|---|---|---|
| **Create** | Copilot tab → describe the ad, pick 4:5 · 1:1 · 9:16 · 1.91:1 | A new board with ~10 named layers appears in ~3s; photos stream into their placeholders (~20s) |
| **Edit a layer** | Select a layer, type the change | Only that layer changes: copy re-fitted with real font metrics, colours snapped to the palette, photos edited in place |
| **Comment to edit** | `C`, click a layer, write the change | The layer under the pin is edited; Crux replies in the thread and resolves it |
| **Variations** | With a board open: “Create 4 different images like this” | 4 deliberately different directions (layout, colourway, copy angle) in parallel |
| **Brand DNA** | 🧬 button (composer, board inspector or a result card) | Score + 6 dimensions, every violation located; *Fix N automatically*, per-issue *Fix/Show*, *Pin issues on canvas*, *Re-check* |
| **Voice to edit** | Press `M` (or the mic) and say the change, e.g. “make the headline say get paid in days” | Speech → ElevenLabs **Scribe v2** → runs as an edit on the selected layer (or board); stops by itself when you pause. Also works in canvas comments |
| **Competitor intel** | *Competitors* tab → category (e.g. fintech, accounting software) + country → *Scan Meta Ad Library* | ~20 public ads from the Meta Ad Library (no login): creative (image / carousel / video + poster), copy, advertiser, “started running on” date → **days active** as the performance proxy (winners stay live). Vision AI reads each creative (hook, angle, format, relevance); patterns are weighted by longevity; 5 original on-brand **ideas** with *Create this →*, and *Remix on-brand* on any ad (~20–50s) |
| **Export** | *Export PNG* | Server-rendered PNG of the board |

### Strict brand & legal compliance
`backend/crux/brand/policy.py` holds the non-negotiable rules, enforced at every stage: no unapproved claims or
competitor names (the planner re-plans with legal feedback), automatic “Terms apply.” for offers, every AI image
vision-checked for text/logos/watermarks/competitor branding and regenerated if needed, logo only in approved
colourways with clear space, primary colours for large fills, brand fonts only; edits that break policy are
blocked or converted to the closest compliant change.

## Architecture

```
Crux Studio (React + SVG, served by the API)  ──HTTP──▶  FastAPI ──start/query──▶ Temporal workflows
   document autosave, uploads, render                          │ (durable: create / edit / Brand DNA / ingest)
                                                               ▼
                                              Celery workers (Redis): per-layer GPT Image generation,
                                              vision compliance, compositing, brand audit, QA
```

* **Competitor research** (`backend/crux/research/`) — `adlibrary.py` scrapes the public Meta Ad Library search
  (one headless session, gentle scrolling, creatives cached locally), `competitors.py` analyses and synthesises;
  orchestrated by `CompetitorWorkflow` (scrape → parallel vision analysis in Celery → synthesis), cached per
  category in `data/competitors/`. Ideas never reuse competitor copy, claims or branding and pass the legal policy.
* **Speech** — ElevenLabs Scribe v2 (`scribe_v2`, `no_verbatim`) via a server-side proxy.
* **LLMs** — DeepSeek-V4-Pro plans briefs and edits; DeepSeek-V4.1-Flash does vision (asset tagging, reference
  analysis, compliance, QA, Brand DNA). Images: **GPT Image 2.5 Flare**.
* **Layout engine** (`backend/crux/design/layouts.py`) — the LLM decides *what*, code decides *where*: five
  archetypes distilled from the reference ads, measured text, story safe zones, waves kept off the copy.
* **Brand guard** (`backend/crux/brand/guard.py`) and **Brand DNA** (`backend/crux/brand/dna.py`).
* **Brand ingestion** (`backend/crux/brand/ingest.py`) — vectorises blooms, waves and the wordmark (potrace),
  slices the charm sprite sheet into 251 charms, AI-tags every asset and reference.
* **Editor** (`editor/src`) — `model/` (document store, undo/redo, edit-op application), `render/BoardSvg.tsx`
  (the renderer), `canvas/` (direct manipulation, comments), `panels/`, `copilot/`.

## Security
Keys live only in `.env` (git-ignored); `.env.example` has placeholders. Secrets are `SecretStr`, never logged or
sent to the browser. All services bind to `127.0.0.1`; uploads are size-capped and validated; ids are validated.

## Tests
* `scripts/smoke_test.py` — create (4 formats), variations and a layer edit through the API.
* `tests/e2e_studio.py` — real browser: create (+ every image layer loaded, canvas-vs-server pixel diff), AI
  layer edit, photo edit, comment edit, manual drag/undo/inline text, 4 variations, Brand DNA on an off-brand
  board (`tests/dna_fixture.py`) with pins and Fix-all, and voice-to-edit through Chromium's fake microphone
  (`tests/fixtures/voice_edit_headline.wav`; skipped without an ElevenLabs key), comment-popover dismissal, and a
  live Meta Ad Library scan → idea → board and competitor remix → board. Tests use throwaway
  documents (`?doc=e2e-…`), never your own. Screenshots in `logs/e2e/`.

Fonts: Barlow / Barlow Condensed (SIL OFL) as the closest open match to Xero's typeface.
