import { useEffect, useState } from "react";
import { bridge } from "../../bridge/bridge";
import type { ConflictExplanation } from "../../types";

/** Shows only plain-language explanation. No resolution suggestion, no merged code. */
export default function ExplainPanel({ hunkId }: { hunkId?: string }) {
  const [exp, setExp] = useState<ConflictExplanation | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setExp(null), [hunkId]);

  const run = async () => {
    if (!hunkId) return;
    setBusy(true);
    try { setExp(await bridge.explainConflict(hunkId)); } finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 16 }}>
      <button className="btn" disabled={!hunkId || busy} onClick={run}>
        {busy ? "Explaining…" : "Explain this conflict"}
      </button>
      <div className="ai-warn">AI explanation - verify before relying on it</div>
      {exp && (
        <div className="ev">
          <p style={{ margin: "0 0 6px" }}><strong>Current:</strong> {exp.currentSummary}</p>
          <p style={{ margin: "0 0 6px" }}><strong>Incoming:</strong> {exp.incomingSummary}</p>
          <p style={{ margin: 0 }}><strong>Why Git reports a conflict:</strong> {exp.whyConflict}</p>
        </div>
      )}
    </div>
  );
}