import type {
  AppSettings, Branch, BranchComparison, Commit, ConflictExplanation, MergeAnalysis,
  RepoSummary, ResolutionPayload, TestStatus,
} from "../types";
import {
  stubAnalysis, stubBranches, stubCommits, stubComparison, stubExplanation, stubRepo,
} from "./stubs";

declare global {
  interface Window {
    pywebview?: { api?: Record<string, (...args: unknown[]) => Promise<unknown>> };
  }
}

type Envelope<T> = { ok: true; data: T } | { ok: false; error: string };

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value));
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function field(value: Record<string, unknown>, camel: string, snake: string): unknown {
  return value[snake] ?? value[camel];
}

async function call<T>(method: string, args: unknown[], fallback: () => T): Promise<T> {
  const fn = window.pywebview?.api?.[method];
  if (!fn) {
    await new Promise((resolve) => setTimeout(resolve, 200));
    return fallback();
  }
  const raw = await fn(...args);
  const parsed = (typeof raw === "string" ? JSON.parse(raw) : raw) as Envelope<T> | T;
  if (parsed && typeof parsed === "object" && "ok" in parsed) {
    const response = parsed as Envelope<T>;
    if (!response.ok) throw new Error(response.error);
    return response.data;
  }
  return parsed as T;
}

function commitFromBackend(value: unknown): Commit {
  const c = object(value);
  const tags = (c.tags as string[] | undefined) ?? [];
  return {
    hash: String(c.hash ?? ""),
    shortHash: String(field(c, "shortHash", "short_hash") ?? ""),
    message: String(c.message ?? ""),
    author: String(c.author ?? ""),
    date: String(c.date ?? ""),
    parents: ((c.parents as string[] | undefined) ?? []).map((p) => p.slice(0, 7)),
    relations: [
      ...(tags.includes("cherry_pick_reference") ? ["Cherry-pick reference" as const] : []),
      ...(tags.includes("equivalent_patch") ? ["Equivalent patch" as const] : []),
    ],
    testStatus: (field(c, "testStatus", "test_status") as TestStatus | undefined) ?? "Unknown",
  };
}

function repoFromBackend(r: Record<string, unknown>): RepoSummary {
  const latest = field(r, "latestCommit", "latest_commit");
  const counts = object(r.counts);
  return {
    name: String(r.name ?? ""),
    path: String(r.path ?? ""),
    currentBranch: String(field(r, "currentBranch", "current_branch") ?? "Detached HEAD"),
    latestCommit: latest ? commitFromBackend(latest) : null,
    branchCount: Number(field(counts, "branchCount", "branches") ?? r.branchCount ?? 0),
    commitsScanned: Number(field(counts, "commitsScanned", "commits_scanned") ?? r.commitsScanned ?? 0),
    evidenceCount: Number(field(counts, "evidenceCount", "evidence_records") ?? r.evidenceCount ?? 0),
    dirty: Boolean(r.dirty),
    warnings: (array(r.warnings).map(object)).map((w) => ({
      code: String(w.code ?? ""),
      message: String(w.message ?? ""),
    })),
  };
}

