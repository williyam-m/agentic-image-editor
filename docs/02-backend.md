# 2. Backend design

## 2.1 Package layout

```
backend/crux/
├── config.py              Settings (pydantic-settings, .env, SecretStr); creates data/ subfolders
├── llm.py                 complete_json(): JSON-mode chat completions, retries, tier fallback
├── imagegen.py            GPT Image generate/edit, size selection, transparent trim, retries
├── api/main.py            FastAPI app: REST endpoints, static SPA, /files, /fonts, cache headers
├── workflows/
│   ├── design.py          Temporal workflows (Design, Edit, BrandIngest, BrandDna, Competitor)
│   ├── activities.py      Temporal activities (LLM work + the celery_task bridge)
│   └── worker.py          Temporal worker process (task queue crux-design, 64-thread activity pool)
├── tasks/
│   ├── app.py             Celery app (Redis broker/backend, JSON only, acks_late)
│   └── jobs.py            Celery tasks — thin wrappers over domain code
├── design/                Creation & editing domain
│   ├── spec.py            DesignSpec / Layer (the shared layer model)
│   ├── brief.py           Brief, archetypes, colourways
│   ├── planner.py         prompt (+reference) → Brief; variation plans; reference analysis
│   ├── layouts.py         Brief → DesignSpec (deterministic geometry)
│   ├── fonts.py           Real-metric text measuring, wrapping, fitting, headline balancing
│   ├── editor.py          Edit planning + compile_ops (intent → brand-safe ops)
│   ├── layers.py          Per-layer image generation with compliance loop; final compose + QA
│   ├── compose.py         Pillow compositor (the server renderer)
│   ├── docs.py            Document persistence; layer_infos/board_info flatteners
│   └── tree.py            Dependency-free spec helpers (safe inside workflow sandbox)
├── brand/                 Brand domain
│   ├── kit.py             Palette, colourways, fonts, formats, safe zones, rules text, catalog loader
│   ├── policy.py          Legal/brand policy: banned claims, competitors, offer → "Terms apply."
│   ├── guard.py           Measured audit + safe auto-fixes on a DesignSpec
│   ├── compliance.py      Vision check of generated images + correction prompts
│   ├── dna.py             Brand DNA: measured + visual audits, merge and scoring
│   ├── ingest.py          Brand kit → asset catalog (vectorise, slice, tag, analyse references)
│   └── vectorize.py       potrace wrapper; SVG path normalisation
└── research/
    ├── adlibrary.py       Playwright scrape of the public Meta Ad Library; media caching
    └── competitors.py     Per-ad vision analysis; longevity-weighted synthesis → on-brand ideas
```

**Dependency rule:** `api`, `workflows` and `tasks` depend on the domain packages (`design`, `brand`,
`research`). The domain packages never import from them. Workflow code imports only `tree`, `editor.merge_image_results`,
`planner.variation_plan` and `competitors.tier`, all deterministic, through `workflow.unsafe.imports_passed_through()`,
so Temporal replay stays deterministic.

## 2.2 API layer (`api/main.py`)

* **Job pattern.** Every AI operation (`/api/designs`, `/api/edits`, `/api/brand-dna`, `/api/competitors`,
  `/api/brand/reindex`) validates input, writes any binary inputs to `data/jobs/<job_id>/`, starts a Temporal
  workflow and returns `{job_id}` right away. Clients poll `GET /api/jobs/{job_id}`. That endpoint maps the
  workflow status to `running | completed | failed | …` and attaches the latest `progress` query result.
* **Synchronous endpoints** cover fast, local operations only: document load/save, uploads, server render/export,
  brand catalog reads, speech proxy.
* **Validation & limits:** Pydantic models bound every field (`prompt ≤ 2000`, `count 1–4`,
  `targets ≤ 60`, `context ≤ 300`, `scale 0.1–3.0`, country `^[A-Z]{2,3}$`). Images are capped at 12 MB, audio at 10 MB,
  documents at 8 MB. Doc ids must match `^[a-z0-9-]{1,40}$`. Job ids must be alphanumeric plus `-`. Competitor
  reference files are resolved and confined to `data/competitors/`.
* **Static serving:** `/files` → `data/`, `/fonts` → bundled TTFs, `/assets` → hashed SPA bundle (immutable,
  1-year cache). Every other path falls back to `index.html` (`no-store`), so a rebuild is picked up on reload.
* **CORS:** limited to the public URL and the Vite dev server; methods `GET/POST/PUT`.

## 2.3 Orchestration — Temporal workflows (`workflows/design.py`)

| Workflow | Id prefix | Steps | Progress state |
|---|---|---|---|
| `DesignWorkflow` | `design-` | [analyse reference] → plan N briefs (parallel) → N layouts + brand guard (parallel) → every pending image layer of every variant (parallel, Celery) → per-variant compose + audit + QA | `stage`, timed `events`, `specs[]`, `results[]`, `version`, `done` |
| `EditWorkflow` | `edit-` | plan + compile ops → image jobs (parallel, Celery) → merge image results into ops | `stage`, `version`, `done` |
| `BrandDnaWorkflow` | `dna-` | measured audit → visual audit grounded in measured facts → merge & score | `stage` |
| `CompetitorWorkflow` | `intel-` | scrape (Celery) → sort by days active, tier → per-ad vision analysis (parallel, **20s deadline**) → synthesis → save | `stage`, `events`, `ads[]`, `insights` |
| `BrandIngestWorkflow` | `brand-` | prepare assets (Celery) → describe charm/illustration batches + analyse references (parallel) → synthesise insights → write catalog | `stage` |

