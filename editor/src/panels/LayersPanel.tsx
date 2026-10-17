import { useState } from "react";
import { findLayer, siblingsOf } from "../model/layers";
import { mutateBoard, setUi, useEditor } from "../model/store";
import type { DesignSpec, Layer } from "../model/types";

const ICON: Record<Layer["kind"], string> = { rect: "▭", ellipse: "◯", text: "T", image: "▣", vector: "✦", group: "▤", mask: "◩" };

function Row({ l, board, depth }: { l: Layer; board: DesignSpec; depth: number }) {
  const selected = useEditor((s) => s.selection === l.id);
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const kids = l.children ?? [];
  const toggle = (key: "hidden" | "locked") => (e: React.MouseEvent) => {
    e.stopPropagation();
    mutateBoard(board.id, (b) => { const x = findLayer(b, l.id); if (x) x[key] = !x[key]; });
  };
  const nudge = (dir: 1 | -1) => (e: React.MouseEvent) => {
    e.stopPropagation();
    mutateBoard(board.id, (b) => {
      const sib = siblingsOf(b, l.id);
      const x = findLayer(b, l.id);
      if (!sib || !x) return;
      const i = sib.indexOf(x), j = i + dir;
      if (j < 0 || j >= sib.length) return;
      [sib[i], sib[j]] = [sib[j], sib[i]];
    });
  };
  return (
    <>
      <div className={`layer-row ${selected ? "selected" : ""} ${l.hidden ? "is-hidden" : ""}`} style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => setUi({ selection: l.id })} onDoubleClick={() => setRenaming(true)} data-testid="layer-row">
        {kids.length ? <button className="caret" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>{open ? "▾" : "▸"}</button> : <span className="caret" />}
        <span className={`kind k-${l.kind}`}>{ICON[l.kind]}</span>
        {renaming ? (
          <input autoFocus defaultValue={l.name} onClick={(e) => e.stopPropagation()}
            onBlur={(e) => { const v = e.target.value.trim(); if (v) mutateBoard(board.id, (b) => { const x = findLayer(b, l.id); if (x) x.name = v; }); setRenaming(false); }}
            onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        ) : <span className="lname">{l.name}{l.status === "pending" ? <i className="gen-dot" /> : null}</span>}
        <span className="row-actions">
          <button title="Bring forward" onClick={nudge(1)}>↑</button>
          <button title="Send backward" onClick={nudge(-1)}>↓</button>
          <button title={l.locked ? "Unlock" : "Lock"} onClick={toggle("locked")} className={l.locked ? "on" : ""}>{l.locked ? "🔒" : "🔓"}</button>
          <button title={l.hidden ? "Show" : "Hide"} onClick={toggle("hidden")} className={l.hidden ? "on" : ""}>{l.hidden ? "◌" : "◉"}</button>
        </span>
      </div>
      {open ? [...kids].reverse().map((c) => <Row key={c.id} l={c} board={board} depth={depth + 1} />) : null}
    </>
  );
}

export function LayersPanel() {
  const board = useEditor((s) => s.doc.boards.find((b) => b.id === s.activeBoardId) ?? null);
  return (
    <section className="panel layers-panel">
      <div className="panel-head"><span>Layers {board ? <small>{board.layers.length}</small> : null}</span></div>
      <div className="layer-list">
        {board ? [...board.layers].reverse().map((l) => <Row key={l.id} l={l} board={board} depth={0} />) : <div className="muted small pad">Select a board</div>}
      </div>
    </section>
  );
}
