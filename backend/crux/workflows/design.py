"""Durable design workflows.

``DesignWorkflow``  – create one design or N variations, progressively:
    analyse reference → plan briefs (parallel) → layout + brand guard → every image layer
    of every variant generated in parallel (Celery) → composite + audit + QA per variant.
    The ``progress`` query exposes a versioned snapshot so the editor can show the
    editable layers as soon as the layout exists and swap images in as each one lands.
``EditWorkflow``    – edit specific layers from a chat message or a canvas comment.
``BrandIngestWorkflow`` – (re)analyse the brand kit into the asset catalog.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..design import tree
    from ..design.editor import merge_image_results
    from ..design.planner import variation_plan
    from ..research.competitors import tier
    from . import activities as act

LLM_RETRY = RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=3, backoff_coefficient=2)
IMG_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_attempts=3, backoff_coefficient=2)



def _llm(fn, arg, seconds: int = 120):
    return workflow.execute_activity(fn, arg, start_to_close_timeout=timedelta(seconds=seconds), retry_policy=LLM_RETRY)


def _celery(name: str, args: list[Any], seconds: int = 240):
    return workflow.execute_activity(act.celery_task, args=[name, args], start_to_close_timeout=timedelta(seconds=seconds),
                                     heartbeat_timeout=timedelta(seconds=30), retry_policy=IMG_RETRY)


@workflow.defn
class DesignWorkflow:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {"stage": "queued", "events": [], "specs": [], "results": [], "version": 0,
                                      "error": None, "done": False}
        self.t0 = None

    def _event(self, text: str, kind: str = "info") -> None:
        elapsed = (workflow.now() - self.t0).total_seconds() if self.t0 else 0
        self.state["events"].append({"t": round(elapsed, 1), "text": text, "kind": kind})
        self.state["version"] += 1

    def _stage(self, stage: str, text: str) -> None:
        self.state["stage"] = stage
        self._event(text, "stage")

    @workflow.query
    def progress(self) -> dict[str, Any]:
        return self.state

    @workflow.run
    async def run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.t0 = workflow.now()
        job_id = req["job_id"]
        count = max(1, min(4, int(req.get("count", 1))))
        reference = req.get("reference")

        if req.get("reference_file"):
            self._stage("analyzing", "Analysing your reference design")
            reference = await _llm(act.analyze_image, {"file": req["reference_file"]}, 90)
            self._event(f"Reference read: “{(reference.get('headline') or '').strip()}” · {reference.get('archetype')}")

        self._stage("planning", "Planning copy, layout and imagery" if count == 1 else f"Planning {count} distinct directions")
        plans = [{}] if count == 1 else variation_plan(req.get("base_brief") or reference, count)
        briefs = await asyncio.gather(*[
            _llm(act.plan_brief, {"prompt": req.get("prompt", ""), "format": req.get("format", "feed"),
                                  "reference": reference, "base": req.get("base_brief"), "variant": i, **plan})
            for i, plan in enumerate(plans)])
        for b in briefs:
            self._event(f"Brief: “{b['headline']}” · {b['archetype'].replace('_', ' ')} · {b['colorway']}")

        self._stage("layout", "Laying out layers and applying brand rules")
        specs = await asyncio.gather(*[_llm(act.build_layout, {"brief": b, "variant": i}, 60) for i, b in enumerate(briefs)])
        self.state["specs"] = list(specs)
        self.state["results"] = [None] * len(specs)
        n_images = sum(len(tree.pending_images(s)) for s in specs)
        self._stage("generating", f"Generating {n_images} image layer{'s' if n_images != 1 else ''} in parallel")

        await asyncio.gather(*[self._process(job_id, i) for i in range(len(specs))])
        self._stage("done", "Ready — every element is an editable layer")
        self.state["done"] = True
        return {"specs": self.state["specs"], "results": self.state["results"], "events": self.state["events"]}

    async def _process(self, job_id: str, idx: int) -> None:
        spec = self.state["specs"][idx]

        async def one(layer: dict[str, Any]) -> None:
            try:
                res = await _celery("crux.generate_layer", [job_id, layer])
                comp = res.get("compliance") or {}
                tree.patch_layer(spec, layer["id"], {"status": "ready", "src": res["src"], "file": res["file"],
                                                     "x": res["x"], "y": res["y"], "w": res["w"], "h": res["h"],
                                                     "compliance": comp})
                tries = comp.get("attempts", 1)
                verdict = ("policy-verified" if comp.get("ok") and comp.get("verified")
                           else "unverified" if not comp.get("verified") else f"flagged: {', '.join(comp.get('blocking', []))}")
                regen = f", regenerated {tries - 1}× to remove {', '.join(comp.get('fixed', [])) or 'issues'}" if tries > 1 else ""
                self._event(f"{layer['name']} ready ({res.get('seconds', '?')}s) · {verdict}{regen}",
                            "check" if comp.get("ok") else "error")
            except Exception as e:  # keep the design; the layer can be retried from the canvas
                tree.patch_layer(spec, layer["id"], {"status": "failed"})
                self._event(f"{layer['name']} failed: {str(e)[:120]}", "error")

        await asyncio.gather(*[one(l) for l in tree.pending_images(spec)])
        try:
            result = await _celery("crux.compose_final", [job_id, spec], 180)
            self.state["specs"][idx] = result.pop("spec")
            self.state["results"][idx] = result
            summary = result.get("summary", {})
            qa = result.get("qa") or {}
            self._event(f"Variant {idx + 1}: brand check {summary.get('score', '?')}/100"
                        + (f", art-director score {qa['score']}/10" if qa.get("score") else ""), "check")
        except Exception as e:
            self._event(f"Compositing failed: {str(e)[:120]}", "error")


@workflow.defn
class EditWorkflow:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {"stage": "queued", "events": [], "version": 0, "done": False}

    @workflow.query
    def progress(self) -> dict[str, Any]:
        return self.state

    @workflow.run
    async def run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.state.update(stage="planning", version=1)
        plan = await _llm(act.plan_edit, req, 90)
        jobs = plan.pop("jobs", [])
        if jobs:
            self.state.update(stage="generating", version=2)
            results = await asyncio.gather(*[_celery("crux.generate_layer", [req["job_id"], j["layer"]]) for j in jobs],
                                           return_exceptions=True)
            merge_image_results(plan["ops"], jobs, [None if isinstance(r, BaseException) else r for r in results])
            failed = sum(isinstance(r, BaseException) for r in results)
            if failed:
                plan["notes"].append(f"{failed} image edit(s) failed — try again")
        self.state.update(stage="done", version=3, done=True)
        return plan


@workflow.defn
class BrandIngestWorkflow:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {"stage": "queued", "version": 0, "done": False}

    @workflow.query
    def progress(self) -> dict[str, Any]:
        return self.state

    @workflow.run
    async def run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.state.update(stage="processing", version=1)
        draft = await _celery("crux.prepare_assets", [], 600)
        by_id = {a["id"]: a for a in draft["assets"]}
        charms = [{"id": i, "file": by_id[i]["file"]} for i in draft["charm_ids"]]
        batches = [(charms[i:i + 30], "charm") for i in range(0, len(charms), 30)] + \
                  [(draft["vision"][i:i + 12], "illustration/product") for i in range(0, len(draft["vision"]), 12)]
        self.state.update(stage="analysing", version=2)
        described, references = await asyncio.gather(
            asyncio.gather(*[_celery("crux.describe_batch", [b, k], 180) for b, k in batches]),
            asyncio.gather(*[_celery("crux.analyze_reference", [r], 180) for r in draft["references"]]),
        )
        descriptions: dict[str, Any] = {}
        for part in described:
            descriptions.update(part)
        self.state.update(stage="synthesising", version=3)
        insights = await _llm(act.synthesize_insights, list(references), 180)
        out = await _llm(act.write_catalog, {"draft": draft, "descriptions": descriptions,
                                             "references": list(references), "insights": insights}, 120)
        self.state.update(stage="done", version=4, done=True)
        return out


@workflow.defn
class BrandDnaWorkflow:
    """Measured (layers + pixels) audit, then a visual (vision model) audit grounded in its facts; merged."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {"stage": "queued", "version": 0, "done": False}

    @workflow.query
    def progress(self) -> dict[str, Any]:
        return self.state

    @workflow.run
    async def run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.state.update(stage="auditing", version=1)
        # Measured first (fast, deterministic) so the visual review is grounded in its facts.
        measured = await _llm(act.dna_measured, {"file": req["file"], "board": req.get("board"),
                                                 "layers": req.get("layers")}, 60)
        visual = await _llm(act.dna_visual, {"file": req["file"], "board": req.get("board"),
                                             "layers": req.get("layers"), "measured": measured}, 120)
        report = await _llm(act.dna_merge, {"measured": measured, "visual": visual}, 30)
        self.state.update(stage="done", version=2, done=True)
        return report


