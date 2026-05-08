---
name: training-brain
description: Answer questions about John's triathlon training and recovery — recent workouts, planned workouts, plan-vs-actual execution, recovery trends (HRV/sleep/RHR), training load (TSS/CTL/ATL/TSB), and progression toward races. Triggers on questions like "how's my recovery", "what's my workout today", "how did I execute yesterday's plan", "show my last ride", "weekly training load". Data lives in a Supabase Postgres project; query via the Supabase MCP.
---

# training-brain

You are answering questions about a triathlete's daily training data, sourced from TrainingPeaks (planned workouts), Garmin Connect (wellness + executed workouts + FIT files), and Strava (cross-check + route data).

## Source authority

When facts conflict, prefer in this order:

1. **TrainingPeaks** — authoritative for planned workouts. Coach-edited.
2. **Garmin Connect** — authoritative for raw physiology (HRV, sleep, RHR, body battery, stress) and executed-workout data.
3. **Strava** — supplemental.

## How to query

Use the Supabase MCP tool `mcp__plugin_supabase_supabase__execute_sql`. Read-only by intent — never write from this skill.

To find the project ref:
1. Check the user's auto-memory for a "Supabase project" entry — that's the canonical record.
2. Fall back to `.env`'s `SUPABASE_URL` (`https://<ref>.supabase.co`).
3. Last resort: `mcp__plugin_supabase_supabase__list_projects` and pick the one named `training_brain`.

The athlete UUID also lives in memory and `.env` (`ATHLETE_ID`); use it as `$1` in the queries below or substitute literally.

When the user asks about "today" or "recent," prefer the athlete's local date (timezone is on `athletes.timezone`, typically `America/Los_Angeles`). Recent days may be partial: the daily sync runs once in the early morning and the intraday sync (when wired into cron) refreshes body battery / stress / training readiness every 30–60 min. Check `wellness_daily.daily_updated_at` and `intraday_updated_at` if freshness matters — if `daily_updated_at` is null on today's row, overnight values (sleep, HRV, RHR) haven't been pulled yet and the user should rerun `daily` or wait for the morning sync.

## Schema (the parts you'll touch)

### `athletes`
`id (uuid pk)`, `name`, `timezone`, `created_at`. Single row in practice.

### `workouts_planned`
One row per TP iCal event.

- `id`, `athlete_id`, `date` (planned day), `sport` (enum: swim/bike/run/strength/mobility/brick/other)
- `duration_planned_s`, `tss_planned`, `description`, `structure` (jsonb, usually null from iCal)
- `source` (`'trainingpeaks'`), `source_uid` (iCal UID)

### `workouts_executed`
One row per real workout, deduped across Garmin/Strava.

