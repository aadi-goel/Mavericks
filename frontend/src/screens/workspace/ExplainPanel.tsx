import { useEffect, useState } from "react";
import { bridge } from "../../bridge/bridge";
import type { ConflictExplanation } from "../../types";

/** Shows only plain-language explanation. No resolution suggestion, no merged code. */
export default function ExplainPanel({ hunkId }: { hunkId?: string }) {
  const [exp, setExp] = useState<ConflictExplanation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { setExp(null); setError(""); }, [hunkId]);

  const run = async () => {
    if (!hunkId) return;
    setBusy(true);
    setError("");
    try { setExp(await bridge.explainConflict(hunkId, hunkId)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 16 }}>
      <button className="btn" disabled={!hunkId || busy} onClick={run}>
        {busy ? "Explaining…" : "Explain this conflict"}
      </button>
      <div className="ai-warn">{exp?.label ?? "AI explanation — verify before relying on it"}</div>
      {error && <div className="error">{error}</div>}
      {exp && (
        <div className="ev">
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{exp.explanation}</p>
          <div className="muted">Model: {exp.model}{exp.cached ? " · cached" : ""}</div>
        </div>
      )}
    </div>
  );
}