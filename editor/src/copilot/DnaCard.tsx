import { useState } from "react";
import type { DnaReport } from "./api";
import { setUi } from "../model/store";

const DIM_LABEL: Record<string, string> = {
  color: "Colour", typography: "Typography", logo: "Logo", imagery: "Imagery", layout: "Layout", copy: "Copy & legal",
};

export interface DnaView {
  title: string;
  stage: string;
  report?: DnaReport;
  error?: string;
  previous?: number;
}

function Ring({ score }: { score: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const tone = score >= 85 ? "var(--ok)" : score >= 60 ? "var(--warn)" : "var(--err)";
  return (
    <svg width="68" height="68" viewBox="0 0 68 68" className="ring">
      <circle cx="34" cy="34" r={r} stroke="#f1efec" strokeWidth="7" fill="none" />
      <circle cx="34" cy="34" r={r} stroke={tone} strokeWidth="7" fill="none" strokeLinecap="round"
        strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 34 34)" />
      <text x="34" y="39" textAnchor="middle" fontSize="17" fontWeight="700" fill="#141414">{score}</text>
    </svg>
  );
}

export function DnaCard({ view, onFix, onFixOne, onPin, onRerun }: {
  view: DnaView;
  onFix: () => Promise<void>;
  onFixOne: (id: string) => Promise<void>;
  onPin: () => Promise<void>;
  onRerun: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const r = view.report;
  const wrap = (key: string, fn: () => Promise<void>) => async () => {
    setBusy(key);
    try { await fn(); } finally { setBusy(null); }
  };
  if (!r) {
    return (
      <div className="card dna-card">
        <div className="row gap6"><span className={`dot ${view.error ? "error" : "running"}`} /><strong>Brand DNA</strong>
          <span className="muted small">· {view.title}</span></div>
        <div className="muted small mt6">{view.error ?? `${view.stage}…`}</div>
      </div>
    );
  }
  const high = r.findings.filter((f) => f.severity === "high").length;
  return (
    <div className="card dna-card">
      <div className="row gap10">
        <Ring score={r.score} />
        <div className="dna-head">
          <div className="row gap6"><strong>Brand DNA</strong>
            <span className={`pill ${r.verdict === "On-brand" ? "pill-ok" : "pill-warn"}`}>{r.verdict}</span></div>
          <div className="muted small">{view.title}{view.previous !== undefined ? ` · was ${view.previous}` : ""}</div>
          <div className="small">{r.findings.length} issue{r.findings.length === 1 ? "" : "s"} · {high} high · {r.fixable} auto-fixable</div>
        </div>
      </div>
      {r.summary ? <p className="small mt6 ink2">{r.summary}</p> : null}
      <div className="dims">
        {Object.entries(r.scores).map(([d, v]) => (
          <div key={d} className="dim">
            <span>{DIM_LABEL[d] ?? d}</span>
            <div className="bar"><div style={{ width: `${v}%` }} className={v >= 85 ? "ok" : v >= 60 ? "warn" : "err"} /></div>
            <b className="mono">{v}</b>
          </div>
        ))}
      </div>
      {r.findings.length ? (
        <ul className="findings">
          {r.findings.map((f) => (
            <li key={f.id} className={f.severity}>
              <div className="row between gap6">
                <span className={`sev ${f.severity}`}>{f.severity}</span>
                <span className="muted tiny">{DIM_LABEL[f.dimension] ?? f.dimension} · {f.source === "measured" ? "measured" : "visual"}</span>
              </div>
              <div className="issue">{f.issue}</div>
              <div className="suggest">→ {f.suggestion}</div>
              <div className="row gap6 mt4">
                {f.layer_id ? <button className="btn-ghost xs" onClick={() => setUi({ selection: f.layer_id! })}>Show</button> : null}
                {f.fix ? <button className="btn-ghost xs" disabled={!!busy} onClick={wrap(f.id, () => onFixOne(f.id))}>{busy === f.id ? "Fixing…" : "Fix"}</button> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : <div className="ok-note mt6">✓ No guideline violations found.</div>}
      {r.strengths?.length ? <div className="muted tiny mt6">Strengths: {r.strengths.join(" · ")}</div> : null}
      <div className="row gap6 mt6 wrap">
        {r.fixable ? <button className="btn-dark sm" disabled={!!busy} onClick={wrap("all", onFix)}>{busy === "all" ? "Fixing…" : `Fix ${r.fixable} automatically`}</button> : null}
        {r.findings.some((f) => f.box) ? <button className="btn-ghost sm" disabled={!!busy} onClick={wrap("pin", onPin)}>{busy === "pin" ? "Pinning…" : "Pin issues on canvas"}</button> : null}
        <button className="btn-ghost sm" onClick={onRerun}>Re-check</button>
      </div>
    </div>
  );
}
