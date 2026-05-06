-- Initial schema: athletes + raw audit tables.
--
-- The `raw_*` tables are append-only audit logs of source-of-truth payloads.
-- Normalization writes into the canonical tables (workouts_planned,
-- workouts_executed, wellness_daily); if normalization logic changes, we can
-- replay from the raw layer without re-fetching from APIs.

create extension if not exists "pgcrypto";

create table athletes (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    timezone text not null default 'UTC',
    created_at timestamptz not null default now()
);

create table raw_garmin_events (
    id bigserial primary key,
    athlete_id uuid not null references athletes(id) on delete cascade,
    kind text not null,
    occurred_on date not null,
    payload jsonb not null,
    ingested_at timestamptz not null default now()
);
create index raw_garmin_events_lookup
    on raw_garmin_events (athlete_id, kind, occurred_on);

create table raw_tp_calendar (
    id bigserial primary key,
    athlete_id uuid not null references athletes(id) on delete cascade,
    ical_uid text not null,
    payload jsonb not null,
    ingested_at timestamptz not null default now()
);
create index raw_tp_calendar_lookup
    on raw_tp_calendar (athlete_id, ical_uid, ingested_at desc);

create table raw_strava_activities (
    id bigserial primary key,
    athlete_id uuid not null references athletes(id) on delete cascade,
    strava_activity_id bigint not null,
    payload jsonb not null,
    ingested_at timestamptz not null default now()
);
create index raw_strava_activities_lookup
    on raw_strava_activities (athlete_id, strava_activity_id, ingested_at desc);

-- RLS: enabled with no policies. Service role and MCP admin bypass RLS;
-- this defends against accidental exposure of an anon/publishable key.
alter table athletes enable row level security;
alter table raw_garmin_events enable row level security;
alter table raw_tp_calendar enable row level security;
alter table raw_strava_activities enable row level security;
