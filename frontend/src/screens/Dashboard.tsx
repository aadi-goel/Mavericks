import { useState } from "react";
import { bridge } from "../bridge/bridge";
import { useApp } from "../state/AppContext";

export default function Dashboard() {
  const { repo, setRepo, branches, setBranches, source, setSource, target, setTarget,
    setAnalysis, resetResolutions, setScreen } = useApp();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const browse = async () => setPath(await bridge.pickFolder());

  const connect = async () => {
    setBusy(true); setError("");
    try {
      const r = await bridge.openRepo(path.trim());
      const b = await bridge.listBranches();
      setRepo(r); setBranches(b); setAnalysis(null); resetResolutions();
      setTarget(r.currentBranch);
      setSource(b.find((x) => x.name !== r.currentBranch)?.name ?? "");
    } catch (e) {
      setError(String(e));
    } finally { setBusy(false); }
  };

  const analyze = async () => {
    setBusy(true); setError("");
    try {
      resetResolutions();
      setAnalysis(await bridge.analyzeMerge(source, target));
      setScreen("workspace");
    } catch (e) {
      setError(String(e));
    } finally { setBusy(false); }
  };

  const lc = repo?.latestCommit;
  return (
    <>
      <h2 className="page-title">Dashboard</h2>

      <div className="card">
        <h3>Repository</h3>
        <div className="row">
          <input type="text" className="grow" placeholder="Local folder path, e.g. C:/projects/my-repo"
            value={path} onChange={(e) => setPath(e.target.value)} />
          <button className="btn" onClick={browse}>Browse…</button>
          <button className="btn primary" disabled={!path.trim() || busy} onClick={connect}>Connect</button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      {repo && lc && (
        <>
          {repo.dirty && (
            <div className="banner">
              ⚠ Working tree has uncommitted changes. Commit or stash them before analyzing a merge.
            </div>
          )}

          <div className="card">
            <h3>Current state</h3>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div><strong style={{ fontSize: 18 }}>{repo.name}</strong> <span className="muted">on</span> <code>{repo.currentBranch}</code></div>
              <span className="muted mono">{repo.path}</span>
            </div>
            <p style={{ marginBottom: 0 }}>
              <code>{lc.shortHash}</code> {lc.message}<br />
              <span className="muted">{lc.author} · {new Date(lc.date).toLocaleString()}</span>
            </p>
          </div>

          <div className="grid3">
            <div className="card"><h3>Branches</h3><div className="metric">{repo.branchCount}</div></div>
            <div className="card"><h3>Commits scanned</h3><div className="metric">{repo.commitsScanned}</div></div>
            <div className="card"><h3>Evidence records</h3><div className="metric">{repo.evidenceCount}</div></div>
          </div>

          <div className="card">
            <h3>Analyze a merge</h3>
            <div className="row">
              <label>Source (incoming)&nbsp;
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  {branches.map((b) => <option key={b.name}>{b.name}</option>)}
                </select>
              </label>
              <span className="muted">→ merge into →</span>
              <label>Target (current)&nbsp;
                <select value={target} onChange={(e) => setTarget(e.target.value)}>
                  {branches.map((b) => <option key={b.name}>{b.name}</option>)}
                </select>
              </label>
              <button className="btn primary" disabled={busy || !source || !target || source === target || repo.dirty} onClick={analyze}>
                {busy ? "Analyzing…" : "Analyze Merge"}
              </button>
            </div>
            <p className="muted" style={{ marginBottom: 0 }}>Runs a dry-run merge locally. Nothing is written until you approve a commit.</p>
          </div>
        </>
      )}
    </>
  );
}