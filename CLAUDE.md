# training_brain

Personal triathlon training data tier. Centralizes data from TrainingPeaks, Garmin Connect, and Strava into Supabase Postgres so Claude / OpenClaw skills can answer training questions and feed daily reports.

The repo is personal but may be published publicly so others can replicate — keep secrets out of the repo and document replication in `README.md`.

## Source authority

When the same fact exists in multiple sources, prefer in this order:

1. **TrainingPeaks** — authoritative for everything, especially planned workouts and coach-edited execution data.
2. **Garmin Connect** — authoritative for raw physiology (HRV, sleep, RHR, body battery, stress) and the bulk of executed-workout data, since most workouts originate on Garmin devices.
3. **Strava** — supplemental; useful for route polylines and as a dedup cross-check.

## Why iCal + Garmin instead of TP scraping

TrainingPeaks does not offer a public API to individuals. We pull the **plan** from TP's iCal feed (official, stable) and the **executed workout data** from Garmin Connect, since TP receives most workouts from Garmin anyway. Trade-off: if a workout is *manually edited in TP after the fact*, we won't see the edit. Acceptable for v1; revisit if it becomes a real problem.

Do not add a TP web scraper without explicit confirmation — it's brittle, ToS gray area, and a maintenance burden for a public repo.

## Data sources & libraries

| Source | Library | Auth | Used for |
|---|---|---|---|
| Garmin Connect | `garminconnect` (cyberjunky) + `curl_cffi` | Stored token (one-time interactive login, cached to `~/.garminconnect`) | Activities, FIT files, sleep, HRV, RHR, body battery, stress, weight, training readiness |
| TrainingPeaks | iCal feed (HTTP GET) | Tokenized URL | Planned workouts |
| Strava | `stravalib` | OAuth | Activity dedup, route polylines |

Zwift workouts auto-sync to Garmin Connect and Strava — no Zwift-specific integration needed.

## Refresh cadences

Different metrics change at different rates, so sync runs in two profiles, both idempotent:

- **`sync intraday`** (every 30–60 min via OpenClaw cron) — body battery, current stress, training readiness, latest HR.
- **`sync daily`** (early morning) — sleep, overnight HRV, RHR, weight, planned workouts (TP iCal), executed activities + FIT files, Strava cross-check.
- **`sync backfill --since YYYY-MM-DD`** (manual) — historical sweep, default 12 months. Rate-limit-aware paging.

CLI entrypoints live in `src/training_brain/sync.py`. Re-running any profile is always safe.

## Storage

- **Supabase Postgres** — canonical schema and raw audit tables. Schema lives in `db/migrations/`. Apply via Supabase MCP or `supabase` CLI.
- **Supabase Storage** — original FIT files. `activity_streams` table holds summary stream metrics for cheap queries; deep-dive analysis re-parses the FIT on demand.

Tables (high level):
- `athletes`
- `raw_garmin_events`, `raw_tp_calendar`, `raw_strava_activities` — append-only audit, never mutated
- `workouts_planned`, `workouts_executed` — canonical, deduped, joined by `(athlete_id, date, sport)`
- `wellness_daily` — one row per athlete per day; columns updated by intraday or daily profile depending on metric
- `activity_streams` — partitioned summary stream metrics

## Secrets

**No credentials in the repo.** This includes Garmin email/password, TP iCal token URL, Strava client secret, Supabase service key.

- Local dev: `.env` (gitignored). See `.env.example`.
- Production cron: env vars on the host running OpenClaw cron.
- `garminconnect`'s token cache (`~/.garminconnect/`) stays out of the repo.

## Layout

```
training_brain/
├── CLAUDE.md
├── README.md                       # replication guide for forkers
├── .env.example
├── pyproject.toml
├── src/training_brain/
│   ├── ingestion/
│   │   ├── garmin.py
│   │   ├── trainingpeaks.py
│   │   └── strava.py
│   ├── normalize.py                # canonical model + cross-source dedup
│   ├── sync.py                     # CLI: intraday | daily | backfill
│   └── db.py
├── db/
│   └── migrations/
└── skills/
    └── training-brain.md           # skill file consumed by Claude/OpenClaw
```

## Skill file contract

`skills/training-brain.md` is what Claude / OpenClaw load when answering training questions. It documents the live schema, source authority, common queries (recovery trend, plan-vs-actual, weekly TSS/CTL/ATL/TSB), and the Supabase MCP query pattern.

**When the canonical schema changes, update the skill file in the same commit.** A drifted skill file means agents return wrong answers silently.

## How to add a new metric

1. Add the column to the relevant canonical table via a new migration in `db/migrations/`.
2. Extend the matching ingester in `src/training_brain/ingestion/` to populate it.
3. Update `skills/training-brain.md` so agents know the metric exists and how to query it.
4. If the metric should be refreshed more than once a day, wire it into the `intraday` profile in `sync.py`; otherwise leave it in `daily`.

## Build status

Code-complete; not yet exercised against live credentials. Build phases:

1. ✅ Repo skeleton (`pyproject.toml`, `.env.example`, `.gitignore`, package layout)
2. ✅ Supabase project + schema migrations (4 migrations applied; `fit-files` bucket created; athlete row seeded)
3. ✅ Garmin ingestion (`garminconnect` — migrated from deprecated `garth` 2026-05-08)
4. ✅ TrainingPeaks iCal ingestion
5. ✅ Daily + intraday sync entrypoints (`src/training_brain/sync.py`)
6. ✅ Backfill (12-month default)
7. ✅ Strava ingestion
8. ✅ Skill file (`skills/training-brain.md`)

**Remaining before first real use:**
- Populate local `.env` (Garmin login, TP iCal URL, Strava OAuth, Supabase service key)
- Run `sync daily` end-to-end and verify data lands in canonical tables
- Schedule the OpenClaw cron (intraday + daily)

Update this section as phases complete.
