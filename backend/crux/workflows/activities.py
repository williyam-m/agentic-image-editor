"""Temporal activities. Blocking LLM work runs in the worker's thread pool; image
generation and compositing are dispatched to Celery and awaited asynchronously."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

log = logging.getLogger(__name__)


@activity.defn
async def celery_task(name: str, args: list[Any]) -> Any:
    """Send a Celery task and await its result without blocking the event loop."""
    from ..tasks.app import celery_app

    result = celery_app.send_task(name, args=args)
    try:
        while not await asyncio.to_thread(result.ready):
            activity.heartbeat(result.id)
            await asyncio.sleep(0.3)
    except asyncio.CancelledError:
        result.revoke(terminate=False)
        raise
    if result.failed():
        raise ApplicationError(f"{name} failed: {result.result}", type="CeleryTaskError")
    return await asyncio.to_thread(result.get, 5)


@activity.defn
def plan_brief(args: dict[str, Any]) -> dict[str, Any]:
    from ..brand.kit import load_kit
    from ..design.planner import plan

    brief = plan(args.get("prompt", ""), load_kit(), fmt=args.get("format", "feed"),
                 reference=args.get("reference"), base=args.get("base"), direction=args.get("direction"),
                 variant=args.get("variant", 0), archetype=args.get("archetype"), colorway=args.get("colorway"),
                 bloom=args.get("bloom"))
    return brief.model_dump()


@activity.defn
def build_layout(args: dict[str, Any]) -> dict[str, Any]:
    from ..brand.guard import audit
    from ..brand.kit import load_kit
    from ..design.brief import Brief
    from ..design.layouts import build_spec

    spec = build_spec(Brief.model_validate(args["brief"]), load_kit(), args.get("variant", 0))
    spec.checks = audit(spec, fix=True)
    return spec.model_dump()


@activity.defn
def analyze_image(args: dict[str, Any]) -> dict[str, Any]:
    from ..config import get_settings
    from ..design.planner import describe_design

    data = (get_settings().data_dir / args["file"]).read_bytes()
    return describe_design(data)


@activity.defn
def plan_edit(req: dict[str, Any]) -> dict[str, Any]:
    from ..brand.kit import load_kit
    from ..design.editor import compile_ops, plan_edit as llm_plan

    kit = load_kit()
    plan = llm_plan(req, kit)
    ops, jobs, notes = compile_ops(req, plan, kit)
    return {"message": plan.get("message") or "Done.", "ops": ops, "jobs": jobs, "notes": notes}


@activity.defn
def synthesize_insights(references: list[dict[str, Any]]) -> dict[str, Any]:
    from ..brand.ingest import synthesize_insights as run

    return run(references)


@activity.defn
def write_catalog(args: dict[str, Any]) -> dict[str, Any]:
    from ..brand.ingest import write_catalog as run

    return run(args["draft"], args["descriptions"], args["references"], args["insights"])


@activity.defn
def dna_measured(args: dict[str, Any]) -> list[dict[str, Any]]:
    from ..brand.dna import layer_audit, load_png
    from ..config import get_settings

    img = load_png((get_settings().data_dir / args["file"]).read_bytes()) if args.get("file") else None
    return layer_audit(args.get("board") or {}, args.get("layers") or [], img)


@activity.defn
def dna_visual(args: dict[str, Any]) -> dict[str, Any]:
    from ..brand.dna import layer_facts, vision_audit
    from ..config import get_settings

    board = args.get("board") or {}
    return vision_audit((get_settings().data_dir / args["file"]).read_bytes(), board.get("width"), board.get("height"),
                        layer_facts(board, args.get("layers") or [], args.get("measured")))


@activity.defn
def dna_merge(args: dict[str, Any]) -> dict[str, Any]:
    from ..brand.dna import merge

    return merge(args["measured"], args["visual"])


@activity.defn
def synthesize_competitors(args: dict[str, Any]) -> dict[str, Any]:
    from ..brand.kit import load_kit
    from ..research.competitors import synthesize

    return synthesize(args["query"], args["ads"], load_kit().insights)


@activity.defn
def save_competitors(args: dict[str, Any]) -> str:
    import json
    import time

    from ..research.adlibrary import results_path

    path = results_path(args["query"], args["country"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**args["report"], "saved_at": time.time()}, ensure_ascii=False))
    return str(path)


ALL = [synthesize_competitors, save_competitors, dna_measured, dna_visual, dna_merge, celery_task, plan_brief, build_layout, analyze_image, plan_edit, synthesize_insights, write_catalog]
