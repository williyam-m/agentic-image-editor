"""Dependency-free helpers over spec dicts (safe to use inside Temporal workflow code)."""
from __future__ import annotations

from typing import Any, Iterator


def walk(layers: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for layer in layers:
        yield layer
        yield from walk(layer.get("children") or [])


def pending_images(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [l for l in walk(spec["layers"]) if l.get("kind") == "image" and l.get("status") == "pending"]


def patch_layer(spec: dict[str, Any], layer_id: str, patch: dict[str, Any]) -> bool:
    for layer in walk(spec["layers"]):
        if layer.get("id") == layer_id:
            layer.update(patch)
            return True
    return False
