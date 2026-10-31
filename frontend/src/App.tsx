import { useApp, type Screen } from "./state/AppContext";
import Dashboard from "./screens/Dashboard";
import Explorer from "./screens/Explorer";
import Workspace from "./screens/Workspace";

export default function App() {
  const { screen, setScreen, repo, analysis } = useApp();
  const items: { id: Screen; label: string; disabled: boolean }[] = [
    { id: "dashboard", label: "Dashboard", disabled: false },
    { id: "explorer", label: "Repository Explorer", disabled: !repo },
    { id: "workspace", label: "Conflict Workspace", disabled: !analysis },
  ];
  return (
    <div className="app">
      <nav className="nav">
        <h1>Git<span>Guardian</span> v2.0</h1>
        {items.map((i) => (
          <button key={i.id} className={screen === i.id ? "active" : ""} disabled={i.disabled} onClick={() => setScreen(i.id)}>
            {i.label}
          </button>
        ))}
        <div className="repo">{repo ? `📁 ${repo.name}` : "No repository connected"}</div>
      </nav>
      <main className="main">
        {screen === "dashboard" && <Dashboard />}
        {screen === "explorer" && <Explorer />}
        {screen === "workspace" && <Workspace />}
      </main>
    </div>
  );
}