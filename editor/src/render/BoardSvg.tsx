// Renders a layered DesignSpec as native SVG — a 1:1 mirror of the backend compositor
// (crux/design/compose.py): same geometry, fonts, text baselines, masks, vectors and shadows.
import { memo, useMemo, type ReactNode } from "react";
import type { DesignSpec, Layer } from "../model/types";
import { bounds } from "../model/layers";
import { fontKey, metricsFor, wrap } from "./fonts";
import { useVector } from "./vectors";

interface Props {
  spec: DesignSpec;
  uid: string;                     // unique prefix for <defs> ids (canvas vs thumbnails)
  width?: number | string;
  height?: number | string;
  fontsVersion?: number;           // re-render once brand fonts are loaded
  editingTextId?: string | null;   // hide the text being edited inline
  className?: string;
}

function VectorShape({ l, color }: { l: Layer; color?: string }) {
  const v = useVector(l.svg ? null : l.svg_url, l.svg);
  if (!v) return null;
  return (
    <svg x={l.x} y={l.y} width={l.w} height={l.h} viewBox={v.viewBox} preserveAspectRatio="none" overflow="visible">
      {v.paths.map((p, i) =>
        p.filled ? (
          <path key={i} d={p.d} fill={color ?? l.fill ?? "#000856"} />
        ) : (
          <path key={i} d={p.d} fill="none" stroke={color ?? l.stroke ?? p.stroke ?? "#1F65D6"}
            strokeWidth={l.stroke_width || p.strokeWidth || 2} strokeLinecap={(p.linecap ?? "round") as "round"}
            strokeLinejoin={(p.linejoin ?? "round") as "round"} />
        ))}
    </svg>
  );
}

function TextShape({ l }: { l: Layer }) {
  const key = fontKey(l.font_family, l.font_weight, l.font ?? "body");
  const size = l.font_size ?? 24;
  const lh = (l.line_height ?? 1.2) * size;
  const { asc, desc } = metricsFor(key);
  const family = l.font_family ?? "Barlow";
  const weight = l.font_weight ?? "400";
  const lines = wrap(l.text ?? "", family, weight, size, l.w);
  const anchor = l.align === "center" ? "middle" : l.align === "right" ? "end" : "start";
  const x = l.align === "center" ? l.x + l.w / 2 : l.align === "right" ? l.x + l.w : l.x;
  return (
    <text fontFamily={`"${family}"`} fontWeight={weight} fontSize={size} fill={l.color ?? "#000856"} textAnchor={anchor}
      style={{ whiteSpace: "pre" }}>
      {lines.map((line, i) => (
        <tspan key={i} x={x} y={l.y + i * lh + (lh - (asc + desc) * size) / 2 + asc * size}>{line}</tspan>
      ))}
    </text>
  );
}

function Placeholder({ l, uid }: { l: Layer; uid: string }) {
  const failed = l.status === "failed";
  return (
    <g>
      <rect x={l.x} y={l.y} width={l.w} height={l.h} fill={failed ? "#fde8e4" : `url(#${uid}-shimmer)`}
        opacity={l.transparent ? 0.7 : 1} />
      <text x={l.x + l.w / 2} y={l.y + l.h / 2} textAnchor="middle" fontFamily="Geist, sans-serif" fontSize={Math.max(14, Math.min(28, l.w / 16))}
        fill={failed ? "#d23a2a" : "#8a8a8a"}>{failed ? "Generation failed — ask Crux to retry" : "✦ Generating…"}</text>
    </g>
  );
}

function maskShape(m: Layer): ReactNode {
  if (m.kind === "vector") return <VectorShape l={m} color="#fff" />;
  if (m.kind === "ellipse") return <ellipse cx={m.x + m.w / 2} cy={m.y + m.h / 2} rx={m.w / 2} ry={m.h / 2} fill="#fff" />;
  return <rect x={m.x} y={m.y} width={m.w} height={m.h} rx={m.radius ?? 0} fill="#fff" />;
}

function LayerNode({ l, uid, editingTextId }: { l: Layer; uid: string; editingTextId?: string | null }): ReactNode {
  if (l.hidden) return null;
  let node: ReactNode = null;
  switch (l.kind) {
    case "rect":
      node = <rect x={l.x} y={l.y} width={l.w} height={l.h} rx={l.radius ?? 0} fill={l.fill ?? "#fff"}
        filter={l.shadow ? `url(#${uid}-shadow)` : undefined} />;
      break;
    case "ellipse":
      node = <ellipse cx={l.x + l.w / 2} cy={l.y + l.h / 2} rx={l.w / 2} ry={l.h / 2} fill={l.fill ?? "#fff"} />;
      break;
    case "text":
      node = editingTextId === l.id ? null : <TextShape l={l} />;
      break;
    case "image":
      node = l.status === "pending" || l.status === "failed" || !l.src
        ? <Placeholder l={l} uid={uid} />
        : <image href={l.src} x={l.x} y={l.y} width={l.w} height={l.h} preserveAspectRatio="none" />;
      break;
    case "vector":
      node = <VectorShape l={l} />;
      break;
    case "group":
      node = <g>{(l.children ?? []).map((c) => <LayerNode key={c.id} l={c} uid={uid} editingTextId={editingTextId} />)}</g>;
      break;
    case "mask": {
      const [m, ...content] = l.children ?? [];
      if (!m) return null;
      const id = `${uid}-mask-${l.id}`;
      node = (
        <g>
          <defs>
            <mask id={id} maskUnits="userSpaceOnUse" x={-1e5} y={-1e5} width={2e5} height={2e5}>{maskShape(m)}</mask>
          </defs>
          <g mask={`url(#${id})`}>{content.map((c) => <LayerNode key={c.id} l={c} uid={uid} editingTextId={editingTextId} />)}</g>
        </g>
      );
      break;
    }
  }
  if (!node) return null;
  const b = bounds(l);
  const transform = l.rotation ? `rotate(${l.rotation} ${b.x + b.w / 2} ${b.y + b.h / 2})` : undefined;
  return <g data-layer={l.id} opacity={l.opacity ?? 1} transform={transform}>{node}</g>;
}

export const BoardSvg = memo(function BoardSvg({ spec, uid, width, height, editingTextId, className }: Props) {
  const defs = useMemo(() => (
    <defs>
      <filter id={`${uid}-shadow`} x="-20%" y="-20%" width="140%" height="160%">
        <feDropShadow dx="0" dy="8" stdDeviation="14" floodColor="#000856" floodOpacity="0.18" />
      </filter>
      <linearGradient id={`${uid}-shimmer`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#e2e8f0" />
        <stop offset="0.5" stopColor="#f1f4f8">
          <animate attributeName="offset" values="0;1;0" dur="1.6s" repeatCount="indefinite" />
        </stop>
        <stop offset="1" stopColor="#e2e8f0" />
      </linearGradient>
      <clipPath id={`${uid}-clip`}><rect width={spec.width} height={spec.height} /></clipPath>
    </defs>
  ), [uid, spec.width, spec.height]);
  return (
    <svg className={className} xmlns="http://www.w3.org/2000/svg" width={width ?? spec.width} height={height ?? spec.height}
      viewBox={`0 0 ${spec.width} ${spec.height}`}>
      {defs}
      <g clipPath={`url(#${uid}-clip)`}>
        <rect width={spec.width} height={spec.height} fill={spec.background} />
        {spec.layers.map((l) => <LayerNode key={l.id} l={l} uid={uid} editingTextId={editingTextId} />)}
      </g>
    </svg>
  );
});
