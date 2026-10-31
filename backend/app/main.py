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
    All methods below are stubs and get real bodies in later parts.
    """

    @staticmethod
    def _not_implemented(name: str) -> JsonDict:
        return fail(f"{name} is not implemented yet")

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
        return self._not_implemented("open_repository")

    @bridge_method
    def analyze_merge(self, source: str, target: str) -> JsonDict:
        return self._not_implemented("analyze_merge")

    @bridge_method
    def get_settings(self) -> JsonDict:
        return self._not_implemented("get_settings")

    @bridge_method
    def set_settings(self, settings: dict) -> JsonDict:
        return self._not_implemented("set_settings")

    @bridge_method
    def explain_conflict(self, file: str, hunk_id: str) -> JsonDict:
        return self._not_implemented("explain_conflict")

    @bridge_method
    def save_resolution(self, file: str, content: str) -> JsonDict:
        return self._not_implemented("save_resolution")

    @bridge_method
    def preview_commit(self) -> JsonDict:
        return self._not_implemented("preview_commit")

    @bridge_method
    def commit_resolution(self, message: str, approved: bool) -> JsonDict:
        return self._not_implemented("commit_resolution")


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

    api = BridgeAPI()
    return run_stdio(api) if args.stdio else run_gui(api, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())