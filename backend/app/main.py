"""GitGuardian v2.0 - backend entrypoint and local Python <-> React bridge.

Run from the repo root:
    python -m backend.app.main            # pywebview desktop window
    python -m backend.app.main --stdio    # newline-delimited JSON-RPC fallback

Every bridge method returns {"ok": True, "data": ...} or {"ok": False, "error": "..."}.
"""

import argparse
import functools
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

from backend.ai import explainer
from backend.app import repository, resolution
from backend.app import settings as app_settings
from backend.app.db import init_db
from backend.git_engine import (
    GitError,
    analyze_merge as git_analyze_merge,
    annotate_analysis,
    check_ready_to_commit,
    create_merge_commit,
    list_branches as git_list_branches,
    list_commits as git_list_commits,
    list_commits_tagged,
    match_branches,
    run_git,
)
from backend.provenance import get_commit_evidence, load_evidence_file

log = logging.getLogger("gitguardian")

APP_TITLE = "GitGuardian"
APP_VERSION = "2.0.0"
ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_INDEX = ROOT_DIR / "frontend" / "dist" / "index.html"

JsonDict = dict[str, Any]


# --------------------------------------------------------------------------
# Response helpers (PRD Section 8 contract)
# --------------------------------------------------------------------------
def ok(data: Any = None) -> JsonDict:
    return {"ok": True, "data": data}


def fail(error: str) -> JsonDict:
    return {"ok": False, "error": error}


