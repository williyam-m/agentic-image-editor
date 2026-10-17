// Canvas comments: pin a note on any layer; Crux edits the layer under the pin and replies.
import { useEffect, useRef, useState } from "react";
import { mutate, setUi, useEditor, type EditorState } from "../model/store";
import type { CanvasComment } from "../model/types";
import { useVoice } from "../voice/useVoice";
import { VoiceButton } from "../voice/VoiceButton";

type Handler = (draft: { boardId: string; x: number; y: number; layerId: string | null }, text: string) => void;
let handler: Handler | null = null;
export const setCommentHandler = (h: Handler) => { handler = h; };

export function CommentLayer({ comments, zoom, pan }: { comments: CanvasComment[]; zoom: number; pan: { x: number; y: number } }) {
  const draft = useEditor((s) => s.commentDraft);
  const open = useEditor((s) => s.openComment);
  const showResolved = useEditor((s) => s.tool === "comment");
  const at = (x: number, y: number) => ({ left: pan.x + x * zoom, top: pan.y + y * zoom });
  const visible = comments.filter((c) => c.status !== "resolved" || showResolved || open === c.id);
  return (
    <>
      {visible.map((c, i) => (
        <button key={c.id} className={`pin ${c.kind} ${c.status} ${c.severity ?? ""}`} style={at(c.x, c.y)} data-testid="comment-pin"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); setUi({ openComment: open === c.id ? null : c.id, commentDraft: null }); }}>
          {c.kind === "dna" ? "!" : c.status === "working" ? "…" : c.status === "resolved" ? "✓" : i + 1}
        </button>
      ))}
      {open ? <Thread c={comments.find((c) => c.id === open)} style={at} /> : null}
      {draft && handler ? <Composer key={`${draft.x}-${draft.y}`} style={at(draft.x, draft.y)} draft={draft} /> : null}
    </>
  );
}

function Composer({ style, draft }: { style: { left: number; top: number }; draft: NonNullable<EditorState["commentDraft"]> }) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const submit = (value = text) => {
    if (!value.trim()) return;
    handler?.(draft, value.trim());
    setUi({ commentDraft: null });
  };
  const voice = useVoice((heard) => { setText(heard); submit(heard); });
  return (
    <div className="comment-pop" style={{ left: style.left + 14, top: style.top - 10 }} onPointerDown={(e) => e.stopPropagation()}>
      <div className="cp-head row between">
        <span>💬 Comment on <b>{draft.layerName ?? "board"}</b></span>
        <button className="cp-close" title="Close (Esc)" aria-label="Close comment" data-testid="comment-close"
          onClick={() => setUi({ commentDraft: null })}>×</button>
      </div>
      <textarea ref={ref} value={text} rows={3} placeholder="Tell Crux what to change here…" data-testid="comment-input"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } if (e.key === "Escape") setUi({ commentDraft: null }); }} />
      <div className="row between">
        <div className="row gap6">
          <VoiceButton compact state={voice.state} levels={voice.levels} enabled={voice.enabled} onClick={() => void voice.toggle()} />
          <span className="muted tiny">{voice.state === "listening" ? "Listening…" : voice.error ?? "Type or speak — Crux edits this layer"}</span>
        </div>
        <button className="btn-dark sm" onClick={() => submit()} disabled={!text.trim()}>Post</button>
      </div>
    </div>
  );
}

function Thread({ c, style }: { c?: CanvasComment; style: (x: number, y: number) => { left: number; top: number } }) {
  if (!c) return null;
  const s = style(c.x, c.y);
  return (
    <div className="comment-pop" style={{ left: s.left + 14, top: s.top - 10 }} onPointerDown={(e) => e.stopPropagation()}>
      <div className="cp-head row between">
        <span>{c.kind === "dna" ? "🧬 Brand DNA issue" : `💬 ${c.status === "working" ? "Crux is editing…" : c.status === "resolved" ? "Resolved" : c.status === "failed" ? "Needs attention" : "Comment"}`}</span>
        <button className="cp-close" title="Close" aria-label="Close thread" onClick={() => setUi({ openComment: null })}>×</button>
      </div>
      {c.thread.map((m, i) => (
        <div key={i} className={`msg-line ${m.author}`}><b>{m.author === "crux" ? "✦ Crux" : "You"}</b> {m.text}</div>
      ))}
      <div className="row gap6 mt6">
        {c.status !== "resolved" ? (
          <button className="btn-ghost xs" onClick={() => mutate((d) => { const x = d.comments.find((k) => k.id === c.id); if (x) x.status = "resolved"; })}>Resolve</button>
        ) : null}
        <button className="btn-ghost xs" onClick={() => { mutate((d) => { d.comments = d.comments.filter((k) => k.id !== c.id); }); setUi({ openComment: null }); }}>Delete</button>
      </div>
    </div>
  );
}