@workflow.defn
class CompetitorWorkflow:
    """Meta Ad Library scan → per-ad vision analysis (parallel) → longevity-weighted synthesis → ideas."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {"stage": "queued", "events": [], "ads": [], "version": 0, "done": False}
        self.t0 = None

    def _event(self, text: str, kind: str = "info") -> None:
        t = (workflow.now() - self.t0).total_seconds() if self.t0 else 0
        self.state["events"].append({"t": round(t, 1), "text": text, "kind": kind})
        self.state["version"] += 1

    @workflow.query
    def progress(self) -> dict[str, Any]:
        return self.state

    @workflow.run
    async def run(self, req: dict[str, Any]) -> dict[str, Any]:
        self.t0 = workflow.now()
        query, country, limit = req["query"], req.get("country", "ALL"), int(req.get("limit", 20))
        self.state["stage"] = "scraping"
        self._event(f"Searching the Meta Ad Library for “{query}” ({country})", "stage")
        ads = await _celery("crux.scrape_ads", [query, country, limit, req["run_id"]], 180)
        ads.sort(key=lambda a: -(a.get("days_active") or 0))
        for a in ads:
            a["tier"] = tier(a.get("days_active"))
        self.state["ads"] = ads
        proven = sum(a["tier"] == "proven" for a in ads)
        self._event(f"Found {len(ads)} ads · {proven} running 90+ days · "
                    f"{sum(a['media_type'] == 'video' for a in ads)} video", "check")

        self.state["stage"] = "analysing"
        self._event("Reading every creative with vision AI", "stage")

        async def one(i: int) -> None:
            try:
                ads[i]["analysis"] = await _celery("crux.analyze_ad", [ads[i], query], 90)
            except Exception:  # noqa: BLE001 - one unreadable ad shouldn't sink the scan
                ads[i]["analysis"] = None
            self.state["version"] += 1

        # Deadline: slow vision calls must not gate the scan; synthesise with what has been read.
        tasks = [asyncio.ensure_future(one(i)) for i in range(len(ads))]
        _, pending = await asyncio.wait(tasks, timeout=20)
        for t in pending:
            t.cancel()
        read = sum(1 for a in ads if a.get("analysis"))
        relevant = sum(1 for a in ads if (a.get("analysis") or {}).get("relevance", 0) >= 4)
        self._event(f"Analysed {read}/{len(ads)} creatives · {relevant} relevant to {query}", "check")

        self.state["stage"] = "synthesising"
        self._event("Finding what long-running ads have in common", "stage")
        insights = await _llm(act.synthesize_competitors, {"query": query, "ads": ads}, 180)
        report = {"query": query, "country": country, "ads": ads, "insights": insights}
        await _llm(act.save_competitors, {"query": query, "country": country, "report": report}, 30)
        self._event(f"{len(insights.get('ideas', []))} on-brand ideas ready", "check")
        self.state.update(stage="done", insights=insights, done=True, version=self.state["version"] + 1)
        return report


WORKFLOWS = [DesignWorkflow, EditWorkflow, BrandIngestWorkflow, BrandDnaWorkflow, CompetitorWorkflow]
