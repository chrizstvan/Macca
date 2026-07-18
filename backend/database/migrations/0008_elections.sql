-- Migration: election system — per-team ketua/wakil election state machine
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- One row per election. status drives the state machine:
--   draft → nomination_open → nomination_closed → voting_open → voting_closed → completed
-- ketua/wakil filled at completion (later iterations). nominations + votes get
-- their own tables in a follow-up migration.

create table if not exists elections (
    id         uuid primary key default gen_random_uuid(),
    team       text not null,
    status     text not null default 'draft'
                 check (status in (
                     'draft', 'nomination_open', 'nomination_closed',
                     'voting_open', 'voting_closed', 'completed'
                 )),
    ketua      text,
    wakil      text,
    created_at timestamptz not null default now()
);

create index if not exists idx_elections_team_status
    on elections (team, status);
