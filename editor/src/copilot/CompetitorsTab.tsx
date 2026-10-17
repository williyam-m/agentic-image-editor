// Competitor intel: scan the public Meta Ad Library for the category, rank by days active
// (advertisers keep winners live), and turn what works into original, on-brand ideas.
import { useCallback, useEffect, useMemo, useState } from "react";
import { pollJob, type JobEvent } from "./api";

export interface CompetitorAd {
  library_id: string; advertiser: string; avatar?: string | null; status: string; started?: string | null; ended?: string | null;
  days_active?: number | null; tier: "proven" | "testing" | "new" | "unknown"; variants: number; body: string; cta?: string | null;
  domain?: string | null; media_type: "video" | "image" | "carousel" | "text"; video_url?: string | null;
  image_urls: string[]; ad_url: string; thumb_url?: string; thumb_file?: string;
  analysis?: { relevance: number; hook: string; angle: string; visual: string; style: string; offer?: string | null; why_it_works: string; tags: string[] } | null;
}
export interface Idea { title: string; headline: string; subhead?: string | null; cta: string; archetype: string; visual: string; why: string; inspired_by: string[] }
interface Insights { summary: string; patterns: { pattern: string; evidence: string; strength: string }[]; whitespace: string[]; ideas: Idea[] }
interface Report { query: string; country: string; ads: CompetitorAd[]; insights: Insights }
interface Progress { stage: string; events: JobEvent[]; ads: CompetitorAd[] }

const PRESETS = ["accounting software", "fintech", "invoicing app", "payroll software", "small business banking"];
const COUNTRIES: [string, string][] = [["ALL", "All countries"], ["US", "United States"], ["GB", "United Kingdom"],
  ["AU", "Australia"], ["NZ", "New Zealand"], ["CA", "Canada"], ["IN", "India"]];
const fmtDate = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");

