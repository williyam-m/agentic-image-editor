"""HTTP API for Crux Studio: the layered editor app plus the copilot services behind it."""
from __future__ import annotations

import base64
import binascii
import io
import logging
import uuid
from typing import Any, Literal

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError

from ..brand.kit import COLORWAYS, FONTS, FORMATS, PALETTE, RULES_TEXT, load_kit
from ..config import get_settings
from ..design import docs, fonts
from ..design.compose import render
from ..design.spec import DesignSpec

log = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Crux Studio API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_api_url, "http://127.0.0.1:8787", "http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

MAX_IMAGE_BYTES = 12 * 1024 * 1024
_client: Client | None = None


async def temporal() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    return _client


def _decode_b64(b64: str) -> bytes:
    try:
        data = base64.b64decode(b64.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, "invalid image data") from e
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image too large")
    return data


def _save_b64(job_id: str, name: str, b64: str) -> str:
    path = settings.jobs_dir / job_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_decode_b64(b64))
    return str(path.relative_to(settings.data_dir))


def _render_spec(spec: dict[str, Any], folder: str, name: str, scale: float = 1.0) -> str:
    """Server-side composite of a spec (the same renderer the chat preview uses)."""
    try:
        model = DesignSpec.model_validate(spec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid design: {e}") from e
    path = settings.jobs_dir / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    render(model, scale).convert("RGB").save(path, "PNG", optimize=True)
    return str(path.relative_to(settings.data_dir))


# ---------------------------------------------------------------------------- models
class DesignRequest(BaseModel):
    prompt: str = Field(default="", max_length=2000)
    format: Literal["feed", "square", "story", "landscape"] = "feed"
    count: int = Field(default=1, ge=1, le=4)
    reference_id: str | None = None          # an analysed library reference (ref-xx)
    reference_spec: dict[str, Any] | None = None   # a board from the editor to take inspiration from
    reference_image: str | None = None       # base64 PNG
    base_brief: dict[str, Any] | None = None  # brief stored on a Crux-made board
    reference_file: str | None = None         # a cached competitor creative (competitors/…)


class CompetitorRequest(BaseModel):
    query: str = Field(min_length=2, max_length=60)
    country: str = Field(default="ALL", pattern=r"^[A-Z]{2,3}$")
    limit: int = Field(default=20, ge=5, le=30)


class EditRequest(BaseModel):
    instruction: str = Field(max_length=2000)
    board: dict[str, Any] = Field(default_factory=dict)
    targets: list[dict[str, Any]] = Field(default_factory=list, max_length=60)
    context: list[dict[str, Any]] = Field(default_factory=list, max_length=300)
    pointer: dict[str, float] | None = None


class SpecBody(BaseModel):
    spec: dict[str, Any]
    scale: float = Field(default=1.0, ge=0.1, le=3.0)


class UploadBody(BaseModel):
    image: str
    name: str = Field(default="upload.png", max_length=120)


# ---------------------------------------------------------------------------- system
@app.get("/api/health")
async def health() -> dict[str, Any]:
    out: dict[str, Any] = {"api": "ok"}
    try:
        await (await temporal()).service_client.check_health()
        out["temporal"] = "ok"
    except Exception as e:  # noqa: BLE001
        out["temporal"] = f"down: {type(e).__name__}"
    try:
        from ..tasks.app import celery_app

        pong = celery_app.control.ping(timeout=1.0)
        out["celery"] = f"ok ({len(pong)} worker)" if pong else "no workers"
    except Exception as e:  # noqa: BLE001
        out["celery"] = f"down: {type(e).__name__}"
    out["brand_assets"] = len(load_kit().assets)
    return out


# ---------------------------------------------------------------------------- brand
@app.get("/api/brand")
def brand() -> dict[str, Any]:
    kit = load_kit()
    counts: dict[str, int] = {}
    for a in kit.assets.values():
        counts[a.category] = counts.get(a.category, 0) + 1
    font_files = {k: f"{settings.public_api_url}/fonts/{f['file']}" for k, f in FONTS.items()}
    return {"palette": PALETTE, "colorways": COLORWAYS, "fonts": FONTS, "font_files": font_files,
            "font_metrics": fonts.metrics(), "formats": FORMATS, "rules": RULES_TEXT,
            "insights": kit.insights, "counts": counts}


@app.get("/api/brand/assets")
def assets(category: str | None = None, q: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    kit = load_kit()
    items = [a for a in kit.assets.values() if (not category or a.category == category)]
    if q:
        ql = q.lower()
        items = [a for a in items if ql in a.name.lower() or ql in a.description.lower() or ql in " ".join(a.tags)]
    return [{**a.to_public(), "file": f"brand/{a.file}"} for a in items[:limit]]


@app.get("/api/references")
def references() -> list[dict[str, Any]]:
    kit = load_kit()
    return [{**{k: r.get(k) for k in ("id", "headline", "cta", "archetype", "colorway", "visual", "copy_angle")},
             "url": f"{settings.public_api_url}/files/brand/{r['file']}"} for r in kit.references]


@app.post("/api/brand/reindex")
async def reindex() -> dict[str, str]:
    client = await temporal()
    wid = f"brand-{uuid.uuid4().hex[:8]}"
    await client.start_workflow("BrandIngestWorkflow", {}, id=wid, task_queue=settings.temporal_task_queue)
    return {"job_id": wid}


# ---------------------------------------------------------------------------- documents
@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str) -> dict[str, Any]:
    if not docs.valid_id(doc_id):
        raise HTTPException(400, "bad id")
    return docs.load(doc_id)


@app.put("/api/docs/{doc_id}")
def put_doc(doc_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    if not docs.valid_id(doc_id):
        raise HTTPException(400, "bad id")
    try:
        return docs.save(doc_id, doc)
    except ValueError as e:
        raise HTTPException(413, str(e)) from e


@app.post("/api/uploads")
def upload(body: UploadBody) -> dict[str, Any]:
    data = _decode_b64(body.image)
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "not an image") from e
    name = f"{uuid.uuid4().hex[:12]}.png"
    path = settings.uploads_dir / name
    im.convert("RGBA").save(path, "PNG", optimize=True)
    rel = str(path.relative_to(settings.data_dir))
    has_alpha = im.mode in ("RGBA", "LA") and Image.open(path).getextrema()[-1][0] < 250
    return {"url": f"{settings.public_api_url}/files/{rel}", "file": rel, "width": im.width, "height": im.height,
            "transparent": has_alpha}


@app.post("/api/render")
def render_spec(body: SpecBody) -> dict[str, str]:
    rel = _render_spec(body.spec, "exports", f"{body.spec.get('id', 'board')}-{uuid.uuid4().hex[:6]}.png", body.scale)
    return {"url": f"{settings.public_api_url}/files/{rel}"}


# ---------------------------------------------------------------------------- voice
MAX_AUDIO_BYTES = 10 * 1024 * 1024


@app.get("/api/voice/status")
def voice_status() -> dict[str, Any]:
    return {"enabled": settings.elevenlabs_api_key is not None, "model": settings.stt_model, "provider": "ElevenLabs"}


@app.post("/api/voice/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict[str, Any]:
    """Speech → text with ElevenLabs Scribe v2 (the key stays on the server)."""
    if settings.elevenlabs_api_key is None:
        raise HTTPException(503, "Voice editing needs ELEVENLABS_API_KEY in .env")
    audio = await file.read()
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "recording too long")
    if len(audio) < 1200:
        raise HTTPException(400, "recording too short")
    data = {"model_id": settings.stt_model, "no_verbatim": "true", "tag_audio_events": "false", "diarize": "false"}
    files = {"file": (file.filename or "voice.webm", audio, file.content_type or "audio/webm")}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post("https://api.elevenlabs.io/v1/speech-to-text", data=data, files=files,
                                  headers={"xi-api-key": settings.elevenlabs_api_key.get_secret_value()})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"speech service unreachable: {type(e).__name__}") from e
    if r.status_code != 200:
        try:
            detail = r.json().get("detail")
            detail = detail.get("message") if isinstance(detail, dict) else detail
        except ValueError:
            detail = r.text[:200]
        log.warning("scribe error %s: %s", r.status_code, detail)
        raise HTTPException(502 if r.status_code >= 500 else 400, f"ElevenLabs: {detail or r.status_code}")
    body = r.json()
    words = [w for w in body.get("words", []) if w.get("type") == "word"]
    return {"text": (body.get("text") or "").strip(), "language": body.get("language_code"),
            "seconds": round(words[-1]["end"], 2) if words else None}


