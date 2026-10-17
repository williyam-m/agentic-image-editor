"""Crux Studio documents: a project holding boards (layered DesignSpecs) and canvas comments.

Stored as JSON under data/docs/<id>.json, written atomically. The editor autosaves here.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from ..config import get_settings

_ID = re.compile(r"^[a-z0-9-]{1,40}$")
MAX_DOC_BYTES = 8 * 1024 * 1024


def valid_id(doc_id: str) -> bool:
    return bool(_ID.match(doc_id))


def empty(doc_id: str) -> dict[str, Any]:
    return {"id": doc_id, "name": "Xero campaign", "boards": [], "comments": [], "updated": 0}


def load(doc_id: str) -> dict[str, Any]:
    path = get_settings().docs_dir / f"{doc_id}.json"
    if not path.exists():
        return empty(doc_id)
    return json.loads(path.read_text())


def save(doc_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    doc = {**doc, "id": doc_id, "updated": time.time()}
    data = json.dumps(doc, ensure_ascii=False)
    if len(data) > MAX_DOC_BYTES:
        raise ValueError("document too large")
    path = get_settings().docs_dir / f"{doc_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data)
    tmp.replace(path)
    return {"id": doc_id, "updated": doc["updated"]}


KIND_TYPE = {"text": "text", "rect": "rect", "ellipse": "ellipse", "image": "image", "vector": "path",
             "group": "group", "mask": "group"}


def layer_infos(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a spec into the per-layer facts the editor/DNA/edit planners reason over (z-order kept)."""
    out: list[dict[str, Any]] = []

    def walk(layers: list[dict[str, Any]], parent: str | None) -> None:
        for l in layers:
            if l.get("hidden"):
                continue
            info = {"id": l["id"], "name": l.get("name"), "type": KIND_TYPE.get(l.get("kind"), "rect"),
                    "role": l.get("role"), "parent_id": parent, "x": l.get("x", 0), "y": l.get("y", 0),
                    "w": l.get("w", 0), "h": l.get("h", 0), "rotation": l.get("rotation", 0),
                    "asset_id": l.get("asset_id")}
            if l.get("kind") == "text":
                info.update(text=l.get("text"), font_size=l.get("font_size"), font_family=l.get("font_family"),
                            font_weight=l.get("font_weight"), color=l.get("color"))
            elif l.get("kind") == "image":
                info["image"] = {"src": l.get("src"), "file": l.get("file"), "prompt": l.get("prompt"),
                                 "transparent": l.get("transparent", False)}
            else:
                info["fill"] = l.get("fill") or l.get("stroke")
            out.append(info)
            walk(l.get("children") or [], l["id"])

    walk(spec.get("layers", []), None)
    return out


def board_info(spec: dict[str, Any]) -> dict[str, Any]:
    return {"id": spec.get("id"), "name": spec.get("name"), "width": spec.get("width"), "height": spec.get("height"),
            "background": spec.get("background"), "brief": spec.get("brief") or None, "x": 0, "y": 0,
            "is_crux": bool(spec.get("brief"))}