function analysisFromBackend(data: Record<string, unknown>): MergeAnalysis {
  const files = array(data.files);
  return {
    source: String(data.source ?? ""),
    target: String(data.target ?? ""),
    cleanMerge: Boolean(field(data, "cleanMerge", "clean_merge")),
    mergeBase: String(field(data, "mergeBase", "merge_base") ?? ""),
    files: files.map((item) => {
      const f = object(item);
      return ({
      path: String(f.path ?? ""),
      isBinary: Boolean(field(f, "isBinary", "is_binary")),
      conflictType: String(field(f, "conflictType", "conflict_type") ?? ""),
      baseContent: (field(f, "baseContent", "base_content") as string | null) ?? null,
      currentDeleted: "current_content" in f
        ? f.current_content === null
        : f.currentDeleted === true,
      incomingDeleted: "incoming_content" in f
        ? f.incoming_content === null
        : f.incomingDeleted === true,
      hunks: array(f.hunks).map((itemHunk) => {
        const h = object(itemHunk);
        return ({
        id: String(h.id ?? f.path ?? ""),
        startLine: Number(field(h, "startLine", "start_line") ?? 1),
        current: String(h.current ?? ""),
        incoming: String(h.incoming ?? ""),
        evidence: array(h.evidence).map((itemEvidence) => {
          const e = object(itemEvidence);
          const relationship = object(e.relationship);
          return ({
          hash: String(e.hash ?? ""),
          shortHash: String(field(e, "shortHash", "short_hash") ?? ""),
          author: String(e.author ?? ""),
          message: String(e.message ?? ""),
          date: String(e.date ?? ""),
          origin: String(e.origin ?? ""),
          equivalentPatch: Boolean(e.equivalent_patch),
          testStatus: (field(e, "testStatus", "test_status") as TestStatus | undefined) ?? "Unknown",
          records: (e.records as EvidenceRecord[] | undefined) ?? [],
          original: (e.original as EvidenceOriginal | null) ?? null,
          originalHash: typeof relationship.original_hash === "string"
            ? relationship.original_hash
            : null,
          originalInRepo: Boolean(relationship.original_exists),
        }); }),
      }); }),
    }); }),
  };
}

export interface EvidenceRecord {
  type: string;
  result: string;
  timestamp: string;
  source: string;
  reference: string | null;
}

interface EvidenceOriginal {
  status: TestStatus;
}

export const bridge = {
  pickFolder: () => call<string>("pick_folder", [], () => ""),
  openRepo: async (path: string) =>
    repoFromBackend(object(await call<unknown>("open_repository", [path], () => stubRepo(path)))),
  listBranches: async () => {
    const branches = array(await call<unknown>("list_branches", [], () => stubBranches));
    return branches.map((item) => {
      const b = object(item);
      return { name: String(b.name ?? ""), isCurrent: Boolean(field(b, "isCurrent", "is_current")) };
    }) as Branch[];
  },
  listCommits: async (branch: string, otherBranch?: string) =>
    array(await call<unknown>("list_commits", [branch, otherBranch ?? null], () => stubCommits)).map(commitFromBackend),
  compareBranches: async (source: string, target: string) => {
    const comparison = object(await call<unknown>("compare_branches", [source, target], () => stubComparison));
    return {
      onlySource: array(field(comparison, "onlySource", "only_source")).map(commitFromBackend),
      onlyTarget: array(field(comparison, "onlyTarget", "only_target")).map(commitFromBackend),
    } satisfies BranchComparison;
  },
  analyzeMerge: async (source: string, target: string) =>
    analysisFromBackend(object(await call<unknown>(
      "analyze_merge", [source, target], () => stubAnalysis(source, target),
    ))),
  explainConflict: async (file: string, hunkId: string) =>
    call<ConflictExplanation>("explain_conflict", [file, hunkId], () => stubExplanation),
  getSettings: () =>
    call<AppSettings>("get_settings", [], () => ({
      evidence_path: ".gitguardian/evidence.json",
      lm_studio_url: "http://localhost:1234",
      lm_model: "gemma",
      gemma_enabled: false,
    })),
  setSettings: (settings: AppSettings) =>
    call<AppSettings>("set_settings", [settings], () => settings),
  previewCommit: (resolutions: Record<string, string>) =>
    call<Record<string, unknown>>("preview_commit", [normalizeResolutions(resolutions)], () => ({})),
  commitResolution: async (p: ResolutionPayload) => {
    const result = await call<Record<string, unknown>>(
      "commit_resolution", [p.message, p.approved, normalizeResolutions(p.resolutions)], () => ({ short_hash: "f00ba12", log: [] }),
    );
    return {
      ok: true,
      hash: String(result.short_hash ?? result.commit_hash ?? ""),
      gitLog: (result.log as string[] | undefined) ?? [],
    };
  },
};

export const DELETE_FILE_RESOLUTION = "__GITGUARDIAN_DELETE_FILE__";

function normalizeResolutions(resolutions: Record<string, string>): Record<string, string | null> {
  return Object.fromEntries(
    Object.entries(resolutions).map(([path, content]) => [
      path,
      content === DELETE_FILE_RESOLUTION ? null : content,
    ]),
  );
}
