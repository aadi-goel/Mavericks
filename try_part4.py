import subprocess
import tempfile
from pathlib import Path

from backend.git_engine.merger import analyze_merge


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def commit_file(repo, name, text, message):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    repo = Path(tmp)
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    # Base commit
    (repo / "app.py").write_text("line1\nline2\nline3\n")
    (repo / "old.txt").write_text("old file\n")
    (repo / "other.txt").write_text("other\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    # feature: 3 commits (only 2 touch conflicted files)
    git(repo, "checkout", "-b", "feature")
    commit_file(repo, "app.py", "line1\nfeature line2\nline3\n", "feature: change app line2")
    commit_file(repo, "other.txt", "other changed\n", "feature: edit other.txt")
    commit_file(repo, "old.txt", "changed on feature\n", "feature: edit old.txt")

    # main: 2 commits
    git(repo, "checkout", "main")
    commit_file(repo, "app.py", "line1\nmain line2\nline3\n", "main: change app line2")
    git(repo, "rm", "old.txt")
    git(repo, "commit", "-m", "main: delete old.txt")

    result = analyze_merge(repo, "feature", "main")
    print("summary:", result["summary"]["message"])

    all_messages = []
    for f in result["conflicted_files"]:
        current = [c["message"] for c in f["current_commits"]]
        incoming = [c["message"] for c in f["incoming_commits"]]
        all_messages += current + incoming
        print(f"\n- {f['path']} ({f['conflict_type']})")
        print(f"    current  (main)   : {current}")
        print(f"    incoming (feature): {incoming}")
        for h in f["hunks"]:
            same = [c["hash"] for c in h["current_commits"]] == [c["hash"] for c in f["current_commits"]]
            print(f"    hunk {h['id']}: precision={h['mapping_precision']}, has same commits as file: {same}")

    print("\nunrelated commit left out:", "feature: edit other.txt" not in all_messages)