def bridge_method(func: Callable[..., JsonDict]) -> Callable[..., JsonDict]:
    """Mark a method as part of the frontend contract and never let it raise.

    Any exception becomes {"ok": False, "error": ...} so the UI always
    receives a well-formed dict.
    """

    @functools.wraps(func)
    def wrapper(self: "BridgeAPI", *args: Any, **kwargs: Any) -> JsonDict:
        try:
            return func(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - bridge boundary
            log.exception("bridge method %s failed", func.__name__)
            return fail(f"{type(exc).__name__}: {exc}")

    wrapper.is_bridge_method = True  # type: ignore[attr-defined]
    return wrapper


# --------------------------------------------------------------------------
# Bridge API - exposed to JS as window.pywebview.api.<method>()
# --------------------------------------------------------------------------
class BridgeAPI:
    """Frontend contract owned by Member 2 (Backend Orchestrator).

    Helpers start with an underscore so pywebview does not expose them.
    """

    def __init__(self) -> None:
        # Underscore names are not exposed to JS by pywebview.
        self._repo_id: int | None = None
        self._repo_path: Path | None = None
        self._analysis: JsonDict | None = None  # latest analyze_merge result
        self._resolutions: dict[str, str | None] = {}  # file path -> resolved content; None deletes the file
        self._raw_analysis: JsonDict | None = None

    @bridge_method
    def ping(self) -> JsonDict:
        """End-to-end bridge check (PRD hour 0-1 milestone)."""
        return ok(
            {
                "pong": True,
                "app": APP_TITLE,
                "version": APP_VERSION,
                "python": sys.version.split()[0],
            }
        )

    @bridge_method
    def open_repository(self, path: str) -> JsonDict:
        if not isinstance(path, str) or not path.strip():
            return fail("Repository path is required")
        try:
            repo_id, root, info = repository.open_repository(path.strip())
        except ValueError as exc:
            return fail(str(exc))
        self._repo_id = repo_id
        self._repo_path = root
        self._analysis = None  # a new repo invalidates any old analysis
        self._raw_analysis = None
        self._resolutions = {}
        return ok(info)

    @bridge_method
    def pick_folder(self) -> JsonDict:
        try:
            import webview
        except ImportError:
            return fail("Folder picker is available in the desktop app; enter the repository path manually.")
        if not webview.windows:
            return fail("No desktop window is available for the folder picker.")
        selected = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return ok(selected[0] if selected else "")

    @bridge_method
    def list_branches(self) -> JsonDict:
        if self._repo_path is None:
            return fail("Open a repository first")
        try:
            return ok([
                {"name": b["name"], "is_current": b["is_current"]}
                for b in git_list_branches(self._repo_path)
            ])
        except GitError as exc:
            return fail(str(exc))

    @bridge_method
    def list_commits(
        self, branch: str, other_branch: str | None = None, limit: int = 50
    ) -> JsonDict:
        if self._repo_path is None:
            return fail("Open a repository first")
        try:
            other = other_branch
            if other is None and self._analysis:
                other = (
                    self._analysis["source"]
                    if branch == self._analysis["target"]
                    else self._analysis["target"]
                )
            commits = (
                list_commits_tagged(self._repo_path, branch, other, limit=limit)
                if other and branch != other
                else git_list_commits(self._repo_path, branch, limit=limit)
            )
            return ok([self._commit_view(c) for c in commits])
        except GitError as exc:
            return fail(str(exc))

    @bridge_method
    def compare_branches(self, source: str, target: str) -> JsonDict:
        if self._repo_path is None:
            return fail("Open a repository first")
        try:
            comparison = match_branches(self._repo_path, source, target)
            return ok({
                "only_source": [self._commit_view(c) for c in comparison["only_in_source"]],
                "only_target": [self._commit_view(c) for c in comparison["only_in_target"]],
            })
        except GitError as exc:
            return fail(str(exc))

    def _commit_view(self, commit: dict[str, Any]) -> JsonDict:
        relation = commit.get("relationship", {})
        tags = commit.get("tags", [])
        status = "Unknown"
        records: list[dict] = []
        if self._repo_path is not None:
            evidence = get_commit_evidence(commit["hash"], self._evidence_path())
            status = evidence["this_commit_evidence"]["status"]
            records = evidence["this_commit_evidence"]["records"]
        return {
            "hash": commit["hash"],
            "short_hash": commit["short_hash"],
            "message": commit["message"],
            "author": commit["author"],
            "date": commit["date"],
            "parents": commit.get("parents", []),
            "tags": tags,
            "relationship": relation,
            "test_status": status,
            "evidence_records": records,
        }

    @bridge_method
    def analyze_merge(self, source: str, target: str) -> JsonDict:
        if self._repo_id is None:
            return fail("Open a repository first")
        for label, value in (("source", source), ("target", target)):
            if not isinstance(value, str) or not value.strip():
                return fail(f"{label} branch is required")
        source, target = source.strip(), target.strip()
        if source == target:
            return fail("Source and target must be different branches")
        try:
            raw = git_analyze_merge(self._repo_path, source, target)
            annotate_analysis(self._repo_path, raw)
            evidence_path = self._evidence_path()
            files = []
            for entry in raw["conflicted_files"]:
                evidence = []
                for side, commits in (
                    ("Target", entry["current_commits"]),
                    ("Source", entry["incoming_commits"]),
                ):
                    for commit in commits:
                        relationship = commit.get("relationship", {})
                        original_hash = relationship.get("original_hash")
                        details = get_commit_evidence(
                            commit["hash"], evidence_path, original_hash=original_hash
                        )
                        own = details["this_commit_evidence"]
                        origin = relationship.get("label", "No evidence of relationship")
                        evidence.append({
                            "hash": commit["hash"],
                            "short_hash": commit["short_hash"],
                            "author": commit["author"],
                            "message": commit["message"],
                            "date": commit["date"],
                            "origin": f"{side}: {origin}",
                            "equivalent_patch": relationship.get("tag") == "equivalent_patch",
                            "test_status": own["status"],
                            "records": own["records"],
                            "original": details.get("original_commit_evidence"),
                            "relationship": relationship,
                        })
                file_entry = {
                    "path": entry["path"],
                    "is_binary": entry["is_binary"],
                    "conflict_type": entry["conflict_type"],
                    "base_content": entry["base_content"],
                    "current_content": entry["current_content"],
                    "incoming_content": entry["incoming_content"],
                    "result_with_markers": entry["result_with_markers"],
                    "hunks": [{
                        "id": entry["path"],
                        "start_line": 1,
                        "current": entry["current_content"] or "",
                        "incoming": entry["incoming_content"] or "",
                        "evidence": evidence,
                        "mapping_precision": "commits_touching_file",
                    }],
                }
                files.append(file_entry)
            analysis = {
                "source": source,
                "target": target,
                "merge_base": raw["merge_base"],
                "clean_merge": not raw["has_conflicts"],
                "summary": raw["summary"],
                "files": files,
                "evidence_file": load_evidence_file(evidence_path),
            }
        except (GitError, ValueError) as exc:
            return fail(str(exc))
        for entry in raw["conflicted_files"]:
            for commit_list in (entry["current_commits"], entry["incoming_commits"]):
                for commit in commit_list:
                    rel = commit.get("relationship", {})
                    original_hash = rel.get("original_hash")
                    evidence = get_commit_evidence(
                        commit["hash"], evidence_path, original_hash=original_hash
                    )
                    commit["evidence"] = {
                        "status": evidence["this_commit_evidence"]["status"],
                        "original": (
                            {"status": evidence["original_commit_evidence"]["status"]}
                            if evidence["original_commit_evidence"] else None
                        ),
                    }
                    commit["origin"] = {
                        "label": rel.get("label", "No evidence of relationship"),
                        "method": rel.get("method"),
                        "original_commit": original_hash,
                        "original_in_repo": rel.get("original_exists", False),
                    }
            for hunk in entry["hunks"]:
                hunk["current_content"] = hunk.get("current_text")
                hunk["incoming_content"] = hunk.get("incoming_text")
                hunk["current_commits"] = entry["current_commits"]
                hunk["incoming_commits"] = entry["incoming_commits"]
                hunk["type_label"] = hunk["type"].replace("_", " ").title()
        self._raw_analysis = raw
        self._analysis = analysis
        self._resolutions = {}  # a new analysis starts a fresh resolve session
        return ok(analysis)

    def _evidence_path(self) -> Path:
        assert self._repo_path is not None
        configured = Path(app_settings.load_settings()["evidence_path"]).expanduser()
        return configured if configured.is_absolute() else self._repo_path / configured

    @bridge_method
    def get_settings(self) -> JsonDict:
        return ok(app_settings.load_settings())

    @bridge_method
    def set_settings(self, settings: dict) -> JsonDict:
        try:
            return ok(app_settings.save_settings(settings))
        except ValueError as exc:
            return fail(str(exc))

    @bridge_method
    def explain_conflict(self, file: str, hunk_id: str) -> JsonDict:
        if self._raw_analysis is None or self._repo_id is None:
            return fail("Run analyze_merge first")
        try:
            raw_hunk_id: Any = hunk_id
            if hunk_id == file:
                entry = next(
                    (item for item in self._raw_analysis["conflicted_files"] if item["path"] == file),
                    None,
                )
                if entry is None or not entry["hunks"]:
                    return fail(f"No conflict hunk found in {file}")
                raw_hunk_id = entry["hunks"][0]["id"]
            return ok(
                explainer.explain(
                    self._repo_id,
                    {
                        **self._raw_analysis,
                        "files": self._raw_analysis["conflicted_files"],
                        "evidence_file": {
                            "loaded": load_evidence_file(self._evidence_path())["loaded"]
                        },
                    },
                    file,
                    raw_hunk_id,
                    app_settings.load_settings(),
                )
            )
        except ValueError as exc:
            return fail(str(exc))

    @bridge_method
    def save_resolution(self, file: str, content: str) -> JsonDict:
        if self._analysis is None:
            return fail("Run analyze_merge first")
        try:
            return ok(resolution.save(self._analysis, self._resolutions, file, content))
        except ValueError as exc:
            return fail(str(exc))

    @bridge_method
    def preview_commit(self, resolutions: dict[str, str | None] | None = None) -> JsonDict:
        if self._analysis is None:
            return fail("Run analyze_merge first")
        if resolutions is not None:
            if not isinstance(resolutions, dict):
                return fail("resolutions must be an object")
            self._resolutions = resolutions
        preview = resolution.build_preview(self._analysis, self._resolutions)
        if self._raw_analysis and self._repo_path and self._raw_analysis.get("merged_tree"):
            excluded = [
                f":(exclude,literal){entry['path']}"
                for entry in self._raw_analysis["conflicted_files"]
            ]
            tree_diff = run_git(
                self._repo_path,
                [
                    "diff", "--no-color", self._raw_analysis["target_hash"],
                    self._raw_analysis["merged_tree"], "--", ".", *excluded,
                ],
                check=True,
            ).stdout
            preview["diff"] = "\n".join(
                part for part in (tree_diff.rstrip(), preview["diff"]) if part
            )
        return ok(preview)

    @bridge_method
    def commit_resolution(
        self, message: str, approved: bool, resolutions: dict[str, str | None] | None = None
    ) -> JsonDict:
        if self._analysis is None or self._repo_id is None or self._repo_path is None:
            return fail("Run analyze_merge first")
        if resolutions is not None:
            if not isinstance(resolutions, dict):
                return fail("resolutions must be an object")
            self._resolutions = resolutions
        try:
            files = resolution.validate_commit(
                self._analysis, self._resolutions, message, approved
            )
            ready = check_ready_to_commit(
                self._repo_path, self._analysis["source"], self._analysis["target"]
            )
            if not ready["ready"]:
                raise ValueError(" ".join(ready["problems"]))
            file_resolutions = {path: self._resolutions[path] for path in files}
            result = create_merge_commit(
                self._repo_path,
                self._analysis["source"],
                self._analysis["target"],
                message.strip(),
                approved,
                file_resolutions,
            )
        except (ValueError, GitError) as exc:
            return fail(str(exc))

        resolution.log_resolution(
            self._repo_id,
            self._analysis["source"],
            self._analysis["target"],
            files,
            approved=True,
            final_commit=result["commit_hash"],
        )
        result["files_resolved"] = files

        # The analysis is stale after a commit; force a fresh analyze_merge.
        self._analysis = None
        self._raw_analysis = None
        self._resolutions = {}
        return ok(result)


# Allow-list of callable names, used by the stdio transport.
BRIDGE_METHODS = frozenset(
    name
    for name, member in vars(BridgeAPI).items()
    if getattr(member, "is_bridge_method", False)
)


def dispatch(api: BridgeAPI, method: str, params: Any = None) -> JsonDict:
    """Route a method name + params to the API (used by the stdio fallback)."""
    if method not in BRIDGE_METHODS:
        return fail(f"Unknown method: {method}")
    handler = getattr(api, method)
    if isinstance(params, dict):
        return handler(**params)
    return handler(*(params or []))


# --------------------------------------------------------------------------
# Transport 1: pywebview desktop window (recommended)
# --------------------------------------------------------------------------
PLACEHOLDER_HTML = """
<!doctype html>
<html>
  <body style="font-family: sans-serif; padding: 2rem">
    <h2>GitGuardian bridge is up</h2>
    <p>No built frontend found. Run <code>npm run build</code> in
       <code>frontend/</code> or set <code>GG_DEV_URL</code>.</p>
    <button id="ping">Ping backend</button>
    <pre id="out"></pre>
    <script>
      window.addEventListener("pywebviewready", () => {
        document.getElementById("ping").onclick = async () => {
          const res = await window.pywebview.api.ping();
          document.getElementById("out").textContent = JSON.stringify(res, null, 2);
        };
      });
    </script>
  </body>
</html>
"""


def _resolve_start_url() -> str | None:
    dev_url = os.environ.get("GG_DEV_URL")  # e.g. http://localhost:5173 (Vite)
    if dev_url:
        return dev_url
    if FRONTEND_INDEX.exists():
        return str(FRONTEND_INDEX)
    return None


def run_gui(api: BridgeAPI, debug: bool = False) -> int:
    try:
        import webview  # pywebview
    except ImportError:
        log.error("pywebview is not installed. Run: pip install -r backend/requirements.txt")
        log.error("Or use the fallback: python -m backend.app.main --stdio")
        return 1

    url = _resolve_start_url()
    source = {"url": url} if url else {"html": PLACEHOLDER_HTML}
    webview.create_window(
        APP_TITLE,
        js_api=api,
        width=1280,
        height=800,
        min_size=(960, 600),
        **source,
    )
    webview.start(debug=debug)
    return 0


# --------------------------------------------------------------------------
# Transport 2: stdio JSON-RPC fallback (Electron/Tauri child process)
#   request : {"id": 1, "method": "ping", "params": []}
#   response: {"id": 1, "result": {"ok": true, "data": ...}}
# --------------------------------------------------------------------------
def run_stdio(api: BridgeAPI) -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            result = dispatch(api, request["method"], request.get("params"))
            response = {"id": request.get("id"), "result": result}
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            response = {"id": None, "result": fail(f"Bad request: {exc}")}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitGuardian local backend")
    parser.add_argument("--stdio", action="store_true", help="use stdio JSON-RPC instead of pywebview")
    parser.add_argument("--debug", action="store_true", help="enable webview devtools")
    args = parser.parse_args(argv)

    # Log to stderr: stdout is reserved for the stdio protocol.
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    init_db()
    api = BridgeAPI()
    return run_stdio(api) if args.stdio else run_gui(api, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())