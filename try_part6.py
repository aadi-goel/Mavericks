import subprocess
import tempfile
from pathlib import Path

from backend.git_engine import GitError, create_merge_commit, get_working_tree_status


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def expect_blocked(label, action):
    try:
        action()
        print(f"{label}: NOT blocked (unexpected!)")
    except GitError as error:
        print(f"{label}: blocked -> {error}")


MESSAGE = "Merge feature into main"
MAIN_APP = "line1\nmain line2\nline3\n"
RESOLUTIONS = {"app.py": "line1\nresolved line2\nline3\n", "old.txt": None}

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    repo = Path(tmp)
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    # Base commit
    (repo / "app.py").write_text("line1\nline2\nline3\n")
    (repo / "old.txt").write_text("old file\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    # feature edits app.py and old.txt
    git(repo, "checkout", "-b", "feature")
    (repo / "app.py").write_text("line1\nfeature line2\nline3\n")
    (repo / "old.txt").write_text("changed on feature\n")
    git(repo, "commit", "-am", "feature edits")

    # main edits app.py differently and deletes old.txt
    git(repo, "checkout", "main")
    (repo / "app.py").write_text(MAIN_APP)
    git(repo, "rm", "old.txt")
    git(repo, "commit", "-am", "main edits")

    print("=== Blocked cases ===")

    # 1. No approval
    expect_blocked("no approval", lambda: create_merge_commit(
        repo, "feature", "main", MESSAGE, False, RESOLUTIONS))

    # 2. Uncommitted change in the working tree
    (repo / "app.py").write_text("dirty change\n")
    print("is_clean:", get_working_tree_status(repo)["is_clean"])
    expect_blocked("dirty tree", lambda: create_merge_commit(
        repo, "feature", "main", MESSAGE, True, RESOLUTIONS))
    print("changes untouched:", (repo / "app.py").read_text() == "dirty change\n")
    git(repo, "checkout", "--", "app.py")

    # 3. Target branch is not checked out
    git(repo, "checkout", "feature")
    expect_blocked("target not checked out", lambda: create_merge_commit(
        repo, "feature", "main", MESSAGE, True, RESOLUTIONS))
    git(repo, "checkout", "main")

    # 4. Conflicted files without a resolution
    expect_blocked("unresolved file", lambda: create_merge_commit(
        repo, "feature", "main", MESSAGE, True, {}))
    merge_head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=repo, capture_output=True
    )
    print(
        "merge cleaned up:", merge_head.returncode != 0,
        "| status clean:", git(repo, "status", "--porcelain") == "",
        "| app.py unchanged:", (repo / "app.py").read_text() == MAIN_APP,
    )

    # 5. Success
    print("\n=== Approved merge with resolutions ===")
    result = create_merge_commit(repo, "feature", "main", MESSAGE, True, RESOLUTIONS)
    print("commit:", result["short_hash"], "| parents:", len(result["parents"]),
          "| is_merge_commit:", result["is_merge_commit"], "| pushed:", result["pushed"])
    print("log:")
    for line in result["log"]:
        print("  ", line)
    print("git status clean:", git(repo, "status", "--porcelain") == "")
    print("app.py has our resolution:", (repo / "app.py").read_text() == RESOLUTIONS["app.py"])
    print("old.txt deleted:", not (repo / "old.txt").exists())