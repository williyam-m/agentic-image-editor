// Backend client.
import type { DesignSpec, EditOp } from "../model/types";

export interface JobEvent { t: number; text: string; kind: "info" | "stage" | "check" | "error" }
export interface DesignResult {
  checks: { rule: string; status: string; detail: string }[];
  summary: { score: number; passed: number; fixed: number; warnings: number };
  qa: { score: number | null; strengths: string[]; issues: string[] };
  final_url: string; thumb_url: string;
}
export interface DesignProgress {
  stage: string; events: JobEvent[]; specs: DesignSpec[]; results: (DesignResult | null)[]; version: number; done: boolean;
}
export interface JobResponse<P, R> { status: string; progress: P | null; result?: R; error?: string }
export interface EditResult { message: string; ops: EditOp[]; notes: string[] }
export interface DnaFinding {
  id: string; dimension: string; severity: "high" | "medium" | "low"; issue: string; suggestion: string;
  layer_id?: string | null; layer_name?: string | null; box?: number[] | null; fix?: EditOp | null;
  source: "measured" | "visual";
}
export interface DnaReport {
  score: number; scores: Record<string, number>; findings: DnaFinding[]; fixable: number;
  strengths: string[]; summary: string; verdict: string;
}
export interface AssetInfo {
  id: string; category: string; name: string; width: number; height: number; description: string; tags: string[];
  url: string; vectorUrl: string | null; hasAlpha: boolean; colors: string[]; file: string;
}
export interface ReferenceInfo {
  id: string; headline: string; cta: string; archetype: string; colorway: string; visual: string; copy_angle: string; url: string;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not json */ }
    throw new Error(`${detail} (${r.status})`);
  }
  return r.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) => json<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => json<Record<string, unknown>>("/api/health"),
  assets: (category?: string, q?: string) =>
    json<AssetInfo[]>(`/api/brand/assets?${new URLSearchParams({ ...(category ? { category } : {}), ...(q ? { q } : {}) })}`),
  references: () => json<ReferenceInfo[]>("/api/references"),
  createDesign: (body: Record<string, unknown>) => post<{ job_id: string }>("/api/designs", body),
  createEdit: (body: Record<string, unknown>) => post<{ job_id: string }>("/api/edits", body),
  brandDna: (spec: DesignSpec) => post<{ job_id: string }>("/api/brand-dna", { spec }),
  render: (spec: DesignSpec, scale = 1) => post<{ url: string }>("/api/render", { spec, scale }),
  job: <P, R>(id: string) => json<JobResponse<P, R>>(`/api/jobs/${id}`),
};

export async function uploadFile(file: File): Promise<{ url: string; file: string; width: number; height: number; transparent: boolean }> {
  const b64 = await new Promise<string>((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result));
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
  return post("/api/uploads", { image: b64, name: file.name });
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function pollJob<P, R>(id: string, onProgress?: (p: P) => void, every = 600): Promise<R> {
  for (;;) {
    const r = await api.job<P, R>(id);
    if (r.progress && onProgress) onProgress(r.progress);
    if (r.status === "completed" && r.result !== undefined) return r.result;
    if (r.status !== "running") throw new Error(r.error ?? "Job failed");
    await sleep(every);
  }
}
