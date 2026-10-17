// Crux Studio landing page — GetCrux visual language with scroll-driven storytelling.
import { useEffect, useRef, useState, type ReactNode } from "react";
import "./landing.css";

const STUDIO = "/studio";

const FEATURES = [
  { id: "create", tag: "Create", title: "A layered, on-brand ad in ~20 seconds",
    body: "Describe the ad. Crux plans copy and layout from your brand kit, generates every image layer in parallel, and builds the board as real, editable layers — headline, photo, bloom, logo, CTA, charms.",
    points: ["5 layout archetypes learned from your reference ads", "Every element is its own layer", "4:5 · 1:1 · 9:16 · 1.91:1"], img: "create" },
  { id: "edit", tag: "Edit any layer", title: "Click a layer. Say what to change.",
    body: "Select anything on the canvas and describe the change. Only that layer changes — copy is re-fitted with real font metrics, colours snap to the palette, photos are edited in place keeping the same person and scene.",
    points: ["Text, colour, layout and image edits", "Photo edits keep identity & framing", "Undo/redo, drag, resize, inline text"], img: "photo" },
  { id: "voice", tag: "Voice to edit", title: "Just say it.",
    body: "Press M and talk: “make the headline say get paid in days.” ElevenLabs Scribe v2 transcribes, Crux applies it to the selected layer. It stops listening the moment you pause.",
    points: ["ElevenLabs Scribe v2 speech-to-text", "Auto-stops on silence", "Works in canvas comments too"], img: "voice" },
  { id: "comment", tag: "Comment to edit", title: "Pin a note on any element.",
    body: "Drop a comment exactly where you point. Crux edits the layer under the pin and replies in the thread — the way you'd brief a designer, minus the wait.",
    points: ["Layer under the pointer is the target", "Threaded replies & resolve", "Dismiss with ×, Esc or a click away"], img: "comment" },
  { id: "variations", tag: "Variations", title: "Generate like this — 1 to 4 at once.",
    body: "Pick a board and choose how many. Each variation gets a different layout, colourway and copy angle, all generated in parallel — real options, not near-duplicates.",
    points: ["Distinct archetypes per variant", "Parallel generation", "Works from any reference"], img: "variations" },
  { id: "dna", tag: "Brand DNA", title: "See every brand violation — and fix it in one click.",
    body: "A measured audit of layers and pixels (fonts, palette, WCAG contrast, logo colourway & clear space, legal copy) plus a visual review. Every issue is located, explained, pinned on the canvas and auto-fixable.",
    points: ["Score across 6 DNA dimensions", "Compliant AI copy rewrites", "Fix all → re-check"], img: "dna" },
  { id: "intel", tag: "Competitor intel", title: "Learn from ads that kept running.",
    body: "Scan the public Meta Ad Library for your category. Ads are ranked by days active — advertisers keep winners live — and Crux turns the patterns into original, on-brand ideas you can create in one click.",
    points: ["~20 ads with creatives & start dates", "Vision AI reads every creative", "Ideas never copy competitors"], img: "intel" },
] as const;

const STACK = [
  ["Temporal", "Durable workflows for every job"], ["Celery + Redis", "Every image layer in parallel"],
  ["DeepSeek V4 Pro", "Planning, copy & edits"], ["DeepSeek V4.1 Flash", "Vision: tagging, QA, Brand DNA"],
  ["GPT Image Flare", "Photos, cut-outs & brand-style art"], ["ElevenLabs Scribe v2", "Voice to edit"],
  ["FastAPI", "API & document store"], ["React + SVG", "Pixel-exact layered canvas"],
];

const PIPELINE = [
  ["Plan", "Brand rules, voice and references shape the brief"], ["Lay out", "Code places every layer with measured text"],
  ["Generate", "All image layers render in parallel"], ["Guard", "Policy checks, auto-fixes and art-director QA"],
  ["Edit", "Everything lands as editable layers"],
];

/** Adds `.in` when the element scrolls into view (once). */
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { el.classList.add("in"); io.disconnect(); } }, { threshold: 0.18 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}

function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  const ref = useReveal<HTMLDivElement>();
  return <div ref={ref} className={`reveal ${className}`} style={{ transitionDelay: `${delay}ms` }}>{children}</div>;
}

