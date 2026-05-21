# AGENTS.md

You are an agent helping your human use the **training_brain** data tier — a Supabase Postgres database that centralizes their training data from TrainingPeaks, Garmin Connect, and Strava. Use it to answer questions about their training: recovery, planned vs. executed workouts, zone distribution, training load, and detailed analysis of individual sessions.

This file tells you what's in the database, how to query it, and how to handle the common patterns. Read it once at the start of any session that touches training questions; refer back when you hit edge cases.

---

## Source authority

When the same fact exists in multiple sources, prefer in this order:

1. **TrainingPeaks** — authoritative for planned workouts (coach-edited) and any execution data the athlete has manually corrected.
2. **Garmin Connect** — authoritative for raw physiology (HRV, sleep, RHR, body battery, stress, training readiness) and the bulk of executed-workout data, since most workouts originate on Garmin devices and sync to TP automatically.
3. **Strava** — supplemental. Useful for route polylines and as a cross-source dedup check.

Don't hedge by averaging across sources. Pick the authoritative one and cite it if relevant.

---

## How to fetch data

Two paths; pick the cheaper one available to you.

> **Aside — local web UI.** `training-brain web` launches a FastAPI + React app
> on `http://localhost:8765` for human-facing tasks: connecting and
> re-authenticating Garmin / TrainingPeaks / Strava, viewing connection status.
> It's not a query interface and you shouldn't drive it programmatically;
> redirect the human there if they're stuck on auth (Garmin MFA loop, Strava
> token expired, TP iCal URL changed).

### Shell access — preferred

The `training-brain` CLI is installed in the project venv. Every read command takes `--json` for machine-readable output:

| Command | Use when the human asks… |
|---|---|
| `training-brain briefing` | "morning briefing", "what's today look like", "give me my daily report" |
| `training-brain today` | "what's planned today", "what am I doing today" |
| `training-brain last [--sport S]` | "how was my last workout", "show me my last ride" |
| `training-brain recent [--days N]` | "what did I do this week", "last 5 days of workouts" |
| `training-brain recovery [--days N]` | "how's my recovery", "show me my HRV trend" |
| `training-brain analyze [<garmin_activity_id>]` | "tell me about that workout", "deep dive on yesterday's ride", "show me lap splits" — defaults to most recent |
| `training-brain strava_relative_effort --days N \| --activities N` | "what's my Relative Effort been", "RE for the last 14 days", "RE on my last 5 rides". Hits Strava live and backfills `workouts_executed.relative_effort` along the way — flags are mutually exclusive, defaults to `--days 7`. |
| `training-brain status` | "is the data up to date", "did the sync run" |

Returns from `--json` are pre-shaped for narration (anomaly flags pre-computed, time-in-zone tables ready, etc.). Prefer these over hand-written SQL when shell access is available; SQL is the fallback for MCP-only contexts.

### Supabase MCP — fallback

Use `mcp__plugin_supabase_supabase__execute_sql`. Read-only by intent — never write through this skill.

To find the project ref:
1. Check the `.env` file's `SUPABASE_URL` (`https://<ref>.supabase.co`).
2. If `.env` isn't accessible, `mcp__plugin_supabase_supabase__list_projects` and pick `training_brain`.

The athlete UUID lives in `.env`'s `ATHLETE_ID`; substitute it for `$1` in the queries below.

---

## Schema (the parts you'll touch)

### `athletes`
Single row per athlete. `id (uuid pk)`, `name`, `timezone` (IANA, e.g. `'America/Los_Angeles'`), `created_at`.

### `workouts_planned`
One row per TP iCal event.
- `id`, `athlete_id`, `date` (planned local date), `sport` (enum: `swim`/`bike`/`run`/`strength`/`mobility`/`brick`/`other`)
- `duration_planned_s`, `tss_planned`, `description` (free text from TP), `structure` (jsonb, usually null)
- `source` (`'trainingpeaks'`), `source_uid` (iCal UID)

### `workouts_executed`
One row per real workout, deduped across Garmin/Strava.
- `id`, `athlete_id`, `started_at` (timestamptz UTC), `sport`, `duration_s`, `distance_m`
- `tss`, `intensity_factor`, `avg_hr`, `max_hr`, `avg_power`, `normalized_power`, `avg_cadence`, `avg_pace_s_per_km`, `elevation_gain_m`, `calories`
- `relative_effort` — Strava's HR-derived effort score (their API field `suffer_score`, branded "Relative Effort"). Populated when the row has a matched Strava activity with HR. NULL for power-only Garmin rides, manual entries with no HR, or any workout that never made it to Strava.
- `garmin_activity_id`, `strava_activity_id`, `tp_workout_id` — cross-source IDs
- `fit_file_path` — path inside the `fit-files` Storage bucket (`<athlete_id>/<garmin_id>.zip`)
- `planned_workout_id` — FK; **often NULL**. Auto-match isn't run; prefer the date+sport join under "Plan ↔ execution matching."

