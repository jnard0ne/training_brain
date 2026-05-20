"""Strava ingestion via stravalib.

Strava is supplemental — Garmin is the primary source for executed workouts.
We pull from Strava to:
1. Cross-check that all Garmin activities have synced.
2. Capture workouts that originated outside Garmin (e.g. manual entries).
3. Get route polylines without parsing FIT files.

For each Strava activity we look up a matching Garmin row by `(sport, started_at ±5min)`.
If found we attach `strava_activity_id`; otherwise we insert a standalone
`workouts_executed` row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from stravalib import Client

from training_brain.db import athlete_id, client as supabase_client, settings


SPORT_MAP: dict[str, str] = {
    "Swim": "swim",
    "Ride": "bike",
    "VirtualRide": "bike",
    "MountainBikeRide": "bike",
    "GravelRide": "bike",
    "EBikeRide": "bike",
    "EMountainBikeRide": "bike",
    "Handcycle": "bike",
    "Run": "run",
    "VirtualRun": "run",
    "TrailRun": "run",
    "WeightTraining": "strength",
    "Workout": "strength",
    "Yoga": "mobility",
}


@dataclass
class StravaSyncResult:
    fetched: int = 0
    matched_to_garmin: int = 0
    inserted_standalone: int = 0
    errors: list[str] = field(default_factory=list)


def sync_recent() -> StravaSyncResult:
    """Pull the last 7 days of activities."""
    return _sync(after=datetime.now(timezone.utc) - timedelta(days=7))


def sync_backfill(since: date) -> StravaSyncResult:
    """Pull all activities since `since`."""
    return _sync(after=datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc))


def authed_client() -> Client:
    """Return a stravalib Client with a fresh access token."""
    s = settings()
    if not (s.strava_client_id and s.strava_client_secret and s.strava_refresh_token):
        raise RuntimeError(
            "STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET/STRAVA_REFRESH_TOKEN must be set in .env"
        )
    sc = Client()
    token = sc.refresh_access_token(
        client_id=int(s.strava_client_id),
        client_secret=s.strava_client_secret,
        refresh_token=s.strava_refresh_token,
    )
    access_token = token["access_token"] if isinstance(token, dict) else token.access_token
    sc.access_token = access_token
    return sc


def _sync(after: datetime) -> StravaSyncResult:
    sc = authed_client()

    result = StravaSyncResult()
    db = supabase_client()
    aid = athlete_id()

    for activity in sc.get_activities(after=after):
        result.fetched += 1
        try:
            payload = _activity_to_dict(activity)
            db.table("raw_strava_activities").insert({
                "athlete_id": aid,
                "strava_activity_id": activity.id,
                "payload": payload,
            }).execute()

            raw_sport = getattr(activity, "sport_type", None) or getattr(activity, "type", None)
            raw_sport_str = getattr(raw_sport, "root", str(raw_sport)) if raw_sport is not None else ""
            sport = SPORT_MAP.get(raw_sport_str, "other")
            started_at = activity.start_date.astimezone(timezone.utc).isoformat()

            relative_effort = _maybe_int(getattr(activity, "suffer_score", None))
            match_id = _find_garmin_match(started_at, sport)
            if match_id:
                db.table("workouts_executed").update(
                    {"strava_activity_id": activity.id, "relative_effort": relative_effort}
                ).eq("id", match_id).execute()
                result.matched_to_garmin += 1
            else:
                db.table("workouts_executed").upsert(
                    {
                        "athlete_id": aid,
                        "strava_activity_id": activity.id,
                        "started_at": started_at,
                        "sport": sport,
                        "duration_s": int(getattr(activity, "moving_time", 0) or 0),
                        "distance_m": float(getattr(activity, "distance", 0) or 0),
                        "avg_hr": _maybe_int(getattr(activity, "average_heartrate", None)),
                        "max_hr": _maybe_int(getattr(activity, "max_heartrate", None)),
                        "avg_power": _maybe_int(getattr(activity, "average_watts", None)),
                        "elevation_gain_m": getattr(activity, "total_elevation_gain", None),
                        "calories": getattr(activity, "calories", None),
                        "relative_effort": relative_effort,
                        "notes": getattr(activity, "name", None),
                    },
                    on_conflict="athlete_id,strava_activity_id",
                ).execute()
                result.inserted_standalone += 1
        except Exception as e:
            result.errors.append(f"{getattr(activity, 'id', '?')}: {e}")

    return result


def _find_garmin_match(started_at_iso: str, sport: str, tolerance_s: int = 300) -> str | None:
    db = supabase_client()
    started_at = datetime.fromisoformat(started_at_iso.replace("Z", "+00:00"))
    lo = (started_at - timedelta(seconds=tolerance_s)).isoformat()
    hi = (started_at + timedelta(seconds=tolerance_s)).isoformat()
    res = (
        db.table("workouts_executed")
        .select("id")
        .eq("athlete_id", athlete_id())
        .eq("sport", sport)
        .gte("started_at", lo)
        .lte("started_at", hi)
        .limit(1)
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def _activity_to_dict(a: Any) -> dict[str, Any]:
    if hasattr(a, "model_dump"):
        return a.model_dump(mode="json")
    if hasattr(a, "to_dict"):
        return a.to_dict()
    out: dict[str, Any] = {}
    for k in (
        "id", "name", "type", "sport_type", "start_date", "distance",
        "moving_time", "elapsed_time", "total_elevation_gain",
        "average_heartrate", "max_heartrate", "average_watts",
        "max_watts", "kilojoules", "calories", "map",
    ):
        v = getattr(a, k, None)
        if isinstance(v, datetime):
            v = v.isoformat()
        out[k] = v
    return out


def _maybe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
