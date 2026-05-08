-- workouts_executed used partial unique indexes for garmin/strava activity
-- IDs. PostgREST upsert(on_conflict=...) requires a real unique CONSTRAINT,
-- not a partial index. Postgres treats NULLs as distinct in unique
-- constraints, so a non-partial constraint still allows many rows with
-- garmin_activity_id IS NULL (e.g. strava-only workouts) and vice versa —
-- behaviour we wanted from the partial index in the first place.

drop index if exists workouts_executed_garmin_uniq;
drop index if exists workouts_executed_strava_uniq;

alter table workouts_executed
    add constraint workouts_executed_garmin_uniq
    unique (athlete_id, garmin_activity_id);

alter table workouts_executed
    add constraint workouts_executed_strava_uniq
    unique (athlete_id, strava_activity_id);
