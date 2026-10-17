# Crux Studio — Engineering Documentation

End-to-end technical documentation for Crux Studio, the layered AI image editor with a brand copilot.
Start with the root [`README.md`](../README.md) for the overview and the high-level design (HLD); the documents
below cover each part in depth.

| # | Document | What it covers |
|---|---|---|
| 1 | [Architecture](01-architecture.md) | System context, HLD, component responsibilities, runtime topology, technology choices and the reasoning behind them |
| 2 | [Backend design](02-backend.md) | Python package layout, the API layer, Temporal workflows and activities, Celery tasks, the LLM and image clients, reliability and concurrency |
| 3 | [End-to-end flows](03-flows.md) | Sequence diagrams for create, variations, layer edit, comment edit, voice edit, Brand DNA, competitor intel, brand ingestion, export |
| 4 | [Design engine & brand compliance](04-design-engine.md) | The layer model, planner → layout engine split, text fitting, compositing, brand guard, image compliance, legal policy, Brand DNA scoring |
| 5 | [Data model & storage](05-data-model.md) | `DesignSpec`/`Layer`, documents, edit ops, brand catalog, on-disk layout of `data/` |
| 6 | [API reference](06-api-reference.md) | Every HTTP endpoint with request/response shapes, status codes and limits |
| 7 | [Frontend architecture](07-frontend.md) | Editor state, rendering parity, canvas interaction, copilot flows, voice capture |
| 8 | [Operations, security & testing](08-operations.md) | Configuration, running locally, observability, security controls, test strategy, scaling path to production |

## Conventions

* Diagrams are [Mermaid](https://mermaid.js.org/) and render natively on GitHub.
* Paths are relative to the repository root, e.g. `backend/crux/workflows/design.py`.
* "Board" = one ad canvas (a `DesignSpec`). "Document" = a project holding boards and comments.
* "Job" = one Temporal workflow execution, addressed by its workflow id (`design-…`, `edit-…`, `dna-…`, `intel-…`, `brand-…`).
