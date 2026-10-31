import { useEffect, useState } from "react";
import { bridge } from "../bridge/bridge";
import { useApp } from "../state/AppContext";
import { RelationTag, StatusBadge } from "../components/Badges";
import type { BranchComparison, Commit } from "../types";

function CommitTable({ commits }: { commits: Commit[] }) {
  if (!commits.length) return <p className="muted">No commits.</p>;
  return (
    <table className="tbl">
      <thead><tr><th>Hash</th><th>Message</th><th>Author</th><th>Date</th><th>Parents</th><th>Testing</th></tr></thead>
      <tbody>
        {commits.map((c) => (
          <tr key={c.hash}>
            <td><code>{c.shortHash}</code></td>
            <td>{c.message}{c.relations.map((r) => <RelationTag key={r} rel={r} />)}</td>
            <td>{c.author}</td>
            <td className="muted">{new Date(c.date).toLocaleDateString()}</td>
            <td><code className="muted">{c.parents.join(", ") || "—"}</code></td>
            <td><StatusBadge status={c.testStatus} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Explorer() {
  const { branches, source, target } = useApp();
  const [branch, setBranch] = useState(target || branches[0]?.name || "");
  const [commits, setCommits] = useState<Commit[]>([]);
  const [cmp, setCmp] = useState<BranchComparison | null>(null);

  useEffect(() => { if (branch) bridge.listCommits(branch).then(setCommits); }, [branch]);
  useEffect(() => { if (source && target) bridge.compareBranches(source, target).then(setCmp); }, [source, target]);

  return (
    <>
      <h2 className="page-title">Repository Explorer</h2>

      <div className="card">
        <h3>Commits</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          <label>Branch&nbsp;
            <select value={branch} onChange={(e) => setBranch(e.target.value)}>
              {branches.map((b) => <option key={b.name}>{b.name}</option>)}
            </select>
          </label>
        </div>
        <CommitTable commits={commits} />
      </div>

      <div className="card">
        <h3>Branch comparison: {source} vs {target}</h3>
        {cmp ? (
          <div className="cols2">
            <div><strong>Only in source ({source})</strong><CommitTable commits={cmp.onlySource} /></div>
            <div><strong>Only in target ({target})</strong><CommitTable commits={cmp.onlyTarget} /></div>
          </div>
        ) : <p className="muted">Loading…</p>}
      </div>
    </>
  );
}