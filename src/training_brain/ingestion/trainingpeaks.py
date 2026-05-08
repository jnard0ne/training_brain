"""TrainingPeaks iCal ingestion.

TP's iCal feed is the official, stable export for the planned workout
calendar. It does not include execution data — that comes from Garmin.

What we do:
1. Fetch the .ics feed over HTTPS using the personal token URL.
2. Parse VEVENTs with the icalendar library.
3. Audit each event into raw_tp_calendar (append-only).
4. Upsert into workouts_planned, keyed by (athlete_id, source='trainingpeaks',
   source_uid=iCal UID).

Sport inference is a keyword heuristic over SUMMARY + CATEGORIES; unrecognized
events fall back to 'other'. Extend SPORT_KEYWORDS as new patterns surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx
from icalendar import Calendar

from training_brain.db import athlete_id, client, settings


SPORT_KEYWORDS: list[tuple[str, str]] = [
    ("brick", "brick"),
    ("swim", "swim"),
    ("bike", "bike"),
    ("ride", "bike"),
    ("cycle", "bike"),
    ("cycling", "bike"),
    ("run", "run"),
    ("running", "run"),
    ("strength", "strength"),
    ("lift", "strength"),
    ("weights", "strength"),
    ("yoga", "mobility"),
    ("mobility", "mobility"),
    ("stretch", "mobility"),
]


@dataclass
class TPSyncResult:
    fetched: int = 0
    upserted: int = 0
    errors: list[str] = field(default_factory=list)


def sync_planned() -> TPSyncResult:
    """Fetch TP iCal feed and upsert all events as planned workouts."""
    s = settings()
    if not s.tp_ical_url:
        raise RuntimeError("TP_ICAL_URL must be set in .env")

    result = TPSyncResult()
    # TP's iCal field issues a webcal:// URL; httpx only speaks http/https.
    url = re.sub(r"^webcal://", "https://", s.tp_ical_url)
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    cal = Calendar.from_ical(response.text)

    aid = athlete_id()
    db = client()

    for component in cal.walk("VEVENT"):
        result.fetched += 1
        try:
            uid = str(component.get("UID") or "")
            if not uid:
                continue

            payload = _component_to_dict(component)
            audit = db.table("raw_tp_calendar").insert({
                "athlete_id": aid,
                "ical_uid": uid,
                "payload": payload,
            }).execute()
            raw_id = audit.data[0]["id"] if audit.data else None

            normalized = _normalize_event(component, raw_id)
            if normalized:
                db.table("workouts_planned").upsert(
                    normalized,
                    on_conflict="athlete_id,source,source_uid",
                ).execute()
                result.upserted += 1
        except Exception as e:
            result.errors.append(f"{component.get('UID')}: {e}")

    return result


def _component_to_dict(component: Any) -> dict[str, Any]:
    """Serialize a VEVENT to JSON-able dict for the audit table."""
    out: dict[str, Any] = {}
    for k, v in component.items():
        try:
            if hasattr(v, "dt"):
                dt = v.dt
                out[str(k)] = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            else:
                out[str(k)] = str(v)
        except Exception:
            out[str(k)] = repr(v)
    return out


def _normalize_event(component: Any, raw_id: int | None) -> dict[str, Any] | None:
    summary = str(component.get("SUMMARY") or "")
    description = str(component.get("DESCRIPTION") or "")
    uid = str(component.get("UID") or "")

    dtstart = component.get("DTSTART")
    if dtstart is None:
        return None

    start_value = dtstart.dt
    if isinstance(start_value, datetime):
        d = start_value.astimezone(timezone.utc).date()
    elif isinstance(start_value, date):
        d = start_value
    else:
        return None

    return {
        "athlete_id": athlete_id(),
        "date": d.isoformat(),
        "sport": _infer_sport(summary, str(component.get("CATEGORIES") or "")),
        "duration_planned_s": _extract_duration_s(component),
        "tss_planned": _extract_tss(description),
        "description": f"{summary}\n{description}".strip(),
        "structure": None,
        "source": "trainingpeaks",
        "source_uid": uid,
        "raw_id": raw_id,
    }


def _extract_duration_s(component: Any) -> int | None:
    duration = component.get("DURATION")
    if duration is not None:
        try:
            return int(duration.dt.total_seconds())
        except Exception:
            return None

    dtstart = component.get("DTSTART")
    dtend = component.get("DTEND")
    if dtstart is not None and dtend is not None:
        try:
            return int((dtend.dt - dtstart.dt).total_seconds())
        except Exception:
            return None
    return None


def _extract_tss(description: str) -> float | None:
    m = re.search(r"\bTSS[:\s]+(\d+(?:\.\d+)?)", description, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _infer_sport(summary: str, categories: str) -> str:
    haystack = f"{summary} {categories}".lower()
    for keyword, sport in SPORT_KEYWORDS:
        if keyword in haystack:
            return sport
    return "other"
