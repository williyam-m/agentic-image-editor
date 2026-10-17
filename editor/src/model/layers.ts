// Pure helpers over the layer tree: lookup, hit-testing, edits.
import type { BoardInfo, DesignSpec, EditOp, Layer, LayerInfo } from "./types";

export const uid = (p = "l") => `${p}_${Math.random().toString(36).slice(2, 12)}`;

export function walk(layers: Layer[]): Layer[] {
  return layers.flatMap((l) => [l, ...walk(l.children ?? [])]);
}

export function findLayer(spec: DesignSpec, id: string): Layer | null {
  return walk(spec.layers).find((l) => l.id === id) ?? null;
}

/** The array that contains ``id`` (top level or a group's children). */
export function siblingsOf(spec: DesignSpec, id: string): Layer[] | null {
  const search = (arr: Layer[]): Layer[] | null => {
    if (arr.some((l) => l.id === id)) return arr;
    for (const l of arr) {
      const r = l.children ? search(l.children) : null;
      if (r) return r;
    }
    return null;
  };
  return search(spec.layers);
}

export function parentOf(spec: DesignSpec, id: string): Layer | null {
  return walk(spec.layers).find((l) => (l.children ?? []).some((c) => c.id === id)) ?? null;
}

/** Bounding box of a layer (groups: union of children). */
export function bounds(l: Layer): { x: number; y: number; w: number; h: number } {
  if (l.kind === "group" && l.children?.length) {
    const bs = l.children.map(bounds);
    const x0 = Math.min(...bs.map((b) => b.x)), y0 = Math.min(...bs.map((b) => b.y));
    const x1 = Math.max(...bs.map((b) => b.x + b.w)), y1 = Math.max(...bs.map((b) => b.y + b.h));
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  return { x: l.x, y: l.y, w: l.w, h: l.h };
}

const inside = (l: Layer, x: number, y: number) => {
  const b = bounds(l);
  return x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h;
};

/**
 * The most specific visible layer under a point (topmost first). Inside a masked photo the
 * designer means the photo, not the mask shape; the board background is only hit last.
 */
export function hitTest(spec: DesignSpec, x: number, y: number, deep = true): Layer | null {
  const visit = (arr: Layer[]): Layer | null => {
    for (const l of [...arr].reverse()) {
      if (l.hidden || !inside(l, x, y)) continue;
      if (l.kind === "mask") {
        const content = (l.children ?? []).slice(1).reverse().find((c) => !c.hidden && inside(c, x, y));
        return deep ? content ?? l : l;
      }
      if (l.kind === "group") return deep ? visit(l.children ?? []) ?? l : l;
      if (l.role === "background") continue;
      return l;
    }
    return null;
  };
  return visit(spec.layers) ?? spec.layers.find((l) => l.role === "background" && !l.hidden) ?? null;
}

export function moveLayer(l: Layer, dx: number, dy: number): void {
  l.x += dx;
  l.y += dy;
  for (const c of l.children ?? []) moveLayer(c, dx, dy);
}

/** Resize a layer's box; groups/masks scale their children proportionally. */
export function resizeLayer(l: Layer, x: number, y: number, w: number, h: number): void {
  const b = bounds(l);
  if ((l.kind === "group" || l.kind === "mask") && l.children?.length) {
    const sx = w / Math.max(b.w, 1), sy = h / Math.max(b.h, 1);
    const scale = (c: Layer) => {
      c.x = x + (c.x - b.x) * sx;
      c.y = y + (c.y - b.y) * sy;
      c.w *= sx;
      c.h *= sy;
      if (c.kind === "text" && c.font_size) c.font_size = Math.max(6, Math.round(c.font_size * Math.min(sx, sy)));
      for (const k of c.children ?? []) scale(k);
    };
    for (const c of l.children) scale(c);
  }
  l.x = x; l.y = y; l.w = Math.max(1, w); l.h = Math.max(1, h);
}

export function layerInfo(l: Layer, parent: string | null = null): LayerInfo {
  const type = { text: "text", rect: "rect", ellipse: "ellipse", image: "image", vector: "path", group: "group", mask: "group" }[l.kind];
  const b = bounds(l);
  const info: LayerInfo = { id: l.id, name: l.name, type, role: l.role, parent_id: parent, x: Math.round(b.x),
    y: Math.round(b.y), w: Math.round(b.w), h: Math.round(b.h), rotation: l.rotation ?? 0, asset_id: l.asset_id ?? null };
  if (l.kind === "text") Object.assign(info, { text: l.text, font_size: l.font_size, font_family: l.font_family, font_weight: l.font_weight, color: l.color });
  else if (l.kind === "image") info.image = { src: l.src, file: l.file, prompt: l.prompt, transparent: !!l.transparent };
  else info.fill = l.fill ?? l.stroke ?? null;
  return info;
}

export function layerInfos(spec: DesignSpec): LayerInfo[] {
  const out: LayerInfo[] = [];
  const rec = (arr: Layer[], parent: string | null) => {
    for (const l of arr) {
      if (l.hidden) continue;
      out.push(layerInfo(l, parent));
      rec(l.children ?? [], l.id);
    }
  };
  rec(spec.layers, null);
  return out;
}

export function boardInfo(spec: DesignSpec): BoardInfo {
  return { id: spec.id, name: spec.name, width: spec.width, height: spec.height, background: spec.background,
    brief: Object.keys(spec.brief ?? {}).length ? spec.brief : null, is_crux: Object.keys(spec.brief ?? {}).length > 0 };
}

/** Apply backend edit operations to a spec in place. Returns human-readable results. */
export function applyOps(spec: DesignSpec, ops: EditOp[]): string[] {
  const results: string[] = [];
  for (const op of ops) {
    if (op.op === "add") {
      spec.layers.push({ ...op.layer, id: op.layer.id && !findLayer(spec, op.layer.id) ? op.layer.id : uid() });
      results.push(`added ${op.layer.name}`);
      continue;
    }
    if (op.target === spec.id && op.op === "update") {  // the board itself
      if (op.props.fill) {
        spec.background = String(op.props.fill);
        const bg = spec.layers.find((l) => l.role === "background");
        if (bg) bg.fill = spec.background;
      }
      results.push("updated board background");
      continue;
    }
    const l = findLayer(spec, op.target);
    if (!l) continue;
    if (op.op === "update") {
      const p = op.props;
      if (typeof p.text === "string") l.text = p.text;
      if (p.font_size) l.font_size = Number(p.font_size);
      if (p.font_family) { l.font_family = String(p.font_family); if (p.font_weight) l.font_weight = String(p.font_weight); }
      if (p.color) l.color = String(p.color);
      if (p.fill) {
        if (l.kind === "text") l.color = String(p.fill);
        else if (l.kind === "group" || l.kind === "mask") for (const c of walk(l.children ?? [])) { if (c.kind !== "text" && c.kind !== "image") c.fill = String(p.fill); }
        else l.fill = String(p.fill);
      }
      if (p.w !== undefined && p.h !== undefined) resizeLayer(l, p.x !== undefined ? Number(p.x) : l.x, p.y !== undefined ? Number(p.y) : l.y, Number(p.w), Number(p.h));
      else if (p.x !== undefined || p.y !== undefined) moveLayer(l, p.x !== undefined ? Number(p.x) - bounds(l).x : 0, p.y !== undefined ? Number(p.y) - bounds(l).y : 0);
      if (p.rotation !== undefined) l.rotation = Number(p.rotation);
      if (p.opacity !== undefined) l.opacity = Number(p.opacity);
      results.push(`updated ${l.name}`);
    } else if (op.op === "image") {
      Object.assign(l, { src: op.src, file: op.file ?? l.file, prompt: op.prompt ?? l.prompt, status: "ready" });
      if (op.asset_id) l.asset_id = op.asset_id;
      if (op.name) l.name = op.name;
      if (op.w !== undefined && op.h !== undefined) Object.assign(l, { x: op.x ?? l.x, y: op.y ?? l.y, w: op.w, h: op.h });
      results.push(`new image in ${l.name}`);
    } else if (op.op === "vector") {
      Object.assign(l, { svg_url: op.svg_url, svg: null, fill: op.fill ?? l.fill, asset_id: op.asset_id ?? l.asset_id,
        x: op.x, y: op.y, w: op.w, h: op.h });
      results.push(`swapped ${l.name}`);
    } else if (op.op === "remove") {
      const sib = siblingsOf(spec, l.id);
      if (sib) sib.splice(sib.indexOf(l), 1);
      results.push(`removed ${l.name}`);
    } else if (op.op === "arrange") {
      const sib = siblingsOf(spec, l.id);
      if (sib) {
        sib.splice(sib.indexOf(l), 1);
        if (op.to === "front") sib.push(l);
        else sib.splice(sib[0]?.role === "background" ? 1 : 0, 0, l);
      }
      results.push(`moved ${l.name} to ${op.to}`);
    }
  }
  return results;
}

/** Merge generated pixels / brand-guard fixes from the backend into a (possibly edited) board. */
export function mergeFromServer(local: DesignSpec, remote: DesignSpec): void {
  for (const r of walk(remote.layers)) {
    const l = findLayer(local, r.id);
    if (!l) continue;
    if (r.kind === "image" && l.status === "pending" && r.status !== "pending") {
      Object.assign(l, { status: r.status, src: r.src, file: r.file, x: r.x, y: r.y, w: r.w, h: r.h, compliance: r.compliance, name: r.name });
    }
    if (r.kind === "text" && r.color && l.color !== r.color) l.color = r.color;
    if ((r.kind === "vector" || r.kind === "rect") && r.fill && l.fill !== r.fill) l.fill = r.fill;
  }
  for (const r of remote.layers) {  // layers the guard added (e.g. "Terms apply.")
    if (!findLayer(local, r.id)) local.layers.push(structuredClone(r));
  }
}
