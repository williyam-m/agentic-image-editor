import { useEffect, useState } from "react";
import { api, type ReferenceInfo } from "./api";
import { GenerateLike } from "./GenerateLike";

export function ReferencesTab({ onUse }: { onUse: (ref: ReferenceInfo, count: number) => void }) {
  const [refs, setRefs] = useState<ReferenceInfo[]>([]);
  useEffect(() => { api.references().then(setRefs).catch(() => setRefs([])); }, []);
  return (
    <div className="tab-body">
      <p className="muted small">Reference ads analysed by AI (headline, layout archetype, colourway). Use one as inspiration.</p>
      <div className="ref-grid">
        {refs.map((r) => (
          <div key={r.id} className="ref">
            <img src={r.url} alt={r.headline} loading="lazy" />
            <div className="ref-meta">
              <b>{r.headline?.replace(/\n/g, " ")}</b>
              <small>{r.archetype?.replace(/_/g, " ")} · {r.colorway}</small>
              <div className="row gap6 mt6">
                <GenerateLike dark onGenerate={(n) => onUse(r, n)} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
