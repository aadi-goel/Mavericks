"""Commit history and branch comparison (read-only).

Everything here only READS from Git. Nothing changes the working tree,
the index, or any branch.
"""

from __future__ import annotations

from pathlib import Path

from .repo_ops import GitError, run_git

# Separators so we can split Git's output safely.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"

# %H = full hash, %s = subject line, %an = author name,
# %aI = author date (ISO 8601), %P = parent hashes (space separated)
_LOG_FORMAT = "%H%x1f%s%x1f%an%x1f%aI%x1f%P%x1e"


def _resolve_commit(repo_path: str | Path, name: str) -> str:
    """Turn a branch name (or hash) into a full commit hash.

    Raises GitError if it does not exist.
    """
    if not name or name.startswith("-"):
        raise GitError(f"Invalid branch name: {name!r}")

    result = run_git(
        repo_path,
        ["rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"],
        check=False,
    )
    commit_hash = result.stdout.strip()
    if result.returncode != 0 or not commit_hash:
        raise GitError(f"Branch or commit not found: {name}")
    return commit_hash


def _parse_commits(output: str) -> list[dict]:
    """Convert raw `git log` output into a list of commit dictionaries."""
    commits: list[dict] = []
    for record in output.split(_RECORD_SEP):
        record = record.lstrip("\r\n")
        if not record:
            continue
        parts = record.split(_FIELD_SEP)
        if len(parts) != 5:
            continue
        commit_hash, message, author, date, parents = parts
        commits.append(
            {
                "hash": commit_hash,
                "short_hash": commit_hash[:7],
                "message": message,
                "author": author,
                "date": date,
                "parents": parents.split(),
                "tags": [],  # relationship tags are filled in later
            }
        )
    return commits


def _read_commits(
    repo_path: str | Path,
    revisions: list[str],
    limit: int,
) -> list[dict]:
    """Run `git log` for the given revisions and parse the result."""
    result = run_git(
        repo_path,
        ["log", f"--format={_LOG_FORMAT}", "-n", str(limit), *revisions, "--"],
    )
    return _parse_commits(result.stdout)


def list_commits(repo_path: str | Path, branch: str, limit: int = 50) -> list[dict]:
    """Return the newest commits of a branch (newest first).

    Each commit: {"hash", "short_hash", "message", "author", "date",
                  "parents", "tags"}
    """
    if not isinstance(limit, int) or limit < 1:
        raise GitError("limit must be a positive whole number.")

    branch_hash = _resolve_commit(repo_path, branch)
    return _read_commits(repo_path, [branch_hash], limit)


def _cherry_equivalents(
    repo_path: str | Path,
    upstream_hash: str,
    head_hash: str,
) -> set[str]:
    """Find commits on head that already exist on upstream as an equivalent patch.

    `git cherry` prints "+ <hash>" for commits with no equivalent upstream
    and "- <hash>" for commits that DO have an equivalent upstream.
    """
    result = run_git(repo_path, ["cherry", upstream_hash, head_hash])
    equivalent: set[str] = set()
    for line in result.stdout.splitlines():
        pieces = line.split()
        if len(pieces) == 2 and pieces[0] == "-":
            equivalent.add(pieces[1])
    return equivalent


def compare_branches(
    repo_path: str | Path,
    source: str,
    target: str,
    max_commits: int = 500,
) -> dict:
    """Compare two branches.

    Returns:
      {
        "source": str, "target": str,
        "merge_base": hash or None,
        "only_in_source": [commit, ...],   # commits to be merged in
        "only_in_target": [commit, ...],
        "counts": {"only_in_source": int, "only_in_target": int}
      }
    A commit tagged "equivalent_patch" has a different hash but the same
    change exists on the other branch.
    """
    source_hash = _resolve_commit(repo_path, source)
    target_hash = _resolve_commit(repo_path, target)

    only_in_source = _read_commits(repo_path, [f"{target_hash}..{source_hash}"], max_commits)
    only_in_target = _read_commits(repo_path, [f"{source_hash}..{target_hash}"], max_commits)

    # Source commits that already exist on target as an equivalent patch
    same_in_target = _cherry_equivalents(repo_path, target_hash, source_hash)
    # Target commits that already exist on source as an equivalent patch
    same_in_source = _cherry_equivalents(repo_path, source_hash, target_hash)

    for commit in only_in_source:
        if commit["hash"] in same_in_target:
            commit["tags"].append("equivalent_patch")
    for commit in only_in_target:
        if commit["hash"] in same_in_source:
            commit["tags"].append("equivalent_patch")

    base_result = run_git(repo_path, ["merge-base", target_hash, source_hash], check=False)
    merge_base = base_result.stdout.strip() or None

    return {
        "source": source,
        "target": target,
        "merge_base": merge_base,
        "only_in_source": only_in_source,
        "only_in_target": only_in_target,
        "counts": {
            "only_in_source": len(only_in_source),
            "only_in_target": len(only_in_target),
        },
    }