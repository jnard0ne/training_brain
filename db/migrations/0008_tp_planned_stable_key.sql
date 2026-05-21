-- Replace the source_uid-based unique key on workouts_planned with a stable
-- content-derived key. TrainingPeaks issues a fresh iCal UID on every feed
-- pull (and also issues separate UIDs for the "planned" and "completed-with-
-- actuals" representations of the same workout), so source_uid was never a
-- usable identity — every sync inserted duplicate rows. As of 2026-05-21,
-- 185 of 226 rows in the table are duplicates.
--
-- dedup_key is `source|date|sport|lower(first-line-of-description)`. The
-- first line is the workout's human title (e.g. "Run: Run Fresh") and stays
-- stable across re-syncs while duration_planned_s and the rest of the
-- description mutate. We can't make this a GENERATED column because lower()
-- and date::text are STABLE (not IMMUTABLE) in Postgres, so the ingester
-- computes and writes it explicitly. The Python upsert uses
-- (athlete_id, dedup_key) as its on_conflict target.

-- 1. Add the dedup_key column (nullable for now; populated below).
alter table workouts_planned add column dedup_key text;

-- 2. Backfill dedup_key for existing rows.
update workouts_planned set dedup_key =
    coalesce(source, '') || '|' ||
    coalesce(date::text, '') || '|' ||
    coalesce(sport::text, '') || '|' ||
    lower(split_part(coalesce(description, ''), E'\n', 1));

-- 3. Collapse duplicates. For each (athlete, dedup_key) group, keep the row
--    with the most useful planned-duration data; ties break on most-recent
--    updated_at. workouts_executed.planned_workout_id has ON DELETE SET NULL,
--    so deletes are safe (and currently no executed rows even reference these).
with ranked as (
    select
        id,
        row_number() over (
            partition by athlete_id, dedup_key
            order by
                case
                    when duration_planned_s > 0 and duration_planned_s < 86400 then 2
                    when description ~* 'Planned Time:\s*\d+:\d+' then 1
                    else 0
                end desc,
                updated_at desc
        ) as rn
    from workouts_planned
)
delete from workouts_planned where id in (select id from ranked where rn > 1);

-- 4. Drop the old (effectively-useless) constraint and enforce the new one.
alter table workouts_planned
    drop constraint if exists workouts_planned_athlete_id_source_source_uid_key;

alter table workouts_planned alter column dedup_key set not null;

alter table workouts_planned
    add constraint workouts_planned_athlete_id_dedup_key_key
    unique (athlete_id, dedup_key);
