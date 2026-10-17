# 8. Operations, security & testing

## 8.1 Configuration

All settings come from `.env` (git-ignored) or the environment (`backend/crux/config.py`).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | ✓ | — | GPT Image |
| `DEEPSEEK_PRO_BASE_URL` / `_MODEL` / `_API_KEY` | ✓ | model `DeepSeek-V4-Pro` | planning & editing |
| `DEEPSEEK_FLASH_BASE_URL` / `_MODEL` / `_API_KEY` | ✓ | model `DeepSeek-V4.1-Flash` | vision & fast tasks |
| `ELEVENLABS_API_KEY` | — | empty ⇒ voice disabled | speech-to-text |
| `IMAGE_MODEL` / `IMAGE_QUALITY` | — | `gpt-image-2.5-flare` / `medium` | image generation |
| `STT_MODEL` | — | `scribe_v2` | |
| `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` / `TEMPORAL_TASK_QUEUE` | — | `localhost:7233` / `default` / `crux-design` | |
| `REDIS_URL` | — | `redis://localhost:6390/0` | Celery broker + backend |
| `API_HOST` / `API_PORT` / `PUBLIC_API_URL` | — | `127.0.0.1` / `8787` / `http://localhost:8787` | |
| `DATA_DIR`, `BRAND_KIT_DIR`, `REFERENCES_DIR`, `FONTS_DIR`, `EDITOR_DIST_DIR` | — | repo paths | |
| `LLM_TIMEOUT_S` | — | `90` | per-request LLM timeout |

## 8.2 Running

```bash
brew install redis temporal potrace node python@3.13   # macOS prerequisites
cp .env.example .env                                   # add keys
./run.sh            # venv + deps + editor build + all services + brand ingestion (first run) → opens the browser
./run.sh status     # API / Temporal / Celery health
./run.sh test       # smoke + browser E2E
./run.sh stop
```

`run.sh` is idempotent: it keeps PID files in `.run/`, skips services that are already running, reinstalls Python
deps only when `requirements.txt` changes, and re-ingests the brand kit only when its fingerprint changes.

Frontend development with hot reload: `cd editor && npm run dev` (Vite on :5173, which is already allowed by CORS).

## 8.3 Observability

* **Temporal UI** at http://localhost:8233 shows every job's full history, inputs/outputs, retries and failures,
  searchable by workflow id (`design-…`, `edit-…`).
* **Per-job event timeline**: workflows record timed events (`t`, `text`, `kind`) visible in the editor's job cards
  and in the progress query.
* **Structured logs** in `logs/*.log`: LLM latency and token counts per call, image generation latency, compliance
  regenerations, scrape stats, retry warnings with backoff.
* **Health**: `GET /api/health` checks Temporal, pings Celery workers and reports the brand asset count.
* **Quality signals per design**: brand-guard score, art-director QA score, compliance verdict per image layer.

## 8.4 Security controls

| Area | Control |
|---|---|
| Secrets | Only in `.env` (git-ignored; `.env.example` has placeholders). Loaded as `SecretStr`, never logged, never sent to the browser. The ElevenLabs key is used only by the server-side proxy |
| Network exposure | Every service binds to `127.0.0.1`. CORS is restricted to the app origin and the Vite dev server; methods `GET/POST/PUT` |
| Input validation | Pydantic bounds on every field; doc/job id regexes; image ≤ 12 MB, audio ≤ 10 MB, doc ≤ 8 MB; uploads re-encoded to PNG by Pillow (rejects non-images) with random server-side names |
| Path traversal | `reference_file` resolved and checked to live under `data/competitors/`; the SPA fallback only serves files inside `editor/dist`; `/files` is a StaticFiles mount rooted at `data/` |
| Content safety | Image policy in every prompt, plus vision verification and regeneration; legal copy policy enforced in code (planner re-plan, edit blocks, guard, idea filtering) |
| Third-party data | The competitor scraper reads only the public Ad Library (no login). Creatives are cached locally for analysis, and generated ideas never reuse competitor copy, claims or branding |
| Serialization | Celery accepts JSON only (no pickle) |

## 8.5 Test strategy

| Suite | Command | Covers |
|---|---|---|
| Smoke (API) | `.venv/bin/python scripts/smoke_test.py all` | create in all 4 formats, variations, a layer edit, end-to-end through Temporal + Celery |
| E2E (browser) | `.venv/bin/python tests/e2e_studio.py all` | Real Chromium against the running studio: create (every image layer loaded + **canvas-vs-server pixel diff**), AI layer edit, photo edit, comment edit, comment-popover dismissal, manual drag/undo/inline text, 4 variations, Brand DNA on an off-brand fixture (`tests/dna_fixture.py`) with pins and Fix-all, voice-to-edit via Chromium's fake microphone (`tests/fixtures/voice_edit_headline.wav`, skipped without a key), live Meta Ad Library scan → idea → board and remix → board |

Individual scenarios: `tests/e2e_studio.py create|edit|photo|comment|comment-ui|variations|dna|manual|voice|intel`.
Screenshots are written to `logs/e2e/`. Tests always use throwaway documents and never touch the designer's own file.

## 8.6 Performance profile (typical)

| Operation | Latency | What bounds it |
|---|---|---|
| Board with editable layers on canvas | ~3s | one Pro planning call + deterministic layout |
| All image layers of a design | ~20s | slowest image layer (all run in parallel); each compliance regeneration adds one image call |
| 4 variations | about one design | every layer of every variant runs at once on Celery |
| Text / colour / geometry edit | one Pro call | the compile step is deterministic and local |
| Photo edit | one image edit call | |
| Competitor scan | ~20–50s | scrape (≤75s cap) + 20s analysis deadline + one synthesis call |

## 8.7 Scaling path to production

The architecture already separates stateless API, durable orchestration and elastic execution, so scaling is
mostly configuration and swapping storage:

| Concern | Today (single node) | Production |
|---|---|---|
| Temporal | `start-dev` with SQLite | Temporal Cloud or a self-hosted cluster (Postgres/Cassandra); multiple workers on the same task queue |
| Celery | 24 threads, local Redis | Autoscaled worker pool per queue (images vs scraping vs analysis); managed Redis/RabbitMQ; per-provider rate limiting |
| Storage | `data/` filesystem | Object storage (S3/GCS) behind the same `/files` URLs + CDN; documents in Postgres with optimistic concurrency (`updated` already returned) |
| API | 1 uvicorn process | N stateless replicas behind a load balancer |
| Progress delivery | 500–600 ms polling | Server-sent events/WebSocket fed by workflow queries or updates |
| Auth & tenancy | none (localhost tool) | SSO/OIDC, per-workspace brand kits and documents, audit log of AI edits |
| Secrets | `.env` | Secret manager (Vault / cloud KMS) |
| Observability | logs + Temporal UI | OpenTelemetry traces across API → workflow → activity → Celery → provider; cost/latency dashboards per model |
