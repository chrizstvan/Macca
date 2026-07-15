-- Migration: retire the volunteers.quota_kg default
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- The program is challenge-based; per-volunteer kg quota is no longer used.
-- Drop the DEFAULT (so new rows are not silently set to 20) and the NOT NULL
-- constraint (so inserts that omit quota_kg succeed). The column is kept as a
-- dormant field for back-compat; readers already tolerate NULL.

alter table volunteers alter column quota_kg drop default;
alter table volunteers alter column quota_kg drop not null;