### `wellness_daily`
One row per athlete per day. Composite PK `(athlete_id, date)`.
- HRV: `hrv_overnight_ms`, `hrv_baseline_ms`
- RHR: `rhr_bpm`
- Sleep: `sleep_total_s`, `sleep_deep_s`, `sleep_light_s`, `sleep_rem_s`, `sleep_awake_s`, `sleep_score`
- Body battery: `body_battery_high`, `body_battery_low`, `body_battery_charged`, `body_battery_drained`
- Stress: `stress_avg`, `stress_max`
- Training: `training_readiness`, `training_status`, `vo2_max`
- Body comp: `weight_kg`, `body_fat_pct` (only populated on weigh-in days)
- Activity counters: `steps`, `floors_climbed`
- Freshness: `intraday_updated_at`, `daily_updated_at` — use these to tell the human how stale a value is.

### `activity_streams`
Time-binned per-workout streams keyed on `(workout_id, bin_offset_s)`. Default `bin_size_s = 1` so this is essentially the 1Hz FIT record stream. Columns: `hr`, `power`, `cadence`, `speed_m_s`, `altitude_m`, `lat`, `lon`. Populated automatically on every sync.

**Pagination warning**: PostgREST caps each page at 1000 rows. Long workouts (5h rides) easily have 17k+ stream rows. Use `range(0, N)` or paginate. The `analyze` CLI handles this for you.

### `workout_laps`
Per-lap summary records pulled from FIT lap messages, keyed on `(workout_id, lap_index)`. Captures interval boundaries — manual lap presses, distance/time auto-laps, swim pool lengths, brick transitions. Columns: `started_at`, `duration_s` (active timer time, matches `workouts_executed.duration_s` convention), `distance_m`, `avg_hr`/`max_hr`, `avg_power`/`max_power`/`normalized_power`, `avg_cadence`, `avg_pace_s_per_km`, `intensity` (`active`/`rest`/`warmup`/`cooldown`), `lap_trigger` (`manual`/`distance`/`time`/`session_end`).

### `training_zones`
Coach-defined zones per `(athlete_id, sport, metric, zone)`. `metric` is `'hr'`, `'power'`, or `'pace_s_per_km'`. Up to 7 zones. May be empty if the athlete hasn't seeded them — fall back to %FTP / %LTHR heuristics if so, but seeded zones are authoritative.

For `pace_s_per_km`: lower numeric = faster pace. Z1 (recovery) has the largest values; Z7 (anaerobic) the smallest. Open-ended bounds use NULL (e.g. Z1 has `upper = NULL` meaning no slower limit).

### `raw_garmin_events`, `raw_tp_calendar`, `raw_strava_activities`
Append-only audit tables. Don't query for normal user questions; use only when canonical fields are missing and you need to inspect the original payload (`payload` is jsonb).

---

## Common task patterns

### Morning briefing

Triggered by phrases like "morning briefing", "what's today look like", "give me my daily report". Goal: one short message a coach could send. 4–6 lines.

**Shell path** (preferred):

```
training-brain briefing --json
```

Returns `{ date, wellness, wellness_fallback_to_yesterday, yesterday, plan, load_14d_avg_tss, anomalies }`. `anomalies` is pre-computed; surface them in the narrative.

**SQL path** (substitute athlete UUID for `$1`, IANA timezone for the literal):

