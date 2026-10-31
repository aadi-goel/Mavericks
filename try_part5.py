import subprocess
import tempfile
from pathlib import Path

from backend.git_engine.matcher import (
    annotate_analysis,
    list_commits_tagged,
    match_branches,
)
from backend.git_engine.merger import analyze_merge


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def commit_file(repo, name, text, message):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def show(commits):
    for c in commits:
        r = c["relationship"]
        print(f"  {c['message']:<16} {r['tag']:<28} level {r['level']}  {r['note']}")


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    repo = Path(tmp)
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    (repo / "app.py").write_text("line1\nline2\nline3\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base commit")

    # feature branch
    git(repo, "checkout", "-b", "feature")
    f1 = commit_file(repo, "b.txt", "bbb\n", "add b")
    f2 = commit_file(repo, "c.txt", "ccc\n", "add c")
    commit_file(repo, "e.txt", "eee\n", "add e")
    commit_file(repo, "app.py", "line1\nfeature line2\nline3\n", "feature: app line2")

    # main branch
    git(repo, "checkout", "main")
    commit_file(repo, "d.txt", "ddd\n", "add d on main")
    git(repo, "cherry-pick", "-x", f1)   # copy WITH the trailer
    git(repo, "cherry-pick", f2)         # copy WITHOUT the trailer
    commit_file(repo, "app.py", "line1\nmain line2\nline3\n", "main: app line2")

    print("=== match_branches: feature -> main ===")
    result = match_branches(repo, "feature", "main")
    print("only in source (feature):")
    show(result["only_in_source"])
    print("only in target (main):")
    show(result["only_in_target"])

    print("\n=== list_commits_tagged: feature compared with main ===")
    for c in list_commits_tagged(repo, "feature", "main", limit=10):
        print(f"  {c['message']:<20} {c['tags']}")

    print("\n=== annotate_analysis on a real conflict ===")
    analysis = analyze_merge(repo, "feature", "main")
    annotate_analysis(repo, analysis)
    for f in analysis["conflicted_files"]:
        print(f"- {f['path']}")
        print("   current :", [(c["message"], c["tags"]) for c in f["current_commits"]])
        print("   incoming:", [(c["message"], c["tags"]) for c in f["incoming_commits"]])
        hunk_commit = f["hunks"][0]["incoming_commits"][0]
        print("   hunk shares tags:", "relationship" in hunk_commit)