import type {
  Branch, BranchComparison, Commit, ConflictExplanation, MergeAnalysis,
  RepoSummary, ResolutionPayload,
} from "../types";
import {
  stubAnalysis, stubBranches, stubCommits, stubComparison, stubExplanation, stubRepo,
} from "./stubs";

declare global {
  interface Window {
    pywebview?: { api?: Record<string, (json: string) => Promise<unknown>> };
  }
}

/** Thin bridge: JSON string in, JSON out, over window.pywebview.api. No HTTP anywhere. */
async function call<T>(method: string, payload: unknown, fallback: () => T): Promise<T> {
  const fn = window.pywebview?.api?.[method];
  if (!fn) {
    await new Promise((r) => setTimeout(r, 250)); // simulate latency in browser dev mode
    return fallback();
  }
  const raw = await fn(JSON.stringify(payload ?? {}));
  return (typeof raw === "string" ? JSON.parse(raw) : raw) as T;
}

export const bridge = {
  pickFolder: () => call<string>("pick_folder", {}, () => "C:/projects/demo-repo"),
  openRepo: (path: string) => call<RepoSummary>("open_repo", { path }, () => stubRepo(path)),
  listBranches: () => call<Branch[]>("list_branches", {}, () => stubBranches),
  listCommits: (branch: string) => call<Commit[]>("list_commits", { branch }, () => stubCommits),
  compareBranches: (source: string, target: string) =>
    call<BranchComparison>("compare_branches", { source, target }, () => stubComparison),
  analyzeMerge: (source: string, target: string) =>
    call<MergeAnalysis>("analyze_merge", { source, target }, () => stubAnalysis(source, target)),
  explainConflict: (hunkId: string) =>
    call<ConflictExplanation>("explain_conflict", { hunkId }, () => stubExplanation),
  commitResolution: (p: ResolutionPayload) =>
    call<{ ok: boolean; hash: string }>("commit_resolution", p, () => ({ ok: true, hash: "f00ba12" })),
};