- `id`, `athlete_id`, `started_at` (timestamptz UTC), `sport`, `duration_s`, `distance_m`
- `tss`, `intensity_factor`, `avg_hr`, `max_hr`, `avg_power`, `normalized_power`, `avg_cadence`, `avg_pace_s_per_km`, `elevation_gain_m`, `calories`
- `garmin_activity_id`, `strava_activity_id`, `tp_workout_id` (cross-source ids)
- `fit_file_path` (path inside the `fit-files` Storage bucket, format `<athlete_id>/<garmin_id>.zip`)
- `planned_workout_id` (FK; **often NULL** — auto-match isn't run yet, so prefer the date+sport join below)
- `notes`

### `wellness_daily`
One row per athlete per day. Composite PK `(athlete_id, date)`.

- HRV: `hrv_overnight_ms`, `hrv_baseline_ms`
- RHR: `rhr_bpm`
- Sleep: `sleep_total_s`, `sleep_deep_s`, `sleep_light_s`, `sleep_rem_s`, `sleep_awake_s`, `sleep_score`
- Body battery: `body_battery_high`, `body_battery_low`, `body_battery_charged`, `body_battery_drained`
- Stress: `stress_avg`, `stress_max`
- Training: `training_readiness`, `training_status`, `vo2_max`
- Body comp: `weight_kg`, `body_fat_pct`
- Activity counters: `steps`, `floors_climbed`
- Freshness: `intraday_updated_at`, `daily_updated_at` — use these to tell the user how stale a value is.

### `activity_streams`
Time-binned summary streams (HR, power, cadence, speed, altitude, lat/lon) keyed on `(workout_id, bin_offset_s)`. For full-resolution analysis, fetch the FIT from Storage and parse on demand.

### `raw_garmin_events`, `raw_tp_calendar`, `raw_strava_activities`
Append-only audit. Don't query these for normal user questions; use them only when canonical fields are missing and you need to inspect the original payload.

## Plan ↔ execution matching

`workouts_executed.planned_workout_id` is often NULL. Do the join yourself by date + sport:

```sql
select e.started_at, e.sport, e.duration_s, e.tss,
       p.duration_planned_s, p.tss_planned, p.description as plan
from workouts_executed e
left join workouts_planned p
  on p.athlete_id = e.athlete_id
 and p.date = (e.started_at at time zone 'America/Los_Angeles')::date
 and p.sport = e.sport
where e.athlete_id = $1
  and e.started_at >= now() - interval '7 days'
order by e.started_at desc;
```

If the user has two workouts of the same sport on the same day, this join is ambiguous — surface that and ask which they mean.

## Common queries

### Recovery snapshot (last 7 days)
```sql
select date,
       hrv_overnight_ms, hrv_baseline_ms,
       rhr_bpm,
       sleep_total_s/3600.0 as sleep_hours,
       sleep_score,
       body_battery_high, body_battery_low,
       training_readiness
from wellness_daily
where athlete_id = $1
  and date >= current_date - 7
order by date desc;
```

### HRV / RHR trend (28 days)
```sql
select date, hrv_overnight_ms, rhr_bpm
from wellness_daily
where athlete_id = $1
  and date >= current_date - 28
order by date asc;
```

When summarizing trends, mention the rolling baseline (`hrv_baseline_ms`) — Garmin's own "balanced range." Below baseline for 3+ consecutive days is a meaningful signal.

### Today's plan
```sql
select sport, duration_planned_s/60.0 as planned_min,
       tss_planned, description
from workouts_planned
where athlete_id = $1
  and date = current_date
order by date;
```

### Last completed workout
```sql
select started_at, sport, duration_s/60.0 as min,
       distance_m/1000.0 as km,
       tss, intensity_factor, avg_hr, avg_power,
       fit_file_path
from workouts_executed
where athlete_id = $1
order by started_at desc
limit 1;
```

### Weekly TSS by sport (last 8 weeks)
```sql
select date_trunc('week', started_at) as week,
       sport,
       sum(coalesce(tss, 0)) as tss,
       sum(duration_s)/3600.0 as hours
from workouts_executed
where athlete_id = $1
  and started_at >= current_date - interval '56 days'
group by 1, 2
order by 1 desc, 2;
```

### Training load (CTL / ATL / TSB)
CTL is a 42-day exponentially-weighted moving average of daily TSS; ATL is the same with a 7-day window; TSB = CTL − ATL. Recursive CTE:

```sql
with daily as (
    select started_at::date as d,
           coalesce(sum(tss), 0) as tss
    from workouts_executed
    where athlete_id = $1
      and started_at::date >= current_date - 90
    group by 1
),
days_filled as (
    select gs::date as d,
           coalesce(daily.tss, 0) as tss
    from generate_series(current_date - 90, current_date, '1 day') gs
    left join daily on daily.d = gs::date
),
load as (
    select d, tss,
           tss * (1.0/42) as ctl,
           tss * (1.0/7) as atl
    from days_filled
    where d = (select min(d) from days_filled)
    union all
    select d.d, d.tss,
           load.ctl + (d.tss - load.ctl) * (1.0/42),
           load.atl + (d.tss - load.atl) * (1.0/7)
    from days_filled d
    join load on d.d = load.d + 1
)
select d, tss, round(ctl::numeric, 1) as ctl,
       round(atl::numeric, 1) as atl,
       round((ctl - atl)::numeric, 1) as tsb
from load
order by d desc
limit 14;
```

The 90-day warmup matters — without it CTL is artificially low at the start of the window. If the user asks about CTL/ATL near the start of the data range, mention that it's still warming up.

## Known data-quality gaps (read before quoting numbers)

The data tier is live but a few extractors are still rough — call these out when relevant rather than presenting bad numbers as fact.

- **TP planned duration is mostly garbage.** All-day iCal events come through with `duration_planned_s = 86400` (24h). The real planned duration lives in the event description text (e.g., `Planned Time: 1:30`). Until the description parser ships, `duration_planned_s` is reliable only on events with a real DTEND in the iCal feed (rare). Prefer pulling the description and quoting the planned time from there.
- **TP `tss_planned` is almost always NULL.** Same reason — it's in the description text, not a structured field. Don't compute plan-vs-actual TSS deltas; quote actual TSS only.
- **Sport inference for TP events is keyword-based.** Anything the heuristic misses lands as `'other'` (rest days, race events, anything non-keyword). For plan-vs-actual, also try matching by date alone when the sport-side join misses, and inspect `description` to confirm.
- **Wellness staleness on the same morning.** The daily sync writes most fields; `weight_kg` / `body_fat_pct` are only populated when the user actually weighs in that day. NULL there means "didn't weigh in," not "missing data."

When something looks weird, the `raw_*` audit tables hold the original payloads — `raw_garmin_events.payload` is jsonb keyed by date and `kind`, useful for diagnosing extractor regressions.

## Things to be careful about

- **Time zones**: `wellness_daily.date` is the athlete's local date (overnight HRV/sleep are reported by Garmin per local night). `workouts_executed.started_at` is UTC — convert with `at time zone 'America/Los_Angeles'` (or whatever's in `athletes.timezone`) when joining to a planned `date`.
- **Missing data**: `tss` is commonly NULL when the workout isn't structured around power/HR. Don't pretend NULL is zero in narrative answers — say "no TSS recorded." See the data-quality section above for `tss_planned` and `duration_planned_s`.
- **Same-day duplicates**: Plan ↔ execution match by date+sport breaks if the athlete does two of the same sport. Disambiguate.
- **Freshness**: Today's `wellness_daily` may have only the intraday columns populated. Tell the user that overnight values (sleep, HRV) usually populate after the morning daily sync.
- **Deep dives**: For a full-resolution workout analysis, fetch the FIT from Storage:
  - `mcp__plugin_supabase_supabase__execute_sql` to get `fit_file_path`
  - Then download via Supabase Storage REST API (`/storage/v1/object/fit-files/<path>`) using the user's auth.
  - The file is a zip; unzip to get the `.fit` and parse with `fitdecode` or similar.

