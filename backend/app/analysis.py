"""Mock analyze_merge payload (PRD sections 7.3-7.6 and 8).

Member 3 (Git Engine) will supply: conflicted files, hunks, per-side commits,
origin labels. Member 4 (Provenance) will supply: evidence per commit.
Until then this module fakes their combined output in the final JSON shape,
so the frontend can build the Conflict Workspace now and nothing changes
when the real modules are wired in.
"""

from typing import Any

from backend.app.settings import load_settings

# Wording follows PRD 7.5: never claim "unrelated", only "no evidence".
ORIGIN_NONE = {
    "label": "No evidence of relationship",
    "method": "none",
    "original_commit": None,
    "original_in_repo": False,
}


def _h(short: str) -> str:
    """Pad a short hash to a 40-char fake hash."""
    return (short + "0" * 40)[:40]


def _record(rtype: str, result: str, source: str) -> dict[str, Any]:
    return {
        "type": rtype,
        "result": result,
        "timestamp": "2026-10-30T09:00:00Z",
        "source": source,
        "reference": None,
    }


def _evidence(status: str, records: list | None = None, original: dict | None = None):
    """Status is one of Verified / Failed / Unverified / Unknown (PRD 7.6).

    `original` is the cherry-picked original commit's evidence. It is shown
    separately and never transferred to the copy.
    """
    return {"status": status, "records": records or [], "original": original}


def _commit(short, author, message, date, origin, evidence) -> dict[str, Any]:
    return {
        "hash": _h(short),
        "short_hash": short,
        "author": author,
        "message": message,
        "date": date,
        "origin": origin,
        "evidence": evidence,
    }


def _cherry_pick(original_short: str) -> dict[str, Any]:
    return {
        "label": "Cherry-pick reference",
        "method": "cherry_pick_trailer",
        "original_commit": _h(original_short),
        "original_in_repo": True,
    }


def _equivalent_patch(other_short: str) -> dict[str, Any]:
    return {
        "label": "Equivalent patch",
        "method": "patch_id",
        "original_commit": _h(other_short),  # same patch, different hash
        "original_in_repo": True,
    }


# --- File contents (current = target branch, incoming = source branch) -------
PAY_BASE = "def charge(order):\n    return gateway.send(order)\n"
PAY_CURRENT = "def charge(order):\n    return gateway.send(order, timeout=10)\n"
PAY_INCOMING = (
    "def charge(order):\n"
    "    for attempt in range(3):\n"
    "        try:\n"
    "            return gateway.send(order)\n"
    "        except GatewayError:\n"
    "            continue\n"
    "    raise PaymentFailed(order.id)\n"
)

CFG_CURRENT = "RETRY_LIMIT = 5\n"
CFG_INCOMING = "RETRY_LIMIT = 3\nRETRY_DELAY = 2\n"

DOC_BASE = "# Legacy notes\nOld deploy steps.\n"
DOC_CURRENT = "# Legacy notes\nOld deploy steps.\nUpdated for v2 rollout.\n"
DOC_INCOMING = None  # deleted on the source branch


