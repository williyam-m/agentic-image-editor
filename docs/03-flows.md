# 3. End-to-end flows

Every AI flow follows the same asynchronous pattern:

```mermaid
sequenceDiagram
    autonumber
    participant UI as Editor SPA
    participant API as FastAPI
    participant T as Temporal
    participant W as Worker (activities)
    participant C as Celery
    UI->>API: POST /api/<operation>
    API->>API: validate, persist binary inputs to data/jobs/<id>/
    API->>T: start_workflow(id = <prefix>-<id>)
    API-->>UI: { job_id }
    loop every 500–600 ms
        UI->>API: GET /api/jobs/{job_id}
        API->>T: describe() + query("progress")
        API-->>UI: { status, progress, result? }
    end
    T->>W: activities (LLM, deterministic code)
    W->>C: celery_task(name, args) — heartbeating
    C-->>W: result
```

---

## 3.1 Create a design (one board)

Trigger: the Copilot composer with no board selected (or text such as "new design …"), format 4:5 · 1:1 · 9:16 · 1.91:1.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Editor
    participant API
    participant DW as DesignWorkflow
    participant ACT as Activities
    participant CEL as Celery
    participant LLM as DeepSeek Pro/Flash
    participant IMG as GPT Image

    UI->>API: POST /api/designs {prompt, format, count:1}
    API->>DW: start design-<id>
    DW->>ACT: plan_brief
    ACT->>LLM: system = brand rules + voice + archetypes + references + asset catalog
    LLM-->>ACT: Brief JSON
    ACT->>ACT: normalise · copy_issues()? → one corrective re-plan with legal feedback
    DW->>ACT: build_layout(brief)
    ACT->>ACT: layouts.build_spec → guard.audit(fix=True)
    Note over DW,UI: progress.specs now holds the layered board → UI places it (~3s), images show as pending
    par every pending image layer
        DW->>CEL: crux.generate_layer
        CEL->>IMG: generate / edit (brand_style) / transparent
        CEL->>LLM: compliance.check_image (Flash vision)
        alt blocking violation (text, logo, watermark, competitor, unsafe, off-palette for non-photos)
            CEL->>IMG: regenerate with STRICT CORRECTION (≤3 attempts)
        end
        CEL-->>DW: file, src, geometry, compliance verdict
        DW->>DW: patch layer → status ready, event "Photo ready (18s) · policy-verified"
    end
    DW->>CEL: crux.compose_final
    CEL->>CEL: guard.audit(fix) → render PNG + thumbnail → vision art-director QA
    CEL-->>DW: spec, checks, summary score, qa, final_url
    DW-->>UI: completed (UI merges final spec, brand score, QA)
```

**What the user sees.** A board with ~10 named layers appears in about 3s. Photos and illustrations fill their
placeholders as each one finishes (~20s). The job card streams timed events ("Brief: …", "Photo ready …", "Variant 1:
brand check 96/100, art-director score 8/10"). The board is editable from the first frame. Server merges (`mergeFromServer`) only fill in pending images,
brand-guard colour fixes and guard-added layers, so the designer's own moves and copy changes are kept.

## 3.2 Variations ("Create 4 different images like this")

`inferIntent` detects a count > 1 while a board is open. The editor sends `count: 4`, `reference_spec` (the current
board), and `base_brief` (if Crux made the board).

```mermaid
flowchart LR
    A[reference_spec] -->|API renders it with the server compositor| B[reference.png]
    B --> C[analyze_image · vision read]
    C --> D[variation_plan]
    D --> V1["#1 closest: same archetype + colourway,<br/>new headline formula + visual"]
    D --> V2["#2 different layout archetype,<br/>new copy angle"]
    D --> V3["#3 different archetype +<br/>contrasting colourway + new bloom"]
    D --> V4["#4 bold minimal: 2–4 word headline,<br/>one strong visual"]
    V1 & V2 & V3 & V4 --> P[plan_brief ×4 in parallel]
    P --> L[build_layout ×4 in parallel]
    L --> G[all image layers of all 4 variants in parallel on Celery]
    G --> F[compose + audit + QA per variant]
