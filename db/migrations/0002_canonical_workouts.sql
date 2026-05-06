-- Canonical workout tables: planned (TP) and executed (Garmin/Strava).
-- Plan ↔ execution match is by (athlete_id, date, sport) with manual override
-- via the `planned_workout_id` FK on `workouts_executed`.

create type sport as enum (
    'swim', 'bike', 'run', 'strength', 'mobility', 'brick', 'other'
);

create table workouts_planned (
    id uuid primary key default gen_random_uuid(),
    athlete_id uuid not null references athletes(id) on delete cascade,
    date date not null,
    sport sport not null,
    duration_planned_s int,
    tss_planned numeric,
    description text,
    structure jsonb,
    source text not null default 'trainingpeaks',
    source_uid text not null,
    raw_id bigint references raw_tp_calendar(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (athlete_id, source, source_uid)
);
create index workouts_planned_by_date on workouts_planned (athlete_id, date);

create table workouts_executed (
    id uuid primary key default gen_random_uuid(),
    athlete_id uuid not null references athletes(id) on delete cascade,
    started_at timestamptz not null,
    sport sport not null,
    duration_s int not null,
    distance_m numeric,
    tss numeric,
    intensity_factor numeric,
    avg_hr int,
    max_hr int,
    avg_power int,
    normalized_power int,
    avg_cadence int,
    avg_pace_s_per_km numeric,
    elevation_gain_m numeric,
    calories int,
    garmin_activity_id bigint,
    strava_activity_id bigint,
    tp_workout_id text,
    fit_file_path text,
    planned_workout_id uuid references workouts_planned(id) on delete set null,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create unique index workouts_executed_garmin_uniq
    on workouts_executed (athlete_id, garmin_activity_id)
    where garmin_activity_id is not null;
create unique index workouts_executed_strava_uniq
    on workouts_executed (athlete_id, strava_activity_id)
    where strava_activity_id is not null;
create index workouts_executed_by_started
    on workouts_executed (athlete_id, started_at desc);
create index workouts_executed_by_plan
    on workouts_executed (planned_workout_id);

alter table workouts_planned enable row level security;
alter table workouts_executed enable row level security;