function Counter({ to, suffix = "", prefix = "" }: { to: number; suffix?: string; prefix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [v, setV] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const tick = (t: number) => {
        const p = Math.min(1, (t - t0) / 1200);
        setV(Math.round(to * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, { threshold: 0.5 });
    io.observe(el);
    return () => io.disconnect();
  }, [to]);
  return <span ref={ref}>{prefix}{v}{suffix}</span>;
}

function Arrow() { return <span className="arrow">→</span>; }

export function Landing() {
  const [scrolled, setScrolled] = useState(false);
  const [active, setActive] = useState(0);
  const heroShot = useRef<HTMLDivElement>(null);
  const pipe = useRef<HTMLDivElement>(null);
  const [pipeP, setPipeP] = useState(0);

  useEffect(() => {
    document.title = "Crux Studio — the AI design copilot that never breaks your brand";
    const onScroll = () => {
      const y = window.scrollY;
      setScrolled(y > 24);
      if (heroShot.current) {
        const p = Math.min(1, y / 700);
        heroShot.current.style.transform = `perspective(1400px) rotateX(${14 - p * 14}deg) translateY(${-p * 40}px) scale(${0.94 + p * 0.06})`;
      }
      if (pipe.current) {
        const r = pipe.current.getBoundingClientRect();
        setPipeP(Math.max(0, Math.min(1, (window.innerHeight * 0.8 - r.top) / (r.height + window.innerHeight * 0.3))));
      }
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Sticky feature story: the step nearest the viewport centre drives the screenshot.
  useEffect(() => {
    const steps = [...document.querySelectorAll<HTMLElement>(".story-step")];
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.i));
    }, { rootMargin: "-45% 0px -45% 0px" });
    steps.forEach((s) => io.observe(s));
    return () => io.disconnect();
  }, []);

  const ads = Array.from({ length: 14 }, (_, i) => `/landing/ads/ad${String(i).padStart(2, "0")}.jpg`);

  return (
    <div className="landing">
      <div className="l-mesh" aria-hidden><i /><i /><i /><i /></div>

      <nav className={`l-nav ${scrolled ? "scrolled" : ""}`}>
        <a className="l-logo" href="/"><img src="/mark.svg" alt="" /><b>crux<span>.</span></b><em>Studio</em></a>
        <div className="l-links">
          <a href="#features">Features</a><a href="#guardrails">Guardrails</a><a href="#how">How it works</a><a href="#stack">Stack</a>
        </div>
        <a className="l-cta" href={STUDIO} data-testid="nav-open-studio">Open Crux Studio <Arrow /></a>
      </nav>

      <header className="l-hero">
        <Reveal><span className="l-eyebrow"><i>Y</i> Built for brand teams · GetCrux</span></Reveal>
        <Reveal delay={80}><h1>The AI design copilot<br /><span className="l-grad">that never breaks your brand.</span></h1></Reveal>
        <Reveal delay={160}><p className="l-sub">Create, edit and remix on-brand ads as real layers — by chat, voice or a comment on the canvas. Every output is checked against your brand kit and legal rules before you see it.</p></Reveal>
        <Reveal delay={240}>
          <div className="l-ctas">
            <a className="l-btn dark" href={STUDIO} data-testid="hero-open-studio">Open Crux Studio <Arrow /></a>
            <a className="l-btn glass" href="#features">See every feature</a>
          </div>
        </Reveal>
        <div className="l-shot-wrap">
          <div className="l-shot" ref={heroShot}>
            <img src="/landing/create.jpg" alt="Crux Studio editor with a generated, layered Xero ad" />
            <span className="chip c1">✓ Brand 100/100</span>
            <span className="chip c2">✦ Photo · policy-verified</span>
            <span className="chip c3">🎙 “make the headline say…”</span>
          </div>
        </div>
      </header>

      <section className="l-marquee" aria-label="Ads generated by Crux Studio">
        <div className="track">{[...ads, ...ads].map((src, i) => <img key={i} src={src} alt="" loading="lazy" />)}</div>
      </section>

      <section className="l-stats">
        {[
          [<Counter key="a" to={20} prefix="~" suffix="s" />, "from prompt to a layered ad"],
          [<Counter key="b" to={10} suffix="+" />, "editable layers per design"],
          [<Counter key="c" to={323} />, "brand assets analysed by AI"],
          [<Counter key="d" to={4} suffix="×" />, "variations generated in parallel"],
        ].map(([n, label], i) => (
          <Reveal key={i} delay={i * 80} className="stat"><b>{n}</b><span>{label as string}</span></Reveal>
        ))}
      </section>

      <section id="features" className="l-story">
        <Reveal><h2 className="l-h2">Everything a brand designer needs.<br /><span className="l-grad">Nothing that breaks the brand.</span></h2></Reveal>
        <div className="story">
          <div className="story-steps">
            {FEATURES.map((f, i) => (
              <article key={f.id} className={`story-step ${active === i ? "on" : ""}`} data-i={i}>
                <span className="tag">{String(i + 1).padStart(2, "0")} · {f.tag}</span>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
                <ul>{f.points.map((p) => <li key={p}>{p}</li>)}</ul>
                <img className="mobile-shot" src={`/landing/${f.img}.jpg`} alt="" loading="lazy" />
              </article>
            ))}
          </div>
          <div className="story-media">
            <div className="frame">
              <div className="frame-bar"><i /><i /><i /><span>localhost:8787/studio</span></div>
              {FEATURES.map((f, i) => (
                <img key={f.id} className={active === i ? "on" : ""} src={`/landing/${f.img}.jpg`} alt={f.title} loading="lazy" />
              ))}
            </div>
            <div className="dots">{FEATURES.map((f, i) => <span key={f.id} className={active === i ? "on" : ""} />)}</div>
          </div>
        </div>
      </section>

      <section id="guardrails" className="l-guard">
        <Reveal className="guard-card">
          <span className="l-eyebrow dark">Enterprise-grade guardrails</span>
          <h2>Built for teams with legal sign-off.</h2>
          <div className="guard-grid">
            {[
              ["No unapproved claims", "“Guaranteed”, “#1”, “risk-free”… are rejected; copy is re-planned with legal feedback."],
              ["Terms added automatically", "Offers (free, trial, %, prices) always ship with “Terms apply.”"],
              ["Every AI image verified", "Vision review for text, logos, watermarks and competitor branding — regenerated if needed."],
              ["Logo & palette locked", "Official wordmark in approved colourways only; primary colours for large fills."],
              ["Brand fonts only", "Typography restricted to the brand’s faces, measured to fit."],
              ["Edits can’t break rules", "Off-policy requests become the closest compliant change, with an explanation."],
            ].map(([t, d], i) => (
              <Reveal key={t} delay={i * 70} className="guard-item"><b>{t}</b><span>{d}</span></Reveal>
            ))}
          </div>
        </Reveal>
      </section>

      <section id="how" className="l-how" ref={pipe}>
        <Reveal><h2 className="l-h2">How it works</h2></Reveal>
        <div className="pipeline">
          <div className="line"><div style={{ width: `${pipeP * 100}%` }} /></div>
          {PIPELINE.map(([t, d], i) => (
            <div key={t} className={`node ${pipeP > i / (PIPELINE.length - 1) - 0.05 ? "lit" : ""}`}>
              <span>{i + 1}</span><b>{t}</b><small>{d}</small>
            </div>
          ))}
        </div>
      </section>

      <section id="stack" className="l-stack">
        <Reveal><h2 className="l-h2">Durable, parallel, production-shaped.</h2></Reveal>
        <div className="stack-grid">
          {STACK.map(([t, d], i) => <Reveal key={t} delay={i * 50} className="stack-item"><b>{t}</b><span>{d}</span></Reveal>)}
        </div>
      </section>

      <section className="l-final">
        <Reveal className="final-card">
          <h2>Design on-brand,<br /><span className="l-grad">layer by layer.</span></h2>
          <p>Your brand kit, your rules, your canvas — with a copilot that does the busywork.</p>
          <a className="l-btn light" href={STUDIO} data-testid="final-open-studio">Open Crux Studio <Arrow /></a>
        </Reveal>
      </section>

      <footer className="l-foot">
        <span><b>crux.</b> Studio — built for the GetCrux hackathon</span>
        <span>Xero brand kit used for demonstration · Meta Ad Library data is public</span>
      </footer>
    </div>
  );
}
