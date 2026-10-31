import subprocess
import tempfile
from pathlib import Path

from backend.git_engine.merger import analyze_merge


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    repo = Path(tmp)
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    # 1. Base commit
    (repo / "app.py").write_text("line1\nline2\nline3\n")
    (repo / "old.txt").write_text("old file\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    # 2. feature: edits app.py line 2 and edits old.txt
    git(repo, "checkout", "-b", "feature")
    (repo / "app.py").write_text("line1\nfeature line2\nline3\n")
    (repo / "old.txt").write_text("changed on feature\n")
    git(repo, "commit", "-am", "feature edits")

    # 3. main: edits app.py line 2 differently and deletes old.txt
    git(repo, "checkout", "main")
    (repo / "app.py").write_text("line1\nmain line2\nline3\n")
    git(repo, "rm", "old.txt")
    git(repo, "commit", "-am", "main edits")

    # 4. clean-branch: only adds a new file
    git(repo, "checkout", "-b", "clean-branch", base)
    (repo / "new.txt").write_text("brand new\n")
    git(repo, "add", "new.txt")
    git(repo, "commit", "-m", "add new.txt")
    git(repo, "checkout", "main")

    status_before = git(repo, "status", "--porcelain")
    app_before = (repo / "app.py").read_text()

    print("=== Conflict test: feature -> main ===")
    result = analyze_merge(repo, "feature", "main")
    print("method:", result["method"])
    print("has_conflicts:", result["has_conflicts"])
    print("summary:", result["summary"]["message"])
    for f in result["conflicted_files"]:
        print(f"- {f['path']} ({f['conflict_type']})")
        for h in f["hunks"]:
            print(f"    hunk {h['id']}: lines {h['start_line']}-{h['end_line']} synthetic={h['synthetic']}")
            print(f"      current : {h['current_text']!r}")
            print(f"      incoming: {h['incoming_text']!r}")

    print("\n=== Clean test: clean-branch -> main ===")
    clean = analyze_merge(repo, "clean-branch", "main")
    print("has_conflicts:", clean["has_conflicts"])
    print("summary:", clean["summary"]["message"])
    print("files:", clean["summary"].get("files_changed_by_source"))

    print("\n=== Fallback (temporary worktree) test ===")
    fallback = analyze_merge(repo, "feature", "main", force_worktree=True)
    same = sorted(f["path"] for f in fallback["conflicted_files"]) == sorted(
        f["path"] for f in result["conflicted_files"]
    )
    print("method:", fallback["method"], "| same conflicted files:", same)

    print("\n=== Safety check ===")
    print("status unchanged:", git(repo, "status", "--porcelain") == status_before)
    print("app.py unchanged:", (repo / "app.py").read_text() == app_before)
    print("current branch:", git(repo, "branch", "--show-current"))
    print("leftover worktrees:", len(git(repo, "worktree", "list").splitlines()) - 1)