"""Deterministic testing-evidence status for a commit.

Status rules (PRD 7.6):
    Failed      any matching record has result == "failed"
    Verified    at least one "passed" record and zero "failed"
    Unverified  evidence file loaded, but no records for this commit
    Unknown     evidence file missing / unparseable (or the lookup is unsafe)

Missing metadata is NEVER interpreted as passed. Deployment records are
display-only and never affect the status.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .parser import MIN_HASH_LEN, load_evidence_file

DEFAULT_EVIDENCE_PATH = ".gitguardian/evidence.json"

FAILED = "Failed"
VERIFIED = "Verified"
UNVERIFIED = "Unverified"
UNKNOWN = "Unknown"

_HASH_RE = re.compile(rf"^[0-9a-f]{{{MIN_HASH_LEN},64}}$")


def _hashes_match(a: str, b: str) -> bool:
    """Prefix match in either direction (both sides are already >= 7 chars)."""
    return a.startswith(b) or b.startswith(a)


def _normalize_hash(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _HASH_RE.match(value) else None


def _file_info(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "loaded": evidence["loaded"],
        "path": evidence["path"],
        "skipped_count": evidence["skipped_count"],
        "error": evidence["error"],
    }


def _result(
    commit: str,
    status: str,
    evidence: dict[str, Any],
    records: list[dict[str, Any]] | None = None,
    deployments: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    records = records or []
    return {
        "commit": commit,
        "status": status,
        "records": records,
        "records_count": len(records),
        "passed_count": sum(r["result"] == "passed" for r in records),
        "failed_count": sum(r["result"] == "failed" for r in records),
        "sources": sorted({r["source"] for r in records}),
        "deployments": deployments or [],  # display only, never proof of testing
        "evidence_file": _file_info(evidence),
        "error": error,
    }


def compute_status(commit_hash: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Compute the status of one commit from an already-loaded evidence dict
    (the return value of load_evidence_file). Pure function, no file access."""
    commit = _normalize_hash(commit_hash)
    if commit is None:
        return _result(
            str(commit_hash), UNKNOWN, evidence,
            error=f"Commit hash must be hex and at least {MIN_HASH_LEN} characters",
        )

    if not evidence["loaded"]:
        return _result(commit, UNKNOWN, evidence, error=evidence["error"])

    matched = [r for r in evidence["records"] if _hashes_match(commit, r["commit"])]

    # A short prefix could match records of two different commits.
    # Never blend their evidence: refuse and say why.
    distinct = sorted({r["commit"] for r in matched})
    if any(not _hashes_match(x, y) for i, x in enumerate(distinct) for y in distinct[i + 1:]):
        return _result(
            commit, UNKNOWN, evidence,
            error="Hash prefix is ambiguous; it matches evidence for multiple commits",
        )

    deployments = [d for d in evidence["deployments"] if _hashes_match(commit, d["commit"])]

    if any(r["result"] == "failed" for r in matched):
        status = FAILED
    elif any(r["result"] == "passed" for r in matched):
        status = VERIFIED
    else:
        status = UNVERIFIED

    return _result(commit, status, evidence, matched, deployments)


def get_commit_evidence(
    commit_hash: str,
    evidence_path: str | Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    """Load the evidence file and return the status dict for one commit.

    Never raises: every problem is reported as data (status "Unknown" + error).
    """
    return compute_status(commit_hash, load_evidence_file(evidence_path))