-- workout_laps: per-lap summary records from FIT files. Distinct from
-- activity_streams (which is the time-series). Captures interval boundaries
-- (manual lap presses, distance/time auto-laps, swim pool lengths, brick
-- transitions) — info that can't be reconstructed from streams alone.
--
-- training_zones: athlete-specific zone definitions used for time-in-zone
-- analysis. Optional table; if empty, agents can fall back to %FTP/%LTHR
-- heuristics. Coach-defined zones from TrainingPeaks are the ideal source.

create table workout_laps (
    workout_id uuid not null references workouts_executed(id) on delete cascade,
    lap_index int not null,
    started_at timestamptz not null,
    duration_s int not null,
    distance_m numeric,
    avg_hr int,
    max_hr int,
    avg_power int,
    max_power int,
    normalized_power int,
    avg_cadence int,
    avg_pace_s_per_km numeric,
    intensity text,
    lap_trigger text,
    primary key (workout_id, lap_index)
);
create index workout_laps_by_started on workout_laps (started_at desc);

create table training_zones (
    athlete_id uuid not null references athletes(id) on delete cascade,
    sport sport not null,
    metric text not null check (metric in ('hr', 'power', 'pace_s_per_km')),
    zone int not null check (zone between 1 and 7),
    lower numeric,
    upper numeric,
    primary key (athlete_id, sport, metric, zone)
);

alter table workout_laps enable row level security;
alter table training_zones enable row level security;