## When the user asks for narrative

Recovery-style questions ("how's my recovery trending") want a short narrative, not a table dump. Pull the data, then say something like:

> HRV averaged 68ms last 7 days vs your 72ms baseline — slightly suppressed. RHR is 51 (baseline 49). Sleep has been consistent at 7h20m. Body battery is recovering well overnight. Looks like mild fatigue but nothing alarming.

Plan-vs-actual questions want concrete numbers: planned X, executed Y, delta Z, and a one-line "you nailed it" / "fell short on duration" / "went harder than planned."

Always cite the dates of the data you pulled.

## Morning briefing

Triggered by phrases like "morning briefing", "what's today look like", "give me my daily report", or by an automated cron at ~6am local. Goal: one short message a coach could send. Pulls everything needed in a single round-trip; narrates in 4–6 lines.

### Two ways to fetch the data

**If you have shell access** (much cheaper): the project ships a `training-brain` CLI that hits the same data via PostgREST and emits identical JSON:

```
training-brain briefing --json
```

Returned shape: `{ date, wellness, wellness_fallback_to_yesterday, yesterday, plan, load_14d_avg_tss, anomalies }`. The CLI already runs the anomaly checks below and returns them pre-computed, so if you have shell access you can skip straight to the narrative step.

The CLI also exposes `today`, `last [--sport S]`, `recent [--days N]`, `recovery [--days N]`, and `status` — same rule, all support `--json`. Prefer these over hand-written SQL when shell access is available.

