import json

from backend.provenance.status import get_commit_evidence

COPY = "c0a1b2c3d4e5f60718293a4b5c6d7e8f90123456"
ORIG = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def rec(commit, result):
    return {
        "commit": commit, "type": "unit", "result": result,
        "timestamp": "2026-10-31T10:00:00Z", "source": "test",
    }


def evidence(tmp_path, records):
    p = tmp_path / "evidence.json"
    p.write_text(json.dumps({"schema_version": 1, "records": records}))
    return p


def test_original_tested_copy_not_is_not_transferred(tmp_path):
    r = get_commit_evidence(COPY, evidence(tmp_path, [rec(ORIG, "passed")]), original_hash=ORIG)
    assert r["is_cherry_pick"] is True
    assert r["this_commit_evidence"]["status"] == "Unverified"
    assert r["original_commit_evidence"]["status"] == "Verified"


def test_copy_failed_original_passed_stay_separate(tmp_path):
    p = evidence(tmp_path, [rec(ORIG, "passed"), rec(COPY, "failed")])
    r = get_commit_evidence(COPY, p, original_hash=ORIG)
    assert r["this_commit_evidence"]["status"] == "Failed"
    assert r["original_commit_evidence"]["status"] == "Verified"


def test_records_are_not_blended(tmp_path):
    p = evidence(tmp_path, [rec(ORIG, "passed"), rec(COPY, "failed")])
    r = get_commit_evidence(COPY, p, original_hash=ORIG)
    assert {x["commit"] for x in r["this_commit_evidence"]["records"]} == {COPY}
    assert {x["commit"] for x in r["original_commit_evidence"]["records"]} == {ORIG}


def test_no_original_hash_means_no_original_block(tmp_path):
    r = get_commit_evidence(COPY, evidence(tmp_path, [rec(COPY, "passed")]))
    assert r["is_cherry_pick"] is False and r["original_commit_evidence"] is None


def test_invalid_original_does_not_affect_copy(tmp_path):
    r = get_commit_evidence(COPY, evidence(tmp_path, [rec(COPY, "passed")]), original_hash="zz")
    assert r["this_commit_evidence"]["status"] == "Verified"
    assert r["original_commit_evidence"]["status"] == "Unknown"


def test_missing_file_gives_unknown_for_both(tmp_path):
    r = get_commit_evidence(COPY, tmp_path / "nope.json", original_hash=ORIG)
    assert r["this_commit_evidence"]["status"] == "Unknown"
    assert r["original_commit_evidence"]["status"] == "Unknown"


def test_same_commit_as_original_is_not_a_cherry_pick(tmp_path):
    r = get_commit_evidence(ORIG, evidence(tmp_path, [rec(ORIG, "passed")]), original_hash=ORIG[:7])
    assert r["is_cherry_pick"] is False and r["original_commit_evidence"] is None