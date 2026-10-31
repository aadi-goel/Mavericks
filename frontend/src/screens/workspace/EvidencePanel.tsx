import { StatusBadge } from "../../components/Badges";
import type { Hunk } from "../../types";

export default function EvidencePanel({ hunk }: { hunk: Hunk | undefined }) {
  if (!hunk) return <p className="muted">Select a conflict region.</p>;
  return (
    <>
      <h4 style={{ margin: "0 0 8px" }}>Evidence · lines from {hunk.startLine}</h4>
      {hunk.evidence.length === 0 && <p className="muted">No commits found touching this region.</p>}
      {hunk.evidence.map((e) => (
        <div className="ev" key={e.hash + e.origin}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <code>{e.shortHash}</code><StatusBadge status={e.testStatus} />
          </div>
          <div>{e.author}</div>
          <div className="muted">Origin: {e.origin}</div>
          <div className="muted">Equivalent patch: {e.equivalentPatch ? "Yes" : "No"}</div>
        </div>
      ))}
    </>
  );
}