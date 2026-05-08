"""CLI entrypoint for training_brain sync.

Invoked by OpenClaw cron with one of:

    python -m training_brain.sync intraday
    python -m training_brain.sync daily [--days-back 1]
    python -m training_brain.sync backfill [--since YYYY-MM-DD]
    python -m training_brain.sync login-garmin   # one-time, interactive

All sync commands are idempotent. Non-zero exit code if any errors surfaced.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any

import typer

from training_brain.ingestion import garmin, trainingpeaks


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("login-garmin")
def login_garmin() -> None:
    """One-time interactive Garmin login. Caches tokens to ~/.garminconnect."""
    garmin.login_interactive()
    typer.echo("Garmin token saved.")


@app.command()
def intraday() -> None:
    """Refresh fast-changing wellness (body battery, stress, training readiness)."""
    result = garmin.sync_intraday()
    _emit({"garmin": result})
    sys.exit(1 if result.errors else 0)


@app.command()
def daily(
    days_back: Annotated[int, typer.Option("--days-back", "-d")] = 1,
) -> None:
    """Daily refresh: sleep, HRV, RHR, weight, activities, planned workouts."""
    g = garmin.sync_daily(days_back=days_back)
    tp = _try_tp()
    s = _try_strava()
    _emit({"garmin": g, "trainingpeaks": tp, "strava": s})
    sys.exit(1 if _has_errors(g, tp, s) else 0)


@app.command()
def backfill(
    since: Annotated[
        str | None,
        typer.Option("--since", help="YYYY-MM-DD; defaults to 12 months ago"),
    ] = None,
) -> None:
    """Historical sweep across all sources."""
    cutoff = date.fromisoformat(since) if since else date.today() - timedelta(days=365)
    g = garmin.sync_backfill(cutoff)
    tp = _try_tp()
    s = _try_strava(backfill_since=cutoff)
    _emit({"garmin": g, "trainingpeaks": tp, "strava": s, "since": cutoff.isoformat()})
    sys.exit(1 if _has_errors(g, tp, s) else 0)


def _try_tp() -> Any:
    try:
        return trainingpeaks.sync_planned()
    except Exception as e:
        typer.echo(f"TrainingPeaks sync failed: {e}", err=True)
        return {"error": str(e)}


def _try_strava(backfill_since: date | None = None) -> Any:
    try:
        from training_brain.ingestion import strava  # noqa: WPS433  (lazy import)
    except ImportError:
        return None
    try:
        if backfill_since:
            return strava.sync_backfill(backfill_since)
        return strava.sync_recent()
    except Exception as e:
        typer.echo(f"Strava sync failed: {e}", err=True)
        return {"error": str(e)}


def _has_errors(*results: Any) -> bool:
    for r in results:
        if r is None:
            continue
        if isinstance(r, dict) and r.get("error"):
            return True
        if hasattr(r, "errors") and getattr(r, "errors"):
            return True
    return False


def _emit(payload: Any) -> None:
    """Emit JSON to stdout so cron logs are parseable."""
    def _convert(o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, dict):
            return {k: _convert(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_convert(x) for x in o]
        return o
    typer.echo(json.dumps(_convert(payload), default=str))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
