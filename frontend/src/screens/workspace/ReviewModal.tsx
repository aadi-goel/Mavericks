import { useEffect, useState } from "react";
import { bridge } from "../../bridge/bridge";
import { Modal } from "../../components/Modal";
import { useApp } from "../../state/AppContext";

export default function ReviewModal({ onClose }: { onClose: () => void }) {
  const { analysis, resolutions, source, target, setScreen, setAnalysis, resetResolutions } = useApp();
  const initialMessage = `Merge '${source}' into '${target}'`;
  const [approved, setApproved] = useState(false);
  const [message, setMessage] = useState(initialMessage);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [gitLog, setGitLog] = useState<string[]>([]);

  const allResolved = analysis!.files.every((f) =>
    !f.isBinary && f.hunks.every((h) => resolutions[h.id] !== undefined),
  );
  const canCommit = approved && message.trim() !== "" && allResolved
    && preview?.can_commit === true && !busy;

  useEffect(() => {
    let active = true;
    bridge.previewCommit(resolutions)
      .then((result) => {
        if (active) {
          setPreview(result);
          setMessage((previous) =>
            previous === initialMessage && typeof result.default_message === "string"
              ? result.default_message
              : previous,
          );
        }
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : String(e)); });
    return () => { active = false; };
  }, []);

  const commit = async () => {
    setBusy(true); setError("");
    try {
      const r = await bridge.commitResolution({ source, target, message: message.trim(), approved, resolutions });
      setDone(r.hash);
      setGitLog(r.gitLog);
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
        {!allResolved && <div className="banner">Some conflicted files are unresolved or contain binary data.</div>}
        <h4>Diff against target branch</h4>
        <pre className="diff mono" style={{ whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto" }}>
          {String(preview?.diff ?? "Loading preview…")}
        </pre>
        {Array.isArray(preview?.unresolved_files) && preview.unresolved_files.length > 0 && (
          <div className="banner">Unresolved: {(preview.unresolved_files as { path: string }[]).map((f) => f.path).join(", ")}</div>
        )}
        <label style={{ display: "block", margin: "12px 0 4px" }}>Commit message</label>
        <textarea style={{ width: "100%" }} rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
        <label className="row" style={{ marginTop: 12 }}>
          <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
          I have reviewed this diff and approve committing this resolution.
        </label>
        {error && <div className="error">{error}</div>}
      </>}
      {done && (
        <div className="ev">
          <strong>Recent Git history</strong>
          {gitLog.map((line) => <div className="mono" key={line}>{line}</div>)}
        </div>
      )}
    </Modal>
  );
}