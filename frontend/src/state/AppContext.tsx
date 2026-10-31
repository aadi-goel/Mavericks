import { createContext, useContext, useState, type ReactNode } from "react";
import type { Branch, MergeAnalysis, RepoSummary } from "../types";

export type Screen = "dashboard" | "explorer" | "workspace";

interface Ctx {
  screen: Screen; setScreen: (s: Screen) => void;
  repo: RepoSummary | null; setRepo: (r: RepoSummary | null) => void;
  branches: Branch[]; setBranches: (b: Branch[]) => void;
  source: string; setSource: (s: string) => void;
  target: string; setTarget: (s: string) => void;
  analysis: MergeAnalysis | null; setAnalysis: (a: MergeAnalysis | null) => void;
  resolutions: Record<string, string>;
  setResolution: (hunkId: string, text: string) => void;
  resetResolutions: () => void;
}

const AppCtx = createContext<Ctx>(null!);
export const useApp = () => useContext(AppCtx);

export function AppProvider({ children }: { children: ReactNode }) {
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [repo, setRepo] = useState<RepoSummary | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [analysis, setAnalysis] = useState<MergeAnalysis | null>(null);
  const [resolutions, setRes] = useState<Record<string, string>>({});

  return (
    <AppCtx.Provider
      value={{
        screen, setScreen, repo, setRepo, branches, setBranches,
        source, setSource, target, setTarget, analysis, setAnalysis,
        resolutions,
        setResolution: (id, t) => setRes((r) => ({ ...r, [id]: t })),
        resetResolutions: () => setRes({}),
      }}
    >
      {children}
    </AppCtx.Provider>
  );
}