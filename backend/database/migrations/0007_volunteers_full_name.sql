-- Migration: add volunteers.full_name (nama lengkap)
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- ``name`` stays the call-name / nickname the bot uses in greetings.
-- ``full_name`` is the volunteer's full legal name for records. Nullable so
-- existing rows and inserts that omit it stay valid; the command-side upsert
-- (Volunteer.save) doesn't touch this column, so it is never overwritten.

alter table volunteers add column if not exists full_name text;
