"""Read-side CLI commands for training_brain.

Pretty terminal output by default; `--json` on every command emits a
machine-readable blob suitable for piping into other tooling (e.g. Leto on
OpenClaw, who can call `training-brain briefing --json` instead of issuing
SQL through the Supabase MCP).

All reads go through the supabase-py PostgREST client (same auth as the sync
job — modern secret key from `.env`). Nothing here writes.

Mounted on the main typer app via `register(app)` from sync.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.table import Table

from training_brain.db import athlete_id, client


console = Console()

JsonOpt = Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")]
DaysOpt = Annotated[int, typer.Option("--days", "-d")]
SportOpt = Annotated[str | None, typer.Option("--sport", "-s")]


# ── helpers ────────────────────────────────────────────────────────────────


def _athlete_tz() -> ZoneInfo:
    rows = (
        client()
        .table("athletes")
        .select("timezone")
        .eq("id", athlete_id())
        .limit(1)
        .execute()
    )
    tz = (rows.data[0].get("timezone") if rows.data else None) or "America/Los_Angeles"
    return ZoneInfo(tz)


def _local_today() -> date:
    return datetime.now(_athlete_tz()).date()


def _local_day_bounds(d: date) -> tuple[str, str]:
    """ISO UTC strings bounding the local-tz day [d, d+1)."""
    tz = _athlete_tz()
    start = datetime.combine(d, datetime.min.time(), tz)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def _emit_json(payload: Any) -> None:
    console.print_json(data=_jsonify(payload))


def _jsonify(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: _jsonify(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonify(x) for x in o]
    return o


def _show(x: Any, default: str = "—") -> str:
    return default if x is None else str(x)


def _hms(seconds: int | float | None) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _km(meters: float | int | None) -> str:
    return f"{meters/1000:.1f}km" if meters else "—"


def _num(x: Any) -> float | None:
    """Postgres numeric round-trips through PostgREST as JSON string."""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ── commands ───────────────────────────────────────────────────────────────


def today(json: JsonOpt = False) -> None:
    """Today's planned workouts."""
    d = _local_today()
    rows = (
        client()
        .table("workouts_planned")
        .select("sport, duration_planned_s, tss_planned, description")
        .eq("athlete_id", athlete_id())
        .eq("date", d.isoformat())
        .order("sport")
        .execute()
    )

    if json:
        _emit_json({"date": d, "plan": rows.data})
        return

    if not rows.data:
        console.print(f"[dim]No plan for {d}.[/dim]")
        return

    table = Table(title=f"Plan for {d.strftime('%A, %b %d')}")
    table.add_column("Sport")
    table.add_column("Description", overflow="fold")
    for r in rows.data:
        first_line = (r.get("description") or "").strip().splitlines()[:1]
        table.add_row(_show(r.get("sport")), first_line[0] if first_line else "")
    console.print(table)


def recent(days: DaysOpt = 7, json: JsonOpt = False) -> None:
    """Recent executed workouts."""
    cutoff = _local_today() - timedelta(days=days - 1)
    start, _ = _local_day_bounds(cutoff)
    rows = (
        client()
        .table("workouts_executed")
        .select("started_at, sport, duration_s, distance_m, tss, avg_hr, avg_power")
        .eq("athlete_id", athlete_id())
        .gte("started_at", start)
        .order("started_at", desc=True)
        .execute()
    )

    if json:
        _emit_json({"days": days, "workouts": rows.data})
        return

    if not rows.data:
        console.print(f"[dim]No workouts in the last {days} days.[/dim]")
        return

    tz = _athlete_tz()
    table = Table(title=f"Last {days} days")
    table.add_column("When")
    table.add_column("Sport")
    table.add_column("Time")
    table.add_column("Dist", justify="right")
    table.add_column("TSS", justify="right")
    table.add_column("HR", justify="right")
    table.add_column("Power", justify="right")
    for r in rows.data:
        when = datetime.fromisoformat(r["started_at"]).astimezone(tz).strftime("%a %b %d %H:%M")
        tss = _num(r.get("tss"))
        table.add_row(
            when,
            _show(r.get("sport")),
            _hms(r.get("duration_s")),
            _km(r.get("distance_m")),
            f"{tss:.0f}" if tss is not None else "—",
            _show(r.get("avg_hr")),
            _show(r.get("avg_power")),
        )
    console.print(table)