export function CompetitorsTab({ onIdea, onRemix }: {
  onIdea: (idea: Idea, category: string) => void;
  onRemix: (ad: CompetitorAd, category: string) => void;
}) {
  const [query, setQuery] = useState("accounting software");
  const [country, setCountry] = useState("ALL");
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [liveAds, setLiveAds] = useState<CompetitorAd[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<"days" | "relevance">("days");
  const [hideOffTopic, setHideOffTopic] = useState(true);

  const loadLatest = useCallback(async (q: string, c: string) => {
    try {
      const r = await fetch(`/api/competitors/latest?${new URLSearchParams({ query: q, country: c })}`);
      setReport(r.ok ? ((await r.json()) as Report) : null);
    } catch { setReport(null); }
  }, []);
  useEffect(() => { void loadLatest(query, country); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const scan = async () => {
    setRunning(true); setError(null); setEvents([]); setLiveAds([]); setReport(null);
    try {
      const r = await fetch("/api/competitors", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), country, limit: 20 }) });
      const { job_id } = await r.json();
      const result = await pollJob<Progress, Report>(job_id, (p) => { setEvents(p.events); if (p.ads?.length) setLiveAds(p.ads); }, 900);
      setReport(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const ads = report?.ads ?? liveAds;
  const maxDays = Math.max(1, ...ads.map((a) => a.days_active ?? 0));
  const shown = useMemo(() => {
    const list = ads.filter((a) => !hideOffTopic || !a.analysis || a.analysis.relevance >= 4);
    return [...list].sort((a, b) => sort === "days" ? (b.days_active ?? 0) - (a.days_active ?? 0)
      : (b.analysis?.relevance ?? 0) - (a.analysis?.relevance ?? 0));
  }, [ads, hideOffTopic, sort]);
  const byId = useMemo(() => Object.fromEntries(ads.map((a) => [a.library_id, a])), [ads]);
  const ins = report?.insights;

  return (
    <div className="tab-body intel">
      <section className="card">
        <div className="row between"><h3>Competitor intel</h3><span className="src-chip">Meta Ad Library</span></div>
        <p className="muted small">Public ads in your category, ranked by how long they've run — advertisers keep winners live and kill losers fast.</p>
        <div className="intel-form">
          <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Category, e.g. fintech"
            onKeyDown={(e) => e.key === "Enter" && !running && void scan()} data-testid="intel-query" />
          <select className="search country" value={country} onChange={(e) => { setCountry(e.target.value); void loadLatest(query, e.target.value); }}>
            {COUNTRIES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </div>
        <div className="chips">
          {PRESETS.map((p) => <button key={p} className={`chip ${query === p ? "active" : ""}`} onClick={() => { setQuery(p); void loadLatest(p, country); }}>{p}</button>)}
        </div>
        <button className="btn-dark full" disabled={running || query.trim().length < 2} onClick={() => void scan()} data-testid="intel-scan">
          {running ? "Scanning…" : <>Scan Meta Ad Library <span className="arrow">→</span></>}
        </button>
        {events.length ? (
          <ol className="timeline mt6">{events.slice(-5).map((e, i) => <li key={i} className={e.kind}><span className="mono">{e.t.toFixed(1)}s</span> {e.text}</li>)}</ol>
        ) : null}
        {error ? <div className="error-note">{error}</div> : null}
      </section>

      {ins ? (
        <section className="card intel-insights">
          <span className="eyebrow dark">What's working · {report!.query}</span>
          <p className="intel-summary">{ins.summary}</p>
          <ul className="patterns">
            {ins.patterns.map((p, i) => (
              <li key={i}><span className={`strength ${p.strength}`}>{p.strength}</span><b>{p.pattern}</b><small>{p.evidence}</small></li>
            ))}
          </ul>
          {ins.whitespace?.length ? <div className="whitespace"><b>Whitespace:</b> {ins.whitespace.join(" · ")}</div> : null}
        </section>
      ) : null}

      {ins?.ideas?.length ? (
        <section>
          <h3 className="sec-title">Ideas for Xero <small>{ins.ideas.length}</small></h3>
          <div className="ideas">
            {ins.ideas.map((idea, i) => (
              <div key={i} className="card idea" data-testid="intel-idea">
                <div className="row between"><span className="idea-arch">{idea.archetype.replace(/_/g, " ")}</span><span className="muted tiny">#{i + 1}</span></div>
                <div className="idea-head">{idea.headline}</div>
                {idea.subhead ? <div className="small ink2">{idea.subhead}</div> : null}
                <div className="small mt6"><b>Visual:</b> {idea.visual}</div>
                <div className="small muted mt6">↳ {idea.why}</div>
                <div className="row between mt6">
                  <div className="sources">{idea.inspired_by.slice(0, 3).map((id) => byId[id]?.thumb_url
                    ? <a key={id} href={byId[id].ad_url} target="_blank" rel="noreferrer" title={`${byId[id].advertiser} · ${byId[id].days_active} days`}><img src={byId[id].thumb_url} alt="" /></a> : null)}</div>
                  <button className="btn-dark sm" onClick={() => onIdea(idea, report!.query)}>Create this <span className="arrow">→</span></button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {ads.length ? (
        <section>
          <div className="row between">
            <h3 className="sec-title">Ads <small>{shown.length}/{ads.length}</small></h3>
            <div className="row gap6">
              <label className="tiny muted row gap6"><input type="checkbox" checked={hideOffTopic} onChange={(e) => setHideOffTopic(e.target.checked)} /> on-topic only</label>
              <div className="seg mini">
                <button className={sort === "days" ? "on" : ""} onClick={() => setSort("days")}>Days live</button>
                <button className={sort === "relevance" ? "on" : ""} onClick={() => setSort("relevance")}>Relevance</button>
              </div>
            </div>
          </div>
          <div className="ad-list">
            {shown.map((a) => (
              <div key={a.library_id} className="card ad-row" data-testid="intel-ad">
                <a className="ad-thumb" href={a.ad_url} target="_blank" rel="noreferrer" title="Open in Meta Ad Library">
                  {a.thumb_url ? <img src={a.thumb_url} alt={a.advertiser} loading="lazy" /> : <span className="no-thumb">{a.media_type}</span>}
                  {a.media_type === "video" ? <span className="badge">▶ video</span> : a.media_type === "carousel" ? <span className="badge">⧉ carousel</span> : null}
                </a>
                <div className="ad-meta">
                  <div className="row between"><b className="adv">{a.advertiser}</b><span className={`tier ${a.tier}`}>{a.tier}</span></div>
                  <div className="days"><div style={{ width: `${((a.days_active ?? 0) / maxDays) * 100}%` }} /></div>
                  <div className="tiny muted">
                    <span className={`status ${a.status}`} />{a.days_active ?? "?"} days · since {fmtDate(a.started)}{a.ended ? ` → ${fmtDate(a.ended)}` : ""}
                    {a.variants > 1 ? ` · ×${a.variants} variants` : ""}
                  </div>
                  {a.analysis?.hook ? <div className="small hook">“{a.analysis.hook}”</div> : <div className="small hook muted">{a.body.slice(0, 90)}</div>}
                  {a.analysis?.tags?.length ? <div className="tags">{a.analysis.tags.map((t) => <span key={t}>{t}</span>)}</div> : null}
                  <div className="row gap6 mt4">
                    {a.video_url ? <a className="btn-ghost xs" href={a.video_url} target="_blank" rel="noreferrer">Watch</a> : null}
                    {a.thumb_file ? <button className="btn-ghost xs" onClick={() => onRemix(a, report?.query ?? query)}>Remix on-brand</button> : null}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <p className="muted tiny">Data: public Meta Ad Library (no login). Days active is a proxy, not a performance metric. Ideas are original and on-brand — competitor copy, claims and branding are never reused.</p>
    </div>
  );
}
