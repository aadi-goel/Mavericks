import { useEffect, useState } from "react";
import { bridge } from "../bridge/bridge";
import { useApp } from "../state/AppContext";
import type { AppSettings } from "../types";

export default function Dashboard() {
  const { repo, setRepo, branches, setBranches, source, setSource, target, setTarget,
    setAnalysis, resetResolutions, setScreen } = useApp();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState<AppSettings>({
    evidence_path: ".gitguardian/evidence.json",
    lm_studio_url: "http://localhost:1234",
    lm_model: "gemma",
    gemma_enabled: false,
  });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsError, setSettingsError] = useState("");

  useEffect(() => {
    bridge.getSettings()
      .then(setSettings)
      .catch((e: unknown) => setSettingsError(e instanceof Error ? e.message : String(e)));
  }, []);

  const saveSettings = async () => {
    setSettingsBusy(true);
    setSettingsError("");
    try { setSettings(await bridge.setSettings(settings)); }
    catch (e) { setSettingsError(e instanceof Error ? e.message : String(e)); }
    finally { setSettingsBusy(false); }
  };

  const browse = async () => {
    setError("");
    try { setPath(await bridge.pickFolder()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

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

      <details className="card">
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Local evidence & AI settings</summary>
        <div className="cols2" style={{ marginTop: 12 }}>
          <label>Evidence file path
            <input className="grow" value={settings.evidence_path}
              onChange={(e) => setSettings((s) => ({ ...s, evidence_path: e.target.value }))} />
          </label>
          <label>LM Studio URL (localhost only)
            <input className="grow" value={settings.lm_studio_url}
              onChange={(e) => setSettings((s) => ({ ...s, lm_studio_url: e.target.value }))} />
          </label>
          <label>Local model name
            <input className="grow" value={settings.lm_model}
              onChange={(e) => setSettings((s) => ({ ...s, lm_model: e.target.value }))} />
          </label>
          <label className="row">
            <input type="checkbox" checked={settings.gemma_enabled}
              onChange={(e) => setSettings((s) => ({ ...s, gemma_enabled: e.target.checked }))} />
            Enable optional Gemma explanations
          </label>
        </div>
        <button className="btn" disabled={settingsBusy} onClick={saveSettings}>
          {settingsBusy ? "Saving…" : "Save settings"}
        </button>
        {settingsError && <div className="error">{settingsError}</div>}
      </details>

      {repo && lc && (
        <>
          {repo.warnings?.map((warning) => (
            <div className="banner" key={warning.code}>{warning.message}</div>
          ))}

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
              <button className="btn primary" disabled={busy || !source || !target || source === target} onClick={analyze}>
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