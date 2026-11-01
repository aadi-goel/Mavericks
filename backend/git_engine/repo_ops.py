"""Repository validation, branch listing and safe merge-commit creation.

Safety rules for this whole module:
  * Git is called with an argument list, never a shell string.
  * Commands that can discard work or touch remotes are blocked.
  * Everything is read-only EXCEPT create_merge_commit(), which only runs
    after explicit approval and aborts the merge if anything goes wrong.
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

# A leftover conflict marker line (start or end of a conflict block).
_CONFLICT_MARKER = re.compile(r"^(?:<{7}|>{7})(?: .*)?$")


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


# ---------------------------------------------------------------------------
# Part 6: safe wrappers for creating the final merge commit
# ---------------------------------------------------------------------------

def _rev_parse_commit(repo_path: str | Path, name: str) -> str | None:
    """Full commit hash for a branch name, or None if it does not exist."""
    if not name or name.startswith("-"):
        return None
    result = run_git(
        repo_path, ["rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"], check=False
    )
    found = result.stdout.strip()
    return found if result.returncode == 0 and found else None


def _has_conflict_markers(text: str) -> bool:
    return any(_CONFLICT_MARKER.match(line.rstrip("\r")) for line in text.split("\n"))


def get_working_tree_status(repo_path: str | Path) -> dict:
    """Describe uncommitted changes. Read-only.

    Returns:
      {"is_clean": bool,                 # no tracked or untracked user changes
       "tracked_changes": [{"status": "M", "path": "app.py"}, ...],
       "untracked_files": [path, ...],   # brand-new files Git does not track
       "merge_in_progress": bool}
    """
    result = run_git(
        repo_path, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    entries = result.stdout.split("\0")

    tracked: list[dict] = []
    untracked: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            index += 1  # a renamed/copied entry is followed by the old path
        if code == "??":
            untracked.append(path)
        elif code == "!!":
            continue
        else:
            tracked.append({"status": code.strip(), "path": path})

    merge_head = run_git(
        repo_path, ["rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False
    )
    return {
        "is_clean": not tracked and not untracked,
        "tracked_changes": tracked,
        "untracked_files": untracked,
        "merge_in_progress": merge_head.returncode == 0,
    }


def check_ready_to_commit(repo_path: str | Path, source: str, target: str) -> dict:
    """Run every safety check before a merge commit. Read-only.

    Returns:
      {"ready": bool, "problems": [str], "warnings": [str],
       "root": str | None, "current_branch": str | None, "status": dict | None}
    """
    problems: list[str] = []
    warnings: list[str] = []
    report = {
        "ready": False,
        "problems": problems,
        "warnings": warnings,
        "root": None,
        "current_branch": None,
        "status": None,
    }

    validation = validate_repository(repo_path)
    if not validation["valid"]:
        problems.append(validation["error"])
        return report

    root = validation["root"]
    report["root"] = root

    status = get_working_tree_status(root)
    report["status"] = status
    if status["merge_in_progress"]:
        problems.append("A merge is already in progress. Finish or abort it with Git first.")

    current = get_current_branch(root)
    report["current_branch"] = current
    if current != target:
        problems.append(
            f"Target branch '{target}' is not checked out "
            f"(current branch: {current or 'detached HEAD'}). "
            "Check it out yourself first; GitGuardian never switches branches for you."
        )

    if not status["is_clean"]:
        paths = [
            change["path"] for change in status["tracked_changes"]
        ] + status["untracked_files"]
        listed = ", ".join(paths[:5])
        if len(paths) > 5:
            listed += f", and {len(paths) - 5} more"
        problems.append(
            f"Uncommitted changes found ({len(paths)}): {listed or 'unknown paths'}. "
            "Commit or save them yourself first; "
            "GitGuardian never stashes or discards your changes."
        )

    source_hash = _rev_parse_commit(root, source)
    target_hash = _rev_parse_commit(root, target)
    if source_hash is None:
        problems.append(f"Source branch not found: {source}")
    if target_hash is None:
        problems.append(f"Target branch not found: {target}")
    if source_hash and target_hash:
        already = run_git(
            root, ["merge-base", "--is-ancestor", source_hash, target_hash], check=False
        )
        if already.returncode == 0:
            problems.append(f"Nothing to merge: '{source}' is already part of '{target}'.")

    if status["untracked_files"]:
        warnings.append(
            f"{len(status['untracked_files'])} untracked file(s) present. They are left "
            "alone, but the merge stops if one of them would be overwritten."
        )

    report["ready"] = not problems
    return report


def create_merge_commit(
    repo_path: str | Path,
    source: str,
    target: str,
    message: str,
    approved: bool,
    resolutions: dict[str, str | None] | None = None,
) -> dict:
    """Create the final merge commit (two parents) on the checked-out target branch.

    resolutions maps each conflicted file path to its final text.
    Use None as the text to resolve a modified-vs-deleted conflict by deleting the file.

    Raises GitError (and leaves the repository exactly as it was) if:
      * approved is not True, or the message is empty
      * any safety check in check_ready_to_commit() fails
      * a conflicted file has no resolution, or still has conflict markers
      * Git itself refuses (for example a failing commit hook)
    This function never pushes anything.
    """
    if approved is not True:
        raise GitError("Developer approval is required before a commit can be created.")
    if not message or not message.strip():
        raise GitError("A commit message is required.")
    resolutions = dict(resolutions or {})

    report = check_ready_to_commit(repo_path, source, target)
    if not report["ready"]:
        raise GitError(" ".join(report["problems"]))

    root = report["root"]
    source_hash = _rev_parse_commit(root, source)

    try:
        # Start the real merge but do not commit yet.
        merge = run_git(
            root, ["merge", "--no-commit", "--no-ff", source_hash], check=False
        )
        started = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False)
        if started.returncode != 0:
            raise GitError(
                (merge.stderr or merge.stdout).strip() or "Git could not start the merge."
            )

        listing = run_git(root, ["diff", "--name-only", "--diff-filter=U", "-z"])
        conflicted = [name for name in listing.stdout.split("\0") if name]

        unresolved = [name for name in conflicted if name not in resolutions]
        if unresolved:
            raise GitError(
                "These conflicted files still need a resolution: "
                + ", ".join(sorted(unresolved))
            )

        not_in_conflict = [path for path in resolutions if path not in conflicted]
        if not_in_conflict:
            raise GitError(
                "These files are not in conflict, so they cannot be resolved here: "
                + ", ".join(sorted(not_in_conflict))
            )

        with_markers = [
            path
            for path, text in resolutions.items()
            if text is not None and _has_conflict_markers(text)
        ]
        if with_markers:
            raise GitError(
                "Conflict markers are still present in: " + ", ".join(sorted(with_markers))
            )

        # Write each resolved file and tell Git it is resolved.
        for path, text in resolutions.items():
            if text is None:
                run_git(root, ["rm", "-q", "--", path])
            else:
                file_path = Path(root) / path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
                run_git(root, ["add", "--", path])

        leftover = run_git(root, ["diff", "--name-only", "--diff-filter=U", "-z"])
        if any(leftover.stdout.split("\0")):
            raise GitError("Some files are still marked as conflicted after resolving.")

        # A normal Git commit. Because a merge is in progress, it gets two parents.
        run_git(root, ["commit", "-m", message])
    except Exception:
        # Put everything back exactly as it was before we started.
        run_git(root, ["merge", "--abort"], check=False)
        raise

    head = run_git(root, ["rev-list", "--parents", "-n", "1", "HEAD"]).stdout.split()
    commit_hash, parents = head[0], head[1:]
    log_lines = run_git(root, ["log", "-3", "--oneline"]).stdout.splitlines()

    return {
        "commit_hash": commit_hash,
        "short_hash": commit_hash[:7],
        "parents": parents,
        "is_merge_commit": len(parents) == 2,
        "branch": target,
        "message": message,
        "resolved_files": sorted(resolutions),
        "log": log_lines,
        "pushed": False,
    }