**If you only have the Supabase MCP**, run the CTE below. Substitute the athlete UUID for `$1` and the local TZ for `'America/Los_Angeles'`:

```sql
with tz as (select 'America/Los_Angeles'::text as tz),
today as (select (now() at time zone (select tz from tz))::date as d),
last_night as (
    select date, sleep_total_s/3600.0 as sleep_h, sleep_score,
           hrv_overnight_ms, hrv_baseline_ms, rhr_bpm,
           body_battery_high, body_battery_low, training_readiness
    from wellness_daily
    where athlete_id = $1
      and date = (select d from today)
),
yesterday_done as (
    select sport, started_at, duration_s/60.0 as min,
           distance_m/1000.0 as km, tss, avg_hr, avg_power
    from workouts_executed
    where athlete_id = $1
      and (started_at at time zone (select tz from tz))::date = (select d from today) - 1
    order by started_at
),
today_plan as (
    select sport, duration_planned_s/60.0 as planned_min,
           tss_planned, description
    from workouts_planned
    where athlete_id = $1
      and date = (select d from today)
    order by sport
),
load as (
    -- 14d rolling so the briefing can flag deep fatigue without paging through CTL/ATL.
    select round(avg(coalesce(tss, 0))::numeric, 1) as avg_tss_14d
    from (
        select gs::date as d
        from generate_series((select d from today) - 13, (select d from today), '1 day') gs
    ) days
    left join workouts_executed e
      on e.athlete_id = $1
     and (e.started_at at time zone (select tz from tz))::date = days.d
)
select
    (select row_to_json(last_night) from last_night)        as wellness,
    (select coalesce(json_agg(yesterday_done), '[]'::json)
       from yesterday_done)                                  as yesterday,
    (select coalesce(json_agg(today_plan), '[]'::json)
       from today_plan)                                      as plan,
    (select avg_tss_14d from load)                           as load_14d;
```

### Narrative shape

Lead with recovery, then plan. Six lines max. Use this template:

> **<weekday>, <date>.** Slept <h>h, score <n>. HRV <ms>ms (baseline <ms>) — <interpretation>. RHR <bpm>. Training readiness <n>/100.
> **Yesterday:** <executed summary, one line per workout, "no workouts logged" if empty>.
> **Today:** <planned summary, prefer description over duration_planned_s — see data-quality gaps>. <Race/key-workout flag if present in description>.
> <One-line coaching nudge if anomaly: HRV >5ms below baseline, sleep <6h, body battery low end >40, or yesterday TSS >2× 14-day avg. Otherwise omit.>

### Anomaly thresholds (call them out, don't bury them)

- HRV: >5ms or >10% below `hrv_baseline_ms` for 2+ consecutive days.
- Sleep: under 6h, or sleep_score <60.
- RHR: >5bpm above the trailing 14-day median.
- Training readiness: <40.
- Acute load: yesterday's TSS >2× the 14-day rolling average.

If two or more of those fire, lead with a "back off today" recommendation rather than just listing the data — the user's coach already wrote the plan, but the briefing's job is to flag when the plan and the body disagree.

### Empty-data behavior

- No `last_night` row → "Wellness sync hasn't run for today yet — running on yesterday's numbers." then re-query for `(select d from today) - 1`.
- No `yesterday_done` and no `today_plan` → keep it short: "Rest day, nothing logged. <wellness line>."
- Briefing called from cron with no recipient → emit the narrative to stdout; the cron host is responsible for piping to wherever (Slack, email, push).
