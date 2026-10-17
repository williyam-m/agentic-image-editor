import { useEffect, useMemo, useState } from "react";
import { api, type AssetInfo } from "./api";
import { useBrand } from "../model/brand";
import { activeBoard, mutateBoard, setUi } from "../model/store";
import { uid } from "../model/layers";
import type { Layer } from "../model/types";

const CATEGORIES: [string, string][] = [
  ["bloom", "Blooms"], ["charm", "Charms"], ["illustration", "Illustrations"], ["device", "Product UI"],
  ["background", "Backgrounds"], ["logo", "Logo"],
];

export function BrandTab({ notify }: { notify: (msg: string, tone?: "ok" | "err") => void }) {
  const brand = useBrand();
  const [cat, setCat] = useState("bloom");
  const [q, setQ] = useState("");
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  useEffect(() => {
    const t = setTimeout(() => api.assets(cat, q || undefined).then(setAssets).catch(() => setAssets([])), 150);
    return () => clearTimeout(t);
  }, [cat, q]);
  const palette = useMemo(() => Object.entries(brand?.palette ?? {}), [brand]);

  const insert = (a: AssetInfo) => {
    const b = activeBoard();
    if (!b) { notify("Create or open a board first", "err"); return; }
    const scale = Math.min(1, (b.width * 0.4) / Math.max(a.width, a.height));
    const w = Math.round(a.width * scale), h = Math.round(a.height * scale);
    const x = Math.round((b.width - w) / 2), y = Math.round((b.height - h) / 2);
    const id = uid("asset");
    const layer: Layer = a.vectorUrl
      ? { id, name: a.name, kind: "vector", role: a.category, x, y, w, h, fill: a.category === "logo" ? "#000856" : "#1F65D6", svg_url: a.vectorUrl, asset_id: a.id }
      : { id, name: a.name, kind: "image", role: a.category, x, y, w, h, src: a.url, file: a.file, asset_id: a.id, transparent: a.hasAlpha, status: "ready" };
    mutateBoard(b.id, (bd) => { bd.layers.push(layer); });
    setUi({ selection: id });
    notify(`Added “${a.name}”`);
  };

  return (
    <div className="tab-body">
      <section className="card">
        <h3>Palette</h3>
        <div className="swatches">
          {palette.map(([name, hex]) => (
            <button key={name} className="swatch" onClick={() => { navigator.clipboard?.writeText(hex); notify(`${hex} copied`); }} title="Copy hex">
              <span style={{ background: hex }} /><b>{name.replace("_", " ")}</b><small className="mono">{hex}</small>
            </button>
          ))}
        </div>
        <div className="type-specimen">
          <div className="spec-headline">Run your business, not your books.</div>
          <div className="spec-body">Barlow Condensed Bold for headlines · Barlow for body &amp; CTAs</div>
        </div>
      </section>
      {brand?.insights?.summary ? (
        <section className="card">
          <h3>AI brand insights</h3>
          <p className="muted">{brand.insights.summary}</p>
          <details>
            <summary>Voice &amp; headline formulas</summary>
            <ul className="bullets">{brand.insights.voice?.map((v) => <li key={v}>{v}</li>)}</ul>
            <ul className="bullets">{brand.insights.headline_formulas?.map((v) => <li key={v}>{v}</li>)}</ul>
          </details>
        </section>
      ) : null}
      <section className="card">
        <h3>Asset library <span className="muted">· AI-tagged · click to add to the board</span></h3>
        <div className="chips">
          {CATEGORIES.map(([id, label]) => (
            <button key={id} className={`chip ${cat === id ? "active" : ""}`} onClick={() => setCat(id)}>
              {label}{brand?.counts?.[id] ? <small> {brand.counts[id]}</small> : null}
            </button>
          ))}
        </div>
        <input className="search" placeholder="Search assets (e.g. sparkle, laptop, coins)…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className={`asset-grid ${cat}`}>
          {assets.map((a) => (
            <button key={a.id} className="asset" onClick={() => insert(a)} title={`${a.name}\n${a.description}`}>
              <img src={a.url} alt={a.name} loading="lazy" /><span>{a.name}</span>
            </button>
          ))}
          {!assets.length ? <div className="muted">No assets match.</div> : null}
        </div>
      </section>
    </div>
  );
}
