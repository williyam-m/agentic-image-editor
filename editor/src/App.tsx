import { useCallback, useEffect, useRef, useState } from "react";
import { Canvas } from "./canvas/Canvas";
import { BoardsPanel, newBlankBoard } from "./panels/BoardsPanel";
import { LayersPanel } from "./panels/LayersPanel";
import { PropertiesPanel } from "./panels/PropertiesPanel";
import { Copilot, type CopilotApi } from "./copilot/Copilot";
import { BrandTab } from "./copilot/BrandTab";
import { ReferencesTab } from "./copilot/ReferencesTab";
import { CompetitorsTab } from "./copilot/CompetitorsTab";
import { api, uploadFile } from "./copilot/api";
import { loadBrand } from "./model/brand";
import { activeBoard, loadDoc, mutate, mutateBoard, redo, setUi, undo, useEditor } from "./model/store";
import { uid } from "./model/layers";
import { loadBrandFonts } from "./render/fonts";
import type { DesignSpec, Tool } from "./model/types";

type Tab = "copilot" | "design" | "brand" | "refs" | "intel";

const I = (d: string) => <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{d.split("|").map((p, i) => <path key={i} d={p} />)}</svg>;
const ICONS = {
  select: I("M5 3l14 8-6 1.6L10.5 19z"),
  text: I("M5 6V4h14v2|M12 4v16|M9 20h6"),
  rect: I("M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5z"),
  comment: I("M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z"),
  hand: I("M8 13V5.5a1.5 1.5 0 0 1 3 0V12|M11 11V4.5a1.5 1.5 0 0 1 3 0V12|M14 11.5V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a5 5 0 0 1-4.3-2.4L3.5 14a1.5 1.5 0 0 1 2.4-1.8L8 15"),
  image: I("M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5z|M4 16l4.5-4.5a2 2 0 0 1 2.8 0L18 18|M14 13l1.5-1.5a2 2 0 0 1 2.8 0L20 13|M9 9h.01"),
  undo: I("M9 14L4 9l5-5|M4 9h10.5a5.5 5.5 0 0 1 0 11H11"),
  redo: I("M15 14l5-5-5-5|M20 9H9.5a5.5 5.5 0 0 0 0 11H13"),
};

const TOOLS: [Tool, keyof typeof ICONS, string][] = [
  ["select", "select", "Select & move (V)"], ["text", "text", "Text (T)"], ["rect", "rect", "Rectangle (R)"],
  ["comment", "comment", "Comment on a layer (C)"], ["hand", "hand", "Pan (H / hold Space)"],
];

