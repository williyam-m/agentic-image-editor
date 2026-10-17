# 6. API reference

Base URL `http://localhost:8787`. JSON unless noted. Errors use FastAPI's `{"detail": "…"}` with the status codes
listed. Interactive OpenAPI docs are served at `/docs` while the API is running.

## 6.1 System

### `GET /api/health`
```json
{ "api": "ok", "temporal": "ok", "celery": "ok (1 worker)", "brand_assets": 323 }
```
Temporal/Celery report `down: <Error>` or `no workers` instead of failing the request.

## 6.2 Brand

| Method & path | Description |
|---|---|
| `GET /api/brand` | palette, colourways, fonts, `font_files` URLs, `font_metrics`, formats, rules text, insights, asset counts per category |
| `GET /api/brand/assets?category=&q=&limit=300` | catalog search (name, description, tags); each item has `url`, `vectorUrl`, `file` |
| `GET /api/references` | analysed reference ads with image URLs |
| `POST /api/brand/reindex` | starts `BrandIngestWorkflow` → `{job_id: "brand-…"}` |

## 6.3 Documents, uploads, rendering

| Method & path | Body | Response | Errors |
|---|---|---|---|
| `GET /api/docs/{doc_id}` | — | document (empty doc if new) | 400 bad id |
| `PUT /api/docs/{doc_id}` | document | `{id, updated}` | 400 bad id · 413 > 8 MB |
| `POST /api/uploads` | `{image: base64/data-URL, name}` | `{url, file, width, height, transparent}` | 400 not an image · 413 > 12 MB |
| `POST /api/render` | `{spec, scale: 0.1–3.0}` | `{url}` of the server-rendered PNG | 400 invalid design |

`doc_id` must match `^[a-z0-9-]{1,40}$`.

## 6.4 Voice

| Method & path | Description |
|---|---|
| `GET /api/voice/status` | `{enabled, model: "scribe_v2", provider: "ElevenLabs"}` |
| `POST /api/voice/transcribe` | multipart `file` (webm/opus) → `{text, language, seconds}`. 503 without key · 400 < 1.2 KB · 413 > 10 MB · 502 upstream unreachable / 5xx |

## 6.5 AI jobs

All return `{job_id}` immediately; poll `GET /api/jobs/{job_id}`.

### `POST /api/designs` → `design-<id>`
```json
{
  "prompt": "Small café owner getting paid faster",   // ≤ 2000 chars
  "format": "feed",                                   // feed | square | story | landscape
  "count": 1,                                         // 1–4 (variations)
  "reference_id": null,       // analysed library reference (ref-xx)
  "reference_spec": null,     // a board to take inspiration from (rendered server-side)
  "reference_image": null,    // base64 PNG
  "reference_file": null,     // cached competitor creative, must be under competitors/
  "base_brief": null          // brief of a Crux-made board (for variations)
}
```
Result: `{specs: DesignSpec[], results: [{checks, summary{score,passed,fixed,warnings}, qa{score,strengths,issues}, final_url, thumb_url}], events}`.

### `POST /api/edits` → `edit-<id>`
```json
{
  "instruction": "make the headline say get paid in days",
  "board":   { "id": "…", "width": 1080, "height": 1350, "brief": { … } },
  "targets": [ /* LayerInfo of the selected layer(s), ≤ 60; image.b64 allowed */ ],
  "context": [ /* LayerInfo of the other layers, ≤ 300 */ ],
  "pointer": { "x": 540, "y": 220 }   // optional (comment pin)
}
```
Result: `{message, ops: EditOp[], notes: string[]}` (see [Data model §5.6](05-data-model.md#56-edit-operations-the-edit-contract)).

### `POST /api/brand-dna` → `dna-<id>`
Body `{spec, scale?}`. Result:
```json
{ "score": 78, "verdict": "Needs fixes",
  "scores": { "color": 82, "typography": 100, "logo": 64, "imagery": 90, "layout": 80, "copy": 91 },
  "findings": [ { "id": "v1", "dimension": "logo", "severity": "high", "issue": "…", "suggestion": "…",
                  "layer_id": "l_…", "layer_name": "Logo", "box": [0.06,0.05,0.2,0.05],
                  "fix": { "op": "update", "target": "l_…", "props": { "fill": "#000856" } },
                  "source": "measured" } ],
  "fixable": 4, "strengths": ["…"], "summary": "…" }
```

### `POST /api/competitors` → `intel-<id>`
Body `{query (2–60 chars), country: "ALL" | ISO-2/3 uppercase, limit: 5–30}`. Result:
`{query, country, ads[{library_id, advertiser, status, started, ended, days_active, tier, variants, body, cta, domain, media_type (image·carousel·video·text), image_urls, video_url, poster_url, ad_url, thumb_url, analysis{hook, angle, visual, style, offer, tags, relevance, why_it_works}}], insights{summary, patterns[], whitespace[], ideas[{title, headline, subhead, cta, archetype, visual, why, inspired_by[]}]}}`.

### `GET /api/competitors/latest?query=&country=ALL`
The last saved report for that query/country, or 404.

### `GET /api/jobs/{job_id}`
```json
{ "status": "running | completed | failed | terminated | timed_out | canceled",
  "progress": { "stage": "generating", "events": [{"t": 3.1, "text": "…", "kind": "stage|info|check|error"}],
                "specs": [ … ], "results": [ … ], "version": 12, "done": false },
  "result": { … },          // when completed
  "error": "The job did not complete. Please try again." }   // when not running/completed
```
400 malformed id · 404 unknown job.

## 6.6 Static

| Path | Served from | Cache |
|---|---|---|
| `/files/*` | `data/` (brand assets, job outputs, uploads, competitor creatives) | default |
| `/fonts/*` | `backend/assets/fonts` | 1 year, immutable |
| `/assets/*` | `editor/dist/assets` (hashed) | 1 year, immutable |
| `/`, `/studio`, other paths | `editor/dist/index.html` | `no-store` |
