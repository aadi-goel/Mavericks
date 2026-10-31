"""Repository validation and branch listing (read-only).

Safety rules for this whole module:
  * Git is called with an argument list, never a shell string.
  * Commands that can change history or touch remotes are blocked.
  * Nothing here modifies the working tree, the index, or any branch.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 30

# Git commands this engine must never run.
FORBIDDEN_COMMANDS = {"push", "reset", "clean", "stash", "rebase"}

# Separator used when asking Git for machine-readable output.
_SEP = "\x1f"


class GitError(Exception):
    """Raised when a Git command fails or Git cannot be run."""


def run_git(
    repo_path: str | Path,
    args: list[str],
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run one Git command inside repo_path and return the result.

    args is a list like ["rev-parse", "--show-toplevel"] (without "git").
    If check is True, a non-zero exit code raises GitError.
    """
    if not args:
        raise GitError("No Git command given.")
    if args[0] in FORBIDDEN_COMMANDS:
        raise GitError(f"Blocked: 'git {args[0]}' is not allowed in GitGuardian.")

    folder = Path(repo_path)
    if not folder.is_dir():
        raise GitError(f"Folder does not exist: {folder}")

    env = {
        **os.environ,
        "GIT_OPTIONAL_LOCKS": "0",  # read commands must not write lock files
        "LC_ALL": "C",              # stable English output for parsing
    }

    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(folder),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except FileNotFoundError:
        raise GitError("Git is not installed or not found in PATH.") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"Git command timed out: git {' '.join(args)}") from None

    if check and result.returncode != 0:
        message = result.stderr.strip() or f"git {' '.join(args)} failed"
        raise GitError(message)
    return result


def get_git_version() -> tuple[int, int, int]:
    """Return the installed Git version, e.g. (2, 43, 0)."""
    result = run_git(Path.cwd(), ["--version"])
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", result.stdout)
    if not match:
        raise GitError(f"Could not read Git version from: {result.stdout.strip()}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def supports_merge_tree_write_tree() -> bool:
    """True if Git is 2.38 or newer (needed for merge-tree --write-tree)."""
    major, minor, _ = get_git_version()
    return (major, minor) >= (2, 38)


def validate_repository(path: str | Path) -> dict:
    """Check that path is a usable Git repository.

    Returns a plain dict:
      {"valid": bool, "path": str, "root": str | None,
       "name": str | None, "error": str | None}
    """
    result = {
        "valid": False,
        "path": str(path),
        "root": None,
        "name": None,
        "error": None,
    }

    folder = Path(path).expanduser()
    if not folder.exists():
        result["error"] = "That folder does not exist."
        return result
    if not folder.is_dir():
        result["error"] = "That path is a file, not a folder."
        return result

    try:
        check = run_git(folder, ["rev-parse", "--is-inside-work-tree"], check=False)
    except GitError as exc:
        result["error"] = str(exc)
        return result

    if check.returncode != 0 or check.stdout.strip() != "true":
        result["error"] = "This folder is not a Git repository."
        return result

    try:
        root = run_git(folder, ["rev-parse", "--show-toplevel"]).stdout.strip()
    except GitError as exc:
        result["error"] = str(exc)
        return result

    result["valid"] = True
    result["root"] = root
    result["name"] = Path(root).name
    return result


def get_current_branch(repo_path: str | Path) -> str | None:
    """Return the checked-out branch name, or None if HEAD is detached."""
    result = run_git(repo_path, ["symbolic-ref", "--short", "-q", "HEAD"], check=False)
    name = result.stdout.strip()
    return name or None


def list_branches(repo_path: str | Path, include_remote: bool = True) -> list[dict]:
    """List local branches (and remote-tracking branches if present).

    Each item looks like:
      {"name": "main", "ref": "refs/heads/main", "is_remote": False,
       "is_current": True, "hash": "<full commit hash>"}
    """
    patterns = ["refs/heads"]
    if include_remote:
        patterns.append("refs/remotes")

    fmt = _SEP.join(["%(refname)", "%(refname:short)", "%(objectname)", "%(HEAD)"])
    result = run_git(
        repo_path,
        ["for-each-ref", f"--format={fmt}", *patterns],
    )

    branches: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.split(_SEP)
        if len(parts) != 4:
            continue
        ref, short_name, commit_hash, head_marker = parts

        # Skip pointers like "origin/HEAD"
        if ref.endswith("/HEAD"):
            continue

        branches.append(
            {
                "name": short_name,
                "ref": ref,
                "is_remote": ref.startswith("refs/remotes/"),
                "is_current": head_marker.strip() == "*",
                "hash": commit_hash,
            }
        )

    # Local branches first, then remote; alphabetical inside each group.
    branches.sort(key=lambda b: (b["is_remote"], b["name"]))
    return branches