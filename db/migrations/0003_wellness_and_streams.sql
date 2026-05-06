-- Daily wellness rollups + per-workout summary streams.
--
-- `wellness_daily` is one row per athlete per day. Some columns (body battery,
-- stress, training readiness) are written by the `intraday` sync profile and
-- updated repeatedly during the day; the rest are written by the `daily`
-- profile after sleep/HRV settle. The two timestamps make it cheap to tell
-- when each half was last refreshed.
--
-- `activity_streams` stores summary (time-binned) stream metrics for fast
-- queries. The original FIT file lives in Supabase Storage and is parsed on
-- demand for full-resolution analysis.

create table wellness_daily (
    athlete_id uuid not null references athletes(id) on delete cascade,
    date date not null,
    hrv_overnight_ms numeric,
    hrv_baseline_ms numeric,
    rhr_bpm int,
    sleep_total_s int,
    sleep_deep_s int,
    sleep_light_s int,
    sleep_rem_s int,
    sleep_awake_s int,
    sleep_score int,
    body_battery_high int,
    body_battery_low int,
    body_battery_charged int,
    body_battery_drained int,
    stress_avg int,
    stress_max int,
    training_readiness int,
    training_status text,
    vo2_max numeric,
    weight_kg numeric,
    body_fat_pct numeric,
    steps int,
    floors_climbed int,
    intraday_updated_at timestamptz,
    daily_updated_at timestamptz,
    primary key (athlete_id, date)
);

create table activity_streams (
    workout_id uuid not null references workouts_executed(id) on delete cascade,
    bin_offset_s int not null,
    bin_size_s int not null default 1,
    hr int,
    power int,
    cadence int,
    speed_m_s numeric,
    altitude_m numeric,
    lat numeric,
    lon numeric,
    primary key (workout_id, bin_offset_s)
);

alter table wellness_daily enable row level security;
alter table activity_streams enable row level security;
