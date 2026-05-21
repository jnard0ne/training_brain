# training_brain

A personal data tier for endurance training. Pulls planned workouts from
TrainingPeaks, executed workouts and physiology from Garmin Connect, and
(optionally) cross-checks against Strava — then normalizes everything into a
Supabase Postgres database that you own.

The point: stop logging into three different apps to answer one question
about your own training. Your data lives in one place, queryable by SQL or
by any AI agent that can read [AGENTS.md](AGENTS.md).

```
Garmin Connect  ──┐
TrainingPeaks   ──┼──►  ingestion  ──►  Supabase Postgres  ──►  CLI / your agent
Strava          ──┘                     + Storage (FIT files)
```

This is a personal project that's been made public so others can replicate
it. I don't take pull requests — fork it and make it yours.

---

## What you get

A working end-to-end data tier with:

- **Daily wellness ingestion** — sleep, HRV, RHR, body battery, stress, training readiness, weight (when you weigh in).
- **Workout ingestion** — every activity from Garmin (which receives most workouts via Garmin/Zwift sync) plus the original `.fit` file in Supabase Storage. One canonical row per workout, deduped across sources.
- **TrainingPeaks plan ingestion** — your coach's planned workouts via the official iCal feed.
- **1Hz workout streams** — every executed workout is parsed into per-second time series (HR, power, cadence, speed, altitude, GPS) for detailed analysis. Plus per-lap summaries from the FIT file.
- **A read CLI** with seven commands: morning briefing, today's plan, last workout, recent activity, recovery trend, deep workout analysis, and status.
- **Time-in-zone analysis** — once you seed your zones, every analysis surfaces zone distributions for HR, power, and pace.
- **Aerobic decoupling, mean-max curves, lap-by-lap splits** — out of the box.
- **An [AGENTS.md](AGENTS.md) file** any AI agent can read to answer training questions — morning briefings, plan vs. actual, recovery summaries, workout deep-dives.
- **A local web UI** (`training-brain web`) for connecting and re-authenticating Garmin, TrainingPeaks, and Strava without touching `.env` by hand.

What it isn't:

- Not a coaching app. It doesn't tell you what to do tomorrow.
- Not a multi-tenant SaaS. One athlete, one database.
- Not a TrainingPeaks scraper. Plan data comes from the official iCal feed, not the TP web app. If you edit a workout in TP after the fact, this pipeline won't see the edit.

---

## Setup

