-- Migration: election finalists (top-3 candidates advancing to voting)
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Written when nomination closes. slot_number 1..N is the rank by nomination
-- count. Candidates are keyed by phone (name kept for display).

create table if not exists election_finalists (
    id               uuid primary key default gen_random_uuid(),
    election_id      uuid not null references elections(id) on delete cascade,
    candidate_phone  text,
    candidate_name   text not null,
    nomination_count int  not null default 0,
    slot_number      int  not null,
    created_at       timestamptz not null default now()
);

create index if not exists idx_election_finalists_election
    on election_finalists (election_id);
