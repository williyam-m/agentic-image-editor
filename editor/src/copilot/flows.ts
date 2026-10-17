// Copilot flows: AI jobs ⇄ the document. Boards appear as soon as the layout exists; generated
// pixels and brand-guard fixes merge in as they land (the board stays editable throughout).
import { applyOps, boardInfo, findLayer, layerInfo, layerInfos, mergeFromServer, uid } from "../model/layers";
import { boardById, getState, mutate, mutateBoard, setUi } from "../model/store";
import type { DesignSpec, Layer } from "../model/types";
import { api, pollJob, type DesignProgress, type DesignResult, type DnaReport, type EditResult, type JobEvent } from "./api";

export type Format = "feed" | "square" | "story" | "landscape";

export interface VariantView { index: number; boardId?: string; imagesTotal: number; imagesDone: number; result?: DesignResult | null; headline?: string; archetype?: string; colorway?: string }
export interface DesignJobView { jobId?: string; stage: string; events: JobEvent[]; variants: VariantView[]; status: "running" | "done" | "error"; error?: string; seconds: number }

const images = (s: DesignSpec) => {
  const out: Layer[] = [];
  const rec = (a: Layer[]) => a.forEach((l) => { if (l.kind === "image") out.push(l); rec(l.children ?? []); });
  rec(s.layers);
  return out;
};

export interface DesignRequest {
  prompt: string; format: Format; count: number;
  reference_id?: string | null; reference_spec?: DesignSpec | null; base_brief?: Record<string, unknown> | null;
  reference_file?: string | null;
}

export async function runDesign(req: DesignRequest, onUpdate: (v: DesignJobView) => void): Promise<DesignJobView> {
  const t0 = performance.now();
  const view: DesignJobView = { stage: "queued", events: [], variants: [], status: "running", seconds: 0 };
  const emit = () => onUpdate({ ...view, seconds: (performance.now() - t0) / 1000, variants: view.variants.map((v) => ({ ...v })) });
  emit();
  const { job_id } = await api.createDesign({ ...req });
  view.jobId = job_id;
  const placed = new Set<string>();
  const finished = new Set<string>();

  const sync = (specs: DesignSpec[], results: (DesignResult | null)[]) => {
    specs.forEach((spec, i) => {
      const v = (view.variants[i] ??= { index: i, imagesTotal: 0, imagesDone: 0 });
      Object.assign(v, { boardId: spec.id, imagesTotal: images(spec).length,
        imagesDone: images(spec).filter((l) => l.status !== "pending").length,
        headline: String(spec.brief?.headline ?? ""), archetype: String(spec.brief?.archetype ?? ""), colorway: String(spec.brief?.colorway ?? "") });
      if (!placed.has(spec.id)) {
        placed.add(spec.id);
        mutate((d) => { d.boards.push({ ...structuredClone(spec), job_id }); }, { history: false });
        if (i === 0) setUi({ activeBoardId: spec.id, selection: null });
      } else if (boardById(spec.id)) {
        mutateBoard(spec.id, (b) => mergeFromServer(b, spec), { history: false });
      }
      const res = results[i];
      if (res && !finished.has(spec.id)) {
        finished.add(spec.id);
        v.result = res;
        mutateBoard(spec.id, (b) => {
          mergeFromServer(b, spec);
          Object.assign(b, { final_url: res.final_url, preview_url: res.thumb_url, qa: res.qa, summary: res.summary, checks: res.checks });
        }, { history: false });
      }
    });
  };

  try {
    const result = await pollJob<DesignProgress, { specs: DesignSpec[]; results: (DesignResult | null)[] }>(job_id, (p) => {
      view.stage = p.stage;
      view.events = p.events;
      sync(p.specs ?? [], p.results ?? []);
      emit();
    });
    sync(result.specs, result.results);
    view.status = "done";
    view.stage = "done";
  } catch (e) {
    view.status = "error";
    view.error = e instanceof Error ? e.message : String(e);
  }
  emit();
  return view;
}

/** Edit layers of a board: the AI plans, the backend renders new pixels, ops apply to the document. */
export async function runEdit(boardId: string, instruction: string, targetIds: string[], pointer: { x: number; y: number } | null,
  onStage: (s: string) => void): Promise<EditResult & { applied: string[] }> {
  const board = boardById(boardId);
  if (!board) throw new Error("Board not found");
  const infos = layerInfos(board);
  const ids = new Set(targetIds);
  const targets = targetIds.length
    ? targetIds.map((id) => findLayer(board, id)).filter((l): l is Layer => !!l).map((l) => layerInfo(l))
    : infos;
  onStage("Planning the edit");
  const { job_id } = await api.createEdit({ instruction, board: boardInfo(board), targets,
    context: infos.filter((c) => !ids.has(c.id)), pointer });
  const result = await pollJob<{ stage: string }, EditResult>(job_id, (p) => {
    if (p.stage === "generating") onStage("Rendering new pixels for this layer");
  }, 500);
  onStage("Applying");
  let applied: string[] = [];
  mutateBoard(boardId, (b) => { applied = applyOps(b, result.ops); });
  return { ...result, applied };
}

