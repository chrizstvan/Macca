-- Migration: allow elections.status = 'cancelled'
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- The dashboard can cancel an in-progress election. Add 'cancelled' to the
-- status CHECK enum (drop-then-recreate the inline constraint from 0008).

alter table elections drop constraint if exists elections_status_check;
alter table elections add constraint elections_status_check
    check (status in (
        'draft', 'nomination_open', 'nomination_closed',
        'voting_open', 'voting_closed', 'completed', 'cancelled'
    ));
