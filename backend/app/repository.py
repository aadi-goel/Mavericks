"""Repository registration and the dummy open_repository payload.

Member 3 (Git Engine) will replace build_dummy_repo_info() with real Git data.
The shape below follows PRD sections 7.1 and 8 so the frontend does not change.
"""

from pathlib import Path
from typing import Any

from backend.app.db import connection, utc_now


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


def build_dummy_repo_info(repo_id: int, repo_path: Path) -> dict[str, Any]:
    """Placeholder data so the frontend can build the Dashboard now."""
    return {
        "is_mock": True,  # remove when Member 3's real data is wired in
        "repo_id": repo_id,
        "path": str(repo_path.resolve()),
        "name": repo_path.resolve().name,
        "current_branch": "dev",
        "latest_commit": {
            "hash": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
            "short_hash": "a1b2c3d",
            "message": "Add retry logic to payment service",
            "author": "Demo Developer",
            "date": "2026-10-31T10:00:00Z",
        },
        "branches": [
            {"name": "dev", "is_current": True},
            {"name": "uat", "is_current": False},
            {"name": "prod", "is_current": False},
        ],
        "counts": {"branches": 3, "commits_scanned": 42, "evidence_records": 5},
        # Banner shape, e.g. {"code": "dirty_worktree", "message": "..."}
        "warnings": [],
    }