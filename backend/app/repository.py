"""Repository registration and the open_repository payload (PRD 7.1 and 8).

Real data comes from Member 3 (backend/git_engine) and Member 4
(backend/provenance). This module only orchestrates: validate, read, combine,
and record the repository in SQLite.
"""

from pathlib import Path
from typing import Any

from backend.app import settings as app_settings
from backend.app.db import connection, utc_now
from backend.git_engine import (
    GitError,
    get_current_branch,
    get_working_tree_status,
    list_branches,
    list_commits,
    run_git,
    validate_repository,
)
from backend.provenance import load_evidence_file


def register_repository(repo_path: Path) -> int:
    """Insert the repo (or refresh last_opened_at) and return its repo_id."""
    resolved = str(repo_path.resolve())
    with connection() as conn:
        conn.execute(
            "INSERT INTO repository (path, name, last_opened_at) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "name = excluded.name, last_opened_at = excluded.last_opened_at",
            (resolved, repo_path.resolve().name, utc_now()),
        )
        row = conn.execute(
            "SELECT id FROM repository WHERE path = ?", (resolved,)
        ).fetchone()
    return row["id"]


def _evidence_info(root: str) -> dict[str, Any]:
    """Load the evidence file (Member 4). Never raises: problems come back as data."""
    configured = app_settings.load_settings()["evidence_path"]
    # A relative setting is relative to the repository; an absolute one is kept.
    path = Path(root) / configured
    ev = load_evidence_file(path)
    return {
        "path": str(path),
        "loaded": bool(ev.get("loaded")),
        "records_found": ev.get("records_count", 0),
        "skipped_records": ev.get("skipped_count", 0),
        "error": ev.get("error"),
    }


def _latest_commit(root: str, ref: str) -> dict[str, Any] | None:
    try:
        commits = list_commits(root, ref, limit=1)
    except GitError:
        return None  # e.g. a repository with no commits yet
    if not commits:
        return None
    c = commits[0]
    return {
        "hash": c["hash"],
        "short_hash": c["short_hash"],
        "message": c["message"],
        "author": c["author"],
        "date": c["date"],
    }


def _count_commits(root: str, ref: str) -> int:
    result = run_git(root, ["rev-list", "--count", ref], check=False)
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


def _warnings(status: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if not status["is_clean"]:
        count = len(status["tracked_changes"])
        warnings.append(
            {
                "code": "dirty_worktree",
                "message": (
                    f"You have {count} uncommitted change(s). GitGuardian never modifies "
                    "them, but a merge commit is blocked until the target checkout is clean."
                ),
            }
        )
    if status["merge_in_progress"]:
        warnings.append(
            {
                "code": "merge_in_progress",
                "message": "A merge is already in progress. Finish or abort it with Git first.",
            }
        )
    if not evidence["loaded"]:
        warnings.append(
            {
                "code": "evidence_missing",
                "message": (
                    f"{evidence['error'] or 'Evidence file not loaded'}. "
                    "Every test status will show Unknown."
                ),
            }
        )
    elif evidence["skipped_records"]:
        warnings.append(
            {
                "code": "evidence_skipped",
                "message": f"{evidence['skipped_records']} invalid evidence record(s) were skipped.",
            }
        )
    return warnings


def open_repository(path: str) -> tuple[int, Path, dict[str, Any]]:
    """Validate and read a repository.

    Returns (repo_id, repo_root, payload). Raises ValueError with a short,
    user-facing message when the folder cannot be used.
    """
    validation = validate_repository(path)
    if not validation["valid"]:
        raise ValueError(validation["error"] or "This folder cannot be opened.")

    root = validation["root"]
    try:
        current = get_current_branch(root)  # None when HEAD is detached
        branches = list_branches(root, include_remote=True)
        status = get_working_tree_status(root)
    except GitError as exc:
        raise ValueError(str(exc)) from exc

    ref = current or "HEAD"
    evidence = _evidence_info(root)
    repo_id = register_repository(Path(root))

    payload = {
        "repo_id": repo_id,
        "path": root,
        "name": validation["name"],
        "current_branch": current,
        "latest_commit": _latest_commit(root, ref),
        "branches": [
            {"name": b["name"], "is_current": b["is_current"], "is_remote": b["is_remote"]}
            for b in branches
        ],
        "counts": {
            "branches": len(branches),
            "commits_scanned": _count_commits(root, ref),
            "evidence_records": evidence["records_found"],
        },
        "evidence_file": evidence,
        "dirty": not status["is_clean"],
        "warnings": _warnings(status, evidence),
    }
    return repo_id, Path(root), payload