### Retry and timeout policy

| Call type | Helper | Start-to-close | Heartbeat | Retry |
|---|---|---|---|---|
| LLM activity | `_llm()` | 30–180s per activity | — | 3 attempts, 1s initial, ×2 backoff |
| Celery-backed activity | `_celery()` | 90–600s per task | 30s | 3 attempts, 2s initial, ×2 backoff |

Inside activities, `llm.complete_json` adds its own fast retries: 4 attempts with jittered exponential backoff on
429, connection, timeout, 5xx and malformed-JSON errors. On the last attempt it falls back to the other model tier
(text-only calls). `imagegen._retry` does the same for image calls. Temporal therefore only sees failures that
persist after these local retries.

### Partial-failure semantics

* One image layer failing does **not** fail the design. The layer is marked `status: "failed"` with an error event,
  the board is still delivered, and the designer can regenerate that layer.
* Compositing failure for one variant emits an error event. The other variants still finish.
* Competitor analysis keeps going when individual ads fail or exceed the 20s deadline. Synthesis uses whatever
  has been read.
* Edit image jobs run with `return_exceptions=True`. Failed ones become a note ("N image edit(s) failed — try
  again"), and the text/geometry ops still apply.

## 2.4 Activities (`workflows/activities.py`)

| Activity | Runs where | Purpose |
|---|---|---|
| `celery_task(name, args)` | async, worker event loop | Bridge: `send_task`, poll `ready()` in a thread every 300 ms while **heartbeating** the Celery id, revoke on cancellation, raise `ApplicationError` on failure |
| `plan_brief` | thread pool | `planner.plan()` → `Brief` |
| `build_layout` | thread pool | `layouts.build_spec()` + `guard.audit(fix=True)` |
| `analyze_image` | thread pool | Vision read of a reference design (headline, archetype, colourway, …) |
| `plan_edit` | thread pool | `editor.plan_edit()` (LLM) + `compile_ops()` (deterministic) |
| `dna_measured` / `dna_visual` / `dna_merge` | thread pool | Brand DNA stages |
| `synthesize_insights` / `write_catalog` | thread pool | Brand ingestion stages |
| `synthesize_competitors` / `save_competitors` | thread pool | Competitor synthesis + persistence |

The worker runs `max_concurrent_activities=64` on a 64-thread executor, so blocking SDK calls never stall the
workflow event loop.

## 2.5 Execution — Celery (`tasks/`)

Configuration: JSON serialisation only, `task_acks_late`, `task_reject_on_worker_lost`, `worker_prefetch_multiplier=1`
(fair dispatch of long tasks), `result_expires=3600`, thread pool of 24.

| Task | Domain function | Bounded by |
|---|---|---|
| `crux.generate_layer` | `design.layers.generate_layer_image` | 1–3 image calls (compliance regeneration) + vision check each |
| `crux.compose_final` | `design.layers.compose_and_audit` | local render + guard, vision QA capped at 25s |
| `crux.scrape_ads` | `research.adlibrary.scrape` + `cache_media` | 75s scrape budget + media downloads (20s timeout each) |
| `crux.analyze_ad` | `research.competitors.analyze_ad` | one vision call |
| `crux.describe_batch` / `crux.analyze_reference` / `crux.prepare_assets` | `brand.ingest.*` | ingestion only |

Tasks are idempotent. Image outputs are written to `data/jobs/<job_id>/<layer_id>-<version>.png`, so a retried task
overwrites its own output and nothing else.

## 2.6 AI clients

### `llm.complete_json`
* Two tiers: **pro** (DeepSeek V4 Pro, text-only, planning/editing) and **flash** (DeepSeek V4.1 Flash,
  vision + fast tasks). Vision input forces `flash`.
* `response_format={"type": "json_object"}`. Output is defensively parsed: code fences are stripped, and prose
  around the object is tolerated. Anything that isn't a JSON object counts as a failure and is retried.
* Per-call `timeout` and `attempts` let callers on the critical path fail fast. Examples: image compliance
  (`attempts=2, timeout=20`) and QA (`attempts=2, timeout=25`). Both are advisory and never block delivery.

### `imagegen`
* `best_size(w, h)` maps a layer's aspect to `1024x1024 | 1024x1536 | 1536x1024`.
* `generate()` for new images. `edit()` for in-place edits and brand-style generation from up to 8 reference
  images. `transparent=True` requests PNG with alpha for cut-outs, charms and illustrations.
* `trim_transparent()` crops empty margins so transparent layers hug their content.

## 2.7 Concurrency budget

| Layer | Limit | Rationale |
|---|---|---|
| Temporal activities | 64 concurrent | Covers 4 variants × (plan + layout) plus edits and audits in flight |
| Celery | 24 threads | 4 variants × ~3 image layers + compositing + analysis with headroom; bounded to respect provider rate limits |
| Competitor analysis | ≤ 30 ads, 20s wall-clock deadline | Slow vision calls can't hold up the scan |
| Ingestion | charm batches of 30, illustration batches of 12 | Contact-sheet vision calls keep request count low |

## 2.8 Configuration (`config.py`)

`Settings` loads `.env` from the project root. Secrets are `SecretStr` with **no defaults**, and the process fails
fast if one is missing. `ELEVENLABS_API_KEY` is optional; an empty value means voice is disabled. Infrastructure
endpoints (Temporal address/namespace/task queue, Redis URL, API host/port, public URL) and paths (`brand_kit_dir`,
`references_dir`, `data_dir`, `fonts_dir`, `editor_dist_dir`) can all be overridden by environment variables.
See [Operations](08-operations.md#81-configuration) for the full table.