This guide assumes you can use a terminal but aren't a working developer.
Each step is independent — if one breaks, you can come back to it. If you'd
rather have an AI agent walk you through it, skip to **[Setup with an AI
agent](#setup-with-an-ai-agent)** below.

### What you'll need

- A computer running macOS or Linux (Windows works with WSL, untested).
- Python 3.11 or newer. Check with `python3 --version`. If you're below 3.11, install from [python.org](https://www.python.org/downloads/) or via your package manager.
- A free [Supabase](https://supabase.com) account.
- A Garmin Connect account.
- A TrainingPeaks account (the iCal feed is free for any TP plan).
- (Optional) A Strava account with API access.

### 1. Clone the repo

```bash
git clone https://github.com/jnard0ne/training_brain.git
cd training_brain
```

### 2. Set up Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The first line creates an isolated Python environment in `.venv/`. The second activates it (you'll need to re-run this whenever you open a new terminal). The third installs the project and its dependencies.

After this you should have a `training-brain` command available:

```bash
training-brain --help
```

### 3. Create your Supabase project

1. Sign in to [supabase.com](https://supabase.com), click **New project**, give it a name and a strong database password (you won't need it for this project, but Supabase requires one). Pick a region close to you.
2. While it provisions, open the **SQL Editor** tab.
3. Apply the migrations in `db/migrations/` **in order** (0001, 0002, …). For each file: open it in your text editor, paste the contents into the SQL Editor, click **Run**. There are 7 migrations as of this writing.
4. After the migrations run, seed your athlete row in the SQL Editor:
   ```sql
   insert into athletes (name, timezone)
   values ('Your Name', 'America/Los_Angeles')
   returning id;
   ```
   Replace the timezone with [your IANA timezone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) (e.g. `Europe/London`, `Australia/Sydney`). Save the returned UUID — you'll need it in the next step.

### 4. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` in your text editor and fill in the values:

- `SUPABASE_URL` — from Supabase → **Project Settings → API**. Format: `https://<project-ref>.supabase.co`.
- `SUPABASE_SECRET_KEY` — same page, under **API Keys**. Use the modern `sb_secret_…` key, not the legacy `service_role` JWT. Treat as a password.
- `ATHLETE_ID` — the UUID you saved from step 3.
- `GARMIN_EMAIL` and `GARMIN_PASSWORD` — your Garmin Connect login. Optional but recommended: with these set, the sync transparently refreshes the cached Garmin token when it expires and silently re-logs in when the refresh token dies, so cron survives token rotation. Without them, an expired session is a hard failure that needs manual re-auth.
- `TP_ICAL_URL` — TrainingPeaks → **Settings → Account Settings → Sharing → Calendar Feed**. The URL is tokenized — treat it as a password.
- (Optional) `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN` — only if you want Strava cross-checking. Leave blank to skip.

### 5. One-time Garmin login

Garmin's API requires a real login with MFA the first time. After that, a token cache at `~/.garminconnect/` keeps subsequent runs unattended.

```bash
training-brain login-garmin
```

You'll be prompted for an MFA code. Enter the 6-digit code Garmin texts/emails you. On success it caches tokens silently. If it errors with a `429`, wait 15 minutes and try again — Garmin rate-limits aggressive logins.

### 6. Backfill your history

```bash
training-brain backfill --since 2025-05-01
```

Pulls the last year of activities, FIT files, and wellness data. Takes a few minutes. Garmin's rate limits are gentle for one athlete; if it does throw a `429` partway through, wait 30 minutes and re-run — the sync is idempotent and picks up where it left off.

### 7. Verify it's working

```bash
training-brain status      # row counts, latest sync timestamps, FIT bucket size
training-brain briefing    # today's morning briefing — your end-to-end smoke test
training-brain analyze     # deep dive on the most recent workout
```

If `status` shows non-zero rows in `workouts_executed`, `wellness_daily`, and `workouts_planned`, you're done with the core setup.

### 8. Schedule the daily sync

Wire whatever scheduler you have (cron, systemd timers, macOS launchd, your AI agent's built-in scheduler, etc.) to run two commands:

```
*/45 * * * *   training-brain intraday
0 5    * * *   training-brain daily
```

The `intraday` profile refreshes fast-changing wellness (body battery, stress, training readiness) every 45 minutes. The `daily` profile pulls overnight HRV, sleep, RHR, weight, executed workouts, and the TP plan — once in the early morning. Both are idempotent; running them too often is harmless beyond extra audit-table rows.

### 9. (Optional) Seed your training zones

Time-in-zone analysis in `analyze` needs zone definitions. If you have them in TrainingPeaks, paste them into the SQL Editor:

```sql
-- Example: 7-zone HR for run, replace with your own thresholds.
insert into training_zones (athlete_id, sport, metric, zone, lower, upper) values
    ('<your-athlete-uuid>', 'run', 'hr', 1, 0,   130),
    ('<your-athlete-uuid>', 'run', 'hr', 2, 131, 145),
    ('<your-athlete-uuid>', 'run', 'hr', 3, 146, 160),
    ('<your-athlete-uuid>', 'run', 'hr', 4, 161, 175),
    ('<your-athlete-uuid>', 'run', 'hr', 5, 176, 190),
    ('<your-athlete-uuid>', 'run', 'hr', 6, 191, 200),
    ('<your-athlete-uuid>', 'run', 'hr', 7, 201, 255);
```

Repeat for each `(sport, metric)` pair you want — common ones are `bike/power`, `bike/hr`, `run/hr`, `run/pace_s_per_km`. Pace zones use seconds-per-km (smaller = faster). `analyze` falls back gracefully when zones aren't seeded — you just won't see the time-in-zone tables.

### 10. (Optional) Strava

If you want Strava as a cross-check source:

1. Create an API app at [strava.com/settings/api](https://www.strava.com/settings/api).
2. Run a one-time OAuth dance to get a refresh token. (Strava's [getting-started guide](https://developers.strava.com/docs/getting-started/) is the canonical reference; the short version is: get an authorization code via the browser, exchange it for a refresh token via `curl`.)
3. Drop `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, and `STRAVA_REFRESH_TOKEN` into `.env`. The next sync will pull Strava activities.

Skip this if you don't care about Strava-specific metrics (route polylines, segment matching) — Garmin is the primary source for execution data.

---

## Setup with an AI agent

If you'd rather have an AI agent walk you through setup, paste this prompt
into your tool of choice (Claude Code, Cursor, Codex, ChatGPT with code
interpreter, etc.). The agent should be able to read files in this repo.

```
I want to set up the training_brain data tier on my machine. It centralizes
my training data from TrainingPeaks, Garmin Connect, and Strava into a
Supabase Postgres database I own.

The repo is cloned at the current directory. Read README.md for the full
setup procedure and AGENTS.md for what you'll be able to do once it's
running. Then walk me through setup step by step:

1. Confirm I have Python 3.11+. Help me create the virtual env (.venv) and
   install the package with `pip install -e .`.
2. Help me create a Supabase project, then apply each migration in
   db/migrations/ in order via the Supabase SQL Editor (or via the
   Supabase MCP if that's connected). Then seed my athlete row.
3. Walk me through populating .env: Supabase URL + secret key, athlete
   UUID, Garmin login, TP iCal URL. Don't echo my secrets back — just
   confirm each var is set with a non-echoing presence check.
4. Have me run `training-brain login-garmin` in my own terminal so I can
   enter the MFA code interactively.
5. Run `training-brain backfill --since YYYY-MM-DD` for the last 12
   months. If Garmin returns 429, wait and retry — the sync is idempotent.
6. Verify with `training-brain status` (row counts, latest sync
   timestamps) and `training-brain briefing` (end-to-end smoke test).
7. Help me schedule the cron (intraday every 45 min, daily at 5am).
8. Optionally: help me seed training_zones with my coach-defined HR and
   power zones if I have them, so time-in-zone analysis works in the
   `analyze` command.

Wait for me to confirm each step before moving on. If anything fails, run
`training-brain status` first, and inspect raw_garmin_events.payload via
the Supabase SQL editor for any wellness fields that look stale or wrong.

Once setup is done, you'll be able to answer my training questions using
the patterns described in AGENTS.md.
```

After setup, your agent can answer training questions directly — no further
configuration needed. AGENTS.md is read on every session.

---

## Daily use

Once it's running, you mostly don't think about it. The cron keeps your
data fresh; you ask your agent training questions and it queries the
database.

A few CLI commands worth knowing for ad-hoc checks:

| Command | What it shows |
|---|---|
| `training-brain briefing` | Today's wellness + yesterday's executed + today's plan + load + anomaly flags |
| `training-brain today` | Just today's planned workouts |
| `training-brain last` | Most recent completed workout |
| `training-brain recent --days 7` | Last week's workouts as a table |
| `training-brain recovery --days 14` | Wellness trend |
| `training-brain analyze [<garmin_id>]` | Lap table, mean-max curve, time-in-zone, aerobic decoupling for one workout |
| `training-brain strava_relative_effort --days N \| --activities N` | Strava Relative Effort (suffer_score) rolled up by day or listed per activity; also backfills `workouts_executed.relative_effort` |
| `training-brain status` | Sync timestamps, row counts, FIT bucket size |

Every read command takes `--json` for piping into other tooling.

---

## Local web UI

A small FastAPI + React app for the parts of this project that benefit from a
screen — currently re-authentication, with data exploration views to come.

```bash
cd web && npm install && npm run build && cd ..    # one-time
training-brain web                                  # then open http://localhost:8765
```

Flags: `--port 8765`, `--host 127.0.0.1`, `--reload`. Binds to loopback only —
there's no auth layer on top, so don't expose it.

For frontend iteration, run the Vite dev server alongside the backend:

```bash
training-brain web                  # terminal 1 — :8765
cd web && npm run dev               # terminal 2 — :5173, proxies /api → :8765
```

What's in the UI today:

- **Calendar** (`/`, default landing) — week (default) and month views of
  planned vs. executed workouts. Each day shows planned workouts as
  dashed-outline cards and executed workouts as solid cards, both colored
  by sport. Clicking any workout opens a placeholder detail page
  (`/workouts/:id`) — full lap / mean-max / time-in-zone view comes later.
- **Auth** (`/auth`) — three cards for re-authenticating your sources:
  - **Garmin Connect** — email + password + MFA prompt; token files cached
    to `~/.garminconnect`. Shows "Last verified <time>" so you can tell
    when the credentials were last confirmed working. On a successful
    login the confirmed credentials are written back to `.env`, so cron's
    auto-refresh keeps working after you change your Garmin password.
  - **TrainingPeaks** — paste a `webcal://` or `https://` iCal URL; the
    backend normalizes, saves to `.env`, and probes the feed (status line
    shows the current event count). Useful for swapping in a fresh
    personal link without hand-editing `.env`.
  - **Strava** — OAuth round-trip; refresh token is written back into
    `.env` on success and live-verified against Strava on every page
    load. Client ID / secret can also be set or rotated from the UI.
    Strava's app settings must list `localhost` as the Authorization
    Callback Domain.

---

## Caveats

- **Garmin auth is fragile by nature.** Garmin can change their login flow at any time and break the underlying library. As of May 2026 the project uses [`cyberjunky/python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) (the previous library, `garth`, was deprecated in March 2026 after Garmin added Cloudflare protections). If your sync starts failing with auth errors after a Garmin update, check the upstream library for a new release.
- **TrainingPeaks edits.** If you manually edit a workout in TP after the fact, this pipeline won't see the edit (Garmin is the execution-data source). Acceptable for most use; revisit if you edit TP heavily.
- **Same-day duplicates.** Plan ↔ execution match is by date + sport. If you do two swims in a day, the join is ambiguous and your agent will tell you so.
- **TP planned duration / TSS.** TrainingPeaks all-day iCal events surface `duration_planned_s = 86400` (24h) and `tss_planned = null`. The real values live in the event description text (`Planned Time: 1:30`). A description parser is on the backlog; until then, agents quote the description directly when asked about planned values.
- **Garmin response drift.** The wellness extractors are calibrated against one account. If new fields surface or rename, inspect `raw_garmin_events.payload` (a jsonb column with the original API response) and extend the extractors in `src/training_brain/ingestion/garmin.py`.

---

## Extending the project

The codebase is a few hundred lines of straightforward Python. The main pieces:

- `src/training_brain/sync.py` — write CLI (sync subcommands, Garmin login, `web` launcher)
- `src/training_brain/query.py` — read CLI (briefing, today, last, recent, recovery, analyze, status)
- `src/training_brain/streams.py` — FIT parser; populates `activity_streams` and `workout_laps`
- `src/training_brain/ingestion/` — per-source ingesters (Garmin, TrainingPeaks, Strava)
- `src/training_brain/web/` — FastAPI backend for the local web UI (auth flows, env writer)
- `src/training_brain/db.py` — Supabase client + env loader
- `web/` — Vite + React + TypeScript + Tailwind frontend; built bundle is served by FastAPI
- `db/migrations/` — SQL migrations, applied in order

If you want to add a new metric (say, `vo2_max` from a different source), the rough recipe is:

1. Add a column to the relevant canonical table via a new migration in `db/migrations/`.
2. Extend the matching ingester in `src/training_brain/ingestion/` to populate it.
3. Update [AGENTS.md](AGENTS.md)'s schema section so any agent reading it knows the metric exists and how to query it.

[AGENTS.md](AGENTS.md) is the source of truth for what an agent can do with this data tier. Keep it in sync with the schema; a stale AGENTS.md means agents return wrong answers silently.

---

## License

[MIT](LICENSE) — fork it, modify it, ship your own version. No warranty.
