import { useState } from "react";
import { DELETE_FILE_RESOLUTION } from "../bridge/bridge";
import { useApp } from "../state/AppContext";
import EvidencePanel from "./workspace/EvidencePanel";
import ExplainPanel from "./workspace/ExplainPanel";
import ReviewModal from "./workspace/ReviewModal";

export default function Workspace() {
  const { analysis, resolutions, setResolution } = useApp();
  const [filePath, setFilePath] = useState(analysis?.files[0]?.path ?? "");
  const [hunkId, setHunkId] = useState<string | undefined>(analysis?.files[0]?.hunks[0]?.id);
  const [review, setReview] = useState(false);

  if (!analysis) return <p className="muted">Run “Analyze Merge” from the Dashboard first.</p>;
  if (analysis.cleanMerge) {
    return (
      <>
        <h2 className="page-title">Clean merge · {analysis.source} → {analysis.target}</h2>
        <div className="card">
          <p>Git reports no conflicts. Review and approve to create a standard merge commit.</p>
          <button className="btn primary" onClick={() => setReview(true)}>Review & Commit</button>
        </div>
        {review && <ReviewModal onClose={() => setReview(false)} />}
      </>
    );
  }

  const file = analysis.files.find((f) => f.path === filePath) ?? analysis.files[0];
  if (!file) return <p className="muted">Git found no text conflicts to resolve.</p>;
  const allHunks = analysis.files.flatMap((f) => f.hunks);
  const hunk = allHunks.find((h) => h.id === hunkId);
  const resolvedCount = allHunks.filter((h) => resolutions[h.id] !== undefined).length;
  const fileDone = (p: string) => {
    const item = analysis.files.find((f) => f.path === p)!;
    return !item.isBinary && item.hunks.length > 0
      && item.hunks.every((h) => resolutions[h.id] !== undefined);
  };

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <h2 className="page-title" style={{ margin: 0 }}>
          Conflict Workspace <span className="muted" style={{ fontSize: 14 }}>{analysis.source} → {analysis.target}</span>
        </h2>
        <div className="row">
          <span className="muted">{resolvedCount}/{allHunks.length} regions resolved</span>
          <button className="btn primary" onClick={() => setReview(true)}>Review & Commit</button>
        </div>
      </div>

      <div className="ws">
        <section>
          <h4 style={{ margin: "0 0 8px" }}>Conflicted files</h4>
          {analysis.files.map((f) => (
            <div key={f.path} className={`file ${f.path === file.path ? "active" : ""}`}
              onClick={() => { setFilePath(f.path); setHunkId(f.hunks[0]?.id); }}>
              <span className="mono">{f.path}</span>
              <span className={`dot ${fileDone(f.path) ? "ok" : ""}`}>{fileDone(f.path) ? "✓" : "●"}</span>
            </div>
          ))}
        </section>

        <section>
          {file.isBinary ? (
            <div className="banner">This binary conflict cannot be edited in the MVP. Resolve it with Git, then reopen the repository.</div>
          ) : file.hunks.map((h) => (
            <div key={h.id} className={`hunk ${h.id === hunkId ? "sel" : ""}`} onClick={() => setHunkId(h.id)}>
              <div className="hunk-head">
                <span>File-level conflict · {file.conflictType}</span>
                <span className={resolutions[h.id] !== undefined ? "dot ok" : "dot"}>
                  {resolutions[h.id] !== undefined ? "resolved" : "unresolved"}
                </span>
              </div>
              <div className="panes">
                <div className="pane cur">
                  <h5>Current (target)
                    {file.currentDeleted
                      ? <button className="btn sm" onClick={() => setResolution(h.id, DELETE_FILE_RESOLUTION)}>Accept deletion</button>
                      : <button className="btn sm" onClick={() => setResolution(h.id, h.current)}>Accept current</button>}
                  </h5>
                  <pre>{file.currentDeleted ? "(file deleted)" : h.current}</pre>
                </div>
                <div className="pane inc">
                  <h5>Incoming (source)
                    {file.incomingDeleted
                      ? <button className="btn sm" onClick={() => setResolution(h.id, DELETE_FILE_RESOLUTION)}>Accept deletion</button>
                      : <button className="btn sm" onClick={() => setResolution(h.id, h.incoming)}>Accept incoming</button>}
                  </h5>
                  <pre>{file.incomingDeleted ? "(file deleted)" : h.incoming}</pre>
                </div>
                <div className="pane">
                  <h5>Result (editable)</h5>
                  <textarea className="code" spellCheck={false} placeholder="Write the resolved code here…"
                    value={resolutions[h.id] === DELETE_FILE_RESOLUTION ? "" : resolutions[h.id] ?? ""}
                    onChange={(e) => setResolution(h.id, e.target.value)} />
                </div>
              </div>
            </div>
          ))}
        </section>

        <section>
          <EvidencePanel hunk={hunk} />
          <ExplainPanel hunkId={hunkId} />
        </section>
      </div>

      {review && <ReviewModal onClose={() => setReview(false)} />}
    </>
  );
}