def last(sport: SportOpt = None, json: JsonOpt = False) -> None:
    """Most recent completed workout."""
    q = (
        client()
        .table("workouts_executed")
        .select(
            "started_at, sport, duration_s, distance_m, tss, intensity_factor, "
            "avg_hr, max_hr, avg_power, normalized_power, calories, fit_file_path"
        )
        .eq("athlete_id", athlete_id())
        .order("started_at", desc=True)
        .limit(1)
    )
    if sport:
        q = q.eq("sport", sport)
    rows = q.execute()

    if not rows.data:
        if json:
            _emit_json({"workout": None})
        else:
            label = f" for sport={sport}" if sport else ""
            console.print(f"[dim]No workouts found{label}.[/dim]")
        return

    w = rows.data[0]
    if json:
        _emit_json({"workout": w})
        return

    started = datetime.fromisoformat(w["started_at"]).astimezone(_athlete_tz())
    tss = _num(w.get("tss"))
    if_ = _num(w.get("intensity_factor"))
    console.print(f"[bold]{w['sport'].title()}[/bold] — {started.strftime('%A %b %d, %H:%M')}")
    console.print(f"  Time:     {_hms(w.get('duration_s'))}")
    if w.get("distance_m"):
        console.print(f"  Distance: {_km(w['distance_m'])}")
    console.print(f"  HR:       {_show(w.get('avg_hr'))} avg / {_show(w.get('max_hr'))} max")
    if w.get("avg_power"):
        console.print(
            f"  Power:    {_show(w.get('avg_power'))} avg / NP {_show(w.get('normalized_power'))}"
        )
    if tss is not None:
        console.print(f"  TSS:      {tss:.0f}" + (f"  IF: {if_:.2f}" if if_ else ""))
    if w.get("fit_file_path"):
        console.print(f"  FIT:      [dim]{w['fit_file_path']}[/dim]")


