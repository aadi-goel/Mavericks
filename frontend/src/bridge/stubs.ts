import type {
  Branch, BranchComparison, Commit, ConflictExplanation, MergeAnalysis, RepoSummary,
} from "../types";

const c = (p: Partial<Commit> & Pick<Commit, "shortHash" | "message">): Commit => ({
  hash: p.shortHash + "e3b0c44298fc1c149afbf4c8996fb92427ae41e4",
  author: "Asha Verma",
  date: "2026-10-28T10:15:00Z",
  parents: [],
  relations: [],
  testStatus: "Unknown",
  ...p,
});

export const stubCommits: Commit[] = [
  c({ shortHash: "a1b2c3d", message: "Add retry logic to payment client", parents: ["9f8e7d6"], testStatus: "Verified" }),
  c({ shortHash: "9f8e7d6", message: "Refactor config loader", author: "Ravi Kumar", date: "2026-10-26T16:40:00Z", parents: ["5c4b3a2"], testStatus: "Verified" }),
  c({ shortHash: "5c4b3a2", message: "Cherry-pick: fix timeout default (from 7d6e5f4)", author: "Mei Tanaka", date: "2026-10-24T09:05:00Z", parents: ["3a2b1c0"], relations: ["Cherry-pick reference"], testStatus: "Unverified" }),
  c({ shortHash: "3a2b1c0", message: "Fix timeout default", author: "Mei Tanaka", date: "2026-10-22T13:20:00Z", parents: ["1d2e3f4"], relations: ["Equivalent patch"], testStatus: "Failed" }),
  c({ shortHash: "1d2e3f4", message: "Initial payment module", author: "Asha Verma", date: "2026-10-15T08:00:00Z", parents: [], testStatus: "Unknown" }),
];

export const stubBranches: Branch[] = [
  { name: "main", isCurrent: true },
  { name: "develop", isCurrent: false },
  { name: "feature/payment-retry", isCurrent: false },
  { name: "hotfix/timeout", isCurrent: false },
];

export const stubRepo = (path: string): RepoSummary => ({
  name: path.split(/[\\/]/).filter(Boolean).pop() || "demo-repo",
  path,
  currentBranch: "main",
  latestCommit: stubCommits[0],
  branchCount: stubBranches.length,
  commitsScanned: 128,
  evidenceCount: 17,
  dirty: path.toLowerCase().includes("dirty"), // type "dirty" in the path to preview the banner
});

export const stubComparison: BranchComparison = {
  onlySource: [stubCommits[0], stubCommits[2]],
  onlyTarget: [stubCommits[1], stubCommits[3]],
};

export const stubAnalysis = (source: string, target: string): MergeAnalysis => ({
  source,
  target,
  files: [
    {
      path: "src/payment/client.py",
      hunks: [
        {
          id: "h1",
          startLine: 42,
          current: "TIMEOUT_SECONDS = 30\nMAX_RETRIES = 1",
          incoming: "TIMEOUT_SECONDS = 10\nMAX_RETRIES = 5",
          evidence: [
            { hash: "a1b2c3d", shortHash: "a1b2c3d", author: "Asha Verma", origin: "Source", equivalentPatch: false, testStatus: "Verified" },
            { hash: "3a2b1c0", shortHash: "3a2b1c0", author: "Mei Tanaka", origin: "Target", equivalentPatch: true, testStatus: "Failed" },
            { hash: "5c4b3a2", shortHash: "5c4b3a2", author: "Mei Tanaka", origin: "Cherry-pick reference", equivalentPatch: true, testStatus: "Unverified" },
          ],
        },
        {
          id: "h2",
          startLine: 88,
          current: "def send(self, payload):\n    return self._post(payload)",
          incoming: "def send(self, payload, retries=3):\n    return self._post_with_retry(payload, retries)",
          evidence: [
            { hash: "a1b2c3d", shortHash: "a1b2c3d", author: "Asha Verma", origin: "Source", equivalentPatch: false, testStatus: "Verified" },
          ],
        },
      ],
    },
    {
      path: "src/config/loader.py",
      hunks: [
        {
          id: "h3",
          startLine: 12,
          current: "CONFIG_PATH = 'config.yaml'",
          incoming: "CONFIG_PATH = os.environ.get('GG_CONFIG', 'config.yaml')",
          evidence: [
            { hash: "9f8e7d6", shortHash: "9f8e7d6", author: "Ravi Kumar", origin: "Target", equivalentPatch: false, testStatus: "Verified" },
          ],
        },
      ],
    },
  ],
});

export const stubExplanation: ConflictExplanation = {
  currentSummary: "The target branch keeps a 30 second timeout and allows a single retry.",
  incomingSummary: "The source branch lowers the timeout to 10 seconds and allows up to 5 retries.",
  whyConflict: "Both branches edited the same two lines after their common ancestor, so Git cannot tell which values should win.",
};