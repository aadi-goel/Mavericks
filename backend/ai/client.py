"""Local LM Studio client for Gemma (PRD section 7.7).

- Talks only to localhost (PRD section 10: source code never leaves the machine).
- 30 second default timeout, no retry loop.
- Never raises: every outcome is a plain dict so the app keeps working when
  LM Studio is not running.

    {"ok": True,  "text": "...", "model": "...", "finish_reason": "stop"}
    {"ok": False, "error": "human readable message", "code": "offline"}

finish_reason "length" means the answer was cut off at max_tokens.
Error codes: invalid_url, offline, timeout, http_error, bad_response.
"""

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("gitguardian.ai")

DEFAULT_BASE_URL = "http://localhost:1234"
DEFAULT_MODEL = "gemma"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RESPONSE_BYTES = 1_000_000
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# An empty ProxyHandler stops macOS/system proxy settings from intercepting
# localhost traffic.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

AIResult = dict[str, Any]


def _success(text: str, model: str, finish_reason: str | None) -> AIResult:
    return {"ok": True, "text": text, "model": model, "finish_reason": finish_reason}


def _failure(error: str, code: str) -> AIResult:
    return {"ok": False, "error": error, "code": code}


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(500).decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001 - detail is best-effort only
        return ""
    return f": {body}" if body else ""


class LMStudioClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.2,
    ) -> AIResult:
        """One chat completion. Never raises."""
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS:
            return _failure("AI server URL must point to localhost", "invalid_url")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with _opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:  # server answered with 4xx/5xx
            return _failure(f"LM Studio returned HTTP {exc.code}{_error_detail(exc)}", "http_error")
        except (socket.timeout, TimeoutError):
            return _failure(f"LM Studio did not answer within {self.timeout:g} seconds", "timeout")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                return _failure(f"LM Studio did not answer within {self.timeout:g} seconds", "timeout")
            log.info("LM Studio unreachable: %s", exc.reason)
            return _failure(
                f"Could not reach LM Studio at {self.base_url}. Is the local server running?",
                "offline",
            )
        except OSError as exc:  # e.g. connection reset
            log.info("LM Studio connection error: %s", exc)
            return _failure(f"Connection to LM Studio failed: {exc}", "offline")

        if len(raw) > MAX_RESPONSE_BYTES:
            return _failure("LM Studio response was too large", "bad_response")
        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            text = choice["message"]["content"].strip()
            finish_reason = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            return _failure("LM Studio sent a response in an unexpected format", "bad_response")
        if not text:
            return _failure("LM Studio returned an empty answer", "bad_response")

        return _success(text, str(data.get("model") or self.model), finish_reason)