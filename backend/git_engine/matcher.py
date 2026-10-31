"""Origin and patch matching (read-only).

Layered, cheapest first. The first layer that matches wins:
  1. Commit ancestry            -> "Same commit"
  2. (cherry picked from ...)   -> "Cherry-pick reference"
  3. git patch-id --stable      -> "Equivalent patch"
  4. nothing matched            -> "No evidence of relationship"

"No evidence" is NOT proof that two changes are unrelated.
Only the most recent `window` commits are checked (default 200).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .history import _resolve_commit, compare_branches, list_commits
from .repo_ops import GIT_TIMEOUT_SECONDS, GitError, run_git

DEFAULT_WINDOW = 200

_TRAILER = re.compile(r"\(cherry picked from commit ([0-9a-f]{7,64})\)", re.IGNORECASE)
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"

# tag -> (level, method, label)
_LEVELS = {
    "same_commit": (1, "ancestry", "Same commit"),
    "cherry_pick_reference": (2, "cherry_pick_trailer", "Cherry-pick reference"),
    "equivalent_patch": (3, "patch_id", "Equivalent patch"),
    "no_evidence_of_relationship": (4, None, "No evidence of relationship"),
}
RELATIONSHIP_TAGS = set(_LEVELS)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _short(commit_hash: str) -> str:
    return commit_hash[:7]


def _relationship(
    tag: str,
    note: str,
    related_hash: str | None = None,
    original_hash: str | None = None,
    original_exists: bool | None = None,
    direction: str | None = None,
) -> dict:
    level, method, label = _LEVELS[tag]
    return {
        "level": level,
        "method": method,
        "label": label,
        "tag": tag,
        "related_hash": related_hash,        # the matching commit on the OTHER branch
        "original_hash": original_hash,      # for cherry-picks: the original commit
        "original_exists": original_exists,  # is the original in this repository?
        "direction": direction,              # "copy_of" or "original_of" (cherry-picks)
        "note": note,
    }


def parse_cherry_pick_trailers(message: str) -> list[str]:
    """Return every hash named in '(cherry picked from commit <hash>)' lines."""
    return [found.lower() for found in _TRAILER.findall(message)]


def _parse_messages(output: str) -> list[tuple[str, str]]:
    """Turn raw `git log --format=%H%x1f%B%x1e` output into (hash, message) pairs."""
    entries: list[tuple[str, str]] = []
    for record in output.split(_RECORD_SEP):
        record = record.lstrip("\r\n")
        if not record:
            continue
        commit_hash, _, message = record.partition(_FIELD_SEP)
        entries.append((commit_hash, message))
    return entries


def _read_messages(repo_path, hashes: list[str]) -> dict[str, str]:
    """Full commit messages for the given commits."""
    if not hashes:
        return {}
    result = run_git(
        repo_path,
        ["log", "--no-walk=unsorted", "--format=%H%x1f%B%x1e", *hashes, "--"],
    )
    return dict(_parse_messages(result.stdout))


def _recent_messages(repo_path, branch_hash: str, window: int) -> list[tuple[str, str]]:
    """The newest `window` commits of a branch as (hash, message), newest first."""
    result = run_git(
        repo_path,
        ["log", "-n", str(window), "--format=%H%x1f%B%x1e", branch_hash, "--"],
    )
    return _parse_messages(result.stdout)


def _reachable_from(repo_path, hashes: list[str], other_hash: str) -> set[str]:
    """Which of these commits are already part of the other branch's history?"""
    result = run_git(repo_path, ["rev-list", *hashes, "--not", other_hash, "--"])
    not_reachable = set(result.stdout.split())
    return {h for h in hashes if h not in not_reachable}


def _is_ancestor(repo_path, commit_hash: str, branch_hash: str) -> bool:
    result = run_git(
        repo_path, ["merge-base", "--is-ancestor", commit_hash, branch_hash], check=False
    )
    return result.returncode == 0


