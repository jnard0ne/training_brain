"""Garmin Connect ingestion via cyberjunky/python-garminconnect.

Public surface:
    login_interactive() — first-time MFA login; cached to ~/.garminconnect.
    sync_intraday() — body battery, stress, training readiness for today.
    sync_daily(days_back) — sleep, HRV, RHR, weight, training readiness, activities.
    sync_backfill(since) — historical sweep (wellness + activities).

Garmin is the source for raw physiology and the bulk of executed-workout data.
TP outranks Garmin if a workout is ever manually edited there, but in practice
that diff is rare; the tradeoff is documented in CLAUDE.md.

Replaces the original garth-based client (deprecated 2026-03-27 after Garmin
added Cloudflare protections). The new lib ships a native mobile-SSO auth
engine with curl_cffi TLS impersonation and exposes a `connectapi(path)` method
on the `Garmin` instance, so the URL paths used here are unchanged from the
prior implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from garminconnect import Garmin

from training_brain.db import athlete_id, client, settings


GARMIN_TOKEN_PATH = "~/.garminconnect"


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

_garmin: Garmin | None = None


def login_interactive() -> None:
    """Run once locally. Prompts for MFA if Garmin asks. Tokens cached to ~/.garminconnect."""
    s = settings()
    if not (s.garmin_email and s.garmin_password):
        raise RuntimeError("GARMIN_EMAIL / GARMIN_PASSWORD must be set in .env")
    api = Garmin(
        email=s.garmin_email,
        password=s.garmin_password,
        prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
    )
    api.login(GARMIN_TOKEN_PATH)


def _client_garmin() -> Garmin:
    global _garmin
    if _garmin is not None:
        return _garmin
    api = Garmin()
    try:
        api.login(GARMIN_TOKEN_PATH)
    except Exception as e:
        raise RuntimeError(
            "Garmin session is stale or missing. Run "
            "`python -m training_brain.sync login-garmin` interactively first."
        ) from e
    _garmin = api
    return api


# ── Sync entry points ───────────────────────────────────────────────────────


def sync_intraday() -> SyncResult:
    _client_garmin()
    result = SyncResult(profile="intraday")
    try:
        _ingest_wellness_day(date.today(), intraday=True)
        result.wellness_days_touched = 1
    except Exception as e:
        result.errors.append(f"intraday {date.today()}: {e}")
    return result


def sync_daily(days_back: int = 1) -> SyncResult:
    _client_garmin()
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
    _client_garmin()
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
    api = _client_garmin()
    if kind == "sleep":
        # get_sleep_data returns { dailySleepDTO: {...}, sleepLevels: [...], ... }.
        return api.get_sleep_data(iso)
    if kind == "hrv":
        return api.get_hrv_data(iso)
    if kind == "rhr":
        # get_user_summary surfaces restingHeartRate alongside steps/calories etc.
        return api.get_user_summary(iso)
    if kind == "body_battery":
        # Returns a list (one entry per day) with charged/drained + values array.
        return api.get_body_battery(iso)
    if kind == "stress":
        return api.get_stress_data(iso)
    if kind == "training_readiness":
        return api.connectapi(f"/metrics-service/metrics/trainingreadiness/{iso}")
    if kind == "weight":
        return api.connectapi(f"/weight-service/weight/dayview/{iso}?includeAll=true")
    raise ValueError(f"Unknown wellness kind: {kind}")


def _extract_wellness_fields(kind: str, raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if kind == "sleep" and isinstance(raw, dict):
        # New endpoint nests the daily numbers under dailySleepDTO.
        sleep = raw.get("dailySleepDTO") or raw
        out["sleep_total_s"] = sleep.get("sleepTimeSeconds")
        out["sleep_deep_s"] = sleep.get("deepSleepSeconds")
        out["sleep_light_s"] = sleep.get("lightSleepSeconds")
        out["sleep_rem_s"] = sleep.get("remSleepSeconds")
        out["sleep_awake_s"] = sleep.get("awakeSleepSeconds")
        scores = sleep.get("sleepScores")
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
    elif kind == "body_battery":
        # get_body_battery returns a list with one entry per day requested.
        day = raw[0] if isinstance(raw, list) and raw else raw if isinstance(raw, dict) else None
        if isinstance(day, dict):
            out["body_battery_charged"] = _int_or_none(day.get("charged"))
            out["body_battery_drained"] = _int_or_none(day.get("drained"))
            values = day.get("bodyBatteryValuesArray") or []
            # Entry shape varies by endpoint:
            #   get_body_battery: [timestamp_ms, value]            (len 2)
            #   /dailyStress:     [timestamp_ms, status, value, version] (len 4)
            nums: list[float] = []
            for v in values:
                if not isinstance(v, list) or len(v) < 2:
                    continue
                candidate = v[2] if len(v) >= 3 and isinstance(v[2], (int, float)) else v[1]
                if isinstance(candidate, (int, float)):
                    nums.append(candidate)
            if nums:
                out["body_battery_high"] = int(max(nums))
                out["body_battery_low"] = int(min(nums))
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
    api = _client_garmin()
    while True:
        path = (
            f"/activitylist-service/activities/search/activities"
            f"?limit={limit}&start={offset}"
            f"&startDate={start.isoformat()}&endDate={end.isoformat()}"
        )
        chunk = api.connectapi(path) or []
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
    return out


def _store_fit_file(activity_id: int, aid: str) -> str:
    data = _client_garmin().download_activity(
        str(activity_id),
        dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
    )
    if not data:
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
        "duration_s": _int_or_none(raw.get("duration")) or 0,
        "distance_m": raw.get("distance"),
        "tss": raw.get("trainingStressScore"),
        "intensity_factor": raw.get("intensityFactor"),
        "avg_hr": _int_or_none(raw.get("averageHR")),
        "max_hr": _int_or_none(raw.get("maxHR")),
        "avg_power": _int_or_none(raw.get("avgPower")),
        "normalized_power": _int_or_none(raw.get("normPower")),
        "avg_cadence": _int_or_none(cadence),
        "avg_pace_s_per_km": _avg_pace(raw),
        "elevation_gain_m": raw.get("elevationGain"),
        "calories": _int_or_none(raw.get("calories")),
        "fit_file_path": fit_path,
    }


def _int_or_none(x: Any) -> int | None:
    if x is None:
        return None
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


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
