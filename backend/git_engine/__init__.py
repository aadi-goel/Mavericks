"""GitGuardian Git Engine.

Talks to a local Git repository using the Git CLI and returns plain,
JSON-serializable Python dictionaries to the Backend Orchestrator.
"""

from .history import compare_branches, list_commits
from .matcher import (
    annotate_analysis,
    annotate_commits,
    find_relationships,
    list_commits_tagged,
    match_branches,
    parse_cherry_pick_trailers,
)
from .merger import analyze_merge, map_hunks_to_commits, parse_conflict_hunks
from .repo_ops import (
    GitError,
    check_ready_to_commit,
    create_merge_commit,
    get_current_branch,
    get_git_version,
    get_working_tree_status,
    list_branches,
    run_git,
    supports_merge_tree_write_tree,
    validate_repository,
)

__all__ = [
    "GitError",
    "analyze_merge",
    "annotate_analysis",
    "annotate_commits",
    "check_ready_to_commit",
    "compare_branches",
    "create_merge_commit",
    "find_relationships",
    "get_current_branch",
    "get_git_version",
    "get_working_tree_status",
    "list_branches",
    "list_commits",
    "list_commits_tagged",
    "map_hunks_to_commits",
    "match_branches",
    "parse_cherry_pick_trailers",
    "parse_conflict_hunks",
    "run_git",
    "supports_merge_tree_write_tree",
    "validate_repository",
]