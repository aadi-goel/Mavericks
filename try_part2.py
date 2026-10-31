import json
import subprocess
import tempfile
from pathlib import Path

from backend.git_engine.history import compare_branches, list_commits


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit_file(repo, name, text, message):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-m", message)


with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    commit_file(repo, "a.txt", "one\n", "base commit")

    git(repo, "checkout", "-b", "feature")
    commit_file(repo, "b.txt", "feature work\n", "add b")
    commit_file(repo, "c.txt", "only on feature\n", "add c")

    git(repo, "checkout", "main")
    commit_file(repo, "d.txt", "only on main\n", "add d on main")
    git(repo, "cherry-pick", "feature~1")  # copies "add b" onto main

    print("=== list_commits(main) ===")
    for c in list_commits(repo, "main", 10):
        print(c["short_hash"], c["message"], c["parents"] and "" or "(root)")

    print("\n=== compare_branches(feature -> main) ===")
    result = compare_branches(repo, "feature", "main")
    print("counts:", result["counts"])
    for side in ("only_in_source", "only_in_target"):
        print(side)
        for c in result[side]:
            print("  ", c["short_hash"], c["message"], c["tags"])