export function App() {
  const [fontsVersion, setFontsVersion] = useState(0);
  const [tab, setTab] = useState<Tab>("copilot");
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "err" } | null>(null);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const copilotApi = useRef<CopilotApi | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const tool = useEditor((s) => s.tool);
  const saving = useEditor((s) => s.saving);
  const canUndo = useEditor((s) => s.canUndo);
  const canRedo = useEditor((s) => s.canRedo);
  const loaded = useEditor((s) => s.loaded);
  const selection = useEditor((s) => s.selection);

  const notify = useCallback((msg: string, tone: "ok" | "err" = "ok") => {
    setToast({ msg, tone });
    setTimeout(() => setToast(null), 2600);
  }, []);

  useEffect(() => {
    loadBrand().then((b) => loadBrandFonts({ fonts: b.fonts, files: b.font_files, metrics: b.font_metrics }))
      .then(() => setFontsVersion((v) => v + 1)).catch(() => notify("Could not load brand fonts", "err"));
    void loadDoc();
    api.health().then((h) => setHealthy(h.temporal === "ok" && String(h.celery).startsWith("ok"))).catch(() => setHealthy(false));
  }, [notify]);

  useEffect(() => { if (selection) setTab((t) => (t === "brand" || t === "refs" ? "design" : t)); }, [selection]);

  const addImage = useCallback(async (file: File, at?: { x: number; y: number }) => {
    let b = activeBoard();
    if (!b) {
      const nb = newBlankBoard("feed");
      mutate((d) => { d.boards.push(nb); });
      setUi({ activeBoardId: nb.id });
      b = nb;
    }
    try {
      const up = await uploadFile(file);
      const w = Math.min(b.width * 0.6, up.width), h = (w * up.height) / up.width;
      const id = uid("img");
      mutateBoard(b.id, (bd) => bd.layers.push({ id, name: file.name.replace(/\.\w+$/, "") || "Image", kind: "image", role: "photo",
        x: at ? at.x - w / 2 : (bd.width - w) / 2, y: at ? at.y - h / 2 : (bd.height - h) / 2, w, h,
        src: up.url, file: up.file, transparent: up.transparent, status: "ready" }));
      setUi({ selection: id, tool: "select" });
      notify("Image added as a layer");
    } catch (e) {
      notify(e instanceof Error ? e.message : "Upload failed", "err");
    }
  }, [notify]);

  const exportPng = useCallback(async (b: DesignSpec) => {
    notify("Rendering PNG…");
    const r = await api.render(b, 1);
    const a = document.createElement("a");
    a.href = r.url;
    a.download = `${b.name.replace(/[^\w-]+/g, "_")}.png`;
    a.click();
  }, [notify]);

  const runDna = useCallback((b: DesignSpec) => { setTab("copilot"); copilotApi.current?.runDna(b.id); }, []);

  return (
    <>
    <div className="bg-mesh" aria-hidden><i /><i /><i /></div>
    <div className="studio" onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f?.type.startsWith("image/")) void addImage(f); }}>
      <header className="topbar">
        <a className="brand" href="/" title="Crux Studio home"><img src="/mark.svg" alt="" /><b>crux<span>.</span></b><em>Studio</em></a>
        <div className="docname">Xero campaign <span className={`save ${saving}`}>{saving === "saving" ? "Saving…" : saving === "error" ? "Not saved" : "Saved"}</span></div>
        <div className="tools">
          {TOOLS.map(([id, icon, title]) => (
            <button key={id} className={tool === id ? "on" : ""} title={title} onClick={() => setUi({ tool: id })} data-testid={`tool-${id}`}>{ICONS[icon]}</button>
          ))}
          <button title="Add image (upload or drop a file)" onClick={() => fileRef.current?.click()}>{ICONS.image}</button>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void addImage(f); e.target.value = ""; }} />
          <span className="sep" />
          <button title="Undo (⌘Z)" disabled={!canUndo} onClick={undo}>{ICONS.undo}</button>
          <button title="Redo (⇧⌘Z)" disabled={!canRedo} onClick={redo}>{ICONS.redo}</button>
        </div>
        <div className="top-right">
          <span className={`health ${healthy === null ? "" : healthy ? "ok" : "down"}`} title={healthy ? "AI services online" : "AI services offline"} />
          <button className="btn-dark sm" onClick={() => { const b = activeBoard(); if (b) void exportPng(b); }}>EXPORT PNG <span className="arrow">→</span></button>
        </div>
      </header>

      <aside className="left">
        <BoardsPanel fontsVersion={fontsVersion} />
        <LayersPanel />
      </aside>

      <main className="center">
        {loaded ? <Canvas fontsVersion={fontsVersion} /> : <div className="canvas empty-canvas">Loading…</div>}
      </main>

      <aside className="right">
        <nav className="tabs">
          {([["copilot", "Copilot"], ["design", "Design"], ["brand", "Brand"], ["refs", "Refs"], ["intel", "Competitors"]] as [Tab, string][]).map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} data-testid={`tab-${id}`}>{label}</button>
          ))}
        </nav>
        <div className="tab-pane" style={{ display: tab === "copilot" ? "flex" : "none" }}>
          <Copilot fontsVersion={fontsVersion} notify={notify} register={(a) => { copilotApi.current = a; }} />
        </div>
        {tab === "design" ? <div className="tab-pane scroll"><PropertiesPanel onExport={exportPng} onDna={runDna} /></div> : null}
        {tab === "brand" ? <div className="tab-pane scroll"><BrandTab notify={notify} /></div> : null}
        {tab === "intel" ? (
          <div className="tab-pane scroll">
            <CompetitorsTab
              onIdea={(idea, category) => {
                setTab("copilot");
                copilotApi.current?.designFrom(`💡 Idea from ${category} competitor intel`, {
                  prompt: `Create an on-brand Xero ad from this idea. Keep the headline exactly: "${idea.headline}". ${idea.why}`,
                  base_brief: { archetype: idea.archetype, headline: idea.headline, subhead: idea.subhead ?? null, cta: idea.cta,
                    visual: { source: "generate", kind: idea.archetype === "navy_illustration" ? "illustration" : "photo", prompt: idea.visual } },
                });
              }}
              onRemix={(ad, category) => {
                setTab("copilot");
                copilotApi.current?.designFrom(`↻ Remix of a ${ad.days_active}-day ${category} ad`, {
                  prompt: `Take inspiration from this long-running competitor ad (its format and angle: ${ad.analysis?.angle ?? ""}) and create an original, on-brand Xero ad. Never reuse its copy, claims or branding.`,
                  reference_file: ad.thumb_file,
                });
              }}
            />
          </div>
        ) : null}
        {tab === "refs" ? <div className="tab-pane scroll"><ReferencesTab onUse={(r, n) => { setTab("copilot"); copilotApi.current?.useReference(r, n); }} /></div> : null}
      </aside>

      {toast ? <div className={`toast ${toast.tone}`}>{toast.msg}</div> : null}
    </div>
    </>
  );
}
