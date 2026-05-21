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

    by_day_planned: dict[str, list[dict]] = {}
    by_day_executed: dict[str, list[dict]] = {}

    for row in planned_rows:
        key = row["date"]
        by_day_planned.setdefault(key, []).append(_shape_planned(row))

    for row in executed_rows:
        started = row.get("started_at")
        if not started:
            continue
        local_dt = datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(tz)
        key = local_dt.date().isoformat()
        by_day_executed.setdefault(key, []).append(_shape_executed(row, local_dt))

    today_iso = datetime.now(tz).date().isoformat()
    days: dict[str, dict[str, list]] = {}
    for d_off in range((end - start).days + 1):
        key = (start + timedelta(days=d_off)).isoformat()
        days[key] = {
            "items": _build_items(
                by_day_planned.get(key, []),
                by_day_executed.get(key, []),
                day_iso=key,
                today_iso=today_iso,
            )
        }

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


# ── Matching + item construction ────────────────────────────────────────────
#
# We collapse planned ↔ executed pairs into a single "item" per logical
# workout. Each item is one of:
#   completed — matched pair; compliance scored against planned duration
#   planned   — planned-only (red X if past, no badge if today/future)
#   unplanned — executed-only (grey !)
#
# Matching is best-effort: same sport within a day, paired in arrival order.
# AGENTS.md flags this as ambiguous when multiple same-sport workouts land
# on one day; we accept the ambiguity rather than surface it in the UI.
#
# Compliance buckets (TP-style):
#   green   — executed within ±20% of planned
#   yellow  — executed 50-79% or 121-150% of planned
#   orange  — executed <50% or >150% of planned
#   red     — planned, not completed (past dates only)
#   grey    — completed without a matching plan

_PLANNED_TIME_RE = re.compile(r"Planned Time[:\s]+(\d+):(\d{2})", re.IGNORECASE)


def _build_items(
    planned: list[dict],
    executed: list[dict],
    *,
    day_iso: str,
    today_iso: str,
) -> list[dict]:
    """Match planned ↔ executed within a day, return one item per workout.

    Output items are sorted by executed start time when available; planned-
    only items (no completion to anchor a time) sort to the end.
    """
    by_sport_p: dict[str, list[dict]] = {}
    by_sport_e: dict[str, list[dict]] = {}
    for p in planned:
        by_sport_p.setdefault(p["sport"], []).append(p)
    for e in executed:
        by_sport_e.setdefault(e["sport"], []).append(e)

    is_past = day_iso < today_iso
    items: list[dict] = []

    for sport in set(by_sport_p) | set(by_sport_e):
        plans = by_sport_p.get(sport, [])
        execs = by_sport_e.get(sport, [])
        n = min(len(plans), len(execs))

        # Matched pairs. "other" sport (rest days, races) gets paired without
        # a compliance score — we don't want a green check on a rest day.
        for i in range(n):
            p, e = plans[i], execs[i]
            compliance: dict | None
            if sport == "other":
                compliance = None
            else:
                compliance = {"status": "completed", "level": _compliance_level(p, e)}
            items.append({
                "id": e["id"],
                "kind": "completed",
                "sport": sport,
                "planned": p,
                "executed": e,
                "compliance": compliance,
            })

        # Planned without execution. Past = red X. Today/future = no badge.
        # "other" never gets a red X (it includes "Day Off" markers).
        for p in plans[n:]:
            compliance = None
            if is_past and sport != "other":
                compliance = {"status": "uncompleted", "level": "red"}
            items.append({
                "id": p["id"],
                "kind": "planned",
                "sport": sport,
                "planned": p,
                "executed": None,
                "compliance": compliance,
            })

        # Execution without a plan. Always grey !.
        for e in execs[n:]:
            compliance = None
            if sport != "other":
                compliance = {"status": "unplanned", "level": "grey"}
            items.append({
                "id": e["id"],
                "kind": "unplanned",
                "sport": sport,
                "planned": None,
                "executed": e,
                "compliance": compliance,
            })

    items.sort(key=_item_sort_key)
    return items


def _item_sort_key(item: dict) -> tuple:
    """Executed workouts in chronological order; planned-only floats to bottom."""
    e = item.get("executed")
    if e and e.get("started_local"):
        return (0, e["started_local"])
    return (1, item.get("sport", ""))


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
