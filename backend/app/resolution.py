"""Manual resolution + commit approval flow (PRD sections 7.8 and 8).

Session edits live in memory (BridgeAPI._resolutions). Nothing touches the
user's working tree. Member 3 (Git Engine) will later replace the mock diff
and the mock commit with real Git operations.
"""

import difflib
import json
import re
from typing import Any

from backend.app.db import connection, utc_now

MAX_CONTENT_BYTES = 5_000_000
MAX_MESSAGE_CHARS = 5_000

# <<<<<<< ours, ||||||| base, =======, >>>>>>> theirs  (PRD 7.3: a file is
# resolved only once no conflict markers remain)
_MARKER_RE = re.compile(r"^(?:<{7}|>{7}|\|{7})(?: .*)?$|^={7}$", re.MULTILINE)


def has_conflict_markers(text: str) -> bool:
    return bool(_MARKER_RE.search(text))


def _resolved_paths(analysis: dict, resolutions: dict[str, str]) -> list[str]:
    return [
        f["path"]
        for f in analysis["files"]
        if f["path"] in resolutions and not has_conflict_markers(resolutions[f["path"]])
    ]


def save(analysis: dict, resolutions: dict[str, str], file: str, content: str) -> dict[str, Any]:
    """Store the developer's content for one conflicted file (session only)."""
    if not isinstance(file, str) or not file.strip():
        raise ValueError("file is required")
    if file not in {f["path"] for f in analysis["files"]}:
        raise ValueError(f"{file} is not a conflicted file in the current analysis")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValueError("content is too large (max 5 MB)")

    resolutions[file] = content  # saved even with markers, so edits are not lost
    markers = has_conflict_markers(content)
    return {
        "file": file,
        "resolved": not markers,
        "has_conflict_markers": markers,
        "resolved_files": len(_resolved_paths(analysis, resolutions)),
        "total_files": len(analysis["files"]),
    }


def build_preview(analysis: dict, resolutions: dict[str, str]) -> dict[str, Any]:
    """Diff of the result vs the target branch, plus resolved/unresolved lists.

    MOCK: the diff is computed with difflib from the mock target content.
    Member 3 will replace this with a real `git diff` against the target.
    """
    resolved_files: list[dict[str, Any]] = []
    unresolved_files: list[dict[str, str]] = []
    diff_parts: list[str] = []

    for f in analysis["files"]:
        path = f["path"]
        content = resolutions.get(path)
        if content is None:
            unresolved_files.append({"path": path, "reason": "not_resolved"})
            continue
        if has_conflict_markers(content):
            unresolved_files.append({"path": path, "reason": "conflict_markers"})
            continue

        target_text = f["current_content"] or ""
        diff_lines = list(
            difflib.unified_diff(
                target_text.splitlines(),
                content.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        resolved_files.append(
            {
                "path": path,
                "additions": sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++")),
                "deletions": sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---")),
                "diff": "\n".join(diff_lines),
            }
        )
        if diff_lines:
            diff_parts.append("\n".join(diff_lines))

    # PRD 7.8: default message + an optional line listing resolved files
    message = f"Merge {analysis['source']} into {analysis['target']}"
    if resolved_files:
        message += "\n\nResolved conflicts:\n" + "\n".join(f"- {r['path']}" for r in resolved_files)

    return {
        "is_mock": True,  # remove when Member 3's real git diff is wired in
        "source": analysis["source"],
        "target": analysis["target"],
        "resolved_files": resolved_files,
        "unresolved_files": unresolved_files,
        "diff": "\n".join(diff_parts),
        "default_message": message,
        "can_commit": not unresolved_files,
    }


def validate_commit(
    analysis: dict, resolutions: dict[str, str], message: Any, approved: Any
) -> list[str]:
    """Raise ValueError unless a commit is allowed. Returns the resolved paths.

    PRD: refuse if `approved` is false or any file is unresolved.
    """
    # `is not True` on purpose: the strings "false" or "yes" never count as approval.
    if approved is not True:
        raise ValueError("Commit refused: developer approval is required")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A commit message is required")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError("Commit message is too long")

    resolved = _resolved_paths(analysis, resolutions)
    unresolved = [f["path"] for f in analysis["files"] if f["path"] not in resolved]
    if unresolved:
        raise ValueError("Commit refused: unresolved files: " + ", ".join(unresolved))
    return resolved


def log_resolution(
    repo_id: int,
    source: str,
    target: str,
    files: list[str],
    approved: bool,
    final_commit: str | None,
) -> int:
    """Write one row to resolution_log and return its id."""
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO resolution_log "
            "(repo_id, source_branch, target_branch, files_resolved, final_commit, approved, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo_id, source, target, json.dumps(files), final_commit, int(approved), utc_now()),
        )
        return cur.lastrowid


def mock_commit_result(message: str, files: list[str]) -> dict[str, Any]:
    """MOCK result shape. Member 3 will return the real hash and `git log -3 --oneline`."""
    short = "c0ffee1"
    first_line = message.strip().splitlines()[0]
    return {
        "is_mock": True,
        "commit_hash": (short + "0" * 40)[:40],
        "short_hash": short,
        "message": message.strip(),
        "files_resolved": files,
        "git_log": [f"{short} {first_line}"],
    }