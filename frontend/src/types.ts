export type TestStatus = "Verified" | "Failed" | "Unverified" | "Unknown";
export type CommitRelation = "Cherry-pick reference" | "Equivalent patch";
export type EvidenceOrigin = "Source" | "Target" | "Cherry-pick reference" | "Common ancestor";

export interface Commit {
  hash: string;
  shortHash: string;
  message: string;
  author: string;
  date: string; // ISO string
  parents: string[]; // short hashes
  relations: CommitRelation[];
  testStatus: TestStatus;
}

export interface Branch {
  name: string;
  isCurrent: boolean;
}

export interface RepoSummary {
  name: string;
  path: string;
  currentBranch: string;
  latestCommit: Commit;
  branchCount: number;
  commitsScanned: number;
  evidenceCount: number;
  dirty: boolean;
}

export interface Evidence {
  hash: string;
  shortHash: string;
  author: string;
  origin: EvidenceOrigin;
  equivalentPatch: boolean;
  testStatus: TestStatus;
}

export interface Hunk {
  id: string;
  startLine: number;
  current: string; // target side
  incoming: string; // source side
  evidence: Evidence[];
}

export interface ConflictFile {
  path: string;
  hunks: Hunk[];
}

export interface BranchComparison {
  onlySource: Commit[];
  onlyTarget: Commit[];
}

export interface MergeAnalysis {
  source: string;
  target: string;
  files: ConflictFile[];
}

/** Plain-language only. Deliberately has NO field for a suggested resolution or merged code. */
export interface ConflictExplanation {
  currentSummary: string;
  incomingSummary: string;
  whyConflict: string;
}

export interface ResolutionPayload {
  source: string;
  target: string;
  message: string;
  approved: boolean;
  resolutions: Record<string, string>; // hunkId -> final text
}localStorage