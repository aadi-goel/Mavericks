import { StatusBadge } from "../../components/Badges";
import type { Hunk } from "../../types";

export default function EvidencePanel({ hunk }: { hunk: Hunk | undefined }) {
  if (!hunk) return <p className="muted">Select a conflict region.</p>;
  return (
    <>
      <h4 style={{ margin: "0 0 8px" }}>Commits touching this file</h4>
      {hunk.evidence.length === 0 && <p className="muted">No commits found touching this region.</p>}
      {hunk.evidence.map((e) => (
        <div className="ev" key={e.hash + e.origin}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <code>{e.shortHash}</code><StatusBadge status={e.testStatus} />
          </div>
            {e.message && <div>{e.message}</div>}
            <div className="muted">{e.author}{e.date ? ` · ${new Date(e.date).toLocaleString()}` : ""}</div>
            <div className="muted">Origin: {e.origin}</div>
            <div className="muted">Equivalent patch: {e.equivalentPatch ? "Yes" : "No"}</div>
            {(e.records ?? []).map((r, i) => (
              <div className="muted" key={`${e.hash}-${i}`}>
                {r.type}: {r.result} · {r.source}
              </div>
            ))}
            {e.original && (
              <div className="muted">
                Original {e.originalHash && <code>{e.originalHash.slice(0, 7)}</code>}
                {e.originalInRepo ? " · in repository" : ""}: {e.original.status} (not transferred)
              </div>
            )}
          </div>
      ))}
    </>
  );
}