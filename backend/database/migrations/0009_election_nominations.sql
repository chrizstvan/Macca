-- Migration: election nominations (one per volunteer, locked)
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Each volunteer may nominate exactly once per election. The UNIQUE
-- (election_id, nominator_volunteer_id) constraint is the race-safe guard.
-- candidate_volunteer_id is best-effort (matched by phone); nominations of
-- non-registered names are still recorded as free text.

create table if not exists election_nominations (
    id                     uuid primary key default gen_random_uuid(),
    election_id            uuid not null references elections(id) on delete cascade,
    nominator_volunteer_id uuid not null references volunteers(id) on delete cascade,
    candidate_name         text not null,
    candidate_phone        text,
    candidate_volunteer_id uuid references volunteers(id) on delete set null,
    created_at             timestamptz not null default now(),
    unique (election_id, nominator_volunteer_id)
);

create index if not exists idx_election_nominations_election
    on election_nominations (election_id);
