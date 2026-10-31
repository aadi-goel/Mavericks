import json

from backend.provenance.status import get_commit_evidence

A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
B = "b2c3d4e5f60718293a4b5c6d7e8f901234567890"


def rec(commit, result, type_="unit"):
    return {
        "commit": commit, "type": type_, "result": result,
        "timestamp": "2026-10-31T10:00:00Z", "source": "test",
    }


def evidence(tmp_path, records, **extra):
    p = tmp_path / "evidence.json"
    p.write_text(json.dumps({"schema_version": 1, "records": records, **extra}))
    return p


def test_verified(tmp_path):
    p = evidence(tmp_path, [rec(A, "passed")])
    assert get_commit_evidence(A, p)["status"] == "Verified"


def test_failed_beats_passed(tmp_path):
    p = evidence(tmp_path, [rec(A, "passed"), rec(A, "failed", "integration")])
    r = get_commit_evidence(A, p)
    assert r["status"] == "Failed" and r["passed_count"] == 1 and r["failed_count"] == 1


def test_unverified_when_no_records_for_commit(tmp_path):
    p = evidence(tmp_path, [rec(B, "passed")])
    assert get_commit_evidence(A, p)["status"] == "Unverified"


def test_unverified_when_file_has_no_records(tmp_path):
    assert get_commit_evidence(A, evidence(tmp_path, []))["status"] == "Unverified"


def test_unknown_when_file_missing(tmp_path):
    assert get_commit_evidence(A, tmp_path / "nope.json")["status"] == "Unknown"


def test_unknown_when_file_malformed(tmp_path):
    p = tmp_path / "evidence.json"
    p.write_text("{broken")
    assert get_commit_evidence(A, p)["status"] == "Unknown"


def test_prefix_match_both_directions(tmp_path):
    assert get_commit_evidence(A[:7], evidence(tmp_path, [rec(A, "passed")]))["status"] == "Verified"
    assert get_commit_evidence(A, evidence(tmp_path, [rec(A[:7], "failed")]))["status"] == "Failed"


def test_prefix_shorter_than_7_is_rejected(tmp_path):
    r = get_commit_evidence(A[:6], evidence(tmp_path, [rec(A, "passed")]))
    assert r["status"] == "Unknown" and r["error"]


def test_ambiguous_prefix_does_not_blend_commits(tmp_path):
    c1, c2 = "abcdef1" + "0" * 33, "abcdef1" + "9" * 33
    p = evidence(tmp_path, [rec(c1, "passed"), rec(c2, "failed")])
    r = get_commit_evidence("abcdef1", p)
    assert r["status"] == "Unknown" and "ambiguous" in r["error"]


def test_deployment_is_not_verification(tmp_path):
    dep = {"commit": A, "environment": "production",
           "timestamp": "2026-10-31T10:00:00Z", "status": "deployed"}
    r = get_commit_evidence(A, evidence(tmp_path, [], deployments=[dep]))
    assert r["status"] == "Unverified" and len(r["deployments"]) == 1


def test_skipped_records_are_reported_not_trusted(tmp_path):
    bad = {**rec(A, "passed"), "result": "success"}  # invalid value
    r = get_commit_evidence(A, evidence(tmp_path, [bad]))
    assert r["status"] == "Unverified" and r["evidence_file"]["skipped_count"] == 1