export async function runBrandDna(boardId: string, onStage: (s: string) => void): Promise<DnaReport> {
  const board = boardById(boardId);
  if (!board) throw new Error("Board not found");
  onStage("Auditing layers and pixels against the brand guidelines");
  const { job_id } = await api.brandDna(board);
  return pollJob<{ stage: string }, DnaReport>(job_id);
}

export function applyDnaFixes(boardId: string, report: DnaReport, ids?: string[]): number {
  const fixed = report.findings.filter((f) => f.fix && (!ids || ids.includes(f.id)));
  if (!fixed.length) return 0;
  const fixedLayers = new Set(fixed.map((f) => f.layer_id).filter(Boolean));
  mutate((d) => {
    const b = d.boards.find((x) => x.id === boardId);
    if (b) applyOps(b, fixed.map((f) => f.fix!));
    // Pins of fixed issues are now stale: clear them (all of them after "Fix all"; re-check re-pins).
    d.comments = d.comments.filter((c) => !(c.boardId === boardId && c.kind === "dna" && (!ids || (c.layerId && fixedLayers.has(c.layerId)))));
  });
  return fixed.length;
}

export function pinDnaFindings(boardId: string, report: DnaReport): number {
  const board = boardById(boardId);
  if (!board) return 0;
  const pins = report.findings.filter((f) => f.box);
  mutate((d) => {
    d.comments = d.comments.filter((c) => !(c.boardId === boardId && c.kind === "dna"));
    for (const f of pins) {
      d.comments.push({ id: uid("c"), boardId, kind: "dna", severity: f.severity, status: "open", layerId: f.layer_id ?? null,
        x: (f.box![0] + f.box![2] / 2) * board.width, y: (f.box![1] + f.box![3] / 2) * board.height,
        thread: [{ author: "crux", text: `🧬 ${f.issue} → ${f.suggestion}`, at: Date.now() }] });
    }
  });
  return pins.length;
}

/** A canvas comment: edit the layer under the pin and reply in the thread. */
export async function runCommentEdit(draft: { boardId: string; x: number; y: number; layerId: string | null }, text: string,
  onDone?: (ok: boolean, msg: string) => void) {
  const id = uid("c");
  mutate((d) => { d.comments.push({ id, boardId: draft.boardId, x: draft.x, y: draft.y, layerId: draft.layerId, kind: "edit",
    status: "working", thread: [{ author: "designer", text, at: Date.now() }] }); });
  setUi({ openComment: id, tool: getState().tool });
  const reply = (status: "resolved" | "failed", msg: string) => mutate((d) => {
    const c = d.comments.find((k) => k.id === id);
    if (c) { c.status = status; c.thread.push({ author: "crux", text: msg, at: Date.now() }); }
  }, { history: false });
  try {
    const r = await runEdit(draft.boardId, text, draft.layerId ? [draft.layerId] : [], { x: draft.x, y: draft.y }, () => undefined);
    const msg = r.message + (r.notes.length ? ` (${r.notes.join("; ")})` : "");
    reply("resolved", msg);
    onDone?.(true, msg);
  } catch (e) {
    const msg = `Couldn't apply that: ${e instanceof Error ? e.message : String(e)}`;
    reply("failed", msg);
    onDone?.(false, msg);
  }
}

// ---- intent ----------------------------------------------------------------------
const WORDS: Record<string, number> = { two: 2, three: 3, four: 4, couple: 2 };

export function detectCount(text: string): number | null {
  const m = text.match(/\b(\d|two|three|four|couple)\s+(?:of\s+)?(?:different\s+|more\s+|new\s+|alternative\s+)?(images?|designs?|variations?|versions?|options?|ads?|alternatives?|takes?)\b/i);
  if (m) return Math.max(1, Math.min(4, Number(m[1]) || WORDS[m[1].toLowerCase()] || 4));
  if (/\b(variations?|alternatives?|like this|similar to this|versions)\b/i.test(text)) return 4;
  return null;
}

export type Intent = { kind: "create"; count: number } | { kind: "variations"; count: number } | { kind: "edit"; scope: "layer" | "board" };

export function inferIntent(text: string, hasBoard: boolean, selection: string | null): Intent {
  const count = detectCount(text);
  const wantsNew = /\bnew (design|ad|image|banner|poster|post|board)\b/i.test(text);
  if (hasBoard && count && count > 1) return { kind: "variations", count };
  if (hasBoard && selection && !wantsNew) return { kind: "edit", scope: "layer" };
  if (hasBoard && !wantsNew && /\b(make|change|replace|move|swap|recolou?r|bigger|smaller|remove|add|edit|update|fix|shorten|rewrite)\b/i.test(text)) {
    return { kind: "edit", scope: "board" };
  }
  return { kind: "create", count: count ?? 1 };
}
