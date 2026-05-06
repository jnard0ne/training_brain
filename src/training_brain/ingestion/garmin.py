"""Garmin Connect ingestion via garth.

Public surface:
    login_interactive() — first-time MFA login; cached to ~/.garth.
    sync_intraday() — body battery, stress, training readiness for today.
    sync_daily(days_back) — sleep, HRV, RHR, weight, training readiness, activities.
    sync_backfill(since) — historical sweep (wellness + activities).

Garmin is the source for raw physiology and the bulk of executed-workout data.
TP outranks Garmin if a workout is ever manually edited there, but in practice
that diff is rare; the tradeoff is documented in CLAUDE.md.

Field extractors below are based on documented Garmin Connect endpoints. Some
shapes vary between accounts and Garmin updates; treat the first end-to-end
run as a calibration step and extend SPORT_MAP / _extract_wellness_fields as
real responses surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import garth

from training_brain.db import athlete_id, client, settings


SPORT_MAP: dict[str, str] = {
    # Swim
    "swimming": "swim",
    "lap_swimming": "swim",
    "open_water_swimming": "swim",
    # Bike
    "cycling": "bike",
    "road_biking": "bike",
    "mountain_biking": "bike",
    "gravel_cycling": "bike",
    "indoor_cycling": "bike",
    "virtual_ride": "bike",
    "cyclocross": "bike",
    # Run
    "running": "run",
    "treadmill_running": "run",
    "trail_running": "run",
    "virtual_run": "run",
    "indoor_running": "run",
    "track_running": "run",
    # Strength
    "strength_training": "strength",
    # Mobility
    "yoga": "mobility",
    "pilates": "mobility",
    "stretching": "mobility",
    # Multi-sport (brick)
    "multi_sport": "brick",
    "transition": "brick",
}


@dataclass
class SyncResult:
    profile: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    activities_ingested: int = 0
    fit_files_uploaded: int = 0
    wellness_days_touched: int = 0
    errors: list[str] = field(default_factory=list)


# ── Auth ────────────────────────────────────────────────────────────────────


def login_interactive() -> None:
    """Run once locally. Prompts for MFA if Garmin asks. Token cached to ~/.garth."""
    s = settings()
    if not (s.garmin_email and s.garmin_password):
        raise RuntimeError("GARMIN_EMAIL / GARMIN_PASSWORD must be set in .env")
    garth.login(s.garmin_email, s.garmin_password)
    garth.save("~/.garth")


def _ensure_session() -> None:
    try:
        garth.resume("~/.garth")
        _ = garth.client.username
    except Exception as e:
        raise RuntimeError(
            "Garmin session is stale or missing. Run "
            "`python -m training_brain.sync login-garmin` interactively first."
        ) from e


# ── Sync entry points ───────────────────────────────────────────────────────


def sync_intraday() -> SyncResult:
    _ensure_session()
    result = SyncResult(profile="intraday")
    try:
        _ingest_wellness_day(date.today(), intraday=True)
        result.wellness_days_touched = 1
    except Exception as e:
        result.errors.append(f"intraday {date.today()}: {e}")
    return result


def sync_daily(days_back: int = 1) -> SyncResult:
    _ensure_session()
    result = SyncResult(profile="daily")
    today = date.today()
    for offset in range(days_back + 1):
        d = today - timedelta(days=offset)
        try:
            _ingest_wellness_day(d, intraday=False)
            result.wellness_days_touched += 1
        except Exception as e:
            result.errors.append(f"wellness {d}: {e}")
    start = today - timedelta(days=days_back + 2)
    try:
        n_act, n_fit = _ingest_activities(start, today)
        result.activities_ingested = n_act
        result.fit_files_uploaded = n_fit
    except Exception as e:
        result.errors.append(f"activities: {e}")
    return result


def sync_backfill(since: date) -> SyncResult:
    _ensure_session()
    result = SyncResult(profile="backfill")
    today = date.today()
    cur = since
    while cur <= today:
        try:
            _ingest_wellness_day(cur, intraday=False)
            result.wellness_days_touched += 1
        except Exception as e:
            result.errors.append(f"wellness {cur}: {e}")
        cur += timedelta(days=1)
    try:
        n_act, n_fit = _ingest_activities(since, today)
        result.activities_ingested = n_act
        result.fit_files_uploaded = n_fit
    except Exception as e:
        result.errors.append(f"activities: {e}")
    return result


# ── Wellness ────────────────────────────────────────────────────────────────


_INTRADAY_KINDS = ("body_battery", "stress", "training_readiness")
_DAILY_KINDS = (
    "sleep", "hrv", "rhr", "weight",
    "training_readiness", "body_battery", "stress",
)


def _ingest_wellness_day(d: date, *, intraday: bool) -> None:
    kinds = _INTRADAY_KINDS if intraday else _DAILY_KINDS

    payload: dict[str, Any] = {}
    raw_audit: list[tuple[str, dict]] = []

    for kind in kinds:
        try:
            raw = _fetch_wellness(kind, d)
        except Exception as e:
            raw_audit.append((kind, {"error": str(e)}))
            continue
        if raw is None:
            continue
        raw_audit.append((kind, raw))
        payload.update(_extract_wellness_fields(kind, raw))

    if not payload and not raw_audit:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    payload["intraday_updated_at"] = now_iso
    if not intraday:
        payload["daily_updated_at"] = now_iso

    aid = athlete_id()
    db = client()

    for kind, raw in raw_audit:
        db.table("raw_garmin_events").insert({
            "athlete_id": aid,
            "kind": kind,
            "occurred_on": d.isoformat(),
            "payload": raw,
        }).execute()

    db.table("wellness_daily").upsert(
        {"athlete_id": aid, "date": d.isoformat(), **payload},
        on_conflict="athlete_id,date",
    ).execute()


def _fetch_wellness(kind: str, d: date) -> dict | list | None:
    iso = d.isoformat()
    if kind == "sleep":
        try:
            rows = garth.DailySleep.list(end=iso, period=1)
            return _first_or_none(rows)
        except Exception:
            return garth.client.connectapi(
                f"/wellness-service/wellness/dailySleepData/{iso}"
            )
    if kind == "hrv":
        return garth.client.connectapi(f"/hrv-service/hrv/{iso}")
    if kind == "rhr":
        return garth.client.connectapi(
            f"/usersummary-service/usersummary/daily/{iso}"
        )
    if kind == "body_battery":
        return garth.client.connectapi(
            f"/wellness-service/wellness/dailyStress/{iso}"
        )
    if kind == "stress":
        return garth.client.connectapi(
            f"/wellness-service/wellness/dailyStress/{iso}"
        )
    if kind == "training_readiness":
        return garth.client.connectapi(
            f"/metrics-service/metrics/trainingreadiness/{iso}"
        )
    if kind == "weight":
        return garth.client.connectapi(
            f"/weight-service/weight/dayview/{iso}?includeAll=true"
        )
    raise ValueError(f"Unknown wellness kind: {kind}")


def _extract_wellness_fields(kind: str, raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if kind == "sleep" and isinstance(raw, dict):
        out["sleep_total_s"] = raw.get("sleepTimeSeconds")
        out["sleep_deep_s"] = raw.get("deepSleepSeconds")
        out["sleep_light_s"] = raw.get("lightSleepSeconds")
        out["sleep_rem_s"] = raw.get("remSleepSeconds")
        out["sleep_awake_s"] = raw.get("awakeSleepSeconds")
        scores = raw.get("sleepScores")
        if isinstance(scores, dict):
            overall = scores.get("overall")
            if isinstance(overall, dict):
                out["sleep_score"] = overall.get("value")
            elif isinstance(overall, (int, float)):
                out["sleep_score"] = int(overall)
    elif kind == "hrv" and isinstance(raw, dict):
        summary = raw.get("hrvSummary") or {}
        out["hrv_overnight_ms"] = summary.get("lastNightAvg")
        baseline = summary.get("baseline")
        if isinstance(baseline, dict):
            out["hrv_baseline_ms"] = baseline.get("balancedLow") or baseline.get("lowUpper")
    elif kind == "rhr" and isinstance(raw, dict):
        out["rhr_bpm"] = raw.get("restingHeartRate")
    elif kind == "body_battery" and isinstance(raw, dict):
        out["body_battery_high"] = raw.get("bodyBatteryHighestValue") or raw.get("bodyBatteryHighValue")
        out["body_battery_low"] = raw.get("bodyBatteryLowestValue") or raw.get("bodyBatteryLowValue")
        out["body_battery_charged"] = raw.get("bodyBatteryChargedValue")
        out["body_battery_drained"] = raw.get("bodyBatteryDrainedValue")
    elif kind == "stress" and isinstance(raw, dict):
        out["stress_avg"] = raw.get("avgStressLevel")
        out["stress_max"] = raw.get("maxStressLevel")
    elif kind == "training_readiness":
        rows = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
        if rows and isinstance(rows[0], dict):
            out["training_readiness"] = rows[0].get("score")
    elif kind == "weight" and isinstance(raw, dict):
        items = raw.get("dateWeightList") or []
        if items:
            grams = items[-1].get("weight")
            if isinstance(grams, (int, float)):
                out["weight_kg"] = grams / 1000.0
            out["body_fat_pct"] = items[-1].get("bodyFat")
    return {k: v for k, v in out.items() if v is not None}


# ── Activities ──────────────────────────────────────────────────────────────


def _ingest_activities(start: date, end: date) -> tuple[int, int]:
    aid = athlete_id()
    db = client()
    n_activities = 0
    n_fit = 0

    for raw in _list_activities(start, end):
        garmin_id = raw.get("activityId")
        if not garmin_id:
            continue

        db.table("raw_garmin_events").insert({
            "athlete_id": aid,
            "kind": "activity",
            "occurred_on": _activity_date(raw),
            "payload": raw,
        }).execute()

        fit_path: str | None = None
        try:
            fit_path = _store_fit_file(garmin_id, aid)
            n_fit += 1
        except Exception:
            fit_path = None

        norm = _normalize_activity(raw, fit_path)
        db.table("workouts_executed").upsert(
            norm,
            on_conflict="athlete_id,garmin_activity_id",
        ).execute()
        n_activities += 1

    return n_activities, n_fit


def _list_activities(start: date, end: date) -> list[dict]:
    out: list[dict] = []
    limit = 100
    offset = 0
    while True:
        path = (
            f"/activitylist-service/activities/search/activities"
            f"?limit={limit}&start={offset}"
            f"&startDate={start.isoformat()}&endDate={end.isoformat()}"
        )
        chunk = garth.client.connectapi(path) or []
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
    return out


def _store_fit_file(activity_id: int, aid: str) -> str:
    raw = garth.client.connectapi(
        f"/download-service/files/activity/{activity_id}",
        api=False,
    )
    data = raw if isinstance(raw, (bytes, bytearray)) else getattr(raw, "content", None)
    if data is None:
        raise RuntimeError(f"FIT download for {activity_id} returned no bytes")
    path = f"{aid}/{activity_id}.zip"
    client().storage.from_("fit-files").upload(
        path, bytes(data), file_options={"upsert": "true", "content-type": "application/zip"},
    )
    return path


def _normalize_activity(raw: dict, fit_path: str | None) -> dict[str, Any]:
    type_key = (raw.get("activityType") or {}).get("typeKey", "")
    sport = SPORT_MAP.get(type_key, "other")
    started_at = raw.get("startTimeGMT") or raw.get("startTimeLocal")
    cadence = (
        raw.get("averageRunningCadenceInStepsPerMinute")
        or raw.get("averageBikingCadenceInRevPerMinute")
    )
    return {
        "athlete_id": athlete_id(),
        "garmin_activity_id": raw.get("activityId"),
        "started_at": _normalize_ts(started_at),
        "sport": sport,
        "duration_s": int(raw.get("duration") or 0),
        "distance_m": raw.get("distance"),
        "tss": raw.get("trainingStressScore"),
        "intensity_factor": raw.get("intensityFactor"),
        "avg_hr": raw.get("averageHR"),
        "max_hr": raw.get("maxHR"),
        "avg_power": raw.get("avgPower"),
        "normalized_power": raw.get("normPower"),
        "avg_cadence": int(cadence) if cadence else None,
        "avg_pace_s_per_km": _avg_pace(raw),
        "elevation_gain_m": raw.get("elevationGain"),
        "calories": raw.get("calories"),
        "fit_file_path": fit_path,
    }


def _normalize_ts(ts: str | None) -> str | None:
    if not ts:
        return None
    if ts.endswith("Z") or "+" in ts[10:]:
        return ts.replace(" ", "T")
    return ts.replace(" ", "T") + "Z"


def _avg_pace(raw: dict) -> float | None:
    distance = raw.get("distance")
    duration = raw.get("duration")
    if not distance or not duration or distance <= 0:
        return None
    return duration / (distance / 1000.0)


def _activity_date(raw: dict) -> str:
    ts = raw.get("startTimeGMT") or raw.get("startTimeLocal") or ""
    return ts[:10] or date.today().isoformat()


def _first_or_none(rows: Any) -> dict | None:
    if not rows:
        return None
    if isinstance(rows, list):
        return rows[0] if rows else None
    return rows
