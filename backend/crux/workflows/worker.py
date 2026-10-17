"""Temporal worker: hosts the design workflows and their activities."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from ..config import get_settings
from .activities import ALL as ACTIVITIES
from .design import WORKFLOWS


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = get_settings()
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    with ThreadPoolExecutor(max_workers=64) as pool:
        worker = Worker(client, task_queue=s.temporal_task_queue, workflows=WORKFLOWS, activities=ACTIVITIES,
                        activity_executor=pool, max_concurrent_activities=64)
        logging.info("temporal worker listening on %s", s.temporal_task_queue)
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
