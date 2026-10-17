// Editor state: the document (autosaved to the backend), selection, tool, viewport, undo/redo.
import { useSyncExternalStore } from "react";
import type { Doc, DesignSpec, Tool } from "./types";

export interface EditorState {
  doc: Doc;
  loaded: boolean;
  activeBoardId: string | null;
  selection: string | null;        // layer id
  tool: Tool;
  zoom: number;                    // screen px per board px
  pan: { x: number; y: number };   // board origin in screen px (within the canvas element)
  editingTextId: string | null;
  commentDraft: { boardId: string; x: number; y: number; layerId: string | null; layerName: string | null } | null;
  openComment: string | null;
  saving: "saved" | "saving" | "error";
  canUndo: boolean;
  canRedo: boolean;
}

// Which document to open: ?doc=<id> (tests use throwaway docs), default the campaign file.
const requested = new URLSearchParams(location.search).get("doc") ?? "";
const DOC_ID = /^[a-z0-9-]{1,40}$/.test(requested) ? requested : "xero-campaign";
let state: EditorState = {
  doc: { id: DOC_ID, name: "Xero campaign", boards: [], comments: [] },
  loaded: false, activeBoardId: null, selection: null, tool: "select", zoom: 0.5, pan: { x: 40, y: 40 },
  editingTextId: null, commentDraft: null, openComment: null, saving: "saved", canUndo: false, canRedo: false,
};
const listeners = new Set<() => void>();
const undoStack: string[] = [];
const redoStack: string[] = [];

function emit(next: Partial<EditorState>) {
  state = { ...state, ...next, canUndo: undoStack.length > 0, canRedo: redoStack.length > 0 };
  listeners.forEach((l) => l());
}

export function getState(): EditorState {
  return state;
}

export function useEditor<T>(selector: (s: EditorState) => T): T {
  return useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, () => selector(state));
}

export function setUi(next: Partial<Omit<EditorState, "doc">>) {
  // Leaving the comment tool closes any comment composer / thread popover.
  if (next.tool && next.tool !== "comment" && next.tool !== state.tool) {
    next = { commentDraft: null, openComment: null, ...next };
  }
  emit(next);
}

// ---- persistence -----------------------------------------------------------------
let saveTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  emit({ saving: "saving" });
  saveTimer = setTimeout(async () => {
    try {
      const r = await fetch(`/api/docs/${DOC_ID}`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.doc) });
      emit({ saving: r.ok ? "saved" : "error" });
    } catch {
      emit({ saving: "error" });
    }
  }, 700);
}

export async function loadDoc() {
  const r = await fetch(`/api/docs/${DOC_ID}`);
  const doc = (await r.json()) as Doc;
  doc.boards ??= [];
  doc.comments ??= [];
  emit({ doc, loaded: true, activeBoardId: doc.boards[doc.boards.length - 1]?.id ?? null });
}

// ---- mutations ------------------------------------------------------------------
/**
 * Change the document. ``history`` records an undo step (drags snapshot once at the start and
 * then mutate with history=false).
 */
export function mutate(fn: (doc: Doc) => void, opts: { history?: boolean; save?: boolean } = {}) {
  const { history = true, save = true } = opts;
  if (history) {
    undoStack.push(JSON.stringify(state.doc));
    if (undoStack.length > 120) undoStack.shift();
    redoStack.length = 0;
  }
  const doc = structuredClone(state.doc);
  fn(doc);
  emit({ doc });
  if (save) scheduleSave();
}

export function snapshot() {
  undoStack.push(JSON.stringify(state.doc));
  redoStack.length = 0;
  emit({});
}

export function undo() {
  const prev = undoStack.pop();
  if (!prev) return;
  redoStack.push(JSON.stringify(state.doc));
  emit({ doc: JSON.parse(prev), editingTextId: null });
  scheduleSave();
}

export function redo() {
  const next = redoStack.pop();
  if (!next) return;
  undoStack.push(JSON.stringify(state.doc));
  emit({ doc: JSON.parse(next), editingTextId: null });
  scheduleSave();
}

export function activeBoard(): DesignSpec | null {
  return state.doc.boards.find((b) => b.id === state.activeBoardId) ?? null;
}

export function boardById(id: string | null | undefined): DesignSpec | null {
  return state.doc.boards.find((b) => b.id === id) ?? null;
}

export function mutateBoard(boardId: string, fn: (b: DesignSpec) => void, opts?: { history?: boolean; save?: boolean }) {
  mutate((doc) => {
    const b = doc.boards.find((x) => x.id === boardId);
    if (b) fn(b);
  }, opts);
}
