"""SQLite cache and log for GitGuardian (PRD Section 9).

Git and the evidence file stay the source of truth. This database is only a
local cache and log, so it can be deleted and rebuilt at any time.

Every table is keyed by repo_id to keep repositories isolated. In `settings`,
repo_id = 0 means an app-wide setting (for example the LM Studio URL).
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

log = logging.getLogger("gitguardian.db")

SCHEMA_VERSION = 1
DEFAULT_DB_DIR = Path.home() / ".gitguardian"
DB_FILENAME = "gitguardian.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repository (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    path           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    last_opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commit_cache (
    repo_id   INTEGER NOT NULL REFERENCES repository(id) ON DELETE CASCADE,
    hash      TEXT NOT NULL,
    author    TEXT,
    message   TEXT,
    timestamp TEXT,
    parents   TEXT,            -- JSON list of parent hashes
    patch_id  TEXT,
    PRIMARY KEY (repo_id, hash)
);

CREATE TABLE IF NOT EXISTS evidence_record (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     INTEGER NOT NULL REFERENCES repository(id) ON DELETE CASCADE,
    commit_hash TEXT NOT NULL,
    type        TEXT,          -- unit | integration | uat | manual
    result      TEXT NOT NULL CHECK (result IN ('passed', 'failed')),
    timestamp   TEXT,
    source      TEXT,
    reference   TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_repo_commit
    ON evidence_record (repo_id, commit_hash);

CREATE TABLE IF NOT EXISTS ai_cache (
    repo_id     INTEGER NOT NULL REFERENCES repository(id) ON DELETE CASCADE,
    input_hash  TEXT NOT NULL,
    explanation TEXT NOT NULL,
    model       TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (repo_id, input_hash)
);

CREATE TABLE IF NOT EXISTS resolution_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER NOT NULL REFERENCES repository(id) ON DELETE CASCADE,
    source_branch   TEXT NOT NULL,
    target_branch   TEXT NOT NULL,
    files_resolved  TEXT,      -- JSON list of file paths
    final_commit    TEXT,      -- NULL until the merge commit exists
    approved        INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resolution_repo
    ON resolution_log (repo_id);

CREATE TABLE IF NOT EXISTS settings (
    repo_id INTEGER NOT NULL DEFAULT 0,   -- 0 = app-wide
    key     TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (repo_id, key)
);
"""

TABLES = (
    "repository",
    "commit_cache",
    "evidence_record",
    "ai_cache",
    "resolution_log",
    "settings",
)


def utc_now() -> str:
    """ISO-8601 UTC timestamp, e.g. 2026-11-01T09:30:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db_path() -> Path:
    """~/.gitguardian/gitguardian.db, or the GG_DB_PATH env var if set."""
    override = os.environ.get("GG_DB_PATH")
    return Path(override).expanduser() if override else DEFAULT_DB_DIR / DB_FILENAME


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a new connection with foreign keys on and dict-like rows.

    pywebview runs each bridge call on its own thread and SQLite connections
    must not be shared across threads, so open one per call via `connection()`.
    """
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, always close.

        with connection() as conn:
            conn.execute("INSERT ...")
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> Path:
    """Create all tables if missing. Safe to call on every startup."""
    path = Path(db_path) if db_path else get_db_path()
    with connection(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    log.info("SQLite ready at %s", path)
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_file = init_db()
    with connection(db_file) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    print(f"DB: {db_file}")
    print("Tables:", ", ".join(r["name"] for r in rows))