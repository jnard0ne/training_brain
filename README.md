# training_brain

A personal data tier for triathlon training. Pulls planned workouts from
TrainingPeaks, executed workouts and physiology from Garmin Connect, and
(optionally) cross-checks against Strava — then normalizes everything into
Supabase Postgres so a Claude / OpenClaw skill can answer questions about
recovery, plan-vs-actual execution, and training load.

This repo is the data tier only. Daily reports and other downstream outputs
are produced by separate skills that query the schema described in
[`skills/training-brain.md`](skills/training-brain.md).

## How it works

```
Garmin Connect  ──┐
TrainingPeaks   ──┼──►  ingestion  ──►  normalize  ──►  Supabase Postgres  ──►  Claude/OpenClaw skill
Strava          ──┘                                     + Storage (FIT files)
```

- **Garmin** (`garminconnect` + `curl_cffi`) — activities, FIT files, sleep, HRV, RHR, body battery, stress, weight, training readiness. Migrated from `garth` after Garmin's March 2026 Cloudflare changes broke its login flow.
- **TrainingPeaks** — official iCal feed parsed for planned workouts. No public TP API exists for individuals; iCal is the stable export.
- **Strava** (`stravalib`) — supplemental, deduped against Garmin by start time + sport.
- **Zwift** — no direct integration; Zwift auto-syncs to Garmin and Strava.

The `training-brain` CLI (installed by `pip install -e .`) is the entrypoint for both writes (sync) and reads (queries):

- **Sync** — drives the OpenClaw cron:
  - `training-brain intraday` — every 30–60 min for body battery / stress / training readiness.
  - `training-brain daily` — early-morning refresh of sleep, HRV, RHR, weight, activities, and TP plan.
- **Queries** — for poking at the data from the terminal (or any agent with shell access):
  - `training-brain briefing` — today's wellness + yesterday's executed + today's plan + 14d load + anomaly flags.
  - `training-brain today` — today's planned workouts.
  - `training-brain last [--sport S]` — most recent completed workout.
  - `training-brain recent [--days N]` — last N days of executed workouts (default 7).
  - `training-brain recovery [--days N]` — wellness trend (default 14).
  - `training-brain analyze [<garmin_id>]` — deep dive on a single workout: laps, mean-max power/HR curve, time-in-zone, aerobic decoupling. Defaults to most recent.
  - `training-brain status` — sync timestamps, row counts, FIT bucket size.

Every read command takes `--json` for machine-readable output. Both sync profiles are idempotent.

## Replication

> Forkers: this section assumes you want your own deployment — your own Supabase project, your own Garmin/TP/Strava credentials.

### 1. Prereqs

- Python 3.11+
- A Supabase account (the free plan is enough)
- A Garmin Connect account
- A TrainingPeaks account with a personal iCal feed URL
- (Optional) A Strava API app (Settings → API at strava.com)

### 2. Install

