# GitGuardian

Local-first Git conflict analysis with commit provenance and testing evidence.
The app reads local repositories, runs merge analysis without changing the
working tree, and creates a normal merge commit only after explicit approval.

## Run the desktop app

Requirements: Python 3.12+, Node.js 20+, and Git 2.38+ (the temporary-worktree
fallback is used with older Git).

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
python3 -m backend.app.main
```

In the Dashboard, enter a local repository folder or use **Browse**, connect,
select source and target branches, and choose **Analyze Merge**. The app does
not switch branches during analysis; to commit, the target branch must already
be checked out and the worktree must be clean.

## Try the seeded demo

Choose a new or empty directory and seed the demo repository:

```bash
python3 scripts/seed_demo_repo.py --path /tmp/gitguardian-demo
```

Open `/tmp/gitguardian-demo` in the Dashboard. Analyze `dev` into `prod` to see
real conflicts, evidence statuses, a cherry-pick reference, and an equivalent
patch. `dev` into `uat` is a clean-merge example. The seed script refuses to
write into a non-empty directory.

## Checks

```bash
python3 -m pytest backend/tests -q
cd frontend
npm run build
```

## Safety and optional AI

Analysis uses Git's merge-tree operation (or a temporary worktree fallback).
Resolution is manual; no AI-generated code is applied. Commits require the
approval checkbox and are blocked when the target worktree has uncommitted
changes. GitGuardian never pushes to a remote.

Testing provenance is read from `.gitguardian/evidence.json`; missing files
produce `Unknown`, and invalid records are skipped and counted. Optional
explanations use Gemma through LM Studio on localhost and are disabled by
default.
