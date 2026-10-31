"""App-wide settings stored in SQLite (settings table, repo_id = 0).

Values are stored as JSON strings so booleans and strings round-trip cleanly.
"""

import json
from typing import Any
from urllib.parse import urlparse

from backend.app.db import connection

APP_WIDE = 0  # repo_id used for settings that do not belong to one repository

DEFAULT_SETTINGS: dict[str, Any] = {
    "evidence_path": ".gitguardian/evidence.json",
    "lm_studio_url": "http://localhost:1234",
    "lm_model": "gemma",
    "gemma_enabled": False,  # PRD 7.7: Gemma is off by default
}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate(key: str, value: Any) -> Any:
    """Return the cleaned value or raise ValueError."""
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"Unknown setting: {key}")

    if key == "gemma_enabled":
        if not isinstance(value, bool):
            raise ValueError("gemma_enabled must be true or false")
        return value

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    value = value.strip()

    if key == "lm_studio_url":
        parsed = urlparse(value)
        # PRD section 10: the only outbound call allowed is to localhost.
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS:
            raise ValueError("lm_studio_url must point to localhost (e.g. http://localhost:1234)")
        value = value.rstrip("/")

    return value


def load_settings() -> dict[str, Any]:
    """Defaults overlaid with whatever is saved in SQLite."""
    merged = dict(DEFAULT_SETTINGS)
    with connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE repo_id = ?", (APP_WIDE,)
        ).fetchall()
    for row in rows:
        if row["key"] in merged:
            merged[row["key"]] = json.loads(row["value"])
    return merged


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Validate every key first, then write them all in one transaction."""
    if not isinstance(updates, dict) or not updates:
        raise ValueError("Provide a dict with at least one setting")

    cleaned = {key: _validate(key, value) for key, value in updates.items()}

    with connection() as conn:
        for key, value in cleaned.items():
            conn.execute(
                "INSERT INTO settings (repo_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(repo_id, key) DO UPDATE SET value = excluded.value",
                (APP_WIDE, key, json.dumps(value)),
            )
    return load_settings()