def _build_files() -> list[dict[str, Any]]:
    pay_current_commits = [
        _commit(
            "9f3a1c2", "Aarav Mehta", "Add gateway timeout\n\n(cherry picked from commit 5be07d1)",
            "2026-10-27T14:20:00Z", _cherry_pick("5be07d1"),
            _evidence(
                "Verified",
                [_record("unit", "passed", "GitHub Actions run 1234"),
                 _record("integration", "passed", "GitHub Actions run 1234")],
                original=_evidence("Verified", [_record("unit", "passed", "GitHub Actions run 1180")]),
            ),
        ),
    ]
    pay_incoming_commits = [
        _commit(
            "a1b2c3d", "Demo Developer", "Add retry logic to payment service",
            "2026-10-31T10:00:00Z", _equivalent_patch("77ce1a9"),
            _evidence("Failed", [_record("unit", "failed", "GitHub Actions run 1301")]),
        ),
        _commit(
            "e44d9b0", "Riya Sharma", "Refactor payment error handling",
            "2026-10-29T16:45:00Z", ORIGIN_NONE, _evidence("Unverified"),
        ),
    ]
    cfg_current_commits = [
        _commit("31aa8f6", "Aarav Mehta", "Raise retry limit to 5",
                "2026-10-26T11:10:00Z", ORIGIN_NONE, _evidence("Unverified")),
    ]
    cfg_incoming_commits = [
        _commit("b7c2d19", "Riya Sharma", "Add retry delay setting",
                "2026-10-30T12:00:00Z", ORIGIN_NONE,
                _evidence("Verified", [_record("manual", "passed", "Manual QA sign-off")])),
    ]
    doc_current_commits = [
        _commit("c01dbe5", "Aarav Mehta", "Update legacy notes for v2 rollout",
                "2026-10-25T09:30:00Z", ORIGIN_NONE, _evidence("Unverified")),
    ]
    doc_incoming_commits = [
        _commit("d3adf11", "Riya Sharma", "Remove legacy notes",
                "2026-10-30T17:05:00Z", ORIGIN_NONE, _evidence("Unverified")),
    ]

    return [
        {
            "path": "src/payment_service.py",
            "base_content": PAY_BASE,
            "current_content": PAY_CURRENT,
            "incoming_content": PAY_INCOMING,
            "hunks": [{
                "id": "h1",
                "type": "both_modified",
                "type_label": "Both modified",
                "base_range": [1, 2],
                "current_range": [1, 2],
                "incoming_range": [1, 7],
                "base_content": PAY_BASE,
                "current_content": PAY_CURRENT,
                "incoming_content": PAY_INCOMING,
                "current_commits": pay_current_commits,
                "incoming_commits": pay_incoming_commits,
            }],
        },
        {
            "path": "src/config.py",
            "base_content": None,
            "current_content": CFG_CURRENT,
            "incoming_content": CFG_INCOMING,
            "hunks": [{
                "id": "h1",
                "type": "both_added",
                "type_label": "Both added",
                "base_range": None,
                "current_range": [1, 1],
                "incoming_range": [1, 2],
                "base_content": None,
                "current_content": CFG_CURRENT,
                "incoming_content": CFG_INCOMING,
                "current_commits": cfg_current_commits,
                "incoming_commits": cfg_incoming_commits,
            }],
        },
        {
            "path": "docs/legacy_notes.md",
            "base_content": DOC_BASE,
            "current_content": DOC_CURRENT,
            "incoming_content": DOC_INCOMING,
            "hunks": [{
                "id": "h1",
                "type": "modified_vs_deleted",
                "type_label": "Modified vs deleted",
                "base_range": [1, 2],
                "current_range": [1, 3],
                "incoming_range": None,
                "base_content": DOC_BASE,
                "current_content": DOC_CURRENT,
                "incoming_content": DOC_INCOMING,
                "current_commits": doc_current_commits,
                "incoming_commits": doc_incoming_commits,
            }],
        },
    ]


def build_mock_analysis(repo_id: int, source: str, target: str) -> dict[str, Any]:
    """Final analyze_merge `data` payload, built from mock data."""
    files = _build_files()
    evidence_path = load_settings()["evidence_path"]
    return {
        "is_mock": True,  # remove when Members 3 and 4 are wired in
        "repo_id": repo_id,
        "source": source,
        "target": target,
        "merge_base": _h("0ab12ef"),
        "clean_merge": False,
        "summary": {
            "conflicted_files": len(files),
            "hunks": sum(len(f["hunks"]) for f in files),
        },
        "evidence_file": {
            "path": evidence_path,
            "loaded": True,  # False -> every status becomes Unknown (PRD 7.6)
            "records_found": 5,
            "skipped_records": 0,  # malformed records are skipped and counted
        },
        # PRD risk table: hunk-to-commit mapping is imprecise, so say so.
        "commit_scope_note": "Commits touching this file since the merge base",
        "files": files,
    }