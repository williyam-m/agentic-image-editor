import { BoardSvg } from "../render/BoardSvg";
import { setUi, useEditor } from "../model/store";
import type { DesignJobView, VariantView } from "./flows";
import { GenerateLike } from "./GenerateLike";

const STAGES = ["analyzing", "planning", "layout", "generating", "done"] as const;
const STAGE_LABEL: Record<string, string> = {
  queued: "Queued", analyzing: "Reading reference", planning: "Planning", layout: "Layout + brand rules",
  generating: "Generating layers", done: "Ready",
};

function Variant({ v, onVariations, onDna, fontsVersion }: { v: VariantView; onVariations: (id: string, count: number) => void; onDna: (id: string) => void; fontsVersion: number }) {
  const board = useEditor((s) => s.doc.boards.find((b) => b.id === v.boardId) ?? null);
  const qa = v.result?.qa;
  const s = v.result?.summary;
  return (
    <div className="variant">
      <button className="thumb" onClick={() => v.boardId && setUi({ activeBoardId: v.boardId, selection: null })} title="Open on canvas">
        {board ? <BoardSvg spec={board} uid={`chat-${board.id}`} width="100%" height="100%" fontsVersion={fontsVersion} />
          : <div className="thumb-skeleton"><span>{v.headline || "Laying out…"}</span></div>}
      </button>
      <div className="variant-meta">
        <div className="variant-title">{v.headline || "…"}</div>
        <div className="variant-sub">{v.archetype?.replace(/_/g, " ")} · {v.colorway}{v.imagesTotal ? ` · ${v.imagesDone}/${v.imagesTotal} images` : ""}</div>
        <div className="row wrap gap6">
          {s ? <span className={`pill ${s.warnings ? "pill-warn" : "pill-ok"}`}>Brand {s.score}/100{s.fixed ? ` · ${s.fixed} auto-fixed` : ""}</span> : null}
          {qa?.score ? <span className="pill pill-neutral" title={[...(qa.strengths ?? []), ...(qa.issues ?? [])].join("\n")}>Art director {qa.score}/10</span> : null}
        </div>
        {qa?.issues?.length ? <div className="qa-note">↳ {qa.issues[0]}</div> : null}
        {v.result && v.boardId ? (
          <div className="row gap6 mt6 wrap">
            <button className="btn-ghost sm" onClick={() => setUi({ activeBoardId: v.boardId!, selection: null })}>Open</button>
            <GenerateLike onGenerate={(n) => onVariations(v.boardId!, n)} />
            <button className="btn-ghost sm" onClick={() => onDna(v.boardId!)}>🧬 DNA</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function DesignCard({ view, onVariations, onDna, fontsVersion }: {
  view: DesignJobView; onVariations: (id: string, count: number) => void; onDna: (id: string) => void; fontsVersion: number;
}) {
  const stageIdx = STAGES.indexOf(view.stage as (typeof STAGES)[number]);
  const total = view.variants.reduce((a, v) => a + v.imagesTotal, 0);
  const done = view.variants.reduce((a, v) => a + v.imagesDone, 0);
  const pct = view.status === "done" ? 100 : Math.max(6, Math.min(96, (stageIdx / 4) * 70 + (total ? (done / total) * 26 : 0)));
  return (
    <div className="card design-card">
      <div className="row between">
        <div className="row gap6"><span className={`dot ${view.status}`} /><strong>{STAGE_LABEL[view.stage] ?? view.stage}</strong></div>
        <span className="mono muted">{view.seconds.toFixed(1)}s</span>
      </div>
      <div className="progress"><div style={{ width: `${pct}%` }} /></div>
      <ol className="timeline">
        {view.events.slice(-5).map((e, i) => <li key={i} className={e.kind}><span className="mono">{e.t.toFixed(1)}s</span> {e.text}</li>)}
      </ol>
      {view.error ? <div className="error-note">{view.error}</div> : null}
      {view.variants.length ? (
        <div className={`variants n${view.variants.length}`}>
          {view.variants.map((v) => <Variant key={v.index} v={v} onVariations={onVariations} onDna={onDna} fontsVersion={fontsVersion} />)}
        </div>
      ) : null}
    </div>
  );
}
