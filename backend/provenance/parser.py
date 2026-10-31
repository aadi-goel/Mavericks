"""Parse and validate .gitguardian/evidence.json (Schema v1).

Rules enforced here:
  * The file is read-only input. We never write or modify it.
  * A missing / unreadable / unparseable file => loaded=False (status engine
    maps this to "Unknown").
  * An invalid individual record is SKIPPED and COUNTED, never guessed at and
    never treated as "passed".
  * This function never raises; every failure comes back as data.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1
VALID_TYPES = frozenset({"unit", "integration", "uat", "manual"})
VALID_RESULTS = frozenset({"passed", "failed"})
MIN_HASH_LEN = 7
_HASH_RE = re.compile(r"^[0-9a-f]{7,64}$")  # SHA-1 (40) or SHA-256 (64)


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string")
    return value.strip()


def _require_timestamp(raw: dict[str, Any]) -> str:
    value = _require_str(raw, "timestamp")
    try:
        datetime.fromisoformat(value)  # Python 3.11+ accepts the trailing "Z"
    except ValueError:
        raise ValueError("'timestamp' is not a valid ISO 8601 date-time") from None
    return value


def _require_commit(raw: dict[str, Any]) -> str:
    value = _require_str(raw, "commit").lower()
    if not _HASH_RE.match(value):
        raise ValueError(
            f"'commit' must be a hex hash of at least {MIN_HASH_LEN} characters"
        )
    return value


def _validate_record(raw: Any) -> dict[str, Any]:
    """Return a normalized test-evidence record or raise ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("record is not a JSON object")

    rec_type = _require_str(raw, "type")
    if rec_type not in VALID_TYPES:
        raise ValueError(f"'type' must be one of {sorted(VALID_TYPES)}")

    result = _require_str(raw, "result")
    if result not in VALID_RESULTS:
        raise ValueError(f"'result' must be one of {sorted(VALID_RESULTS)}")

    reference = raw.get("reference")
    if reference is not None and not isinstance(reference, str):
        raise ValueError("'reference' must be a string when present")

    return {
        "commit": _require_commit(raw),
        "type": rec_type,
        "result": result,
        "timestamp": _require_timestamp(raw),
        "source": _require_str(raw, "source"),
        "reference": reference,
    }


def _validate_deployment(raw: Any) -> dict[str, Any]:
    """Deployment records are display-only; never proof of testing."""
    if not isinstance(raw, dict):
        raise ValueError("deployment is not a JSON object")
    return {
        "commit": _require_commit(raw),
        "environment": _require_str(raw, "environment"),
        "timestamp": _require_timestamp(raw),
        "status": _require_str(raw, "status"),
    }


def _failure(path: str, error: str) -> dict[str, Any]:
    return {
        "loaded": False,
        "path": path,
        "schema_version": None,
        "records": [],
        "deployments": [],
        "records_count": 0,
        "deployments_count": 0,
        "skipped_count": 0,
        "skipped": [],
        "error": error,
    }


def load_evidence_file(path: str | Path) -> dict[str, Any]:
    """Load and validate an evidence file.

    Returns a dict:
        loaded            True only if the file was read and has a valid envelope
        path              the path that was attempted
        schema_version    int, or None if not loaded
        records           list of valid, normalized test-evidence records
        deployments       list of valid deployment records (display only)
        records_count     len(records)
        deployments_count len(deployments)
        skipped_count     number of invalid entries skipped (records + deployments)
        skipped           [{"section", "index", "reason"}, ...]
        error             None, or a short message when loaded is False
    """
    path_str = str(path)

    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _failure(path_str, "Evidence file not found")
    except (OSError, UnicodeDecodeError) as exc:
        return _failure(path_str, f"Evidence file could not be read: {exc}")
    except Exception as exc:  # defensive: bad path types etc. must not crash the app
        return _failure(path_str, f"Unexpected error reading evidence file: {exc}")

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        return _failure(path_str, f"Evidence file is not valid JSON: {exc}")

    if not isinstance(data, dict):
        return _failure(path_str, "Evidence file must contain a JSON object")

    version = data.get("schema_version")
    if isinstance(version, bool) or version != SUPPORTED_SCHEMA_VERSION:
        return _failure(
            path_str,
            f"Unsupported or missing schema_version (expected {SUPPORTED_SCHEMA_VERSION})",
        )

    raw_records = data.get("records")
    if not isinstance(raw_records, list):
        return _failure(path_str, "'records' must be an array")

    records: list[dict[str, Any]] = []
    deployments: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, raw in enumerate(raw_records):
        try:
            records.append(_validate_record(raw))
        except (ValueError, TypeError) as exc:
            skipped.append({"section": "records", "index": index, "reason": str(exc)})

    raw_deployments = data.get("deployments", [])
    if not isinstance(raw_deployments, list):
        skipped.append(
            {"section": "deployments", "index": None, "reason": "'deployments' must be an array"}
        )
        raw_deployments = []

    for index, raw in enumerate(raw_deployments):
        try:
            deployments.append(_validate_deployment(raw))
        except (ValueError, TypeError) as exc:
            skipped.append({"section": "deployments", "index": index, "reason": str(exc)})

    return {
        "loaded": True,
        "path": path_str,
        "schema_version": version,
        "records": records,
        "deployments": deployments,
        "records_count": len(records),
        "deployments_count": len(deployments),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "error": None,
    }