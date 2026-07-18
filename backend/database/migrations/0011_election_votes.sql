-- Migration: election final votes (one per volunteer, locked)
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Each volunteer casts one final vote for a finalist. UNIQUE
-- (election_id, voter_volunteer_id) is the race-safe guard.

create table if not exists election_votes (
    id                 uuid primary key default gen_random_uuid(),
    election_id        uuid not null references elections(id) on delete cascade,
    voter_volunteer_id uuid not null references volunteers(id) on delete cascade,
    candidate_phone    text,
    candidate_name     text not null,
    created_at         timestamptz not null default now(),
    unique (election_id, voter_volunteer_id)
);

create index if not exists idx_election_votes_election
    on election_votes (election_id);
