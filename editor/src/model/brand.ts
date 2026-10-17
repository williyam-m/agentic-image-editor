// Brand kit data from the backend (palette, fonts, metrics, insights), loaded once.
import { useSyncExternalStore } from "react";

export interface BrandData {
  palette: Record<string, string>;
  fonts: Record<string, { family: string; weight: string; file: string; line_height: number; letter_spacing: number }>;
  font_files: Record<string, string>;
  font_metrics: Record<string, { asc: number; desc: number }>;
  insights: { voice?: string[]; headline_formulas?: string[]; cta_bank?: string[]; summary?: string };
  counts: Record<string, number>;
}

let data: BrandData | null = null;
const subs = new Set<() => void>();

export async function loadBrand(): Promise<BrandData> {
  const r = await fetch("/api/brand");
  data = (await r.json()) as BrandData;
  subs.forEach((s) => s());
  return data;
}

export function useBrand(): BrandData | null {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => subs.delete(cb); }, () => data);
}

export const PRIMARY = ["navy", "blue", "sky", "sky_soft", "white", "paper"];
export const isPalette = (hex?: string | null) =>
  !!hex && !!data && Object.values(data.palette).some((v) => v.toUpperCase() === hex.toUpperCase());
