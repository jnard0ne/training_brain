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

- **Garmin** (`garth`) — activities, FIT files, sleep, HRV, RHR, body battery, stress, weight, training readiness.
- **TrainingPeaks** — official iCal feed parsed for planned workouts. No public TP API exists for individuals; iCal is the stable export.
- **Strava** (`stravalib`) — supplemental, deduped against Garmin by start time + sport.
- **Zwift** — no direct integration; Zwift auto-syncs to Garmin and Strava.

OpenClaw cron drives two profiles:

- `python -m training_brain.sync intraday` — every 30–60 min for body battery / stress / training readiness.
- `python -m training_brain.sync daily` — early-morning refresh of sleep, HRV, RHR, weight, activities, and TP plan.

Both are idempotent.

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

Required: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ATHLETE_ID`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `TP_ICAL_URL`. Strava vars are optional.

The TP iCal URL is found at TrainingPeaks under **Settings → Account Settings → Sharing → Calendar Feed**. It's tokenized — treat as secret.

### 5. One-time Garmin login

```bash
python -m training_brain.sync login-garmin
```

This will prompt for MFA. The token is cached to `~/.garth/` and refreshed automatically on subsequent runs. Re-run it if cron starts complaining about a stale session.

### 6. Backfill history

```bash
python -m training_brain.sync backfill --since 2025-05-04
```

Defaults to 12 months. Garmin and Strava rate limits are gentle for one athlete; expect this to take a few minutes for the wellness sweep plus more for activity FIT downloads.

### 7. Schedule the daily and intraday sync

Wire OpenClaw cron (or any cron) to:

```
*/45 * * * *   python -m training_brain.sync intraday
0 5    * * *   python -m training_brain.sync daily
```

Both write a JSON blob to stdout and exit non-zero on any per-source failure, so logging and alerting are straightforward.

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
│   ├── sync.py                  # CLI entrypoint (intraday / daily / backfill / login-garmin)
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
- **Untested fields**: the Garmin Connect response shapes vary between accounts and update over time. The first end-to-end run is a calibration step — extend `SPORT_MAP` and `_extract_wellness_fields` in `ingestion/garmin.py` as your real responses surface.