```sql
with tz as (select 'America/Los_Angeles'::text as tz),
today as (select (now() at time zone (select tz from tz))::date as d),
last_night as (
    select date, sleep_total_s/3600.0 as sleep_h, sleep_score,
           hrv_overnight_ms, hrv_baseline_ms, rhr_bpm,
           body_battery_high, body_battery_low, training_readiness
    from wellness_daily
    where athlete_id = $1 and date = (select d from today)
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
    where athlete_id = $1 and date = (select d from today)
    order by sport
),
load as (
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

**Narrative shape:**

> **<weekday>, <date>.** Slept <h>h, score <n>. HRV <ms>ms (baseline <ms>) — <interpretation>. RHR <bpm>. Training readiness <n>/100.
> **Yesterday:** <executed summary, one line per workout, "no workouts logged" if empty>.
> **Today:** <planned summary; prefer description over duration_planned_s — see data-quality gaps>. <Race/key-workout flag if present in description>.
> <One-line coaching nudge if anomaly. Otherwise omit.>

**Anomaly thresholds** (call them out, don't bury them):

- HRV: >5ms or >10% below `hrv_baseline_ms`.
- Sleep: under 6h, or sleep_score <60.
- RHR: >5bpm above the trailing 14-day median.
- Training readiness: <40.
- Acute load: yesterday's TSS >2× the 14-day rolling average.

If two or more fire, lead with a "back off today" recommendation rather than just listing the data — the briefing's job is to flag when the plan and the body disagree.

**Empty-data behavior:**

- No `last_night` row → "Wellness sync hasn't run for today yet — running on yesterday's numbers." Fall back to yesterday's `wellness_daily`.
- No `yesterday_done` and no `today_plan` → keep it short: "Rest day, nothing logged. <wellness line>."

### Recovery / wellness questions

For "how's my recovery trending":

```
training-brain recovery --days 14
```

When summarizing trends, mention the rolling baseline (`hrv_baseline_ms`) — Garmin's own "balanced range." HRV below baseline for 3+ consecutive days is a meaningful signal worth flagging.

Recovery answers want short narrative, not table dumps. Pull the data, then say something like:

> HRV averaged 68ms last 7 days vs. your 72ms baseline — slightly suppressed. RHR is 51 (baseline 49). Sleep has been consistent at 7h20m. Body battery is recovering well overnight. Mild fatigue but nothing alarming.

### Today's plan / yesterday's execution

```
training-brain today
training-brain last
```

For a plan-vs-actual comparison, see the next section.

### Plan ↔ execution matching

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

If the athlete has two workouts of the same sport on the same day, the join is ambiguous — surface that and ask which they mean.

Plan-vs-actual answers want concrete numbers: planned X, executed Y, delta Z, and a one-line "you nailed it" / "fell short on duration" / "went harder than planned." **But** see "Known data-quality gaps" before quoting `duration_planned_s` or `tss_planned` directly — both are unreliable today.

### Deep workout analysis

For "tell me about that workout" / "how hard was that ride" / "compare those intervals":

```
training-brain analyze <garmin_activity_id> --json
```

Returns the full picture: lap table, mean-max curve at 5s/30s/1m/5m/20m/1h, time-in-zone for HR/power/pace (when zones seeded), aerobic decoupling. Cheaper than running multiple SQL queries.

If the human gives you a date or "yesterday's ride" instead of a Garmin ID, look it up first:

```sql
select garmin_activity_id, sport, started_at, duration_s/60 as min
from workouts_executed
where athlete_id = $1
  and started_at >= now() - interval '2 days'
order by started_at desc;
```

#### SQL fallback for analysis

**Lap-by-lap breakdown:**
```sql
select lap_index, duration_s, distance_m,
       avg_hr, max_hr, avg_power, normalized_power,
       avg_cadence, avg_pace_s_per_km, intensity, lap_trigger
from workout_laps
where workout_id = $1
order by lap_index;
```

**Mean-max power curve** — best 5s, 30s, 1m, 5m, 20m, 60m windows. Window assumes 1Hz bins (the default):

```sql
with bins as (
    select bin_offset_s, power
    from activity_streams
    where workout_id = $1 and power is not null
    order by bin_offset_s
)
select 'peak_5s'  as window, max(avg_p)::int as best from (
    select avg(power) over (order by bin_offset_s rows between current row and 4 following) as avg_p from bins) t
union all
select 'peak_5m',  max(avg_p)::int from (
    select avg(power) over (order by bin_offset_s rows between current row and 299 following) as avg_p from bins) t
union all
select 'peak_20m', max(avg_p)::int from (
    select avg(power) over (order by bin_offset_s rows between current row and 1199 following) as avg_p from bins) t;
```

**Time-in-zone (HR):**
```sql
with stream as (
    select s.hr, tz.zone
    from activity_streams s
    join training_zones tz
      on tz.athlete_id = $athlete and tz.sport = $sport and tz.metric = 'hr'
     and (tz.lower is null or s.hr >= tz.lower)
     and (tz.upper is null or s.hr <= tz.upper)
    where s.workout_id = $1 and s.hr is not null
)
select zone, count(*) as seconds
from stream
group by zone
order by zone;
```

**Aerobic decoupling (Pw:Hr drift):**
```sql
with halves as (
    select case
             when bin_offset_s < (select max(bin_offset_s)/2 from activity_streams where workout_id = $1)
             then 'first' else 'second'
           end as half,
           hr, power
    from activity_streams
    where workout_id = $1 and hr is not null and power is not null
)
select half, sum(power)::numeric / nullif(sum(hr), 0) as pw_hr_ratio
from halves group by half;
```

A 5%+ drop in second-half ratio = meaningful aerobic decoupling.

### Training load (CTL / ATL / TSB)

CTL = 42-day exponentially-weighted moving average of daily TSS. ATL = same with 7-day window. TSB = CTL − ATL.

```sql
with daily as (
    select started_at::date as d, coalesce(sum(tss), 0) as tss
    from workouts_executed
    where athlete_id = $1 and started_at::date >= current_date - 90
    group by 1
),
days_filled as (
    select gs::date as d, coalesce(daily.tss, 0) as tss
    from generate_series(current_date - 90, current_date, '1 day') gs
    left join daily on daily.d = gs::date
),
load as (
    select d, tss, tss * (1.0/42) as ctl, tss * (1.0/7) as atl
    from days_filled where d = (select min(d) from days_filled)
    union all
    select d.d, d.tss,
           load.ctl + (d.tss - load.ctl) * (1.0/42),
           load.atl + (d.tss - load.atl) * (1.0/7)
    from days_filled d join load on d.d = load.d + 1
)
select d, tss, round(ctl::numeric, 1) as ctl,
       round(atl::numeric, 1) as atl,
       round((ctl - atl)::numeric, 1) as tsb
