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


def  get_commit_evidence(
    commit_hash: str,
    evidence_path: str | Path = DEFAULT_EVIDENCE_PATH,
    *,
    original_hash: str | None = None,
) -> dict[str, Any]:
    """Return evidence for a commit and, optionally, for its cherry-pick original.

    The two statuses are computed independently and returned in separate keys.
    Results are NEVER transferred or merged between the copy and the original.

    Returns:
        {
          "commit": normalized hash of this commit,
          "original_hash": normalized original hash, or None,
          "is_cherry_pick": bool,
          "this_commit_evidence": {...status dict from compute_status...},
          "original_commit_evidence": {...status dict...} or None,
          "note": explanatory text, or None,
        }

    Never raises: problems come back as data (status "Unknown" + error).
    """
    evidence = load_evidence_file(evidence_path)  # parse once, use for both

    this = compute_status(commit_hash, evidence)
    this["relationship"] = "this_commit"

    result: dict[str, Any] = {
        "commit": this["commit"],
        "original_hash": None,
        "is_cherry_pick": False,
        "this_commit_evidence": this,
        "original_commit_evidence": None,
        "note": None,
    }

    # No original supplied (or blank): not a cherry-pick as far as we know.
    if original_hash is None or (isinstance(original_hash, str) and not original_hash.strip()):
        return result

    # Guard against a commit being passed as its own original.
    this_norm = _normalize_hash(commit_hash)
    orig_norm = _normalize_hash(original_hash)
    if this_norm and orig_norm and _hashes_match(this_norm, orig_norm):
        result["note"] = "original_hash is the same commit; not treated as a cherry-pick"
        return result

    original = compute_status(original_hash, evidence)
    original["relationship"] = "original_commit"

    result["original_hash"] = original["commit"]
    result["is_cherry_pick"] = True
    result["original_commit_evidence"] = original
    result["note"] = (
        "Evidence for the cherry-pick and its original is shown separately. "
        "Test results are never transferred between them."
    )
    return result