```

Variety comes from code, not from hoping the model varies its output. Each variant gets a forced archetype from a
rotation, a colourway override for #3, and its own bloom (a deterministic pick seeded by the base headline, never
repeated within the set).

## 3.3 Edit a layer (chat)

Trigger: a layer is selected and the designer types an instruction. Without a selection, edit-like verbs
(`make|change|replace|move|recolour|…`) run a board-scoped edit.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Editor
    participant API
    participant EW as EditWorkflow
    participant ACT as plan_edit activity
    participant CEL as Celery
    UI->>API: POST /api/edits {instruction, board, targets:[selected], context:[other layers], pointer?}
    Note right of API: inline image bytes in targets → saved to data/jobs/<id>/src-*.png
    API->>EW: start edit-<id>
    EW->>ACT: plan_edit
    ACT->>ACT: LLM (Pro) → intent ops: set_text, style_text, set_fill, transform,<br/>edit_image, swap_asset, remove, arrange, add_charm, add_text
    ACT->>ACT: compile_ops → policy blocks · text re-fit with real metrics · CTA resize ·<br/>palette snap · legal line · image jobs
    opt image jobs (edit_image / generated charm)
        par
            EW->>CEL: crux.generate_layer (gen_mode=edit keeps same person/pose/framing)
        end
        EW->>EW: merge_image_results → image / add ops
    end
    EW-->>UI: {message, ops[], notes[]}
    UI->>UI: applyOps(board, ops) as ONE undo step → autosave
```

Examples of compile-time guarantees:

| Instruction | Compiled result |
|---|---|
| "Make the headline say *Get paid in days*" | `update` with text balanced across ≤3 lines and font size re-fitted to the original box |
| "Change the CTA to *Start your free trial today*" | Label re-fitted **and** CTA background resized to the new label width; offer detected → "Terms apply." layer added under the CTA |
| "Make the background orange" | Colour snapped to the nearest brand colour, with a note: "#FF8800 snapped to brand …" |
| "Remove the logo" / "rotate the logo" | Blocked: "the Xero wordmark is mandatory …" |
| "Say we're the best accounting app" | Blocked: "Unapproved claim 'best' needs legal sign-off" |
| "Make her smile" (photo) | `edit_image` mode=edit on the existing file: same person, pose, framing |

## 3.4 Comment to edit

```mermaid
sequenceDiagram
    participant D as Designer
    participant UI as Editor
    participant BE as Backend (EditWorkflow)
    D->>UI: C tool, click on a layer, type the change
    UI->>UI: comment {status: working, layerId under the pin, x,y}
    UI->>BE: runEdit(board, text, [layerId], pointer)
    BE-->>UI: {message, ops, notes}
    UI->>UI: applyOps · thread reply from Crux · status → resolved (failed on error)
```

The pin's board coordinates are sent as `pointer`, so position-relative requests ("add a sparkle here") are placed
at the pin.

## 3.5 Voice to edit

```mermaid
sequenceDiagram
    participant D as Designer
    participant UI as useVoice (MediaRecorder + analyser)
    participant API as /api/voice/transcribe
    participant EL as ElevenLabs Scribe v2
    D->>UI: press M (or mic) and speak
    UI->>UI: RMS level meter · auto-stop after 1.3s of silence (max 25s)
    UI->>API: multipart audio/webm
    API->>API: 1.2 KB ≤ size ≤ 10 MB
    API->>EL: speech-to-text (model scribe_v2, no_verbatim)
    EL-->>API: text + words
    API-->>UI: {text, language, seconds}
    UI->>UI: route the text as an edit on the selected layer (or board) — same as §3.3
```

`GET /api/voice/status` reports whether a key is configured. Without one the mic is disabled and nothing else is
affected. The ElevenLabs key never reaches the browser.

## 3.6 Brand DNA audit and fix

