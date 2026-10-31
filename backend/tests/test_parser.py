import json

from backend.provenance.parser import load_evidence_file

GOOD = {
    "commit": "a1b2c3d4e5f6",
    "type": "unit",
    "result": "passed",
    "timestamp": "2026-10-31T10:00:00Z",
    "source": "GitHub Actions run 1",
}


def write(tmp_path, payload):
    p = tmp_path / "evidence.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return p


def test_missing_file_is_not_loaded(tmp_path):
    r = load_evidence_file(tmp_path / "nope.json")
    assert r["loaded"] is False and r["error"]


def test_malformed_json_is_not_loaded(tmp_path):
    assert load_evidence_file(write(tmp_path, "{not json"))["loaded"] is False


def test_wrong_schema_version_is_not_loaded(tmp_path):
    p = write(tmp_path, {"schema_version": 2, "records": []})
    assert load_evidence_file(p)["loaded"] is False


def test_valid_file_loads(tmp_path):
    r = load_evidence_file(write(tmp_path, {"schema_version": 1, "records": [GOOD]}))
    assert r["loaded"] and r["records_count"] == 1 and r["skipped_count"] == 0
    assert r["records"][0]["reference"] is None


def test_invalid_records_are_skipped_and_counted(tmp_path):
    bad_result = {**GOOD, "result": "maybe"}
    short_hash = {**GOOD, "commit": "abc12"}
    no_source = {k: v for k, v in GOOD.items() if k != "source"}
    payload = {"schema_version": 1, "records": [GOOD, bad_result, short_hash, no_source, 42]}
    r = load_evidence_file(write(tmp_path, payload))
    assert r["loaded"] and r["records_count"] == 1 and r["skipped_count"] == 4


def test_empty_records_is_loaded(tmp_path):
    r = load_evidence_file(write(tmp_path, {"schema_version": 1, "records": []}))
    assert r["loaded"] and r["records_count"] == 0