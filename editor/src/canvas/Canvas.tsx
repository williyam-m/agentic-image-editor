// The editing canvas: renders the active board and handles direct manipulation.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BoardSvg } from "../render/BoardSvg";
import { bounds, findLayer, hitTest, moveLayer, resizeLayer, siblingsOf, uid } from "../model/layers";
import { activeBoard, getState, mutateBoard, redo, setUi, snapshot, undo, useEditor } from "../model/store";
import type { CanvasComment, DesignSpec, Layer } from "../model/types";
import { CommentLayer } from "./Comments";

type Handle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";
const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

interface Drag {
  mode: "move" | "resize" | "pan" | "create-rect";
  start: { x: number; y: number };          // board coords (screen for pan)
  orig: { x: number; y: number; w: number; h: number };
  handle?: Handle;
  layerId?: string;
  snap: boolean;
  panStart?: { x: number; y: number };
}

export function Canvas({ fontsVersion }: { fontsVersion: number }) {
  const board = useEditor((s) => s.doc.boards.find((b) => b.id === s.activeBoardId) ?? null);
  const selection = useEditor((s) => s.selection);
  const tool = useEditor((s) => s.tool);
  const zoom = useEditor((s) => s.zoom);
  const pan = useEditor((s) => s.pan);
  const editingTextId = useEditor((s) => s.editingTextId);
  const comments = useEditor((s) => s.doc.comments);
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [spaceDown, setSpaceDown] = useState(false);
  const [draftRect, setDraftRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  const toBoard = useCallback((clientX: number, clientY: number) => {
    const r = ref.current!.getBoundingClientRect();
    return { x: (clientX - r.left - pan.x) / zoom, y: (clientY - r.top - pan.y) / zoom };
  }, [pan, zoom]);

  const fit = useCallback(() => {
    const b = activeBoard();
    const el = ref.current;
    if (!b || !el) return;
    const z = Math.min((el.clientWidth - 80) / b.width, (el.clientHeight - 80) / b.height);
    setUi({ zoom: z, pan: { x: (el.clientWidth - b.width * z) / 2, y: (el.clientHeight - b.height * z) / 2 } });
  }, []);

  useLayoutEffect(() => { fit(); }, [board?.id, fit]);
  useEffect(() => {
    const onResize = () => fit();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [fit]);

  // ---- keyboard ----------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, [contenteditable]")) return;
      const s = getState();
      const b = activeBoard();
      const mod = e.metaKey || e.ctrlKey;
      if (e.code === "Space") { setSpaceDown(true); e.preventDefault(); return; }
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
      if (mod && e.key.toLowerCase() === "d" && b && s.selection) {
        e.preventDefault();
        const id = s.selection;
        let newId = "";
        mutateBoard(b.id, (bd) => {
          const l = findLayer(bd, id);
          const sib = siblingsOf(bd, id);
          if (!l || !sib) return;
          const copy: Layer = structuredClone(l);
          const reid = (x: Layer) => { x.id = uid(); (x.children ?? []).forEach(reid); };
          reid(copy);
          copy.name = `${l.name} copy`;
          moveLayer(copy, 24, 24);
          sib.splice(sib.indexOf(l) + 1, 0, copy);
          newId = copy.id;
        });
        setUi({ selection: newId || id });
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && b && s.selection) {
        const id = s.selection;
        mutateBoard(b.id, (bd) => { const sib = siblingsOf(bd, id); const l = findLayer(bd, id); if (sib && l) sib.splice(sib.indexOf(l), 1); });
        setUi({ selection: null });
        return;
      }
      if (e.key.startsWith("Arrow") && b && s.selection) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
        const id = s.selection;
        mutateBoard(b.id, (bd) => { const l = findLayer(bd, id); if (l && !l.locked) moveLayer(l, dx, dy); });
        return;
      }
      if (e.key === "Escape") { setUi({ selection: null, editingTextId: null, commentDraft: null, openComment: null, tool: "select" }); return; }
      if (e.shiftKey && e.key === "!") { fit(); return; }
      if (mod) return;
      const tools: Record<string, typeof s.tool> = { v: "select", t: "text", r: "rect", c: "comment", h: "hand" };
      if (tools[e.key.toLowerCase()]) setUi({ tool: tools[e.key.toLowerCase()] });
      if (e.key === "+" || e.key === "=") setUi({ zoom: Math.min(4, s.zoom * 1.2) });
      if (e.key === "-") setUi({ zoom: Math.max(0.05, s.zoom / 1.2) });
    };
    const onUp = (e: KeyboardEvent) => { if (e.code === "Space") setSpaceDown(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onUp);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("keyup", onUp); };
  }, [fit]);

  // ---- wheel: pan / pinch-zoom ----------------------------------------------------
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const s = getState();
      if (e.ctrlKey || e.metaKey) {
        const r = el.getBoundingClientRect();
        const mx = e.clientX - r.left, my = e.clientY - r.top;
        const z = Math.max(0.05, Math.min(4, s.zoom * Math.exp(-e.deltaY * 0.0025)));
        setUi({ zoom: z, pan: { x: mx - ((mx - s.pan.x) * z) / s.zoom, y: my - ((my - s.pan.y) * z) / s.zoom } });
      } else {
        setUi({ pan: { x: s.pan.x - e.deltaX, y: s.pan.y - e.deltaY } });
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const selected = useMemo(() => (board && selection ? findLayer(board, selection) : null), [board, selection]);
  const hovered = useMemo(() => (board && hover && hover !== selection ? findLayer(board, hover) : null), [board, hover, selection]);

  // ---- pointer -----------------------------------------------------------------
  const onPointerDown = (e: React.PointerEvent) => {
    if (!board || e.button !== 0 || editingTextId) return;
    const p = toBoard(e.clientX, e.clientY);
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (tool !== "comment" && (getState().commentDraft || getState().openComment)) {
      setUi({ commentDraft: null, openComment: null });  // clicking the canvas dismisses comment popovers
    }
    if (tool === "hand" || spaceDown) {
      drag.current = { mode: "pan", start: { x: e.clientX, y: e.clientY }, orig: { x: 0, y: 0, w: 0, h: 0 }, snap: false, panStart: { ...pan } };
      return;
    }
    if (tool === "comment") {
      const hit = hitTest(board, p.x, p.y);
      setUi({ commentDraft: { boardId: board.id, x: p.x, y: p.y, layerId: hit?.id ?? null, layerName: hit?.name ?? null },
        selection: hit?.id ?? null, openComment: null });
      return;
    }
    if (tool === "text") {
      const id = uid("text");
      mutateBoard(board.id, (b) => b.layers.push({
        id, name: "Text", kind: "text", role: "text", x: p.x, y: p.y, w: 520, h: 60, text: "Your headline",
        font: "headline", font_family: "Barlow Condensed", font_weight: "700", font_size: 56, line_height: 1,
        color: b.background && ["#000856", "#1F65D6"].includes(b.background) ? "#FFFFFF" : "#000856", align: "left",
      }));
      setUi({ selection: id, editingTextId: id, tool: "select" });
      return;
    }
    if (tool === "rect") {
      drag.current = { mode: "create-rect", start: p, orig: { x: p.x, y: p.y, w: 0, h: 0 }, snap: false };
      setDraftRect({ x: p.x, y: p.y, w: 0, h: 0 });
      return;
    }
    const handle = (e.target as HTMLElement).dataset?.handle as Handle | undefined;
    if (handle && selected && !selected.locked) {
      drag.current = { mode: "resize", start: p, orig: bounds(selected), handle, layerId: selected.id, snap: false };
      return;
    }
    const hit = hitTest(board, p.x, p.y);
    setUi({ selection: hit?.id ?? null });
    if (hit && !hit.locked && hit.role !== "background") {
      drag.current = { mode: "move", start: p, orig: bounds(hit), layerId: hit.id, snap: false };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!board) return;
    const d = drag.current;
    const p = toBoard(e.clientX, e.clientY);
    if (!d) {
      if (tool === "select" && !spaceDown) setHover(hitTest(board, p.x, p.y)?.id ?? null);
      return;
    }
    if (d.mode === "pan") {
      setUi({ pan: { x: d.panStart!.x + e.clientX - d.start.x, y: d.panStart!.y + e.clientY - d.start.y } });
      return;
    }
    if (d.mode === "create-rect") {
      setDraftRect({ x: Math.min(d.start.x, p.x), y: Math.min(d.start.y, p.y), w: Math.abs(p.x - d.start.x), h: Math.abs(p.y - d.start.y) });
      return;
    }
    if (!d.snap) { snapshot(); d.snap = true; }
    const dx = p.x - d.start.x, dy = p.y - d.start.y;
    if (d.mode === "move") {
      mutateBoard(board.id, (b) => {
        const l = findLayer(b, d.layerId!);
        if (!l) return;
        const cur = bounds(l);
        moveLayer(l, d.orig.x + dx - cur.x, d.orig.y + dy - cur.y);
      }, { history: false, save: false });
    } else if (d.mode === "resize") {
      const o = d.orig;
      let { x, y, w, h } = o;
      const hd = d.handle!;
      if (hd.includes("e")) w = Math.max(4, o.w + dx);
      if (hd.includes("s")) h = Math.max(4, o.h + dy);
      if (hd.includes("w")) { w = Math.max(4, o.w - dx); x = o.x + o.w - w; }
      if (hd.includes("n")) { h = Math.max(4, o.h - dy); y = o.y + o.h - h; }
      const layer = findLayer(board, d.layerId!);
      const keepAspect = e.shiftKey || (hd.length === 2 && layer && ["image", "vector", "mask", "group"].includes(layer.kind));
      if (keepAspect && hd.length === 2) {
        const ratio = o.w / o.h;
        if (w / h > ratio) w = h * ratio; else h = w / ratio;
        if (hd.includes("w")) x = o.x + o.w - w;
        if (hd.includes("n")) y = o.y + o.h - h;
      }
      mutateBoard(board.id, (b) => { const l = findLayer(b, d.layerId!); if (l) resizeLayer(l, x, y, w, h); }, { history: false, save: false });
    }
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!board || !d) return;
    if (d.mode === "create-rect" && draftRect) {
      const r = draftRect.w > 4 && draftRect.h > 4 ? draftRect : { ...draftRect, w: 300, h: 200 };
      const id = uid("rect");
      mutateBoard(board.id, (b) => b.layers.push({ id, name: "Rectangle", kind: "rect", role: "shape", ...r, fill: "#1F65D6", radius: 16 }));
      setDraftRect(null);
      setUi({ selection: id, tool: "select" });
      return;
    }
    if (d.snap) mutateBoard(board.id, () => undefined, { history: false });  // persist the drag
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    if (!board) return;
    const p = toBoard(e.clientX, e.clientY);
    const hit = hitTest(board, p.x, p.y);
    if (hit?.kind === "text" && !hit.locked) setUi({ selection: hit.id, editingTextId: hit.id });
  };

  if (!board) {
    return <div className="canvas empty-canvas"><div><b>No board yet.</b><span>Ask Crux for a design, or press <kbd>T</kbd> after creating a blank board.</span></div></div>;
  }

  const sb = selected ? bounds(selected) : null;
  const screen = (b: { x: number; y: number; w: number; h: number }) => ({ left: pan.x + b.x * zoom, top: pan.y + b.y * zoom, width: b.w * zoom, height: b.h * zoom });
  const cursor = tool === "hand" || spaceDown ? (drag.current?.mode === "pan" ? "grabbing" : "grab") : tool === "text" ? "text" : tool === "comment" || tool === "rect" ? "crosshair" : "default";

  return (
    <div className="canvas" ref={ref} style={{ cursor }} onPointerDown={onPointerDown} onPointerMove={onPointerMove}
      onPointerUp={onPointerUp} onDoubleClick={onDoubleClick} onPointerLeave={() => setHover(null)} data-testid="canvas">
      <div className="board-frame" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, width: board.width, height: board.height }}>
        <BoardSvg spec={board} uid="canvas" fontsVersion={fontsVersion} editingTextId={editingTextId} className="board-svg" />
      </div>
      <div className="board-label" style={{ left: pan.x, top: pan.y - 22 }}>{board.name} · {board.width}×{board.height}</div>
      {hovered && !drag.current ? <div className="hover-box" style={screen(bounds(hovered))} /> : null}
      {sb && selected ? (
        <div className={`sel-box ${selected.locked ? "locked" : ""}`} style={screen(sb)}>
          {!selected.locked ? HANDLES.map((h) => <span key={h} className={`handle h-${h}`} data-handle={h} />) : null}
          <span className="sel-tag">{selected.name}{selected.locked ? " 🔒" : ""}</span>
        </div>
      ) : null}
      {draftRect ? <div className="sel-box" style={screen(draftRect)} /> : null}
      {editingTextId ? <InlineText board={board} layerId={editingTextId} zoom={zoom} pan={pan} /> : null}
      <CommentLayer comments={comments.filter((c: CanvasComment) => c.boardId === board.id)} zoom={zoom} pan={pan} />
      <div className="zoom-ctl">
        <button onClick={() => setUi({ zoom: Math.max(0.05, zoom / 1.2) })}>−</button>
        <button onClick={fit} title="Fit (Shift+1)">{Math.round(zoom * 100)}%</button>
        <button onClick={() => setUi({ zoom: Math.min(4, zoom * 1.2) })}>+</button>
      </div>
    </div>
  );
}