```mermaid
sequenceDiagram
    autonumber
    participant UI as Editor
    participant API
    participant BW as BrandDnaWorkflow
    UI->>API: POST /api/brand-dna {spec}
    API->>API: render spec with the shared compositor → dna.png, flatten layer_infos + board_info
    API->>BW: start dna-<id>
    BW->>BW: dna_measured — fonts, palette, WCAG contrast sampled from pixels,<br/>logo colourway/size/clear space, legal copy, safe zones (each with a ready fix op)
    BW->>BW: dna_visual — Flash vision audit grounded in the measured facts,<br/>every violation with a normalised box
    BW->>BW: dna_merge — drop visual duplicates (IoU > 0.25), sort by severity, score 6 dimensions
    BW-->>UI: {score, scores, verdict, findings[], fixable, strengths, summary}
    UI->>UI: DNA card · Fix N automatically · per-issue Fix/Show · Pin issues on canvas · Re-check
```

"Fix" applies the finding's pre-compiled `fix` op locally, so it can be undone, and clears the stale pins. Fixes are
*coherent*: structural fills snap to primary colours first, then text and logo colours are chosen against the
background they will actually sit on.

## 3.7 Competitor intel (Meta Ad Library)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Competitors tab
    participant API
    participant CW as CompetitorWorkflow
    participant CEL as Celery
    participant META as Meta Ad Library (public)
    participant LLM as DeepSeek
    UI->>API: POST /api/competitors {query, country, limit}
    API->>CW: start intel-<id>
    CW->>CEL: crux.scrape_ads
    CEL->>META: headless Chromium, gentle scrolling, dedupe by Library ID
    CEL->>CEL: cache lead creative (image / video poster) to data/competitors/<run>/
    CEL-->>CW: ads[] with started-running date → days_active
    CW->>CW: sort by days_active · tier: proven ≥90 · testing 30–89 · new <30
    par each ad (20s deadline for the whole stage)
        CW->>CEL: crux.analyze_ad (vision: hook, angle, format, style, offer, relevance)
    end
    CW->>LLM: synthesize (Pro) — longevity-weighted patterns, whitespace, 5 original ideas
    CW->>CW: drop ideas failing copy_issues() · save data/competitors/<query-country>.json
    CW-->>UI: report → idea cards with "Create this →" and "Remix on-brand" per ad
```

"Create this →" starts a §3.1 design seeded with the idea. "Remix on-brand" starts a design with
`reference_file` set to the cached competitor creative. The API confines that path to `data/competitors/`. The
synthesis prompt forbids reusing competitor copy, claims, characters or branding, and forbids naming any
competitor or advertiser.

## 3.8 Brand ingestion (first run / reindex)

```mermaid
flowchart TB
    S[Candidate-resources/Brand-Kit + Image_Ad_References] --> FP{fingerprint matches catalog.json?}
    FP -- yes --> SKIP[use cached catalog]
    FP -- no --> P[prepare_assets — deterministic]
    P --> P1[Wordmark → potrace SVG at 8×]
    P --> P2[12 named blooms → SVG + masks]
    P --> P3[Background templates → blue wave vectors]
    P --> P4[Illustrations PNG/SVG → bitmaps]
    P --> P5[Charm sprite sheet → sliced into 251 charms]
    P --> P6[Product UI device shots]
    P --> P7[Reference ads]
    P4 & P6 --> V1[describe_batch — vision on contact sheets of 12]
    P5 --> V2[describe_batch — contact sheets of 30]
    P7 --> V3[analyze_reference — headline, archetype, colourway, copy angle]
    V3 --> SY[synthesize_insights — voice, headline formulas, CTA bank]
    V1 & V2 & SY --> WC[write_catalog → data/brand/catalog.json]
```

`./run.sh` runs ingestion locally on first start (~1 min). `POST /api/brand/reindex` runs the same pipeline as a
durable `BrandIngestWorkflow`. The catalog fingerprint is computed from the source files' names and sizes, so editing
the brand kit triggers re-analysis.

## 3.9 Manual editing, autosave and export

* Direct manipulation (move, resize, inline text, nudge, duplicate, delete, reorder, hide/lock) mutates the document
  in the browser store. Drags snapshot one undo step at the start. The undo stack holds 120 steps.
* Every mutation schedules a debounced (700 ms) `PUT /api/docs/{id}`. The server writes atomically (temp file +
  rename) and rejects documents over 8 MB.
* **Export PNG** → `POST /api/render {spec, scale}` → the server compositor renders → `data/jobs/exports/*.png`.
