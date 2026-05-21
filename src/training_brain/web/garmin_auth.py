"""Garmin login orchestration for the web UI.

The underlying client (`garminconnect.Garmin`) does login synchronously and
calls a `prompt_mfa` callable when MFA is required. We run that login in a
background thread and use two events to bridge the UI:
  - `mfa_required` — set by the prompt callback when Garmin asks for a code
  - `mfa_provided` — set by the UI after the user submits the code

The session is a process-wide singleton; this is a single-user local tool, so
concurrent logins aren't a concern.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from garminconnect import Garmin

from training_brain.ingestion.garmin import GARMIN_TOKEN_PATH


LoginState = Literal["idle", "running", "needs_mfa", "success", "error"]


@dataclass
class _Session:
    state: LoginState = "idle"
    error: str | None = None
    mfa_required: threading.Event = field(default_factory=threading.Event)
    mfa_provided: threading.Event = field(default_factory=threading.Event)
    mfa_code: str | None = None
    thread: threading.Thread | None = None


_session: _Session = _Session()
_lock = threading.Lock()


def status() -> dict:
    """Snapshot of the current login attempt (if any) plus token-file presence."""
    with _lock:
        return {
            "state": _session.state,
            "error": _session.error,
            "token_exists": _token_exists(),
        }


def start(email: str, password: str) -> dict:
    """Kick off a fresh login. Returns the same shape as `status()`."""
    global _session
    with _lock:
        if _session.state == "running" or _session.state == "needs_mfa":
            return _snapshot()
        _session = _Session(state="running")
        t = threading.Thread(
            target=_run_login,
            args=(email, password, _session),
            daemon=True,
            name="garmin-login",
        )
        _session.thread = t
        t.start()
        return _snapshot()


def submit_mfa(code: str) -> dict:
    """Hand the MFA code to the worker thread."""
    with _lock:
        if _session.state != "needs_mfa":
            return _snapshot()
        _session.mfa_code = code.strip()
        _session.mfa_provided.set()
        return _snapshot()


def reset() -> None:
    """Drop the current session (post-success cleanup, or to retry after error)."""
    global _session
    with _lock:
        _session = _Session()


def _run_login(email: str, password: str, sess: _Session) -> None:
    def prompt_mfa() -> str:
        with _lock:
            sess.state = "needs_mfa"
        sess.mfa_required.set()
        if not sess.mfa_provided.wait(timeout=300):
            raise RuntimeError("MFA prompt timed out after 5 minutes")
        return sess.mfa_code or ""

    try:
        api = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
        api.login(GARMIN_TOKEN_PATH)
        # garminconnect skips writing tokens when the cached ones are still
        # valid, so an mtime check alone makes a successful re-auth look like a
        # no-op. Touch the files so the UI reflects "verified as of now."
        _touch_tokens()
        with _lock:
            sess.state = "success"
    except Exception as e:
        with _lock:
            sess.state = "error"
            sess.error = str(e)


def _snapshot() -> dict:
    return {
        "state": _session.state,
        "error": _session.error,
        "token_exists": _token_exists(),
    }


def _token_exists() -> bool:
    return any(Path(GARMIN_TOKEN_PATH).expanduser().glob("*.json"))


def _touch_tokens() -> None:
    for f in Path(GARMIN_TOKEN_PATH).expanduser().glob("*.json"):
        f.touch()


def token_mtime() -> str | None:
    """ISO timestamp of the most recently written token file, or None."""
    files = list(Path(GARMIN_TOKEN_PATH).expanduser().glob("*.json"))
    if not files:
        return None
    latest = max(f.stat().st_mtime for f in files)
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()
