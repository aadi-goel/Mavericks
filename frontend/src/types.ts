export type TestStatus = "Verified" | "Failed" | "Unverified" | "Unknown";
export type CommitRelation = "Cherry-pick reference" | "Equivalent patch";
export type EvidenceOrigin = "Source" | "Target" | "Cherry-pick reference" | "Common ancestor";

export interface AppSettings {
  evidence_path: string;
  lm_studio_url: string;
  lm_model: string;
  gemma_enabled: boolean;
}

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
  latestCommit: Commit | null;
  branchCount: number;
  commitsScanned: number;
  evidenceCount: number;
  dirty: boolean;
  warnings?: { code: string; message: string }[];
}

export interface Evidence {
  hash: string;
  shortHash: string;
  author: string;
  origin: string;
  equivalentPatch: boolean;
  testStatus: TestStatus;
  message?: string;
  date?: string;
  records?: EvidenceRecord[];
  original?: { status: TestStatus } | null;
  originalHash?: string | null;
  originalInRepo?: boolean;
}

export interface EvidenceRecord {
  type: string;
  result: string;
  timestamp: string;
  source: string;
  reference: string | null;
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
  isBinary?: boolean;
  conflictType?: string;
  baseContent?: string | null;
  currentDeleted?: boolean;
  incomingDeleted?: boolean;
  hunks: Hunk[];
}

export interface BranchComparison {
  onlySource: Commit[];
  onlyTarget: Commit[];
}

export interface MergeAnalysis {
  source: string;
  target: string;
  cleanMerge?: boolean;
  mergeBase?: string;
  files: ConflictFile[];
}

/** Plain-language only. Deliberately has NO field for a suggested resolution or merged code. */
export interface ConflictExplanation {
  label: string;
  explanation: string;
  model: string;
  cached: boolean;
}

export interface ResolutionPayload {
  source: string;
  target: string;
  message: string;
  approved: boolean;
  resolutions: Record<string, string>; // hunkId -> final text
}localStorage