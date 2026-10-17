"""Layered design spec — the contract between the backend and the Crux Studio editor.

Every visual element is its own layer so designers can re-edit any part on the
canvas. Coordinates are in board space (pixels, origin top-left). Layers are
ordered bottom → top.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

LayerKind = Literal["rect", "ellipse", "text", "image", "vector", "group", "mask"]
LayerStatus = Literal["ready", "pending", "failed"]


def new_id(prefix: str = "l") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Layer(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    kind: LayerKind
    role: str = "decor"
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    rotation: float = 0
    opacity: float = 1
    hidden: bool = False
    locked: bool = False

    # rect / ellipse / vector
    fill: str | None = None
    radius: float = 0
    stroke: str | None = None
    stroke_width: float = 0
    shadow: bool = False

    # text
    text: str | None = None
    font: str | None = None            # key into brand FONTS
    font_family: str | None = None
    font_weight: str | None = None
    font_size: float | None = None
    line_height: float | None = None
    letter_spacing: float | None = None
    color: str | None = None
    align: Literal["left", "center", "right"] | None = None

    # image
    src: str | None = None             # public URL
    file: str | None = None            # path relative to data/ (backend use)
    asset_id: str | None = None
    prompt: str | None = None
    transparent: bool = False
    fit: Literal["cover", "contain"] = "cover"
    anchor: Literal["center", "bottom", "top"] = "center"
    status: LayerStatus = "ready"
    gen_mode: Literal["generate", "brand_style", "edit"] | None = None
    style_refs: list[str] | None = None  # asset ids used as style references
    compliance: dict[str, Any] | None = None  # vision policy verdict for AI images

    # vector
    svg_url: str | None = None
    svg: str | None = None             # inline SVG for small generated vectors

    # group / mask (for "mask", children[0] is the mask shape)
    children: list["Layer"] | None = None

    def walk(self):
        yield self
        for c in self.children or []:
            yield from c.walk()


class DesignSpec(BaseModel):
    id: str = Field(default_factory=lambda: new_id("d"))
    name: str = "Untitled design"
    format: str = "feed"
    width: int = 1080
    height: int = 1350
    background: str = "#FFFFFF"
    layers: list[Layer] = Field(default_factory=list)
    brief: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    preview_url: str | None = None
    variant: int = 0

    def all_layers(self):
        for layer in self.layers:
            yield from layer.walk()

    def find(self, layer_id: str) -> Layer | None:
        return next((l for l in self.all_layers() if l.id == layer_id), None)

    def pending_images(self) -> list[Layer]:
        return [l for l in self.all_layers() if l.kind == "image" and l.status == "pending"]


Layer.model_rebuild()
