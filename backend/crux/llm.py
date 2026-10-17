"""Chat-completion clients for the copilot (DeepSeek V4 Pro / V4.1 Flash on Azure).

* ``pro``   – planning and editing (text only, strongest reasoning).
* ``flash`` – fast tasks and anything that needs vision.

All calls go through :func:`complete_json`, which enforces JSON output, retries
rate limits (HTTP 429) and transient errors with jittered backoff, and falls
back to the other model when one keeps failing.
"""
from __future__ import annotations

import base64
import json
import logging
import random
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import openai
from openai import OpenAI

from .config import get_settings

log = logging.getLogger(__name__)

Tier = Literal["pro", "flash"]


@lru_cache
def _client(tier: Tier) -> tuple[OpenAI, str]:
    s = get_settings()
    if tier == "pro":
        return (
            OpenAI(base_url=s.deepseek_pro_base_url, api_key=s.deepseek_pro_api_key.get_secret_value(),
                   timeout=s.llm_timeout_s, max_retries=0),
            s.deepseek_pro_model,
        )
    return (
        OpenAI(base_url=s.deepseek_flash_base_url, api_key=s.deepseek_flash_api_key.get_secret_value(),
               timeout=s.llm_timeout_s, max_retries=0),
        s.deepseek_flash_model,
    )


def image_part(path_or_bytes: Path | bytes, mime: str = "image/png") -> dict[str, Any]:
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(text: str) -> Any:
    text = _FENCE.sub("", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tolerate prose around the object.
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def complete_json(
    system: str,
    user: str | list[dict[str, Any]],
    *,
    tier: Tier = "pro",
    temperature: float = 0.7,
    max_tokens: int = 4000,
    attempts: int = 4,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Return the model's JSON object answer. Vision input forces the flash tier."""
    if isinstance(user, list) and tier == "pro":
        tier = "flash"  # Pro is text-only.
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_err: Exception | None = None
    order: list[Tier] = [tier] * (attempts - 1) + (["flash" if tier == "pro" else "pro"] if not isinstance(user, list) else [tier])
    for i, t in enumerate(order):
        client, model = _client(t)
        if timeout:
            client = client.with_options(timeout=timeout)
        started = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
            out = _parse_json(content)
            log.info("llm %s ok in %.1fs (%s tokens)", model, time.perf_counter() - started,
                     getattr(resp.usage, "total_tokens", "?"))
            if not isinstance(out, dict):
                raise ValueError("expected a JSON object")
            return out
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError,
                openai.InternalServerError, json.JSONDecodeError, ValueError) as e:
            last_err = e
            delay = min(8.0, 0.8 * 2**i) + random.random() * 0.5
            log.warning("llm %s attempt %d failed (%s); retrying in %.1fs", model, i + 1, type(e).__name__, delay)
            time.sleep(delay)
    raise RuntimeError(f"LLM call failed after {attempts} attempts: {last_err}")
