"""Dry-run merge and conflict detection (the core feature).

Safety rules:
  * The user's working tree, index and branches are never modified.
  * Main method: `git merge-tree --write-tree` (Git 2.38+). Git works out
    the merge in its object database only.
  * Fallback for older Git: a temporary worktree in a temp folder. The
    merge is tried there and the worktree is deleted afterwards.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from .history import _LOG_FORMAT, _parse_commits, _resolve_commit, compare_branches
from .repo_ops import GitError, run_git, supports_merge_tree_write_tree

# Conflict marker lines written by Git.
_MARK_START = re.compile(r"^<{7}(?: .*)?$")
_MARK_BASE = re.compile(r"^\|{7}(?: .*)?$")
_MARK_MIDDLE = re.compile(r"^={7}$")
_MARK_END = re.compile(r"^>{7}(?: .*)?$")

# How many commits to list per side, per file.
MAX_COMMITS_PER_SIDE = 100


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _find_merge_base(repo_path, target_hash: str, source_hash: str) -> str:
    """Return the common ancestor commit of the two branches."""
    result = run_git(repo_path, ["merge-base", target_hash, source_hash], check=False)
    base = result.stdout.strip()
    if result.returncode != 0 or not base:
        raise GitError("These two branches have no common history, so they cannot be merged.")
    return base.splitlines()[0]


def _read_blob(repo_path, revision: str | None, path: str) -> str | None:
    """Read a file's text from a commit or tree. Returns None if it does not exist."""
    if revision is None:
        return None
    result = run_git(repo_path, ["cat-file", "blob", f"{revision}:{path}"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def _count_lines(text: str | None) -> int:
    if not text:
        return 1
    return max(1, text.count("\n") + (0 if text.endswith("\n") else 1))


def _classify(base: str | None, current: str | None, incoming: str | None) -> str:
    """Simple rule-based label for a conflict (no AI)."""
    if current is None or incoming is None:
        return "modified_vs_deleted"
    if base is None:
        return "both_added"
    return "both_modified"


# ---------------------------------------------------------------------------
# Conflict marker parsing
# ---------------------------------------------------------------------------

def parse_conflict_hunks(text: str, conflict_type: str = "both_modified") -> list[dict]:
    """Find conflict blocks in text that contains Git conflict markers.

    Line numbers are 1-based and refer to the text you pass in.
    Each hunk:
      {"id", "type", "start_line", "end_line",
       "current_range": [first, last], "incoming_range": [first, last],
       "current_text", "incoming_text", "base_text", "synthetic": False}
    start_line / end_line are the marker lines themselves.
    An empty side has a range where last < first.
    """
    hunks: list[dict] = []
    state = None  # None, "current", "base" or "incoming"
    start = base_marker = middle = 0
    current: list[str] = []
    base: list[str] = []
    incoming: list[str] = []

    for number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.rstrip("\r")

        if state is None:
            if _MARK_START.match(line):
                state = "current"
                start, base_marker, middle = number, 0, 0
                current, base, incoming = [], [], []
            continue

        if state == "current" and _MARK_BASE.match(line):
            state = "base"
            base_marker = number
        elif state in ("current", "base") and _MARK_MIDDLE.match(line):
            state = "incoming"
            middle = number
        elif state == "incoming" and _MARK_END.match(line):
            current_last = (base_marker or middle) - 1
            hunks.append(
                {
                    "id": len(hunks),
                    "type": conflict_type,
                    "start_line": start,
                    "end_line": number,
                    "current_range": [start + 1, current_last],
                    "incoming_range": [middle + 1, number - 1],
                    "current_text": "\n".join(current),
                    "incoming_text": "\n".join(incoming),
                    "base_text": "\n".join(base) if base_marker else None,
                    "synthetic": False,
                }
            )
            state = None
        elif state == "current":
            current.append(line)
        elif state == "base":
            base.append(line)
        else:
            incoming.append(line)

    return hunks


def _whole_file_hunk(
    base: str | None,
    current: str | None,
    incoming: str | None,
    conflict_type: str,
) -> dict:
    """Used when Git gives no markers (for example modified vs deleted).

    The whole file is treated as one hunk.
    """
    surviving = current if current is not None else incoming
    return {
        "id": 0,
        "type": conflict_type,
        "start_line": 1,
        "end_line": _count_lines(surviving),
        "current_range": None,
        "incoming_range": None,
        "current_text": current,
        "incoming_text": incoming,
        "base_text": base,
        "synthetic": True,
    }


# ---------------------------------------------------------------------------
# The two ways of doing the dry run
# ---------------------------------------------------------------------------

def _dry_run_merge_tree(repo_path, target_hash: str, source_hash: str) -> tuple[str, list[str]]:
    """Main method. Returns (merged_tree_hash, conflicted_file_paths)."""
    result = run_git(
        repo_path,
        ["merge-tree", "--write-tree", "--name-only", "-z", target_hash, source_hash],
        check=False,
    )
    # Exit code 0 = clean merge, 1 = conflicts, anything else = real error.
    if result.returncode not in (0, 1):
        raise GitError(result.stderr.strip() or "git merge-tree failed.")

    output = result.stdout
    match = re.match(r"[0-9a-f]+", output)
    if not match:
        raise GitError("Could not read the result of git merge-tree.")
    tree_hash = match.group(0)

    names: list[str] = []
    if result.returncode == 1:
        # After the tree hash come the conflicted file names, NUL-separated,
        # ending at the first empty entry.
        for name in output[match.end() + 1:].split("\0"):
            if name == "":
                break
            names.append(name)
    return tree_hash, names


def _dry_run_worktree(repo_path, target_hash: str, source_hash: str) -> tuple[list[str], dict[str, str]]:
    """Fallback for Git older than 2.38.

    Merges inside a temporary worktree (a throwaway copy in a temp folder),
    reads the conflicted files, then deletes everything.
    Returns (conflicted_file_paths, {path: text_with_markers}).
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="gitguardian-"))
    worktree = temp_dir / "worktree"
    try:
        run_git(repo_path, ["worktree", "add", "--detach", str(worktree), target_hash])

        merge = run_git(
            worktree,
            ["merge", "--no-commit", "--no-ff", source_hash],
            check=False,
        )
        # Exit code 0 = clean, 1 = conflicts, anything else = real error.
        if merge.returncode not in (0, 1):
            raise GitError(merge.stderr.strip() or "Temporary merge failed.")

        listing = run_git(worktree, ["diff", "--name-only", "--diff-filter=U", "-z"])
        names = [name for name in listing.stdout.split("\0") if name]

        marked: dict[str, str] = {}
        for name in names:
            file_path = worktree / name
            if file_path.is_file():
                marked[name] = file_path.read_text(encoding="utf-8", errors="replace")

        run_git(worktree, ["merge", "--abort"], check=False)
        return names, marked
    finally:
        run_git(repo_path, ["worktree", "remove", "--force", str(worktree)], check=False)
        shutil.rmtree(temp_dir, ignore_errors=True)
        run_git(repo_path, ["worktree", "prune"], check=False)


# ---------------------------------------------------------------------------
# Building the result
# ---------------------------------------------------------------------------

def _build_conflict_file(
    repo_path,
    path: str,
    merge_base: str,
    target_hash: str,
    source_hash: str,
    marked_text: str | None,
) -> dict:
    base = _read_blob(repo_path, merge_base, path)
    current = _read_blob(repo_path, target_hash, path)
    incoming = _read_blob(repo_path, source_hash, path)
    conflict_type = _classify(base, current, incoming)

    is_binary = any("\x00" in text for text in (base, current, incoming, marked_text) if text)
    if is_binary:
        return {
            "path": path,
            "conflict_type": conflict_type,
            "is_binary": True,
            "base_content": None,
            "current_content": None,
            "incoming_content": None,
            "result_with_markers": None,
            "hunks": [],
            "current_commits": [],
            "incoming_commits": [],
        }

    hunks = parse_conflict_hunks(marked_text, conflict_type) if marked_text else []
    if not hunks:
        hunks = [_whole_file_hunk(base, current, incoming, conflict_type)]

    return {
        "path": path,
        "conflict_type": conflict_type,
        "is_binary": False,
        "base_content": base,
        "current_content": current,      # target side
        "incoming_content": incoming,    # source side
        "result_with_markers": marked_text,
        "hunks": hunks,
        "current_commits": [],
        "incoming_commits": [],
    }


# ---------------------------------------------------------------------------
# Part 4: map hunks to the commits responsible
# ---------------------------------------------------------------------------

def _commits_touching_file(
    repo_path,
    merge_base: str,
    branch_hash: str,
    path: str,
    limit: int = MAX_COMMITS_PER_SIDE,
) -> list[dict]:
    """Commits on a branch, made after the merge base, that changed one file.

    This is `git log <merge-base>..<branch> -- <file>`. A commit that deleted
    the file is included too.
    """
    result = run_git(
        repo_path,
        [
            "log",
            f"--format={_LOG_FORMAT}",
            "-n",
            str(limit),
            f"{merge_base}..{branch_hash}",
            "--",
            path,
        ],
    )
    return _parse_commits(result.stdout)


def map_hunks_to_commits(
    repo_path,
    conflicted_files: list[dict],
    merge_base: str,
    target_hash: str,
    source_hash: str,
) -> list[dict]:
    """Add the responsible commits to every conflicted file and hunk.

    For each file:
      file["current_commits"]  = commits on the TARGET side touching this file
      file["incoming_commits"] = commits on the SOURCE side touching this file
    Every hunk in the file gets the same two lists, plus
      hunk["mapping_precision"] = "commits_touching_file"
    so the UI can honestly label them "commits touching this file".
    """
    for conflict_file in conflicted_files:
        path = conflict_file["path"]
        current_commits = _commits_touching_file(repo_path, merge_base, target_hash, path)
        incoming_commits = _commits_touching_file(repo_path, merge_base, source_hash, path)

        conflict_file["current_commits"] = current_commits
        conflict_file["incoming_commits"] = incoming_commits

        for hunk in conflict_file["hunks"]:
            hunk["current_commits"] = current_commits
            hunk["incoming_commits"] = incoming_commits
            hunk["mapping_precision"] = "commits_touching_file"

    return conflicted_files


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def analyze_merge(
    repo_path,
    source: str,
    target: str,
    force_worktree: bool = False,
) -> dict:
    """Dry-run merge of `source` into `target`. Nothing in the repo is changed.

    Returns:
      {
        "source", "target", "source_hash", "target_hash", "merge_base",
        "method": "merge-tree" | "worktree",
        "has_conflicts": bool,
        "merged_tree": hash or None,
        "conflicted_files": [ {path, conflict_type, is_binary,
                               base_content, current_content,
                               incoming_content, result_with_markers,
                               hunks: [...],
                               current_commits: [...],
                               incoming_commits: [...]}, ... ],
        "summary": {...}
      }
    """
    source_hash = _resolve_commit(repo_path, source)
    target_hash = _resolve_commit(repo_path, target)
    merge_base = _find_merge_base(repo_path, target_hash, source_hash)

    use_merge_tree = supports_merge_tree_write_tree() and not force_worktree

    merged_tree: str | None = None
    marked_by_path: dict[str, str] = {}

    if use_merge_tree:
        method = "merge-tree"
        merged_tree, names = _dry_run_merge_tree(repo_path, target_hash, source_hash)
        for name in names:
            text = _read_blob(repo_path, merged_tree, name)
            if text is not None:
                marked_by_path[name] = text
    else:
        method = "worktree"
        names, marked_by_path = _dry_run_worktree(repo_path, target_hash, source_hash)

    conflicted_files = [
        _build_conflict_file(
            repo_path, name, merge_base, target_hash, source_hash, marked_by_path.get(name)
        )
        for name in names
    ]

    # Part 4: attach the responsible commits to every file and hunk.
    map_hunks_to_commits(repo_path, conflicted_files, merge_base, target_hash, source_hash)

    has_conflicts = bool(conflicted_files)
    commits_to_merge = compare_branches(repo_path, source, target)["counts"]["only_in_source"]
    hunk_count = sum(len(f["hunks"]) for f in conflicted_files)

    summary: dict = {
        "conflicted_file_count": len(conflicted_files),
        "hunk_count": hunk_count,
        "commits_to_merge": commits_to_merge,
    }

    if has_conflicts:
        summary["message"] = (
            f"{len(conflicted_files)} conflicted file(s), {hunk_count} conflict hunk(s)."
        )
    elif commits_to_merge == 0:
        summary["message"] = f"Nothing to merge: '{source}' is already included in '{target}'."
    else:
        listing = run_git(repo_path, ["diff", "--name-only", "-z", merge_base, source_hash])
        summary["files_changed_by_source"] = [n for n in listing.stdout.split("\0") if n]
        summary["message"] = (
            f"Clean merge: no conflicts. {commits_to_merge} commit(s) from "
            f"'{source}' can be merged into '{target}'."
        )

    return {
        "source": source,
        "target": target,
        "source_hash": source_hash,
        "target_hash": target_hash,
        "merge_base": merge_base,
        "method": method,
        "has_conflicts": has_conflicts,
        "merged_tree": merged_tree,
        "conflicted_files": conflicted_files,
        "summary": summary,
    }