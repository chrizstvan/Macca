-- Migration: challenge active-window start date
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Adds ``start_date`` to ``action_items`` so a challenge auto-activates only
-- within its period: bot treats a challenge as active when
--   is_active = true AND (start_date IS NULL OR start_date <= today)
--                    AND (deadline   IS NULL OR deadline   >= today)
-- start_date NULL = active from creation (back-compat with existing rows).

alter table action_items
    add column if not exists start_date date;

-- Backfill the two seeded GBP Batch 9 challenges with their period start.
update action_items set start_date = date '2026-07-18'
    where type = 'challenge' and title = 'Less Plastic More Life'
      and start_date is null;

update action_items set start_date = date '2026-07-29'
    where type = 'challenge' and title = 'Proyek Sosial Challenge'
      and start_date is null;
