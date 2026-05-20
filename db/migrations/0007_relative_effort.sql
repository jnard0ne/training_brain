-- relative_effort: Strava's HR-derived effort score (the field they expose as
-- `suffer_score` in the API, branded as "Relative Effort" in the app). Only
-- populated for activities with heart-rate data. Nullable on workouts_executed
-- because Garmin-only rows won't have a Strava match, and Strava activities
-- without HR won't have a score.

alter table workouts_executed
    add column if not exists relative_effort int;
