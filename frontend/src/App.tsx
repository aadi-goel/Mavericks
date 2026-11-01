import { useApp, type Screen } from "./state/AppContext";
import Dashboard from "./screens/Dashboard";
import Explorer from "./screens/Explorer";
import Workspace from "./screens/Workspace";

const NAV_ITEMS: { id: Screen; label: string; icon: string; desc: string }[] = [
  { id: "dashboard",  label: "Dashboard",           icon: "⬡", desc: "Connect & analyze" },
  { id: "explorer",   label: "Repository Explorer", icon: "⎇", desc: "Commits & branches"  },
  { id: "workspace",  label: "Conflict Workspace",  icon: "⚔", desc: "Resolve conflicts"  },
];

export default function App() {
  const { screen, setScreen, repo, analysis } = useApp();

  const isDisabled = (id: Screen) =>
    (id === "explorer" && !repo) || (id === "workspace" && !analysis);

  return (
    <div className="app">
      <nav className="nav">
        {/* Brand */}
        <div className="brand">
          <div className="brand-icon">🛡</div>
          <div>
            <h1>GitGuardian</h1>
            <div className="version">v2.0 · merge intelligence</div>
          </div>
        </div>

        <div className="nav-section">Navigation</div>

        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={screen === item.id ? "active" : ""}
            disabled={isDisabled(item.id)}
            onClick={() => setScreen(item.id)}
            title={item.desc}
          >
            <span className="nav-icon">{item.icon}</span>
            {item.label}
          </button>
        ))}

        {repo && (
          <div className="repo-info">
            <div className="repo-label">Active Repo</div>
            <div className="repo-name">
              <span>📁</span>
              <span>{repo.name}</span>
            </div>
          </div>
        )}
      </nav>

      <main className="main">
        {screen === "dashboard"  && <Dashboard />}
        {screen === "explorer"   && <Explorer />}
        {screen === "workspace"  && <Workspace />}
      </main>
    </div>
  );
}
