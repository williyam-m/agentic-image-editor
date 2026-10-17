"""Celery application: the parallel execution layer for image generation and compositing.

Temporal decides *what* runs and survives restarts; Celery fans the heavy,
I/O-bound OpenAI image calls out across a worker pool so every layer of every
variant renders at the same time.
"""
from __future__ import annotations

import logging

from celery import Celery

from ..config import get_settings

settings = get_settings()

celery_app = Celery("crux", broker=settings.redis_url, backend=settings.redis_url, include=["crux.tasks.jobs"])
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
