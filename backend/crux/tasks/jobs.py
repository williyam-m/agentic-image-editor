"""Celery tasks. Each is a thin, idempotent wrapper around pure domain code."""
from __future__ import annotations

import logging
import time
from typing import Any

from ..brand import ingest
from ..design import layers as layer_ops
from ..design.spec import DesignSpec
from .app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="crux.generate_layer", bind=True, max_retries=2, default_retry_delay=2)
def generate_layer(self, job_id: str, layer: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        out = layer_ops.generate_layer_image(job_id, layer)
    except Exception as e:  # surfaced to Temporal, which owns the retry policy
        log.exception("layer %s failed", layer.get("id"))
        raise RuntimeError(f"image generation failed: {e}") from e
    out["seconds"] = round(time.perf_counter() - started, 1)
    return out


@celery_app.task(name="crux.compose_final")
def compose_final(job_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return layer_ops.compose_and_audit(job_id, DesignSpec.model_validate(spec))


@celery_app.task(name="crux.describe_batch")
def describe_batch(items: list[dict[str, str]], kind: str) -> dict[str, Any]:
    return ingest.describe_batch(items, kind)


@celery_app.task(name="crux.analyze_reference")
def analyze_reference(item: dict[str, str]) -> dict[str, Any]:
    return ingest.analyze_reference(item)


@celery_app.task(name="crux.prepare_assets")
def prepare_assets() -> dict[str, Any]:
    return ingest.prepare_assets()


@celery_app.task(name="crux.scrape_ads")
def scrape_ads(query: str, country: str, limit: int, run_id: str) -> list[dict[str, Any]]:
    from ..research.adlibrary import cache_media, scrape

    return cache_media(scrape(query, country=country, limit=limit), run_id)


@celery_app.task(name="crux.analyze_ad")
def analyze_ad(ad: dict[str, Any], category: str) -> dict[str, Any]:
    from ..research.competitors import analyze_ad as run

    return run(ad, category)
