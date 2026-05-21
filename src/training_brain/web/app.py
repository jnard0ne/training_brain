"""FastAPI app for the local training_brain web UI.

Bind to 127.0.0.1 only. There is no auth layer — anyone who can reach the
loopback interface can re-authenticate Garmin/Strava on your behalf.

Routes:
  GET  /api/status                   — combined connection status
  POST /api/garmin/login             — start Garmin login {email, password}
  GET  /api/garmin/login/status      — poll for state (running/needs_mfa/...)
  POST /api/garmin/login/mfa         — submit MFA code {code}
  POST /api/garmin/login/reset       — clear current attempt
  GET  /api/strava/status            — credentials + token-validity probe
  POST /api/strava/credentials       — save client_id / client_secret
  GET  /api/strava/authorize_url     — build the Strava authorize URL
  GET  /api/strava/callback          — OAuth redirect target
  GET  /                             — built frontend (if present)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from training_brain.web import garmin_auth, strava_auth, trainingpeaks_auth


app = FastAPI(title="training_brain", docs_url="/api/docs")

# Vite dev server runs on a different port; allow CORS during dev only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ──────────────────────────────────────────────────────────────────


class GarminLoginRequest(BaseModel):
    email: str
    password: str


class MfaRequest(BaseModel):
    code: str


class StravaCredentialsRequest(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None


class TrainingPeaksUrlRequest(BaseModel):
    url: str


# ── Status ──────────────────────────────────────────────────────────────────


@app.get("/api/status")
def overall_status() -> dict:
    g = garmin_auth.status()
    s = strava_auth.credentials_status()
    return {
        "garmin": {
            "connected": g["token_exists"],
            "token_updated_at": garmin_auth.token_mtime(),
            "login_state": g["state"],
            "login_error": g["error"],
        },
        "strava": s,
        "trainingpeaks": {"configured": bool(trainingpeaks_auth.status()["configured"])},
    }


# ── Garmin ──────────────────────────────────────────────────────────────────


@app.post("/api/garmin/login")
def garmin_login(req: GarminLoginRequest) -> dict:
    if not req.email or not req.password:
        raise HTTPException(400, "email and password are required")
    return garmin_auth.start(req.email, req.password)


@app.get("/api/garmin/login/status")
def garmin_login_status() -> dict:
    return garmin_auth.status()


@app.post("/api/garmin/login/mfa")
def garmin_mfa(req: MfaRequest) -> dict:
    if not req.code.strip():
        raise HTTPException(400, "MFA code is required")
    return garmin_auth.submit_mfa(req.code)


@app.post("/api/garmin/login/reset")
def garmin_reset() -> dict:
    garmin_auth.reset()
    return garmin_auth.status()


# ── Strava ──────────────────────────────────────────────────────────────────


@app.get("/api/strava/status")
def strava_status() -> dict:
    creds = strava_auth.credentials_status()
    verification: dict | None = None
    if creds["has_refresh_token"]:
        verification = strava_auth.verify_refresh_token()
    return {**creds, "verification": verification}


@app.post("/api/strava/credentials")
def strava_credentials(req: StravaCredentialsRequest) -> dict:
    if not (req.client_id or req.client_secret):
        raise HTTPException(400, "Provide at least one of client_id, client_secret")
    strava_auth.save_credentials(req.client_id, req.client_secret)
    return strava_auth.credentials_status()


@app.get("/api/strava/authorize_url")
def strava_authorize_url(request: Request) -> dict:
    redirect_uri = str(request.url_for("strava_callback"))
    try:
        return {"url": strava_auth.authorize_url(redirect_uri), "redirect_uri": redirect_uri}
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/strava/callback", name="strava_callback")
def strava_callback(code: str | None = None, error: str | None = None) -> HTMLResponse:
    if error:
        return _callback_page(success=False, message=f"Strava returned error: {error}")
    if not code:
        return _callback_page(success=False, message="Missing OAuth code in callback")
    try:
        strava_auth.exchange_code(code)
    except Exception as e:
        return _callback_page(success=False, message=f"Token exchange failed: {e}")
    return _callback_page(success=True, message="Strava connected. You can close this tab.")


def _callback_page(*, success: bool, message: str) -> HTMLResponse:
    color = "#16a34a" if success else "#dc2626"
    html = f"""<!doctype html>
<html><head><title>Strava OAuth</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0a0a0a; color: #e5e5e5;
          display: flex; min-height: 100vh; align-items: center; justify-content: center; margin: 0; }}
  .card {{ background: #171717; border: 1px solid #262626; border-radius: 12px;
           padding: 32px 40px; max-width: 480px; }}
  h1 {{ margin: 0 0 12px; font-size: 20px; color: {color}; }}
  p {{ margin: 0 0 16px; line-height: 1.5; }}
  a {{ color: #60a5fa; }}
</style></head>
<body><div class="card">
  <h1>{"Connected" if success else "Failed"}</h1>
  <p>{message}</p>
  <p><a href="/">← Back to training_brain</a></p>
  <script>
    // Tell the opener (if any) to refresh status, then close after a moment.
    if (window.opener) {{
      try {{ window.opener.postMessage({{type: "strava:complete", success: {str(success).lower()}}}, "*"); }} catch (e) {{}}
    }}
  </script>
</div></body></html>"""
    return HTMLResponse(html)


# ── TrainingPeaks ───────────────────────────────────────────────────────────


@app.get("/api/trainingpeaks/status")
def trainingpeaks_status() -> dict:
    return trainingpeaks_auth.status()


@app.post("/api/trainingpeaks/url")
def trainingpeaks_set_url(req: TrainingPeaksUrlRequest) -> dict:
    try:
        return trainingpeaks_auth.save_url(req.url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ── Static frontend ─────────────────────────────────────────────────────────


_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"

if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:
        # Let API routes 404 normally; everything else falls back to the SPA shell.
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = _FRONTEND_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def index_missing() -> HTMLResponse:
        return HTMLResponse(
            "<h1>Frontend not built yet</h1>"
            "<p>Run <code>cd web && npm install && npm run build</code>, "
            "or start the Vite dev server with <code>npm run dev</code> "
            "(it proxies to this backend automatically).</p>",
            status_code=200,
        )