def _resolve_optional(repo_path, ref: str) -> str | None:
    """Full hash of ref if that commit exists in this repo, else None."""
    result = run_git(
        repo_path, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False
    )
    found = result.stdout.strip()
    return found if result.returncode == 0 and found else None


# ---------------------------------------------------------------------------
# Layer 3: patch-id
# ---------------------------------------------------------------------------

def _compute_patch_ids(repo_path, hashes: list[str]) -> dict[str, str]:
    """Return {commit_hash: patch_id} using `git patch-id --stable`.

    Merge commits and empty commits have no patch-id and are left out.
    """
    if not hashes:
        return {}

    log = run_git(
        repo_path,
        [
            "log", "--no-walk=unsorted", "-p",
            "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--no-decorate", "--no-abbrev-commit",
            *hashes, "--",
        ],
    )
    if not log.stdout.strip():
        return {}

    # run_git cannot pipe text into Git, so this one command runs here.
    try:
        result = subprocess.run(
            ["git", "patch-id", "--stable"],
            input=log.stdout,
            cwd=str(Path(repo_path)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise GitError("Git is not installed or not found in PATH.") from None
    except subprocess.TimeoutExpired:
        raise GitError("git patch-id timed out.") from None
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git patch-id failed.")

    ids: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            patch_id, commit_hash = parts
            ids[commit_hash] = patch_id
    return ids


# ---------------------------------------------------------------------------
# Layer 2: cherry-pick trailers
# ---------------------------------------------------------------------------

def _trailer_relationship(
    repo_path,
    commit_hash: str,
    message: str,
    other_hash: str,
    copies: list[tuple[str, str]],
) -> dict | None:
    """Check both directions of a cherry-pick link.

    copies = [(original_hash_named_in_trailer, copy_commit_on_other_branch), ...]
    """
    # (a) This commit says it is a copy of an original.
    refs = parse_cherry_pick_trailers(message)
    if refs:
        infos = []
        for ref in refs:
            full = _resolve_optional(repo_path, ref)
            on_other = bool(full) and _is_ancestor(repo_path, full, other_hash)
            infos.append((ref, full, on_other))
        ref, full, on_other = next((i for i in infos if i[2]), infos[-1])

        note = f"Cherry-picked from {_short(full or ref)}"
        if on_other:
            note += "; the original is on the other branch."
        elif full:
            note += "; the original is not on the other branch."
        else:
            note += "; the original commit was not found in this repository."

        return _relationship(
            "cherry_pick_reference",
            note,
            related_hash=full if on_other else None,
            original_hash=full or ref,
            original_exists=bool(full),
            direction="copy_of",
        )

    # (b) A commit on the other branch says it is a copy of THIS commit.
    for ref, copy_hash in copies:
        if len(ref) >= 7 and commit_hash.startswith(ref):
            return _relationship(
                "cherry_pick_reference",
                f"Copied to the other branch as {_short(copy_hash)} (cherry-pick reference).",
                related_hash=copy_hash,
                original_hash=commit_hash,
                original_exists=True,
                direction="original_of",
            )
    return None


# ---------------------------------------------------------------------------
# The layered matcher
# ---------------------------------------------------------------------------

def find_relationships(
    repo_path,
    commits: list[dict],
    other_branch: str,
    window: int = DEFAULT_WINDOW,
) -> list[dict]:
    """For each commit, find how it relates to `other_branch`.

    Returns one relationship dict per commit, in the same order.
    """
    if not commits:
        return []

    other_hash = _resolve_commit(repo_path, other_branch)
    hashes = [c["hash"] for c in commits]
    results: dict[str, dict] = {}

    # Layer 1: ancestry
    for h in _reachable_from(repo_path, hashes, other_hash):
        results[h] = _relationship(
            "same_commit",
            "This exact commit is already part of the other branch.",
            related_hash=h,
        )

    pending = [h for h in hashes if h not in results]
    other_messages: list[tuple[str, str]] = []

    if pending:
        other_messages = _recent_messages(repo_path, other_hash, window)

        # Layer 2: cherry-pick trailers
        own_messages = _read_messages(repo_path, pending)
        copies = [
            (ref, copy_hash)
            for copy_hash, message in other_messages
            for ref in parse_cherry_pick_trailers(message)
        ]
        for h in pending:
            found = _trailer_relationship(
                repo_path, h, own_messages.get(h, ""), other_hash, copies
            )
            if found:
                results[h] = found

    # Layer 3: patch-id
    pending = [h for h in hashes if h not in results]
    if pending:
        to_check = pending[:window]
        checking = set(to_check)
        candidate_hashes = [h for h, _ in other_messages if h not in checking]

        own_ids = _compute_patch_ids(repo_path, to_check)
        if own_ids:
            candidate_ids = _compute_patch_ids(repo_path, candidate_hashes)
            by_patch_id: dict[str, str] = {}
            for h in candidate_hashes:
                patch_id = candidate_ids.get(h)
                if patch_id:
                    by_patch_id.setdefault(patch_id, h)

            for h in to_check:
                patch_id = own_ids.get(h)
                if patch_id and patch_id in by_patch_id:
                    match = by_patch_id[patch_id]
                    results[h] = _relationship(
                        "equivalent_patch",
                        f"Same change as {_short(match)} on the other branch "
                        "(different commit hash).",
                        related_hash=match,
                    )

    # Layer 4: nothing matched. Worded carefully on purpose.
    for h in hashes:
        if h not in results:
            results[h] = _relationship(
                "no_evidence_of_relationship",
                "No evidence of a relationship was found "
                "(this does not prove the changes are unrelated).",
            )

    return [results[h] for h in hashes]


def annotate_commits(
    repo_path,
    commits: list[dict],
    other_branch: str,
    window: int = DEFAULT_WINDOW,
) -> list[dict]:
    """Add "relationship" and a relationship tag to each commit dict (in place)."""
    relationships = find_relationships(repo_path, commits, other_branch, window)
    for commit, relationship in zip(commits, relationships):
        commit["relationship"] = relationship
        tags = [t for t in commit.get("tags", []) if t not in RELATIONSHIP_TAGS]
        tags.append(relationship["tag"])
        commit["tags"] = tags
    return commits


# ---------------------------------------------------------------------------
# Convenience functions for the Backend
# ---------------------------------------------------------------------------

def list_commits_tagged(
    repo_path,
    branch: str,
    other_branch: str,
    limit: int = 50,
    window: int = DEFAULT_WINDOW,
) -> list[dict]:
    """Commits of `branch`, each tagged by how it relates to `other_branch`."""
    commits = list_commits(repo_path, branch, limit)
    return annotate_commits(repo_path, commits, other_branch, window)


def match_branches(
    repo_path,
    source: str,
    target: str,
    window: int = DEFAULT_WINDOW,
) -> dict:
    """compare_branches() result with the layered relationship tags filled in."""
    comparison = compare_branches(repo_path, source, target)
    annotate_commits(repo_path, comparison["only_in_source"], target, window)
    annotate_commits(repo_path, comparison["only_in_target"], source, window)
    return comparison


def annotate_analysis(repo_path, analysis: dict, window: int = DEFAULT_WINDOW) -> dict:
    """Add relationships to the commits inside an analyze_merge() result.

    Target-side commits are compared with the source branch, and
    source-side commits are compared with the target branch.
    """
    sides = (
        ("current_commits", analysis["source"]),
        ("incoming_commits", analysis["target"]),
    )
    for key, other_branch in sides:
        unique: dict[str, dict] = {}
        for conflict_file in analysis["conflicted_files"]:
            for commit in conflict_file[key]:
                unique.setdefault(commit["hash"], commit)
        if not unique:
            continue

        annotate_commits(repo_path, list(unique.values()), other_branch, window)

        # The same commit can appear (as a separate dict) in several files.
        for conflict_file in analysis["conflicted_files"]:
            for commit in conflict_file[key]:
                first = unique[commit["hash"]]
                if commit is not first:
                    commit["relationship"] = first["relationship"]
                    commit["tags"] = list(first["tags"])
    return analysis