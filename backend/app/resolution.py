"""Manual resolution + commit approval flow (PRD sections 7.8 and 8).

Session edits live in memory (BridgeAPI._resolutions). Preview generation is
read-only; only the explicitly approved commit path writes to the Git worktree.
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


def validate_resolution_data(analysis: dict, resolutions: dict[str, str | None]) -> None:
    if not isinstance(resolutions, dict):
        raise ValueError("resolutions must be an object")
    allowed = {file["path"] for file in analysis["files"]}
    unknown = set(resolutions) - allowed
    if unknown:
        raise ValueError("Resolution provided for non-conflicted files: " + ", ".join(sorted(unknown)))
    for path, content in resolutions.items():
        if not isinstance(path, str) or not path:
            raise ValueError("Resolution file paths must be non-empty strings")
        if content is not None and not isinstance(content, str):
            raise ValueError(f"Resolution for {path} must be text or a file deletion")
        if content is not None:
            try:
                size = len(content.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise ValueError(f"Resolution for {path} is not valid UTF-8 text") from exc
            if size > MAX_CONTENT_BYTES:
                raise ValueError(f"Resolution for {path} is too large (max 5 MB)")


def _resolved_paths(analysis: dict, resolutions: dict[str, str | None]) -> list[str]:
    return [
        f["path"]
        for f in analysis["files"]
        if f["path"] in resolutions
        and (resolutions[f["path"]] is None or not has_conflict_markers(resolutions[f["path"]]))
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


def build_preview(analysis: dict, resolutions: dict[str, str | None]) -> dict[str, Any]:
    """Diff the edited conflict files against target content."""
    validate_resolution_data(analysis, resolutions)
    resolved_files: list[dict[str, Any]] = []
    unresolved_files: list[dict[str, str]] = []
    diff_parts: list[str] = []

    for f in analysis["files"]:
        path = f["path"]
        if path not in resolutions:
            unresolved_files.append({"path": path, "reason": "not_resolved"})
            continue
        content = resolutions[path]
        if content is not None and has_conflict_markers(content):
            unresolved_files.append({"path": path, "reason": "conflict_markers"})
            continue

        target_text = f["current_content"] or ""
        result_text = content or ""
        diff_lines = list(
            difflib.unified_diff(
                target_text.splitlines(),
                result_text.splitlines(),
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
        "source": analysis["source"],
        "target": analysis["target"],
        "resolved_files": resolved_files,
        "unresolved_files": unresolved_files,
        "diff": "\n".join(diff_parts),
        "default_message": message,
        "can_commit": not unresolved_files,
    }


def validate_commit(
    analysis: dict, resolutions: dict[str, str | None], message: Any, approved: Any
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
    validate_resolution_data(analysis, resolutions)

    binary = [f["path"] for f in analysis["files"] if f.get("is_binary")]
    if binary:
        raise ValueError(
            "Binary conflicts cannot be resolved in the app: " + ", ".join(binary)
        )

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