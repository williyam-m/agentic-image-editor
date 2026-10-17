import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { activeBoard, boardById, useEditor } from "../model/store";
import { findLayer } from "../model/layers";
import { setCommentHandler } from "../canvas/Comments";
import type { ReferenceInfo } from "./api";
import { DesignCard } from "./DesignCard";
import { DnaCard, type DnaView } from "./DnaCard";
import { useVoice } from "../voice/useVoice";
import { VoiceButton } from "../voice/VoiceButton";
import {
  applyDnaFixes, inferIntent, pinDnaFindings, runBrandDna, runCommentEdit, runDesign, runEdit,
  type DesignJobView, type Format,
} from "./flows";

type ChatItem =
  | { id: number; kind: "user"; text: string; context?: string; voice?: boolean }
  | { id: number; kind: "assistant"; text: string }
  | { id: number; kind: "design"; view: DesignJobView }
  | { id: number; kind: "dna"; view: DnaView; boardId: string }
  | { id: number; kind: "edit"; stage: string; title: string; message?: string; applied?: string[]; notes?: string[]; error?: string; via?: "chat" | "comment" };

const FORMATS: [Format, string][] = [["feed", "4:5"], ["square", "1:1"], ["story", "9:16"], ["landscape", "1.91:1"]];
const SUGGESTIONS = [
  "Feed ad: tradies get paid faster with Xero invoicing",
  "Checklist ad — Payroll, Invoices, GST all sorted",
  "Story ad for cash flow insights, bold and optimistic",
  "Create 4 different images like this",
];

let seq = 0;
const nextId = () => ++seq;

export interface CopilotApi {
  runDna: (boardId: string) => void;
  useReference: (r: ReferenceInfo, count: number) => void;
  designFrom: (label: string, body: Partial<Parameters<typeof runDesign>[0]> & { prompt: string }) => void;
}

