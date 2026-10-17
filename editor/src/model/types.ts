// The layered design model — identical to the backend DesignSpec, so the editor canvas,
// the server compositor (chat previews, exports) and the AI planners all share one source of truth.

export interface Layer {
  id: string;
  name: string;
  kind: "rect" | "ellipse" | "text" | "image" | "vector" | "group" | "mask";
  role: string;
  x: number; y: number; w: number; h: number;
  rotation?: number; opacity?: number; hidden?: boolean; locked?: boolean;
  fill?: string | null; radius?: number; stroke?: string | null; stroke_width?: number; shadow?: boolean;
  text?: string | null; font?: string | null; font_family?: string | null; font_weight?: string | null;
  font_size?: number | null; line_height?: number | null; letter_spacing?: number | null;
  color?: string | null; align?: "left" | "center" | "right" | null;
  src?: string | null; file?: string | null; asset_id?: string | null; prompt?: string | null;
  transparent?: boolean; fit?: "cover" | "contain"; anchor?: string;
  status?: "ready" | "pending" | "failed";
  compliance?: { ok?: boolean; verified?: boolean; attempts?: number; blocking?: string[] } | null;
  svg_url?: string | null; svg?: string | null;
  children?: Layer[] | null;
}

export interface Check { rule: string; status: "pass" | "fixed" | "warn"; detail: string; layer?: string | null }

export interface DesignSpec {
  id: string; name: string; format: string; width: number; height: number; background: string;
  layers: Layer[]; brief: Record<string, unknown>; checks: Check[]; preview_url?: string | null; variant: number;
  // editor bookkeeping
  job_id?: string | null;
  final_url?: string | null;
  qa?: { score: number | null; strengths: string[]; issues: string[] } | null;
  summary?: { score: number; passed: number; fixed: number; warnings: number } | null;
}

export interface CommentReply { author: "designer" | "crux"; text: string; at: number }

export interface CanvasComment {
  id: string;
  boardId: string;
  x: number; y: number;            // board coordinates of the pin
  layerId?: string | null;         // layer under the pin
  kind: "edit" | "dna";
  severity?: "high" | "medium" | "low";
  thread: CommentReply[];
  status: "open" | "working" | "resolved" | "failed";
}

export interface Doc {
  id: string;
  name: string;
  boards: DesignSpec[];
  comments: CanvasComment[];
  updated?: number;
}

/** Compiled edit operations from the backend (board-relative coordinates, layer-id targets). */
export type EditOp =
  | { op: "update"; target: string; props: Record<string, unknown> }
  | { op: "image"; target: string; src: string; file?: string; prompt?: string; x?: number; y?: number; w?: number; h?: number; asset_id?: string; name?: string }
  | { op: "vector"; target: string; svg_url: string; fill?: string; asset_id?: string; x: number; y: number; w: number; h: number }
  | { op: "remove"; target: string }
  | { op: "arrange"; target: string; to: "front" | "back" }
  | { op: "add"; layer: Layer };

/** Per-layer facts sent to the AI planners (same shape the backend's docs.layer_infos produces). */
export interface LayerInfo {
  id: string; name: string; type: string; role?: string | null; parent_id?: string | null;
  x: number; y: number; w: number; h: number; rotation?: number;
  text?: string | null; font_size?: number | null; font_family?: string | null; font_weight?: string | null;
  color?: string | null; fill?: string | null; asset_id?: string | null;
  image?: { src?: string | null; file?: string | null; prompt?: string | null; transparent?: boolean } | null;
}

export interface BoardInfo {
  id: string; name: string; width: number; height: number; background?: string;
  brief?: Record<string, unknown> | null; is_crux: boolean; x?: number; y?: number;
}

export type Tool = "select" | "text" | "rect" | "comment" | "hand";
