// Vector layers (blooms, waves, wordmark, sparklines): parsed once into paths and drawn natively
// in the board SVG, recoloured by the layer's fill.
import { useEffect, useState } from "react";

export interface VectorPath { d: string; stroke?: string | null; strokeWidth?: number | null; linecap?: string | null; linejoin?: string | null; filled: boolean }
export interface VectorData { viewBox: string; paths: VectorPath[] }

const cache = new Map<string, VectorData>();
const pending = new Map<string, Promise<VectorData>>();

export function parseSvg(text: string): VectorData {
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  const root = doc.documentElement;
  const vb = root.getAttribute("viewBox") ?? `0 0 ${parseFloat(root.getAttribute("width") ?? "100")} ${parseFloat(root.getAttribute("height") ?? "100")}`;
  const paths = [...doc.querySelectorAll("path")].map((p) => ({
    d: p.getAttribute("d") ?? "",
    stroke: p.getAttribute("stroke"),
    strokeWidth: p.getAttribute("stroke-width") ? parseFloat(p.getAttribute("stroke-width")!) : null,
    linecap: p.getAttribute("stroke-linecap"),
    linejoin: p.getAttribute("stroke-linejoin"),
    filled: (p.getAttribute("fill") ?? "#000") !== "none",
  }));
  return { viewBox: vb, paths };
}

export function loadVector(url: string): Promise<VectorData> {
  if (cache.has(url)) return Promise.resolve(cache.get(url)!);
  if (!pending.has(url)) {
    pending.set(url, fetch(url).then((r) => r.text()).then((t) => {
      const v = parseSvg(t);
      cache.set(url, v);
      return v;
    }));
  }
  return pending.get(url)!;
}

export function useVector(url?: string | null, inline?: string | null): VectorData | null {
  const [v, setV] = useState<VectorData | null>(() => (inline ? parseSvg(inline) : url ? cache.get(url) ?? null : null));
  useEffect(() => {
    if (inline) { setV(parseSvg(inline)); return; }
    if (!url) return;
    let alive = true;
    loadVector(url).then((d) => alive && setV(d)).catch(() => undefined);
    return () => { alive = false; };
  }, [url, inline]);
  return v;
}
