-- Migration: action_items deadline gains a time component
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Changes ``action_items.deadline`` from ``date`` to ``timestamptz`` so a
-- deadline can carry an hour (e.g. 24 Juli 23:59). Existing date-only rows are
-- converted to end-of-day (23:59 UTC) on the same date, matching the "jam 24
-- pada tanggal deadline" default. All readers already take the first 10 chars
-- (date part) for gating, so date-level behaviour is unchanged.

do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_name = 'action_items'
          and column_name = 'deadline'
          and data_type = 'date'
    ) then
        alter table action_items
            alter column deadline type timestamptz
            using (deadline::timestamptz + interval '23 hours 59 minutes');
    end if;
end $$;
