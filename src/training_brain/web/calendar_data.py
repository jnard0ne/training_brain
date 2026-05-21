"""Calendar data for the web UI.

Returns planned + executed workouts in a date range, grouped by the athlete's
local date. The frontend renders both sides in a single per-day cell — we
intentionally do not try to match planned ↔ executed here; that join is
fuzzy and best done by the human reading the calendar.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from training_brain.db import athlete_id, client


@lru_cache(maxsize=1)
def _athlete_tz_name() -> str:
    rows = (
        client()
        .table("athletes")
        .select("timezone")
        .eq("id", athlete_id())
        .limit(1)
        .execute()
    )
    return (rows.data[0].get("timezone") if rows.data else None) or "America/Los_Angeles"


def range_payload(start: date, end: date) -> dict[str, Any]:
    """Fetch the range and shape it for the calendar view.

    `start` and `end` are inclusive local dates. We widen the executed query
    by ±1 day so timezone conversion at the edges doesn't lose workouts that
    fall just inside the local range but outside the UTC range.
    """
    if end < start:
        raise ValueError("end must be >= start")

    tz_name = _athlete_tz_name()
    tz = ZoneInfo(tz_name)
    db = client()
    aid = athlete_id()

    lo_local = datetime.combine(start, datetime.min.time(), tz)
    hi_local = datetime.combine(end + timedelta(days=1), datetime.min.time(), tz)
    lo_utc = (lo_local - timedelta(days=1)).isoformat()
    hi_utc = (hi_local + timedelta(days=1)).isoformat()

    planned_rows = (
        db.table("workouts_planned")
        .select(
            "id, date, sport, duration_planned_s, tss_planned, description"
        )
        .eq("athlete_id", aid)
        .gte("date", start.isoformat())
        .lte("date", end.isoformat())
        .order("date")
        .execute()
    ).data or []

    executed_rows = (
        db.table("workouts_executed")
        .select(
            "id, started_at, sport, duration_s, distance_m, tss, "
            "avg_hr, max_hr, avg_power, normalized_power, "
            "avg_pace_s_per_km, elevation_gain_m, relative_effort, "
            "garmin_activity_id, strava_activity_id"
        )
        .eq("athlete_id", aid)
        .gte("started_at", lo_utc)
        .lte("started_at", hi_utc)
        .order("started_at")
        .execute()
    ).data or []

    days: dict[str, dict[str, list]] = {}
    for d_off in range((end - start).days + 1):
        key = (start + timedelta(days=d_off)).isoformat()
        days[key] = {"planned": [], "executed": []}

    for row in planned_rows:
        key = row["date"]
        if key in days:
            days[key]["planned"].append(_shape_planned(row))

    for row in executed_rows:
        started = row.get("started_at")
        if not started:
            continue
        local_dt = datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(tz)
        key = local_dt.date().isoformat()
        if key in days:
            days[key]["executed"].append(_shape_executed(row, local_dt))

    today_iso = datetime.now(tz).date().isoformat()
    for key, bucket in days.items():
        _match_and_score(bucket["planned"], bucket["executed"], day_iso=key, today_iso=today_iso)

    return {"timezone": tz_name, "start": start.isoformat(), "end": end.isoformat(), "days": days}


def _shape_planned(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "sport": row.get("sport") or "other",
        "duration_planned_s": row.get("duration_planned_s"),
        "tss_planned": row.get("tss_planned"),
        "description": row.get("description") or "",
    }


def _shape_executed(row: dict, local_dt: datetime) -> dict:
    return {
        "id": row.get("id"),
        "sport": row.get("sport") or "other",
        "started_at": row.get("started_at"),
        "started_local": local_dt.isoformat(),
        "duration_s": row.get("duration_s"),
        "distance_m": row.get("distance_m"),
        "tss": _to_float(row.get("tss")),
        "avg_hr": row.get("avg_hr"),
        "avg_power": row.get("avg_power"),
        "avg_pace_s_per_km": _to_float(row.get("avg_pace_s_per_km")),
        "elevation_gain_m": row.get("elevation_gain_m"),
        "relative_effort": row.get("relative_effort"),
        "garmin_activity_id": row.get("garmin_activity_id"),
        "strava_activity_id": row.get("strava_activity_id"),
    }


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Compliance matching ─────────────────────────────────────────────────────
#
# TP-style buckets:
#   green   — executed value within ±20% of planned
#   yellow  — executed 50-79% or 121-150% of planned
#   orange  — executed <50% or >150% of planned
#   red     — planned workout not completed (only for past dates)
#   grey    — completed workout with no matching plan
#
# Matching is best-effort: planned ↔ executed of the same sport within a
# single day, paired in arrival order. AGENTS.md flags this as ambiguous when
# multiple same-sport workouts land on one day; we accept the ambiguity here
# rather than surface it in the calendar UI.

_PLANNED_TIME_RE = re.compile(r"Planned Time[:\s]+(\d+):(\d{2})", re.IGNORECASE)


def _match_and_score(
    planned: list[dict],
    executed: list[dict],
    *,
    day_iso: str,
    today_iso: str,
) -> None:
    """In-place: attach a `compliance` dict to each workout where applicable."""
    by_sport_p: dict[str, list[dict]] = {}
    by_sport_e: dict[str, list[dict]] = {}
    for p in planned:
        by_sport_p.setdefault(p["sport"], []).append(p)
    for e in executed:
        by_sport_e.setdefault(e["sport"], []).append(e)

    is_past = day_iso < today_iso

    for sport in set(by_sport_p) | set(by_sport_e):
        # "other" is TP's catch-all for rest days, races, day-off notes, etc.
        # Scoring those as compliance is misleading — skip the badge entirely.
        if sport == "other":
            continue
        plans = by_sport_p.get(sport, [])
        execs = by_sport_e.get(sport, [])
        n = min(len(plans), len(execs))
        for i in range(n):
            level = _compliance_level(plans[i], execs[i])
            tag = {"status": "completed", "level": level}
            plans[i]["compliance"] = tag
            execs[i]["compliance"] = tag
        # Unmatched planned: red X only for past days; today/future stays blank.
        if is_past:
            for p in plans[n:]:
                p["compliance"] = {"status": "uncompleted", "level": "red"}
        for e in execs[n:]:
            e["compliance"] = {"status": "unplanned", "level": "grey"}


def _compliance_level(planned: dict, executed: dict) -> str:
    p_dur = _planned_duration_s(planned)
    e_dur = executed.get("duration_s")
    if not p_dur or not e_dur:
        # No usable planned duration → can't score; trust the completion.
        return "green"
    ratio = e_dur / p_dur
    if 0.8 <= ratio <= 1.2:
        return "green"
    if (0.5 <= ratio < 0.8) or (1.2 < ratio <= 1.5):
        return "yellow"
    return "orange"


def _planned_duration_s(planned: dict) -> int | None:
    """Return a usable planned duration in seconds, or None if indeterminate.

    `duration_planned_s` from the TP iCal feed is often 86400 (all-day event)
    or NULL; fall back to parsing `Planned Time: H:MM` from the description.
    """
    dur = planned.get("duration_planned_s")
    if dur and 0 < dur < 86400:
        return int(dur)
    m = _PLANNED_TIME_RE.search(planned.get("description") or "")
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60
    return None
