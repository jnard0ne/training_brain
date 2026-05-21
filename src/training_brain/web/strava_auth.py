"""Strava OAuth helpers for the web UI.

The flow:
  1. Frontend asks `/api/strava/authorize_url` with the current redirect URI.
  2. User opens that URL, approves on strava.com, and Strava redirects back to
     `/api/strava/callback?code=...&scope=...`.
  3. We exchange the code for an access + refresh token and write the refresh
     token back into .env (overwriting any prior value).
  4. The rest of the app picks up the new token via the existing `settings()`
     loader, which calls `load_dotenv()` on each fresh process.

Strava requires the redirect URI registered on the app to match exactly, so
the user must set it to `http://localhost:<port>` (we always callback to the
same origin we're served from).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from training_brain.web.env_writer import read_keys, write_keys


STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
DEFAULT_SCOPE = "read,activity:read_all"


def credentials_status() -> dict[str, Any]:
    """Report which Strava env vars are populated (without exposing values)."""
    vals = read_keys(["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"])
    return {
        "has_client_id": bool(vals["STRAVA_CLIENT_ID"]),
        "has_client_secret": bool(vals["STRAVA_CLIENT_SECRET"]),
        "has_refresh_token": bool(vals["STRAVA_REFRESH_TOKEN"]),
    }


def save_credentials(client_id: str | None, client_secret: str | None) -> None:
    """Persist client_id/secret to .env. Empty strings are ignored."""
    updates: dict[str, str] = {}
    if client_id:
        updates["STRAVA_CLIENT_ID"] = client_id.strip()
    if client_secret:
        updates["STRAVA_CLIENT_SECRET"] = client_secret.strip()
    if updates:
        write_keys(updates)


def authorize_url(redirect_uri: str) -> str:
    """Build the URL the user should hit to approve our app."""
    client_id = read_keys(["STRAVA_CLIENT_ID"])["STRAVA_CLIENT_ID"]
    if not client_id:
        raise RuntimeError("STRAVA_CLIENT_ID is not set yet")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": DEFAULT_SCOPE,
    }
    return f"{STRAVA_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    """Exchange an OAuth code for tokens; persist the refresh token to .env."""
    creds = read_keys(["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET"])
    client_id = creds["STRAVA_CLIENT_ID"]
    client_secret = creds["STRAVA_CLIENT_SECRET"]
    if not (client_id and client_secret):
        raise RuntimeError("STRAVA_CLIENT_ID/SECRET must be set before exchanging a code")

    resp = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    refresh = payload.get("refresh_token")
    if not refresh:
        raise RuntimeError(f"Strava token response missing refresh_token: {payload}")
    write_keys({"STRAVA_REFRESH_TOKEN": refresh})
    return {
        "athlete": payload.get("athlete"),
        "expires_at": payload.get("expires_at"),
        "scope": payload.get("scope"),
    }


def verify_refresh_token() -> dict[str, Any]:
    """Try a refresh_token grant — confirms the stored refresh token still works."""
    creds = read_keys(["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"])
    if not all(creds.values()):
        return {"ok": False, "reason": "missing credentials"}
    try:
        resp = httpx.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": creds["STRAVA_CLIENT_ID"],
                "client_secret": creds["STRAVA_CLIENT_SECRET"],
                "refresh_token": creds["STRAVA_REFRESH_TOKEN"],
                "grant_type": "refresh_token",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"network: {e}"}
    if resp.status_code != 200:
        return {"ok": False, "reason": f"http {resp.status_code}: {resp.text[:200]}"}
    payload = resp.json()
    new_refresh = payload.get("refresh_token")
    if new_refresh and new_refresh != creds["STRAVA_REFRESH_TOKEN"]:
        write_keys({"STRAVA_REFRESH_TOKEN": new_refresh})
    return {"ok": True, "expires_at": payload.get("expires_at")}