function InlineText({ board, layerId, zoom, pan }: { board: DesignSpec; layerId: string; zoom: number; pan: { x: number; y: number } }) {
  const layer = findLayer(board, layerId);
  const [value, setValue] = useState(layer?.text ?? "");
  const taRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { taRef.current?.focus(); taRef.current?.select(); }, []);
  if (!layer) return null;
  const size = (layer.font_size ?? 24) * zoom;
  const commit = () => {
    if (value !== layer.text) mutateBoard(board.id, (b) => { const l = findLayer(b, layerId); if (l) l.text = value; });
    setUi({ editingTextId: null });
  };
  return (
    <textarea ref={taRef} className="inline-text" value={value} onChange={(e) => setValue(e.target.value)}
      onBlur={commit} onPointerDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => { if (e.key === "Escape" || (e.key === "Enter" && (e.metaKey || e.ctrlKey))) { e.preventDefault(); commit(); } }}
      style={{ left: pan.x + layer.x * zoom, top: pan.y + layer.y * zoom, width: layer.w * zoom, minHeight: layer.h * zoom,
        fontFamily: `"${layer.font_family ?? "Barlow"}"`, fontWeight: Number(layer.font_weight ?? 400), fontSize: size,
        lineHeight: String(layer.line_height ?? 1.2), color: layer.color ?? "#000856", textAlign: layer.align ?? "left" }} />
  );
}
