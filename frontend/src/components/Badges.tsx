import type { CommitRelation, TestStatus } from "../types";

export const StatusBadge = ({ status }: { status: TestStatus }) => (
  <span className={`badge b-${status}`} title="Testing evidence">{status}</span>
);

export const RelationTag = ({ rel }: { rel: CommitRelation }) => (
  <span className={`tag ${rel === "Equivalent patch" ? "equiv" : ""}`}>{rel}</span>
);