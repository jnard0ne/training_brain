-- Private Supabase Storage bucket for original FIT files.
-- Path convention: <athlete_id>/<garmin_activity_id>.fit
-- Read/write happens via the service-role key from the sync job; no public
-- access. activity_streams holds summary metrics for fast queries; the FIT
-- file is parsed on demand for full-resolution analysis.

insert into storage.buckets (id, name, public)
values ('fit-files', 'fit-files', false)
on conflict (id) do nothing;
