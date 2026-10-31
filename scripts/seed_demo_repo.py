#!/usr/bin/env python3
"""Build a throwaway demo Git repo + .gitguardian/evidence.json for local UI testing.

Usage:
    python scripts/seed_demo_repo.py                       # temp dir, normal evidence
    python scripts/seed_demo_repo.py --path /tmp/demo      # choose an EMPTY folder
    python scripts/seed_demo_repo.py --evidence missing    # => every status Unknown
    python scripts/seed_demo_repo.py --evidence malformed  # => every status Unknown

Branches:   prod (base), uat, dev
Conflicts:  dev -> prod has TWO real conflicts
              config.py  (both modified)
              notes.txt  (modified on dev, deleted on prod)
Clean:      dev -> uat merges without conflict
Relations:  prod_cherry_pick   = cherry-pick of dev_verified WITH the trailer
            prod_equivalent    = same patch as dev_version, NO trailer (patch-id match)

Only standard Git is used, via argument lists (no shell). The script never
touches remotes and never runs in an existing repo.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAME = "Demo Dev"
EMAIL = "demo@example.com"

# What the status engine should report for each commit in "normal" mode.
EXPECTED = {
    "dev_verified": "Verified",       # unit + integration passed
    "dev_failed": "Failed",           # unit passed, integration FAILED
    "dev_unverified": "Unverified",   # no record at all
    "dev_version": "Verified",        # manual passed
    "uat_docs": "Unverified",
    "prod_cherry_pick": "Unverified", # original is Verified; NOT transferred
    "prod_equivalent": "Unverified",
    "prod_timeout": "Verified",       # uat passed
    "prod_delete_notes": "Unverified",
}

BASE_FILES = {
    "config.py": 'APP_NAME = "demo"\nTIMEOUT = 30\nRETRIES = 3\n',
    "notes.txt": "legacy notes\n",
    "README.md": "# Demo repo for GitGuardian\n",
}
HELPERS = (
    "def retry(fn, attempts=3):\n"
    "    for _ in range(attempts):\n"
    "        try:\n"
    "            return fn()\n"
    "        except Exception:\n"
    "            pass\n"
)


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self._clock = datetime(2026, 10, 30, 9, 0, 0, tzinfo=timezone.utc)

    def git(self, *args: str) -> str:
        self._clock += timedelta(minutes=10)  # strictly increasing, deterministic dates
        stamp = self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": NAME, "GIT_AUTHOR_EMAIL": EMAIL,
            "GIT_COMMITTER_NAME": NAME, "GIT_COMMITTER_EMAIL": EMAIL,
            "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp,
        }
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.path, env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"git {' '.join(args)} failed:\n{proc.stderr or proc.stdout}")
        return proc.stdout.strip()

    def write(self, rel: str, content: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")


def _build_history(repo: Repo) -> dict[str, str]:
    c: dict[str, str] = {}

    repo.git("init")
    repo.git("symbolic-ref", "HEAD", "refs/heads/prod")  # works on old Git too
    # Keep the evidence file out of `git status` so the tree stays clean.
    with open(repo.path / ".git" / "info" / "exclude", "a", encoding="utf-8") as f:
        f.write(".gitguardian/\n")

    for rel, content in BASE_FILES.items():
        repo.write(rel, content)
    c["base"] = repo.commit("Initial commit")
    repo.git("branch", "uat")
    repo.git("branch", "dev")

    # ---- dev -------------------------------------------------------------
    repo.git("checkout", "dev")
    repo.write("helpers.py", HELPERS)
    c["dev_verified"] = repo.commit("Add retry helper")
    repo.write("config.py", BASE_FILES["config.py"].replace("TIMEOUT = 30", "TIMEOUT = 45"))
    c["dev_failed"] = repo.commit("Set TIMEOUT to 45")
    repo.write("notes.txt", "legacy notes\nupdated on dev\n")
    c["dev_unverified"] = repo.commit("Update notes")
    repo.write("VERSION", "1.0\n")
    c["dev_version"] = repo.commit("Add VERSION file")

    # ---- uat (independent change => dev -> uat is a clean merge) ---------
    repo.git("checkout", "uat")
    repo.write("docs.md", "# Docs\n")
    c["uat_docs"] = repo.commit("Add docs")

    # ---- prod ------------------------------------------------------------
    repo.git("checkout", "prod")
    repo.git("cherry-pick", "-x", c["dev_verified"])  # adds the trailer
    c["prod_cherry_pick"] = repo.git("rev-parse", "HEAD")
    repo.write("VERSION", "1.0\n")  # same patch as dev_version, different hash, no trailer
    c["prod_equivalent"] = repo.commit("Add version file (manual backport)")
    repo.write("config.py", BASE_FILES["config.py"].replace("TIMEOUT = 30", "TIMEOUT = 60"))
    c["prod_timeout"] = repo.commit("Set TIMEOUT to 60")
    (repo.path / "notes.txt").unlink()
    c["prod_delete_notes"] = repo.commit("Remove legacy notes")
    return c


def _evidence(c: dict[str, str]) -> dict:
    def rec(commit, type_, result, run, minute, label):
        return {
            "commit": commit,
            "type": type_,
            "result": result,
            "timestamp": f"2026-10-30T12:{minute:02d}:00Z",
            "source": f"GitHub Actions run {run} - {label}",
            "reference": f"https://github.com/example/gitguardian/actions/runs/{run}",
        }

    return {
        "schema_version": 1,
        "records": [
            rec(c["dev_verified"], "unit", "passed", 1001, 0, "backend pytest"),
            rec(c["dev_verified"], "integration", "passed", 1001, 1, "frontend build"),
            rec(c["dev_failed"], "unit", "passed", 1002, 0, "backend pytest"),
            rec(c["dev_failed"], "integration", "failed", 1002, 1, "frontend build"),
            {
                "commit": c["dev_version"], "type": "manual", "result": "passed",
                "timestamp": "2026-10-30T13:00:00Z", "source": "Manual QA check",
            },
            rec(c["prod_timeout"], "uat", "passed", 1003, 0, "UAT suite"),
            # INVALID on purpose ("success" is not allowed): must be skipped and
            # counted, and must NOT make the cherry-pick copy look tested.
            {**rec(c["prod_cherry_pick"], "unit", "success", 1004, 0, "bad record")},
        ],
        # Display only; a deployment is never proof of testing.
        "deployments": [
            {
                "commit": c["dev_verified"], "environment": "production",
                "timestamp": "2026-10-30T14:00:00Z", "status": "deployed",
            }
        ],
        # Commits with NO records (=> Unverified): dev_unverified, uat_docs,
        # prod_equivalent, prod_delete_notes, and the cherry-pick copy.
    }


def seed(path: Path, evidence_mode: str = "normal") -> dict:
    """Create the demo repo at `path` (must be empty or new)."""
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise SystemExit(f"Refusing to seed into a non-empty folder: {path}")

    commits = _build_history(Repo(path))

    evidence_path = path / ".gitguardian" / "evidence.json"
    if evidence_mode != "missing":
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        if evidence_mode == "malformed":
            evidence_path.write_text('{"schema_version": 1, "records": [', encoding="utf-8")
        else:
            evidence_path.write_text(json.dumps(_evidence(commits), indent=2), encoding="utf-8")

    return {"path": path, "commits": commits, "evidence_path": evidence_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a local GitGuardian demo repo.")
    parser.add_argument("--path", type=Path, help="empty folder to create the repo in")
    parser.add_argument("--evidence", choices=["normal", "missing", "malformed"], default="normal")
    args = parser.parse_args()

    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        print("Git is not installed or not on PATH.", file=sys.stderr)
        return 1

    path = args.path or Path(tempfile.mkdtemp(prefix="gitguardian-demo-"))
    result = seed(path, args.evidence)

    print(f"\nDemo repo created: {result['path']}")
    print(f"Evidence file:     {result['evidence_path']}  (mode: {args.evidence})\n")
    print(f"{'commit':<18}{'hash':<10}expected status (normal mode)")
    for label, status in EXPECTED.items():
        print(f"{label:<18}{result['commits'][label][:7]:<10}{status}")
    print("\nTry in the app:  open this folder, then analyze  dev -> prod  (2 conflicts)")
    print("                 or  dev -> uat  (clean merge)")
    return 0


if __name__ == "__main__":
    sys.exit(main())