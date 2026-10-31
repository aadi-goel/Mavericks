"""GitGuardian Git Engine.

Talks to a local Git repository using the Git CLI and returns plain,
JSON-serializable Python dictionaries to the Backend Orchestrator.
"""

from .repo_ops import (
    GitError,
    get_current_branch,
    get_git_version,
    list_branches,
    run_git,
    supports_merge_tree_write_tree,
    validate_repository,
)

__all__ = [
    "GitError",
    "get_current_branch",
    "get_git_version",
    "list_branches",
    "run_git",
    "supports_merge_tree_write_tree",
    "validate_repository",
]