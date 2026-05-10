"""FIT file parsing → activity_streams + workout_laps.

Two-tier model:
- Hot tier: time-binned streams in `activity_streams` (1Hz default). Cheap
  to query for HR drift, mean-max power, time-in-zone, etc.
- Cold tier: original FIT in Supabase Storage, parsed on demand for
  full-resolution work that doesn't fit the bin model.

Public surface:
    ingest_streams(workout_id, fit_storage_path) — orchestrator. Downloads
        the FIT bytes from Storage, parses, deletes any existing rows for
        the workout, bulk-inserts streams + laps. Idempotent.

The Garmin ORIGINAL download is sometimes a raw .fit file and sometimes a
.zip wrapping one .fit; we sniff the magic bytes and handle both. GPS in
FIT is stored as int32 semicircles (1 sc = 180/2^31 degrees) — converted
on the way out.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

import fitdecode

from training_brain.db import client


SEMICIRCLE_TO_DEG = 180.0 / (2**31)
STREAM_INSERT_CHUNK = 500


@dataclass
class StreamsResult:
    workout_id: str
    stream_rows: int = 0
    lap_rows: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class _ParsedFit:
    records: list[dict]
    laps: list[dict]
    session_start: datetime | None


# ── public ─────────────────────────────────────────────────────────────────


def ingest_streams(workout_id: str, fit_storage_path: str, bin_size_s: int = 1) -> StreamsResult:
    """Parse the FIT for a workout and write streams + laps to Postgres."""
    result = StreamsResult(workout_id=workout_id)
    db = client()

    try:
        data = db.storage.from_("fit-files").download(fit_storage_path)
    except Exception as e:
        result.errors.append(f"download: {e}")
        return result

    try:
        parsed = _parse(data)
    except Exception as e:
        result.errors.append(f"parse: {e}")
        return result

    if parsed.session_start is None and parsed.records:
        parsed.session_start = parsed.records[0].get("timestamp")
    if parsed.session_start is None:
        result.errors.append("no session_start (workout had no records or session msg)")
        return result

    bins = _bin_records(parsed.records, parsed.session_start, bin_size_s)
    laps = _extract_laps(parsed.laps)

    # Idempotent: drop existing rows for this workout, then insert.
    db.table("activity_streams").delete().eq("workout_id", workout_id).execute()
    db.table("workout_laps").delete().eq("workout_id", workout_id).execute()

    if bins:
        for chunk in _chunked(bins, STREAM_INSERT_CHUNK):
            payload = [{**b, "workout_id": workout_id} for b in chunk]
            db.table("activity_streams").insert(payload).execute()
        result.stream_rows = len(bins)

    if laps:
        payload = [{**lap, "workout_id": workout_id} for lap in laps]
        db.table("workout_laps").insert(payload).execute()
        result.lap_rows = len(laps)

    return result


# ── parser ─────────────────────────────────────────────────────────────────


def _parse(data: bytes) -> _ParsedFit:
    fit_bytes = _maybe_unzip(data)
    records: list[dict] = []
    laps: list[dict] = []
    session_start: datetime | None = None

    with fitdecode.FitReader(io.BytesIO(fit_bytes)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            name = frame.name
            if name == "session" and session_start is None:
                session_start = _val(frame, "start_time")
            elif name == "record":
                rec = _record_dict(frame)
                if rec.get("timestamp") is not None:
                    records.append(rec)
            elif name == "lap":
                laps.append(_lap_dict(frame))

    return _ParsedFit(records=records, laps=laps, session_start=session_start)


def _maybe_unzip(data: bytes) -> bytes:
    """Return raw FIT bytes whether the caller passed a .fit or a .zip."""
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".fit"):
                    return zf.read(name)
        raise ValueError("zip contained no .fit file")
    return data


def _record_dict(frame: fitdecode.FitDataMessage) -> dict[str, Any]:
    return {
        "timestamp": _val(frame, "timestamp"),
        "heart_rate": _val(frame, "heart_rate"),
        "power": _val(frame, "power"),
        "cadence": _val(frame, "cadence"),
        "speed": _val(frame, "enhanced_speed") or _val(frame, "speed"),
        "altitude": _val(frame, "enhanced_altitude") or _val(frame, "altitude"),
        "position_lat": _val(frame, "position_lat"),
        "position_long": _val(frame, "position_long"),
    }


def _lap_dict(frame: fitdecode.FitDataMessage) -> dict[str, Any]:
    avg_speed = _val(frame, "enhanced_avg_speed") or _val(frame, "avg_speed")
    # total_timer_time = active time (excludes auto-pause); total_elapsed_time
    # is wall-clock and double-counts red lights. We match workouts_executed
    # convention (timer time) so a single-lap workout's lap duration ==
    # the activity's duration_s.
    timer = _val(frame, "total_timer_time") or _val(frame, "total_elapsed_time")
    return {
        "started_at": _val(frame, "start_time"),
        "duration_s": _int_or_none(timer),
        "distance_m": _val(frame, "total_distance"),
        "avg_hr": _int_or_none(_val(frame, "avg_heart_rate")),
        "max_hr": _int_or_none(_val(frame, "max_heart_rate")),
        "avg_power": _int_or_none(_val(frame, "avg_power")),
        "max_power": _int_or_none(_val(frame, "max_power")),
        "normalized_power": _int_or_none(_val(frame, "normalized_power")),
        "avg_cadence": _int_or_none(_val(frame, "avg_cadence")),
        "avg_pace_s_per_km": _pace_from_speed(avg_speed),
        "intensity": _str_or_none(_val(frame, "intensity")),
        "lap_trigger": _str_or_none(_val(frame, "lap_trigger")),
    }


def _val(frame: fitdecode.FitDataMessage, name: str) -> Any:
    try:
        return frame.get_value(name)
    except KeyError:
        return None


# ── binning ────────────────────────────────────────────────────────────────


def _bin_records(
    records: list[dict],
    session_start: datetime,
    bin_size_s: int,
) -> list[dict]:
    """Group records by bin_offset and average numeric fields within each bin."""
    by_bin: dict[int, dict[str, Any]] = {}

    for rec in records:
        ts = rec["timestamp"]
        if not isinstance(ts, datetime):
            continue
        offset = int((ts - session_start).total_seconds())
        if offset < 0:
            continue
        bin_key = (offset // bin_size_s) * bin_size_s
        acc = by_bin.setdefault(bin_key, {"_n": 0})
        acc["_n"] += 1
        for src, dst in (
            ("heart_rate", "hr"),
            ("power", "power"),
            ("cadence", "cadence"),
            ("speed", "speed_m_s"),
            ("altitude", "altitude_m"),
        ):
            v = rec.get(src)
            if v is not None:
                acc[dst] = acc.get(dst, 0.0) + float(v)
        # GPS: take the first non-null in the bin (averaging coords is wrong).
        if "lat" not in acc and rec.get("position_lat") is not None:
            acc["lat"] = rec["position_lat"]
            acc["lon"] = rec.get("position_long")

    rows: list[dict] = []
    for bin_offset, acc in sorted(by_bin.items()):
        n = acc["_n"]
        rows.append({
            "bin_offset_s": bin_offset,
            "bin_size_s": bin_size_s,
            "hr": _avg_int(acc.get("hr"), n),
            "power": _avg_int(acc.get("power"), n),
            "cadence": _avg_int(acc.get("cadence"), n),
            "speed_m_s": _avg_num(acc.get("speed_m_s"), n),
            "altitude_m": _avg_num(acc.get("altitude_m"), n),
            "lat": _semicircles_to_deg(acc.get("lat")),
            "lon": _semicircles_to_deg(acc.get("lon")),
        })
    return rows


def _extract_laps(laps_raw: list[dict]) -> list[dict]:
    out = []
    for i, lap in enumerate(laps_raw):
        started = lap.get("started_at")
        duration = lap.get("duration_s")
        if started is None or duration is None:
            continue
        out.append({
            "lap_index": i,
            "started_at": started.isoformat() if isinstance(started, datetime) else str(started),
            "duration_s": int(duration),
            "distance_m": _num_or_none(lap.get("distance_m")),
            "avg_hr": lap.get("avg_hr"),
            "max_hr": lap.get("max_hr"),
            "avg_power": lap.get("avg_power"),
            "max_power": lap.get("max_power"),
            "normalized_power": lap.get("normalized_power"),
            "avg_cadence": lap.get("avg_cadence"),
            "avg_pace_s_per_km": lap.get("avg_pace_s_per_km"),
            "intensity": lap.get("intensity"),
            "lap_trigger": lap.get("lap_trigger"),
        })
    return out


# ── tiny helpers ───────────────────────────────────────────────────────────


def _semicircles_to_deg(sc: Any) -> float | None:
    if sc is None:
        return None
    try:
        return float(sc) * SEMICIRCLE_TO_DEG
    except (TypeError, ValueError):
        return None


def _avg_int(total: float | None, n: int) -> int | None:
    if total is None or n == 0:
        return None
    return int(round(total / n))


def _avg_num(total: float | None, n: int) -> float | None:
    if total is None or n == 0:
        return None
    return total / n


def _int_or_none(x: Any) -> int | None:
    if x is None:
        return None
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _num_or_none(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _str_or_none(x: Any) -> str | None:
    return str(x) if x is not None else None


def _pace_from_speed(speed_m_s: Any) -> float | None:
    """Pace in s/km from m/s. Speed of 0 (rest interval) → None."""
    if not speed_m_s:
        return None
    try:
        s = float(speed_m_s)
        return 1000.0 / s if s > 0 else None
    except (TypeError, ValueError):
        return None


def _chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
