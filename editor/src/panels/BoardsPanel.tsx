import { useState } from "react";
import { BoardSvg } from "../render/BoardSvg";
import { uid } from "../model/layers";
import { mutate, setUi, useEditor } from "../model/store";
import type { DesignSpec } from "../model/types";

const FORMATS: Record<string, [number, number, string]> = {
  feed: [1080, 1350, "Feed 4:5"], square: [1080, 1080, "Square 1:1"], story: [1080, 1920, "Story 9:16"], landscape: [1200, 628, "Landscape"],
};

export function newBlankBoard(format: string): DesignSpec {
  const [w, h] = FORMATS[format] ?? FORMATS.feed;
  return { id: uid("d"), name: "Untitled board", format, width: w, height: h, background: "#FFFFFF", brief: {}, checks: [], variant: 0,
    layers: [{ id: uid("bg"), name: "Background", kind: "rect", role: "background", x: 0, y: 0, w, h, fill: "#FFFFFF" }] };
}

export function BoardsPanel({ fontsVersion }: { fontsVersion: number }) {
  const boards = useEditor((s) => s.doc.boards);
  const active = useEditor((s) => s.activeBoardId);
  const [menu, setMenu] = useState(false);
  const add = (format: string) => {
    const b = newBlankBoard(format);
    mutate((d) => { d.boards.push(b); });
    setUi({ activeBoardId: b.id, selection: null });
    setMenu(false);
  };
  return (
    <section className="panel boards-panel">
      <div className="panel-head">
        <span>Boards <small>{boards.length}</small></span>
        <div className="menu-wrap">
          <button className="icon-btn" title="New blank board" onClick={() => setMenu(!menu)}>＋</button>
          {menu ? (
            <div className="menu">
              {Object.entries(FORMATS).map(([k, [w, h, label]]) => (
                <button key={k} onClick={() => add(k)}>{label} <small>{w}×{h}</small></button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className="board-list">
        {[...boards].reverse().map((b) => (
          <div key={b.id} className={`board-item ${b.id === active ? "active" : ""}`} data-testid="board-item"
            onClick={() => setUi({ activeBoardId: b.id, selection: null, editingTextId: null })}>
            <div className="board-thumb" style={{ aspectRatio: `${b.width} / ${b.height}` }}>
              <BoardSvg spec={b} uid={`thumb-${b.id}`} width="100%" height="100%" fontsVersion={fontsVersion} />
            </div>
            <div className="board-meta">
              <span title={b.name}>{b.name}</span>
              <button className="icon-btn xs" title="Delete board" onClick={(e) => {
                e.stopPropagation();
                if (!confirm(`Delete “${b.name}”?`)) return;
                mutate((d) => { d.boards = d.boards.filter((x) => x.id !== b.id); d.comments = d.comments.filter((c) => c.boardId !== b.id); });
                if (active === b.id) setUi({ activeBoardId: null, selection: null });
              }}>×</button>
            </div>
          </div>
        ))}
        {!boards.length ? <div className="muted small pad">No boards yet — ask Crux for a design →</div> : null}
      </div>
    </section>
  );
}