export function Copilot({ fontsVersion, notify, register }: {
  fontsVersion: number;
  notify: (m: string, tone?: "ok" | "err") => void;
  register: (api: CopilotApi) => void;
}) {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [text, setText] = useState("");
  const [format, setFormat] = useState<Format>("feed");
  const [busy, setBusy] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const boardId = useEditor((s) => s.activeBoardId);
  const boardName = useEditor((s) => s.doc.boards.find((b) => b.id === s.activeBoardId)?.name ?? null);
  const selection = useEditor((s) => s.selection);
  const selName = useEditor((s) => {
    const b = s.doc.boards.find((x) => x.id === s.activeBoardId);
    return b && s.selection ? findLayer(b, s.selection)?.name ?? null : null;
  });

  const push = useCallback((it: ChatItem) => setItems((xs) => [...xs, it]), []);
  const patch = useCallback((id: number, fn: (it: ChatItem) => ChatItem) => setItems((xs) => xs.map((x) => (x.id === id ? fn(x) : x))), []);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }); }, [items]);

  const design = useCallback(async (body: Parameters<typeof runDesign>[0]) => {
    const id = nextId();
    push({ id, kind: "design", view: { stage: "queued", events: [], variants: [], status: "running", seconds: 0 } });
    setBusy((b) => b + 1);
    try {
      await runDesign(body, (view) => patch(id, (it) => ({ ...it, view } as ChatItem)));
    } finally {
      setBusy((b) => b - 1);
    }
  }, [patch, push]);

  const edit = useCallback(async (bId: string, instruction: string, targets: string[], title: string) => {
    const id = nextId();
    push({ id, kind: "edit", stage: "Starting", title });
    setBusy((b) => b + 1);
    try {
      const r = await runEdit(bId, instruction, targets, null, (stage) => patch(id, (it) => ({ ...it, stage } as ChatItem)));
      patch(id, (it) => ({ ...it, stage: "done", message: r.message, applied: r.applied, notes: r.notes } as ChatItem));
    } catch (e) {
      patch(id, (it) => ({ ...it, stage: "error", error: e instanceof Error ? e.message : String(e) } as ChatItem));
    } finally {
      setBusy((b) => b - 1);
    }
  }, [patch, push]);

  const dna = useCallback(async (bId: string, previous?: number) => {
    const id = nextId();
    const b = boardById(bId);
    push({ id, kind: "dna", boardId: bId, view: { title: b?.name ?? "Board", stage: "Starting", previous } });
    setBusy((x) => x + 1);
    try {
      const report = await runBrandDna(bId, (stage) => patch(id, (it) => it.kind === "dna" ? { ...it, view: { ...it.view, stage } } : it));
      patch(id, (it) => it.kind === "dna" ? { ...it, view: { ...it.view, report } } : it);
    } catch (e) {
      patch(id, (it) => it.kind === "dna" ? { ...it, view: { ...it.view, error: e instanceof Error ? e.message : String(e) } } : it);
    } finally {
      setBusy((x) => x - 1);
    }
  }, [patch, push]);

  const variationsOf = useCallback((bId: string, count = 4) => {
    const b = boardById(bId);
    if (!b) return;
    const n = Math.max(1, Math.min(4, count));
    const prompt = n === 1 ? "Create a fresh take like this" : `Create ${n} different images like this`;
    push({ id: nextId(), kind: "user", text: prompt, context: `${n} like “${b.name}”` });
    const brief = Object.keys(b.brief ?? {}).length ? b.brief : null;
    void design({ prompt, format: (b.format as Format) || format, count: n, base_brief: brief, reference_spec: brief ? null : b });
  }, [design, format, push]);

  useEffect(() => {
    register({
      runDna: (bId) => void dna(bId),
      designFrom: (label, body) => {
        push({ id: nextId(), kind: "user", text: body.prompt, context: label });
        void design({ format, count: 1, ...body });
      },
      useReference: (r, count) => {
        const prompt = count > 1 ? `Create ${count} different images like this` : "Recreate this idea on-brand with a fresh angle";
        push({ id: nextId(), kind: "user", text: prompt, context: `Inspired by: ${r.headline?.replace(/\n/g, " ")}` });
        void design({ prompt, format, count, reference_id: r.id });
      },
    });
    setCommentHandler((draft, t) => {
      const b = boardById(draft.boardId);
      const layerName = b && draft.layerId ? findLayer(b, draft.layerId)?.name : null;
      push({ id: nextId(), kind: "user", text: t, context: `💬 comment on ${layerName ?? "board"}` });
      const id = nextId();
      push({ id, kind: "edit", stage: "Editing the layer under your comment", title: layerName ?? "Board", via: "comment" });
      void runCommentEdit(draft, t, (ok, msg) => patch(id, (it) => ({ ...it, stage: ok ? "done" : "error", message: ok ? msg : undefined, error: ok ? undefined : msg } as ChatItem)));
    });
  }, [design, dna, format, patch, push, register]);

  const intent = useMemo(() => inferIntent(text, !!boardId, selection), [text, boardId, selection]);
  const contextLabel = intent.kind === "edit"
    ? (intent.scope === "layer" ? `Editing ${selName ?? "layer"}` : `Editing board “${boardName}”`)
    : intent.kind === "variations" ? `${intent.count} variations of “${boardName}”`
    : intent.count > 1 ? `${intent.count} new designs` : "New design";

  const submit = useCallback(async (raw?: string, voice = false) => {
    const prompt = (raw ?? text).trim();
    if (!prompt) return;
    setText("");
    const b = activeBoard();
    const it = inferIntent(prompt, !!b, selection);
    push({ id: nextId(), kind: "user", text: prompt, context: contextLabel, voice });
    if (it.kind === "edit" && b) {
      await edit(b.id, prompt, it.scope === "layer" && selection ? [selection] : [], it.scope === "layer" ? selName ?? "Layer" : `Board “${b.name}”`);
    } else if (it.kind === "variations" && b) {
      variationsOf(b.id, it.count);
    } else {
      await design({ prompt, format, count: it.kind === "create" ? it.count : 1 });
    }
  }, [contextLabel, design, edit, format, push, selName, selection, text, variationsOf]);

  // Voice to edit: what you say runs exactly like a typed instruction on the current selection.
  const voice = useVoice((heard) => void submit(heard, true));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "m" || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement).closest("input, textarea, [contenteditable]")) return;
      e.preventDefault();
      if (voice.enabled) void voice.toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [voice]);

  return (
    <div className="copilot">
      <div className="messages" ref={listRef}>
        {!items.length ? (
          <div className="empty">
            <div className="hero">
              <span className="eyebrow">✦ Backed by your brand kit</span>
              <h1>Design on-brand,<br /><span className="grad">layer by layer.</span></h1>
              <p>Every headline, photo, bloom and logo lands as its own editable layer on the canvas.</p>
            </div>
            <div className="suggestions">{SUGGESTIONS.map((s) => <button key={s} onClick={() => setText(s)}>{s}</button>)}</div>
            <ul className="tips">
              <li><b>Edit a layer</b> — click it on the canvas, then tell me what to change.</li>
              <li><b>Comment</b> — press <kbd>C</kbd>, click any layer and write what you want.</li>
              <li><b>Variations</b> — with a board open, ask for “4 different images like this”.</li>
              <li><b>Voice</b> — press <kbd>M</kbd> (or the mic) and just say the change.</li>
            </ul>
          </div>
        ) : null}
        {items.map((it) => {
          if (it.kind === "user") return <div key={it.id} className="msg user">{it.context ? <span className="ctx">{it.voice ? "🎙 voice · " : ""}{it.context}</span> : null}<div className="bubble">{it.text}</div></div>;
          if (it.kind === "assistant") return <div key={it.id} className="msg assistant"><div className="card">{it.text}</div></div>;
          if (it.kind === "design") return <div key={it.id} className="msg assistant"><DesignCard view={it.view} onVariations={variationsOf} onDna={(b) => void dna(b)} fontsVersion={fontsVersion} /></div>;
          if (it.kind === "dna") {
            const rerun = () => void dna(it.boardId, it.view.report?.score);
            return (
              <div key={it.id} className="msg assistant">
                <DnaCard view={it.view} onRerun={rerun}
                  onFix={async () => { const n = applyDnaFixes(it.boardId, it.view.report!); notify(`Applied ${n} brand fix${n === 1 ? "" : "es"} — re-checking`); rerun(); }}
                  onFixOne={async (fid) => { applyDnaFixes(it.boardId, it.view.report!, [fid]); notify("Fixed"); }}
                  onPin={async () => { const n = pinDnaFindings(it.boardId, it.view.report!); notify(`Pinned ${n} issue${n === 1 ? "" : "s"} on the canvas`); }} />
              </div>
            );
          }
          return (
            <div key={it.id} className="msg assistant">
              <div className="card edit-card">
                <div className="row between">
                  <div className="row gap6"><span className={`dot ${it.stage === "done" ? "done" : it.stage === "error" ? "error" : "running"}`} />
                    <strong>{it.via === "comment" ? "Comment edit" : "Layer edit"}</strong></div>
                  <span className="muted small">{it.title}</span>
                </div>
                {it.stage !== "done" && it.stage !== "error" ? <div className="muted small mt6">{it.stage}…</div> : null}
                {it.message ? <p className="mt6">{it.message}</p> : null}
                {it.applied?.length ? <ul className="bullets small">{it.applied.map((a, i) => <li key={i}>{a}</li>)}</ul> : null}
                {it.notes?.length ? <div className="notes">{it.notes.map((n, i) => <div key={i}>⚑ {n}</div>)}</div> : null}
                {it.error ? <div className="error-note">{it.error}</div> : null}
              </div>
            </div>
          );
        })}
      </div>
      <footer className="composer">
        <div className="row between">
          <span className={`context-chip ${intent.kind}`}>{intent.kind === "edit" ? "✎" : intent.kind === "variations" ? "⧉" : "✦"} {contextLabel}</span>
          <div className="row gap6">
            {busy ? <span className="muted small">{busy} running</span> : null}
            <button className="dna-btn" disabled={!boardId} title="Check this board against the brand guidelines"
              onClick={() => boardId && void dna(boardId)}>🧬 Brand DNA</button>
          </div>
        </div>
        {intent.kind !== "edit" ? (
          <div className="segmented">
            {FORMATS.map(([id, label]) => <button key={id} className={format === id ? "active" : ""} onClick={() => setFormat(id)}>{label}</button>)}
          </div>
        ) : null}
        {voice.state === "listening" || voice.state === "transcribing" || voice.error ? (
          <div className={`voice-strip ${voice.state}`} data-testid="voice-strip">
            {voice.state === "listening" ? <>Listening… say what to change{selName ? <> on <b>{selName}</b></> : boardName ? <> on <b>{boardName}</b></> : null}</>
              : voice.state === "transcribing" ? "Transcribing with ElevenLabs Scribe v2…"
              : <>{voice.error} <button className="x" onClick={voice.clearError}>×</button></>}
          </div>
        ) : null}
        <div className="input-row">
          <VoiceButton state={voice.state} levels={voice.levels} enabled={voice.enabled} onClick={() => void voice.toggle()} />
          <textarea value={text} rows={2} data-testid="chat-input"
            placeholder={intent.kind === "edit" ? "Tell me what to change — or press M and say it" : "Describe the ad you need — or press M and say it"}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }} />
          <button className="send" disabled={!text.trim()} onClick={() => void submit()} aria-label="Send">↑</button>
        </div>
      </footer>
    </div>
  );
}