```bash
git clone <your-fork>
cd training_brain
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 3. Provision Supabase

Create a Supabase project, then apply the migrations in `db/migrations/` in order. Two ways:

- **Supabase CLI**: `supabase link --project-ref <ref>` then `supabase db push` after copying the SQL into a `supabase/migrations` directory.
- **Supabase MCP** (if using Claude Code): the `apply_migration` tool runs each file directly.
- **Dashboard**: paste each SQL file into the SQL editor and run.

Then seed your athlete row:

```sql
insert into athletes (name, timezone)
values ('Your Name', 'America/Los_Angeles')
returning id;
```

Save the returned UUID — it goes in `.env` as `ATHLETE_ID`.

### 4. Configure `.env`

```bash
cp .env.example .env
# then fill in the values
```

Required: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `ATHLETE_ID`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `TP_ICAL_URL`. Strava vars are optional.

`SUPABASE_SECRET_KEY` is the modern `sb_secret_...` key from **Project Settings → API Keys** — not the legacy `service_role` JWT.

The TP iCal URL is found at TrainingPeaks under **Settings → Account Settings → Sharing → Calendar Feed**. It's tokenized — treat as secret.

### 5. One-time Garmin login

```bash
training-brain login-garmin
```

This will prompt for MFA. Tokens are cached to `~/.garminconnect/` and refreshed automatically on subsequent runs. Re-run it if cron starts complaining about a stale session.

### 6. Backfill history

```bash
training-brain backfill --since 2025-05-04
```

Defaults to 12 months. Garmin and Strava rate limits are gentle for one athlete; expect this to take a few minutes for the wellness sweep plus more for activity FIT downloads.

### 7. Schedule the daily and intraday sync

Wire OpenClaw cron (or any cron) to:

```
*/45 * * * *   training-brain intraday
0 5    * * *   training-brain daily
```

Both write a JSON blob to stdout and exit non-zero on any per-source failure, so logging and alerting are straightforward.

### 8. Verify it's working

```bash
training-brain status      # row counts, latest sync timestamps, FIT bucket size
training-brain briefing    # today's morning briefing — your end-to-end smoke test
training-brain analyze     # deep dive on the most recent workout (laps, mean-max, decoupling)
```

### 9. (Optional) Seed your training zones

Time-in-zone analysis in `analyze` needs zone definitions. Insert your coach-defined HR / power / pace zones into `training_zones`:

```sql
-- example: 5-zone HR for run, replace with your own thresholds
insert into training_zones (athlete_id, sport, metric, zone, lower, upper) values
    ('<your-athlete-uuid>', 'run', 'hr', 1, 0,   130),
    ('<your-athlete-uuid>', 'run', 'hr', 2, 130, 145),
    ('<your-athlete-uuid>', 'run', 'hr', 3, 145, 160),
    ('<your-athlete-uuid>', 'run', 'hr', 4, 160, 175),
    ('<your-athlete-uuid>', 'run', 'hr', 5, 175, 999);
```

Skip this step if you only want lap analysis + mean-max curves; analyze falls back gracefully without zones.

## Layout

```
training_brain/
├── CLAUDE.md                    # context for AI agents working in this repo
├── README.md                    # you are here
├── .env.example
├── pyproject.toml
├── db/migrations/               # SQL migrations, applied in order
├── src/training_brain/
│   ├── db.py                    # Supabase client + env loader
│   ├── sync.py                  # CLI entrypoint; sync subcommands (intraday / daily / backfill / login-garmin)
│   ├── query.py                 # CLI read subcommands (briefing / today / last / recent / recovery / analyze / status)
│   ├── streams.py               # FIT parser; populates activity_streams + workout_laps on every sync
│   └── ingestion/
│       ├── garmin.py
│       ├── trainingpeaks.py
│       └── strava.py
└── skills/
    └── training-brain.md        # the skill consumed by Claude / OpenClaw
```

For deeper architectural context (why iCal, source authority, refresh cadences, how to add a metric), see [`CLAUDE.md`](CLAUDE.md).

## Caveats

- **TrainingPeaks edits**: if you manually edit a workout in TP after the fact, this pipeline won't see the edit (Garmin is the execution-data source). Acceptable for v1.
- **Same-day duplicates**: plan-↔-execution match is by date + sport. If you do two swims in a day, the join is ambiguous.
- **Garmin response drift**: Garmin Connect response shapes vary between accounts and change over time. The wellness extractors and `SPORT_MAP` in `ingestion/garmin.py` are calibrated against one account as of May 2026. If new accounts or a Garmin update surface fields that aren't being captured, inspect `raw_garmin_events.payload` (jsonb) for the original response and extend the extractors.
- **TP planned duration / TSS**: TrainingPeaks all-day iCal events surface `duration_planned_s = 86400` and `tss_planned = null`. The real values live in the event description text (`Planned Time: 1:30`, etc.). A description parser is on the backlog; until then, use `description` directly when quoting plan numbers.
