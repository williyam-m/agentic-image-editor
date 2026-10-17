import { useEffect, useState } from "react";
import { bounds, findLayer, moveLayer, resizeLayer } from "../model/layers";
import { mutateBoard, setUi, useEditor } from "../model/store";
import { isPalette, useBrand } from "../model/brand";
import { brandFamilies, weightsFor } from "../render/fonts";
import type { DesignSpec, Layer } from "../model/types";
import { uploadFile } from "../copilot/api";

function Num({ label, value, onCommit, step = 1 }: { label: string; value: number; onCommit: (v: number) => void; step?: number }) {
  const [v, setV] = useState(String(Math.round(value * 100) / 100));
  useEffect(() => setV(String(Math.round(value * 100) / 100)), [value]);
  const commit = () => { const n = parseFloat(v); if (!Number.isNaN(n) && n !== value) onCommit(n); };
  return (
    <label className="num"><span>{label}</span>
      <input value={v} step={step} onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
    </label>
  );
}

function Swatches({ value, onPick }: { value?: string | null; onPick: (hex: string) => void }) {
  const brand = useBrand();
  const [hex, setHex] = useState(value ?? "");
  useEffect(() => setHex(value ?? ""), [value]);
  const off = !!value && !isPalette(value);
  return (
    <div className="swatch-picker">
      <div className="sw-row">
        {Object.entries(brand?.palette ?? {}).map(([name, c]) => (
          <button key={name} title={`${name.replace("_", " ")} ${c}`} className={`sw ${value?.toUpperCase() === c.toUpperCase() ? "on" : ""}`}
            style={{ background: c }} onClick={() => onPick(c)} />
        ))}
      </div>
      <div className="row gap6">
        <input className="hex" value={hex} onChange={(e) => setHex(e.target.value)}
          onBlur={() => /^#[0-9a-f]{6}$/i.test(hex) && hex !== value && onPick(hex.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        {off ? <span className="warn-chip" title="Not a Xero brand colour">off-palette</span> : null}
      </div>
    </div>
  );
}

export function PropertiesPanel({ onExport, onDna }: { onExport: (b: DesignSpec) => void; onDna: (b: DesignSpec) => void }) {
  const board = useEditor((s) => s.doc.boards.find((b) => b.id === s.activeBoardId) ?? null);
  const selId = useEditor((s) => s.selection);
  if (!board) return <div className="props muted pad">Select or create a board.</div>;
  const layer = selId ? findLayer(board, selId) : null;
  const set = (fn: (l: Layer) => void) => mutateBoard(board.id, (b) => { const l = selId ? findLayer(b, selId) : null; if (l) fn(l); });

  if (!layer) {
    return (
      <div className="props">
        <h4>Board</h4>
        <label className="field"><span>Name</span>
          <input defaultValue={board.name} key={board.id} onBlur={(e) => mutateBoard(board.id, (b) => { b.name = e.target.value || b.name; })} /></label>
        <div className="muted small">{board.width} × {board.height}px · {board.format}</div>
        <h4>Background</h4>
        <Swatches value={board.background} onPick={(c) => mutateBoard(board.id, (b) => {
          b.background = c; const bg = b.layers.find((l) => l.role === "background"); if (bg) bg.fill = c;
        })} />
        <div className="col gap6 mt12">
          <button className="btn-dark" onClick={() => onDna(board)}>🧬 Brand DNA check</button>
          <button className="btn-ghost" onClick={() => onExport(board)}>⤓ Export PNG</button>
        </div>
        {board.summary ? <div className="muted small mt12">Brand guard {board.summary.score}/100 · art director {board.qa?.score ?? "–"}/10</div> : null}
      </div>
    );
  }

  const b = bounds(layer);
  const isText = layer.kind === "text";
  const families = brandFamilies();
  return (
    <div className="props">
      <h4>{layer.name} <small className="muted">{layer.kind}{layer.role ? ` · ${layer.role}` : ""}</small></h4>
      <div className="grid2">
        <Num label="X" value={b.x} onCommit={(v) => set((l) => moveLayer(l, v - bounds(l).x, 0))} />
        <Num label="Y" value={b.y} onCommit={(v) => set((l) => moveLayer(l, 0, v - bounds(l).y))} />
        <Num label="W" value={b.w} onCommit={(v) => set((l) => { const o = bounds(l); resizeLayer(l, o.x, o.y, Math.max(1, v), o.h); })} />
        <Num label="H" value={b.h} onCommit={(v) => set((l) => { const o = bounds(l); resizeLayer(l, o.x, o.y, o.w, Math.max(1, v)); })} />
        <Num label="↻" value={layer.rotation ?? 0} onCommit={(v) => set((l) => { l.rotation = v; })} />
        <Num label="α %" value={Math.round((layer.opacity ?? 1) * 100)} onCommit={(v) => set((l) => { l.opacity = Math.max(0, Math.min(100, v)) / 100; })} />
      </div>

      {isText ? (
        <>
          <h4>Text</h4>
          <textarea className="text-input" value={layer.text ?? ""} rows={3} onChange={(e) => set((l) => { l.text = e.target.value; })} />
          <div className="grid2">
            <label className="field"><span>Font</span>
              <select value={layer.font_family ?? ""} onChange={(e) => set((l) => { l.font_family = e.target.value; l.font_weight = weightsFor(e.target.value).includes(l.font_weight ?? "") ? l.font_weight : weightsFor(e.target.value)[0]; })}>
                {families.map((f) => <option key={f}>{f}</option>)}
              </select></label>
            <label className="field"><span>Weight</span>
              <select value={layer.font_weight ?? ""} onChange={(e) => set((l) => { l.font_weight = e.target.value; })}>
                {weightsFor(layer.font_family ?? "Barlow").map((w) => <option key={w}>{w}</option>)}
              </select></label>
            <Num label="Size" value={layer.font_size ?? 24} onCommit={(v) => set((l) => { l.font_size = Math.max(6, v); })} />
            <Num label="Line" value={layer.line_height ?? 1.2} step={0.05} onCommit={(v) => set((l) => { l.line_height = v; })} />
          </div>
          <div className="seg">
            {(["left", "center", "right"] as const).map((a) => (
              <button key={a} className={(layer.align ?? "left") === a ? "on" : ""} onClick={() => set((l) => { l.align = a; })}>{a}</button>
            ))}
          </div>
          <h4>Colour</h4>
          <Swatches value={layer.color} onPick={(c) => set((l) => { l.color = c; })} />
        </>
      ) : null}

      {["rect", "ellipse", "vector"].includes(layer.kind) ? (
        <>
          <h4>Fill</h4>
          <Swatches value={layer.fill ?? layer.stroke} onPick={(c) => set((l) => { if (l.svg && !l.fill) l.stroke = c; else l.fill = c; })} />
          {layer.kind === "rect" ? <Num label="Radius" value={layer.radius ?? 0} onCommit={(v) => set((l) => { l.radius = Math.max(0, v); })} /> : null}
        </>
      ) : null}

      {layer.kind === "image" ? (
        <>
          <h4>Image</h4>
          {layer.src ? <img className="img-prev" src={layer.src} alt={layer.name} /> : <div className="muted small">Generating…</div>}
          {layer.prompt ? <div className="muted tiny mt6">Prompt: {layer.prompt.slice(0, 180)}</div> : null}
          {layer.compliance ? (
            <div className={`small mt6 ${layer.compliance.ok ? "ok-text" : "err-text"}`}>
              {layer.compliance.ok ? "✓ Policy-verified (no text, logos or off-brand content)" : `⚠ ${layer.compliance.blocking?.join(", ")}`}
            </div>
          ) : null}
          <label className="btn-ghost mt6 file-btn">Replace image…
            <input type="file" accept="image/*" hidden onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              const up = await uploadFile(f);
              set((l) => { Object.assign(l, { src: up.url, file: up.file, status: "ready", prompt: null, compliance: null }); const r = up.width / up.height; l.h = l.w / r; });
            }} /></label>
        </>
      ) : null}

      <div className="row gap6 mt12">
        <button className="btn-ghost sm" onClick={() => set((l) => { l.locked = !l.locked; })}>{layer.locked ? "Unlock" : "Lock"}</button>
        <button className="btn-ghost sm" onClick={() => set((l) => { l.hidden = !l.hidden; })}>{layer.hidden ? "Show" : "Hide"}</button>
        <button className="btn-ghost sm" onClick={() => setUi({ selection: null })}>Deselect</button>
      </div>
    </div>
  );
}