def recovery(days: DaysOpt = 14, json: JsonOpt = False) -> None:
    """Wellness trend (sleep, HRV, RHR, readiness)."""
    cutoff = _local_today() - timedelta(days=days - 1)
    rows = (
        client()
        .table("wellness_daily")
        .select(
            "date, sleep_total_s, sleep_score, hrv_overnight_ms, hrv_baseline_ms, "
            "rhr_bpm, body_battery_high, body_battery_low, training_readiness"
        )
        .eq("athlete_id", athlete_id())
        .gte("date", cutoff.isoformat())
        .order("date", desc=True)
        .execute()
    )

    if json:
        _emit_json({"days": days, "wellness": rows.data})
        return

    if not rows.data:
        console.print(f"[dim]No wellness data in the last {days} days.[/dim]")
        return

    table = Table(title=f"Recovery — last {days} days")
    table.add_column("Date")
    table.add_column("Sleep", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("HRV", justify="right")
    table.add_column("Base", justify="right")
    table.add_column("RHR", justify="right")
    table.add_column("Read", justify="right")
    for r in rows.data:
        table.add_row(
            r["date"],
            _hms(r.get("sleep_total_s")),
            _show(r.get("sleep_score")),
            _show(r.get("hrv_overnight_ms")),
            _show(r.get("hrv_baseline_ms")),
            _show(r.get("rhr_bpm")),
            _show(r.get("training_readiness")),
        )
    console.print(table)


def briefing(json: JsonOpt = False) -> None:
    """Morning briefing: wellness + yesterday's executed + today's plan + 14d load."""
    aid = athlete_id()
    tz = _athlete_tz()
    today_d = datetime.now(tz).date()
    yesterday = today_d - timedelta(days=1)
    db = client()

    # Wellness — fall back to yesterday's row if today's sync hasn't run.
    w_resp = (
        db.table("wellness_daily")
        .select("*")
        .eq("athlete_id", aid)
        .eq("date", today_d.isoformat())
        .limit(1)
        .execute()
    )
    wellness = w_resp.data[0] if w_resp.data else None
    used_fallback = False
    if not wellness:
        w_resp = (
            db.table("wellness_daily")
            .select("*")
            .eq("athlete_id", aid)
            .eq("date", yesterday.isoformat())
            .limit(1)
            .execute()
        )
        wellness = w_resp.data[0] if w_resp.data else None
        used_fallback = wellness is not None

    y_start, y_end = _local_day_bounds(yesterday)
    y_resp = (
        db.table("workouts_executed")
        .select("sport, started_at, duration_s, distance_m, tss, avg_hr, avg_power")
        .eq("athlete_id", aid)
        .gte("started_at", y_start)
        .lt("started_at", y_end)
        .order("started_at")
        .execute()
    )

    plan_resp = (
        db.table("workouts_planned")
        .select("sport, duration_planned_s, tss_planned, description")
        .eq("athlete_id", aid)
        .eq("date", today_d.isoformat())
        .order("sport")
        .execute()
    )

    fourteen_start, _ = _local_day_bounds(today_d - timedelta(days=14))
    load_resp = (
        db.table("workouts_executed")
        .select("tss")
        .eq("athlete_id", aid)
        .gte("started_at", fourteen_start)
        .execute()
    )
    tss_values = [_num(r.get("tss")) for r in (load_resp.data or [])]
    tss_values = [v for v in tss_values if v is not None]
    avg_tss_14d = round(sum(tss_values) / 14.0, 1) if tss_values else 0.0

    # Anomalies — single-day signals only; multi-day patterns are deferred.
    anomalies: list[str] = []
    if wellness:
        sleep_h = (wellness.get("sleep_total_s") or 0) / 3600.0
        if 0 < sleep_h < 6:
            anomalies.append(f"sleep under 6h ({sleep_h:.1f}h)")
        readiness = wellness.get("training_readiness")
        if readiness is not None and readiness < 40:
            anomalies.append(f"readiness low ({readiness}/100)")
        hrv = _num(wellness.get("hrv_overnight_ms"))
        baseline = _num(wellness.get("hrv_baseline_ms"))
        if hrv is not None and baseline is not None and hrv < baseline:
            anomalies.append(f"HRV {hrv:.0f}ms below baseline {baseline:.0f}ms")
    yesterday_tss = sum((_num(r.get("tss")) or 0) for r in (y_resp.data or []))
    if avg_tss_14d > 0 and yesterday_tss > 2 * avg_tss_14d:
        anomalies.append(f"yesterday TSS {yesterday_tss:.0f} > 2× 14d avg ({avg_tss_14d})")

    payload: dict[str, Any] = {
        "date": today_d,
        "wellness": wellness,
        "wellness_fallback_to_yesterday": used_fallback,
        "yesterday": y_resp.data,
        "plan": plan_resp.data,
        "load_14d_avg_tss": avg_tss_14d,
        "anomalies": anomalies,
    }

    if json:
        _emit_json(payload)
        return

    console.print(f"[bold]Briefing for {today_d.strftime('%A, %B %d')}[/bold]")
    if used_fallback:
        console.print("[dim](today's daily sync hasn't run; wellness is yesterday's)[/dim]")
    if wellness:
        sleep_h = (wellness.get("sleep_total_s") or 0) / 3600.0
        hrv = _num(wellness.get("hrv_overnight_ms"))
        base = _num(wellness.get("hrv_baseline_ms"))
        marker = " ✓" if hrv and base and hrv >= base else (" ✗" if hrv and base else "")
        console.print(f"  Sleep:    {sleep_h:.1f}h (score {_show(wellness.get('sleep_score'))})")
        console.print(
            f"  HRV:      {_show(int(hrv)) if hrv else '—'}ms "
            f"(baseline {_show(int(base)) if base else '—'}ms){marker}"
        )
        console.print(f"  RHR:      {_show(wellness.get('rhr_bpm'))} bpm")
        console.print(
            f"  Body bat: {_show(wellness.get('body_battery_low'))} → "
            f"{_show(wellness.get('body_battery_high'))}"
        )
        console.print(f"  Readines: {_show(wellness.get('training_readiness'))}/100")
    else:
        console.print("[dim]  no wellness data yet[/dim]")

    console.print("\n[bold]Yesterday:[/bold]")
    if y_resp.data:
        for w in y_resp.data:
            line = f"  • {w['sport']:<8} {_hms(w.get('duration_s')):>7}"
            if w.get("distance_m"):
                line += f"  {_km(w['distance_m']):>7}"
            if w.get("avg_hr"):
                line += f"  HR {w['avg_hr']}"
            tss = _num(w.get("tss"))
            if tss is not None:
                line += f"  TSS {tss:.0f}"
            console.print(line)
    else:
        console.print("  [dim]nothing logged[/dim]")

    console.print("\n[bold]Today's plan:[/bold]")
    if plan_resp.data:
        for p in plan_resp.data:
            desc = (p.get("description") or "").strip().splitlines()[:1]
            console.print(f"  • {p['sport']:<8} {desc[0] if desc else ''}")
    else:
        console.print("  [dim]rest day[/dim]")

    console.print(f"\n  Load (14d avg TSS): {avg_tss_14d}")
    if anomalies:
        console.print("\n[yellow]Anomalies:[/yellow]")
        for a in anomalies:
            console.print(f"  • {a}")


def status(json: JsonOpt = False) -> None:
    """Diagnostic: latest sync timestamps, row counts, FIT bucket size."""
    aid = athlete_id()
    db = client()

    latest_resp = (
        db.table("wellness_daily")
        .select("date, daily_updated_at, intraday_updated_at")
        .eq("athlete_id", aid)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    latest = latest_resp.data[0] if latest_resp.data else {}

    counts: dict[str, Any] = {}
    for tbl in [
        "athletes",
        "workouts_executed",
        "workouts_planned",
        "wellness_daily",
        "raw_garmin_events",
        "raw_tp_calendar",
    ]:
        try:
            r = db.table(tbl).select("*", count="exact", head=True).execute()
            counts[tbl] = r.count
        except Exception as e:
            counts[tbl] = f"error: {e}"

    try:
        files = db.storage.from_("fit-files").list(aid)
        fit_count: Any = len(files)
    except Exception as e:
        fit_count = f"error: {e}"

    payload = {
        "latest_wellness_date": latest.get("date"),
        "daily_updated_at": latest.get("daily_updated_at"),
        "intraday_updated_at": latest.get("intraday_updated_at"),
        "row_counts": counts,
        "fit_files": fit_count,
    }

    if json:
        _emit_json(payload)
        return

    table = Table(title="training_brain status")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Latest wellness date", _show(payload["latest_wellness_date"]))
    table.add_row("Daily sync ran at", _show(payload["daily_updated_at"]))
    table.add_row("Intraday sync ran at", _show(payload["intraday_updated_at"]))
    for k, v in counts.items():
        table.add_row(f"rows in {k}", _show(v))
    table.add_row("FIT files in storage", _show(fit_count))
    console.print(table)


def register(app: typer.Typer) -> None:
    """Mount read commands on the main typer app."""
    app.command()(briefing)
    app.command()(today)
    app.command()(last)
    app.command()(recent)
    app.command()(recovery)
    app.command()(status)
