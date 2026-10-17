// Brand fonts: loaded from the backend's own TTF files (the same files the server compositor
// measures with), so text wraps and sits on exactly the same baselines in the editor.

export interface FontDef { family: string; weight: string; file: string; line_height: number; letter_spacing: number }
export interface BrandFonts {
  fonts: Record<string, FontDef>;
  files: Record<string, string>;
  metrics: Record<string, { asc: number; desc: number }>;
}

let brand: BrandFonts | null = null;
let ready: Promise<void> | null = null;
const ctx = document.createElement("canvas").getContext("2d")!;

export function loadBrandFonts(b: BrandFonts): Promise<void> {
  brand = b;
  ready ??= Promise.all(Object.entries(b.fonts).map(async ([key, f]) => {
    const face = new FontFace(f.family, `url(${b.files[key]})`, { weight: f.weight, style: "normal" });
    document.fonts.add(await face.load());
  })).then(() => undefined);
  return ready;
}

export function fontKey(family?: string | null, weight?: string | null, fallback = "body"): string {
  if (!brand || !family) return fallback;
  const keys = Object.keys(brand.fonts).filter((k) => brand!.fonts[k].family === family);
  return keys.find((k) => brand!.fonts[k].weight === String(weight ?? "")) ?? keys[0] ?? fallback;
}

export function metricsFor(key: string): { asc: number; desc: number } {
  return brand?.metrics[key] ?? { asc: 0.95, desc: 0.25 };
}

export function brandFamilies(): string[] {
  return brand ? [...new Set(Object.values(brand.fonts).map((f) => f.family))] : ["Barlow Condensed", "Barlow"];
}

export function weightsFor(family: string): string[] {
  return brand ? Object.values(brand.fonts).filter((f) => f.family === family).map((f) => f.weight) : ["400"];
}

function measure(text: string, family: string, weight: string, size: number): number {
  ctx.font = `${weight} ${size}px "${family}"`;
  return ctx.measureText(text).width;
}

/** Same greedy wrap as the backend (explicit line breaks respected, then width). */
export function wrap(text: string, family: string, weight: string, size: number, maxW: number): string[] {
  const lines: string[] = [];
  for (const para of text.split("\n")) {
    const words = para.split(/\s+/).filter(Boolean);
    if (!words.length) { lines.push(""); continue; }
    let cur = words[0];
    for (const w of words.slice(1)) {
      const trial = `${cur} ${w}`;
      if (measure(trial, family, weight, size) <= maxW + 0.5) cur = trial;
      else { lines.push(cur); cur = w; }
    }
    lines.push(cur);
  }
  return lines;
}

export function textWidth(text: string, family: string, weight: string, size: number): number {
  return measure(text, family, weight, size);
}
