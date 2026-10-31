import importlib.util
import subprocess
from pathlib import Path

import pytest

from backend.provenance.status import get_commit_evidence

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_repo.py"


def load_seeder():
    spec = importlib.util.spec_from_file_location("seed_demo_repo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


@pytest.fixture
def seeded(tmp_path):
    seeder = load_seeder()
    return seeder, seeder.seed(tmp_path / "demo")


def test_statuses_match_expected(seeded):
    seeder, result = seeded
    for label, expected in seeder.EXPECTED.items():
        got = get_commit_evidence(result["commits"][label], result["evidence_path"])
        assert got["this_commit_evidence"]["status"] == expected, label


def test_cherry_pick_does_not_inherit_original_result(seeded):
    _, result = seeded
    c = result["commits"]
    r = get_commit_evidence(c["prod_cherry_pick"], result["evidence_path"],
                            original_hash=c["dev_verified"])
    assert r["this_commit_evidence"]["status"] == "Unverified"
    assert r["original_commit_evidence"]["status"] == "Verified"


def test_invalid_record_is_counted(seeded):
    _, result = seeded
    r = get_commit_evidence(result["commits"]["dev_verified"], result["evidence_path"])
    assert r["this_commit_evidence"]["evidence_file"]["skipped_count"] == 1


@pytest.mark.parametrize("mode", ["missing", "malformed"])
def test_missing_or_malformed_file_is_unknown(tmp_path, mode):
    seeder = load_seeder()
    result = seeder.seed(tmp_path / "demo", evidence_mode=mode)
    r = get_commit_evidence(result["commits"]["dev_verified"], result["evidence_path"])
    assert r["this_commit_evidence"]["status"] == "Unknown"


def test_working_tree_is_clean_and_cherry_pick_has_trailer(seeded):
    _, result = seeded
    path = result["path"]
    assert git(path, "status", "--porcelain").stdout.strip() == ""
    body = git(path, "log", "-1", "--format=%B", result["commits"]["prod_cherry_pick"]).stdout
    assert f"(cherry picked from commit {result['commits']['dev_verified']})" in body


def test_dev_to_prod_conflicts_and_dev_to_uat_is_clean(seeded):
    _, result = seeded
    path = result["path"]
    conflict = git(path, "merge-tree", "--write-tree", "--name-only", "prod", "dev")
    if conflict.returncode not in (0, 1):
        pytest.skip("git merge-tree --write-tree needs Git 2.38+")
    assert conflict.returncode == 1
    assert "config.py" in conflict.stdout and "notes.txt" in conflict.stdout
    assert git(path, "merge-tree", "--write-tree", "uat", "dev").returncode == 0