from load order by d desc limit 14;
```

The 90-day warmup matters — without it CTL is artificially low at the start of the window. If the athlete asks about CTL/ATL near the start of their data range, mention it's still warming up.

### Weekly volume

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

---

## Known data-quality gaps (read before quoting numbers)

The data tier is live but a few extractors are still rough. Surface these gaps when relevant rather than presenting bad numbers as fact.

- **TP planned duration is mostly garbage.** All-day iCal events come through with `duration_planned_s = 86400` (24h). The real planned duration lives in the event description text (`Planned Time: 1:30`). Prefer pulling the description and quoting the planned time from there. `duration_planned_s` is reliable only on events with a real DTEND in the iCal feed (rare).
- **TP `tss_planned` is almost always NULL.** Same reason — it's in the description text. Don't compute plan-vs-actual TSS deltas; quote actual TSS only.
- **Sport inference for TP events is keyword-based.** Anything the heuristic misses lands as `'other'` (rest days, race events, anything non-keyword). For plan-vs-actual, also try matching by date alone when the sport-side join misses, and inspect `description` to confirm.
- **Wellness staleness on the same morning.** The daily sync writes most fields; `weight_kg` / `body_fat_pct` are only populated when the athlete actually weighs in that day. NULL there means "didn't weigh in," not "missing data."
- **Run/bike `tss` is commonly NULL** when the workout isn't structured around power/HR (e.g., easy spins, strength sessions). Don't pretend NULL is zero in narrative answers — say "no TSS recorded."

When something looks weird, the `raw_*` audit tables hold the original payloads. `raw_garmin_events.payload` is jsonb keyed by `kind`+`occurred_on`, useful for diagnosing extractor regressions.

---

## Things to be careful about

- **Time zones.** `wellness_daily.date` is the athlete's local date (overnight HRV/sleep are reported by Garmin per local night). `workouts_executed.started_at` is UTC — convert with `at time zone <athletes.timezone>` when joining to a planned `date` or computing local-day boundaries.
- **Same-day duplicates.** Plan ↔ execution match by date+sport breaks if the athlete does two of the same sport in one day (two swims, AM+PM run). Disambiguate by asking which they mean.
- **Freshness.** Today's `wellness_daily` may have only the intraday columns populated until the morning daily sync runs. If overnight values (sleep, HRV) are missing, tell the athlete the daily sync hasn't run yet — don't say "no data."
- **Numeric round-trip.** Postgres `numeric` columns serialize as JSON strings through PostgREST (e.g., `hrv_overnight_ms = "55"`). Cast to float in Python or `::numeric` in SQL when comparing.
- **Pagination on streams.** `activity_streams` for a 5h ride is ~17k rows. Naive `select * where workout_id=…` returns only 1000. Paginate via `.range(start, end)` or use the `analyze` CLI.
- **FIT deep dives** for sub-second analysis or fields not in `activity_streams`:
  1. SQL to get `fit_file_path`.
  2. Download via Supabase Storage (`/storage/v1/object/fit-files/<path>`).
  3. The file is a zip; unzip to get the `.fit` and parse with `fitdecode` or similar.

---

## Narrative style

- **Recovery questions** want short narrative, not tables. Pull data, write 3–5 sentences, end with a verdict ("mild fatigue but nothing alarming" / "well rested" / "back off today").
- **Plan-vs-actual** wants concrete numbers + one-line judgment ("you nailed it" / "went harder than planned" / "fell short on duration").
- **"Tell me about that workout"** wants the analyze output, lightly narrated. Surface the most interesting thing first (a peak power, big decoupling, a clean interval split) — don't just dump tables.
- **Always cite the dates of the data you pulled.**
- **Never write to canonical tables from a query path.** This file is read-only by intent. Writes happen through the sync CLI, which the human runs (manually or via cron).
- **If you don't know, say so.** Better to ask the athlete a clarifying question than to guess at their training intent. The data is good but coach-level interpretation isn't always derivable from numbers alone.
