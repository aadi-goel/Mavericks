import subprocess

from backend.app.db import init_db
from backend.app.main import BridgeAPI
from scripts.seed_demo_repo import seed


def git(path, *args):
    return subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("GG_DB_PATH", str(tmp_path / "gitguardian.db"))
    init_db()
    result = seed(tmp_path / "demo")
    git(result["path"], "config", "user.name", "Presentation Test")
    git(result["path"], "config", "user.email", "presentation@example.test")
    api = BridgeAPI()
    opened = api.open_repository(str(result["path"]))
    assert opened["ok"], opened
    return api, result


def test_bridge_reads_real_repo_and_detects_conflicts(tmp_path, monkeypatch):
    api, result = demo(tmp_path, monkeypatch)

    branches = api.list_branches()
    assert branches["ok"]
    assert {branch["name"] for branch in branches["data"]} == {"dev", "prod", "uat"}

    commits = api.list_commits("dev")
    assert commits["ok"]
    assert any(commit["test_status"] == "Failed" for commit in commits["data"])

    analysis = api.analyze_merge("dev", "prod")
    assert analysis["ok"], analysis
    assert {file["path"] for file in analysis["data"]["files"]} == {
        "config.py", "notes.txt",
    }
    assert analysis["data"]["clean_merge"] is False
    conflict_evidence = analysis["data"]["files"][0]["hunks"][0]["evidence"]
    origins = {item["origin"] for item in conflict_evidence}
    statuses = {item["test_status"] for item in conflict_evidence}
    assert any("Cherry-pick reference" in origin for origin in origins)
    assert any("Equivalent patch" in origin for origin in origins)
    assert {"Verified", "Failed", "Unverified"} <= statuses
    original_evidence = [
        item["original"]["status"] for item in conflict_evidence if item["original"]
    ]
    assert "Verified" in original_evidence
    assert git(result["path"], "status", "--porcelain") == ""


def test_bridge_previews_and_creates_real_merge_commit(tmp_path, monkeypatch):
    api, result = demo(tmp_path, monkeypatch)
    analysis = api.analyze_merge("dev", "prod")
    assert analysis["ok"], analysis
    files = analysis["data"]["files"]
    resolutions = {
        file["path"]: (
            None if file["path"] == "notes.txt" else file["incoming_content"]
        )
        for file in files
    }

    preview = api.preview_commit(resolutions)
    assert preview["ok"], preview
    assert preview["data"]["can_commit"] is True
    assert "config.py" in preview["data"]["diff"]
    assert "notes.txt" in {file["path"] for file in preview["data"]["resolved_files"]}

    committed = api.commit_resolution(
        "Resolve demo conflicts", approved=True, resolutions=resolutions
    )
    assert committed["ok"], committed
    data = committed["data"]
    assert data["is_merge_commit"] is True
    assert data["pushed"] is False
    assert len(data["parents"]) == 2
    assert git(result["path"], "rev-parse", "HEAD") == data["commit_hash"]
    assert git(result["path"], "status", "--porcelain") == ""
    assert not (result["path"] / "notes.txt").exists()
    assert len(git(result["path"], "log", "-1", "--format=%P", "HEAD").split()) == 2


def test_clean_merge_is_reported_with_reviewable_diff(tmp_path, monkeypatch):
    api, result = demo(tmp_path, monkeypatch)
    analysis = api.analyze_merge("dev", "uat")
    assert analysis["ok"], analysis
    assert analysis["data"]["clean_merge"] is True
    assert analysis["data"]["files"] == []

    preview = api.preview_commit({})
    assert preview["ok"], preview
    assert preview["data"]["can_commit"] is True
    assert "helpers.py" in preview["data"]["diff"]

    git(result["path"], "checkout", "uat")
    committed = api.commit_resolution("Merge dev into uat", approved=True, resolutions={})
    assert committed["ok"], committed
    assert committed["data"]["is_merge_commit"] is True
    assert len(committed["data"]["parents"]) == 2
    assert git(result["path"], "status", "--porcelain") == ""


def test_commit_refuses_dirty_target_without_changing_user_file(tmp_path, monkeypatch):
    api, result = demo(tmp_path, monkeypatch)
    analysis = api.analyze_merge("dev", "prod")
    assert analysis["ok"]
    resolutions = {file["path"]: file["incoming_content"] for file in analysis["data"]["files"]}

    readme = result["path"] / "README.md"
    original = readme.read_text(encoding="utf-8")
    readme.write_text(original + "local edit\n", encoding="utf-8")
    untracked = result["path"] / "untracked.txt"
    untracked.write_text("keep this file\n", encoding="utf-8")

    committed = api.commit_resolution(
        "Must not commit", approved=True, resolutions=resolutions
    )
    assert committed["ok"] is False
    assert "Uncommitted changes" in committed["error"]
    assert readme.read_text(encoding="utf-8") == original + "local edit\n"
    assert untracked.read_text(encoding="utf-8") == "keep this file\n"
    assert git(result["path"], "rev-parse", "HEAD") == result["commits"]["prod_delete_notes"]
