-- Macca Supabase database schema
-- Run this in the Supabase SQL editor (or via supabase db push).

-- ------------------------------------------------------------------ --
-- Tables                                                               --
-- ------------------------------------------------------------------ --

create table if not exists volunteers (
    id          uuid primary key default gen_random_uuid(),
    telegram_id bigint unique not null,
    phone       text,
    name        text not null,
    area        text not null, -- kelurahan assignment
    team        text[],        -- array of teammate names
    quota_kg    numeric not null default 20,
    joined_at   timestamptz default now(),
    is_active   boolean default true
);

create table if not exists missions (
    id          uuid primary key default gen_random_uuid(),
    title       text not null,
    description text,
    deadline    timestamptz not null,
    status      text default 'active' check (status in ('active', 'completed', 'cancelled')),
    created_at  timestamptz default now(),
    created_by  text
);

create table if not exists volunteer_missions (
    id            uuid primary key default gen_random_uuid(),
    volunteer_id  uuid references volunteers(id),
    mission_id    uuid references missions(id),
    quota_kg      numeric not null,
    assigned_area text not null,
    reported_kg   numeric default 0
);

create table if not exists reports (
    id           uuid primary key default gen_random_uuid(),
    volunteer_id uuid references volunteers(id),
    mission_id   uuid references missions(id),
    kg_collected numeric not null,
    location     text not null,
    photo_url    text,
    raw_message  text,
    source       text default 'telegram' check (source in ('telegram', 'whatsapp', 'google_form')),
    extra_data   jsonb default '{}',
    is_flagged   boolean default false,
    flag_reason  text,
    reported_at  timestamptz default now(),
    verified     boolean default false
);

create table if not exists chat_history (
    id           uuid primary key default gen_random_uuid(),
    telegram_id  bigint not null,
    role         text not null check (role in ('user', 'assistant')),
    content      text not null,
    agent_module text,
    created_at   timestamptz default now()
);

create table if not exists notifications (
    id          uuid primary key default gen_random_uuid(),
    telegram_id bigint not null,
    type        text not null check (type in ('reminder', 'alert', 'broadcast')),
    message     text not null,
    sent_at     timestamptz,
    status      text default 'pending'
);

-- ------------------------------------------------------------------ --
-- Indexes                                                              --
-- ------------------------------------------------------------------ --

create index if not exists idx_volunteers_telegram_id on volunteers (telegram_id);
create index if not exists idx_reports_volunteer_id on reports (volunteer_id);
create index if not exists idx_reports_mission_id on reports (mission_id);
create index if not exists idx_chat_history_telegram_id on chat_history (telegram_id);
create index if not exists idx_chat_history_created_at on chat_history (created_at);

-- ------------------------------------------------------------------ --
-- Migration for existing databases (run once in the SQL editor)        --
-- ------------------------------------------------------------------ --
-- alter table reports add column source text default 'telegram'
--     check (source in ('telegram', 'whatsapp', 'google_form'));
-- alter table reports add column extra_data jsonb default '{}';
-- alter table volunteer_missions add column reported_kg numeric default 0;
