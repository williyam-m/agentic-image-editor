import { useEffect, useRef, useState } from "react";

/** "Generate like this" → pick how many (1–4) → generate. */
export function GenerateLike({ onGenerate, dark, size = "sm" }: { onGenerate: (count: number) => void; dark?: boolean; size?: "sm" | "xs" }) {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(4);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("pointerdown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="gen-like" ref={ref}>
      <button className={`${dark ? "btn-dark" : "btn-ghost"} ${size}`} onClick={() => setOpen(!open)} data-testid="generate-like">
        Generate like this
      </button>
      {open ? (
        <div className="gen-pop" role="dialog" aria-label="How many designs?">
          <div className="gen-pop-head">How many? <small>max 4</small></div>
          <div className="gen-count">
            {[1, 2, 3, 4].map((n) => (
              <button key={n} className={count === n ? "on" : ""} onClick={() => setCount(n)} data-testid={`gen-count-${n}`}>{n}</button>
            ))}
          </div>
          <button className="btn-dark sm full" data-testid="gen-confirm" onClick={() => { setOpen(false); onGenerate(count); }}>
            Generate {count} <span className="arrow">→</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