# ---------------------------------------------------------------------------- AI jobs
@app.post("/api/designs")
async def create_design(req: DesignRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex[:12]
    payload: dict[str, Any] = {"job_id": job_id, "prompt": req.prompt, "format": req.format, "count": req.count,
                               "base_brief": req.base_brief}
    if req.reference_id:
        ref = next((r for r in load_kit().references if r["id"] == req.reference_id), None)
        if not ref:
            raise HTTPException(404, "unknown reference")
        payload["reference"] = ref
    if req.reference_file:
        path = (settings.data_dir / req.reference_file).resolve()
        if not (req.reference_file.startswith("competitors/") and path.is_file()
                and (settings.data_dir / "competitors").resolve() in path.parents):
            raise HTTPException(400, "invalid reference file")
        payload["reference_file"] = req.reference_file
    elif req.reference_spec:
        payload["reference_file"] = _render_spec(req.reference_spec, job_id, "reference.png")
    elif req.reference_image:
        payload["reference_file"] = _save_b64(job_id, "reference.png", req.reference_image)
    client = await temporal()
    await client.start_workflow("DesignWorkflow", payload, id=f"design-{job_id}", task_queue=settings.temporal_task_queue)
    return {"job_id": f"design-{job_id}"}


@app.post("/api/edits")
async def create_edit(req: EditRequest) -> dict[str, str]:
    job_id = uuid.uuid4().hex[:12]
    body = req.model_dump()
    for t in body["targets"]:
        image = t.get("image") or {}
        if image.get("b64"):
            image["file"] = _save_b64(job_id, f"src-{uuid.uuid4().hex[:6]}.png", image.pop("b64"))
            t["image"] = image
    body["job_id"] = job_id
    client = await temporal()
    await client.start_workflow("EditWorkflow", body, id=f"edit-{job_id}", task_queue=settings.temporal_task_queue)
    return {"job_id": f"edit-{job_id}"}


@app.post("/api/competitors")
async def competitor_scan(req: CompetitorRequest) -> dict[str, str]:
    """Scan the public Meta Ad Library for a category and turn it into on-brand ideas."""
    run_id = uuid.uuid4().hex[:12]
    client = await temporal()
    await client.start_workflow("CompetitorWorkflow", {"query": req.query.strip(), "country": req.country,
                                                       "limit": req.limit, "run_id": run_id},
                                id=f"intel-{run_id}", task_queue=settings.temporal_task_queue)
    return {"job_id": f"intel-{run_id}"}


@app.get("/api/competitors/latest")
def competitor_latest(query: str, country: str = "ALL") -> dict[str, Any]:
    import json

    from ..research.adlibrary import results_path

    path = results_path(query, country)
    if not path.exists():
        raise HTTPException(404, "no scan yet")
    return json.loads(path.read_text())


@app.post("/api/brand-dna")
async def brand_dna(body: SpecBody) -> dict[str, str]:
    """Audit a board: render it with the shared compositor, then measured + visual audits."""
    job_id = uuid.uuid4().hex[:12]
    file = _render_spec(body.spec, job_id, "dna.png")
    client = await temporal()
    await client.start_workflow("BrandDnaWorkflow", {"file": file, "board": docs.board_info(body.spec),
                                                     "layers": docs.layer_infos(body.spec)},
                                id=f"dna-{job_id}", task_queue=settings.temporal_task_queue)
    return {"job_id": f"dna-{job_id}"}


@app.get("/api/jobs/{job_id}")
async def job(job_id: str) -> dict[str, Any]:
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(400, "bad id")
    client = await temporal()
    handle = client.get_workflow_handle(job_id)
    try:
        desc = await handle.describe()
    except RPCError as e:
        raise HTTPException(404, "job not found") from e
    status = desc.status
    if status == WorkflowExecutionStatus.COMPLETED:
        return {"status": "completed", "progress": await _safe_query(handle), "result": await handle.result()}
    if status == WorkflowExecutionStatus.RUNNING:
        return {"status": "running", "progress": await _safe_query(handle)}
    return {"status": status.name.lower() if status else "unknown", "progress": await _safe_query(handle),
            "error": "The job did not complete. Please try again."}


async def _safe_query(handle) -> dict[str, Any] | None:
    try:
        return await handle.query("progress")
    except Exception:  # noqa: BLE001 - workflow not yet started its first task
        return None


# ---------------------------------------------------------------------------- static
@app.middleware("http")
async def cache_policy(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store"  # always load the latest editor build
    elif path.startswith("/assets/") or path.startswith("/fonts/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # hashed / static
    return response


app.mount("/files", StaticFiles(directory=settings.data_dir), name="files")
app.mount("/fonts", StaticFiles(directory=settings.fonts_dir), name="fonts")

if (settings.editor_dist_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=settings.editor_dist_dir / "assets"), name="editor-assets")


@app.get("/{path:path}", include_in_schema=False)
def editor(path: str) -> FileResponse:
    """The Crux Studio single-page app."""
    if path.startswith(("api/", "files/", "fonts/")):
        raise HTTPException(404)
    target = settings.editor_dist_dir / path
    if path and target.is_file() and settings.editor_dist_dir in target.resolve().parents:
        return FileResponse(target)
    index = settings.editor_dist_dir / "index.html"
    if not index.exists():
        raise HTTPException(503, "editor not built — run ./run.sh")
    return FileResponse(index)
