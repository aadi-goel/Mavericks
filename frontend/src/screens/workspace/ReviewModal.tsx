import { useState } from "react";
import { bridge } from "../../bridge/bridge";
import { Modal } from "../../components/Modal";
import { useApp } from "../../state/AppContext";

export default function ReviewModal({ onClose }: { onClose: () => void }) {
  const { analysis, resolutions, source, target, setScreen, setAnalysis, resetResolutions } = useApp();
  const [approved, setApproved] = useState(false);
  const [message, setMessage] = useState(`Merge '${source}' into '${target}'`);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [error, setError] = useState("");

  const hunks = analysis!.files.flatMap((f) => f.hunks);
  const allResolved = hunks.every((h) => resolutions[h.id] !== undefined);
  const canCommit = approved && message.trim() !== "" && allResolved && !busy;

  const commit = async () => {
    setBusy(true); setError("");
    try {
      const r = await bridge.commitResolution({ source, target, message: message.trim(), approved, resolutions });
      if (!r.ok) throw new Error("Commit failed");
      setDone(r.hash);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };

  const finish = () => { setAnalysis(null); resetResolutions(); setScreen("dashboard"); onClose(); };

  return (
    <Modal title="Review & Commit" onClose={done ? finish : onClose} footer={
      done ? <button className="btn primary" onClick={finish}>Back to Dashboard</button> : <>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={!canCommit} onClick={commit}>
          {busy ? "Committing…" : "Complete resolution"}
        </button>
      </>
    }>
      {done ? <p>✅ Merge committed as <code>{done}</code>.</p> : <>
        {!allResolved && <div className="banner">Some conflict regions are still unresolved.</div>}
        {analysis!.files.map((f) => (
          <div key={f.path}>
            <strong className="mono">{f.path}</strong>
            {f.hunks.map((h) => (
              <div className="diff mono" key={h.id}>
                <div className="l hd">@@ line {h.startLine} @@</div>
                {h.current.split("\n").map((l, i) => <div key={"d" + i} className="l del">- {l}</div>)}
                {(resolutions[h.id] ?? "").split("\n").map((l, i) => <div key={"a" + i} className="l add">+ {l}</div>)}
              </div>
            ))}
          </div>
        ))}
        <label style={{ display: "block", margin: "12px 0 4px" }}>Commit message</label>
        <textarea style={{ width: "100%" }} rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
        <label className="row" style={{ marginTop: 12 }}>
          <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
          I have reviewed this diff and approve committing this resolution.
        </label>
        {error && <div className="error">{error}</div>}
      </>}
    </Modal>
  );
}