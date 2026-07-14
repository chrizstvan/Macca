-- Migration: reminders + quiz drafts + education/content drafts + reporting flag
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Adds the tables introduced by the fasilitator reminder/quiz/education flows:
--   action_items        — reminder targets the WA bot resolves ("ingetin <judul>")
--   quizzes             — quiz drafts (draft → approved → sent) before broadcast
--   content_drafts      — draft-only education/content (copy-paste, never auto-sent)
--   scheduled_messages  — queued reminder/quiz sends drained by the per-minute job
-- Plus fasilitator_context seeds for the live settings (reporting flag, delays).
--
-- Pre-existing (not created here): volunteers, missions, reports, chat_history,
-- active_quizzes, quiz_attempts, volunteer_scores, fasilitator_context.

-- ------------------------------------------------------------------ --
-- action_items                                                         --
-- ------------------------------------------------------------------ --

create table if not exists action_items (
    id           uuid primary key default gen_random_uuid(),
    type         text not null check (type in (
                     'challenge', 'submission', 'kelas', 'presensi',
                     'pre_test', 'post_test', 'tautan', 'buku_saku')),
    title        text not null,
    description  text,
    link_url     text,
    deadline     date,          -- challenge/submission/presensi/pre_test/post_test
    scheduled_at timestamptz,   -- kelas/presensi event time
    location     text,          -- kelas (physical or online link)
    reward       text,          -- challenge incentive
    is_active    boolean not null default true,
    created_at   timestamptz not null default now()
);

create index if not exists idx_action_items_active on action_items (is_active);
create index if not exists idx_action_items_type on action_items (type) where is_active;

-- ------------------------------------------------------------------ --
-- quizzes (draft store; distinct from the live active_quizzes table)   --
-- ------------------------------------------------------------------ --

create table if not exists quizzes (
    id          uuid primary key default gen_random_uuid(),
    question    text not null,
    options     jsonb not null default '[]',
    answer      text,
    explanation text,
    status      text not null default 'draft'
                  check (status in ('draft', 'approved', 'sent', 'cancelled')),
    created_at  timestamptz not null default now()
);

create index if not exists idx_quizzes_status_created
    on quizzes (status, created_at desc);

-- ------------------------------------------------------------------ --
-- content_drafts (education / copy-paste content; draft-only)          --
-- ------------------------------------------------------------------ --

create table if not exists content_drafts (
    id         uuid primary key default gen_random_uuid(),
    type       text not null,           -- e.g. 'education'
    topic      text,
    content    text,
    created_at timestamptz not null default now()
);

create index if not exists idx_content_drafts_type_created
    on content_drafts (type, created_at desc);

-- ------------------------------------------------------------------ --
-- scheduled_messages (per-minute dispatch queue: reminders + quizzes)  --
-- ------------------------------------------------------------------ --

create table if not exists scheduled_messages (
    id               uuid primary key default gen_random_uuid(),
    message_template text,          -- reminder body ({nama} filled at send time)
    content          text,          -- plain broadcast body (admin route)
    quiz             jsonb,         -- quiz spec → broadcast + active_quizzes row
    recipient_filter text default 'all',
    action_item_id   uuid references action_items(id) on delete set null,
    quiz_id          uuid references quizzes(id) on delete set null,
    scheduled_at     timestamptz not null,
    status           text not null default 'pending'
                       check (status in ('pending', 'sent', 'failed', 'cancelled')),
    created_by       text,
    created_at       timestamptz not null default now()
);

-- Drives the every-minute poll: WHERE status='pending' AND scheduled_at <= now().
create index if not exists idx_scheduled_messages_due
    on scheduled_messages (status, scheduled_at);

-- ------------------------------------------------------------------ --
-- fasilitator_context (live key/value settings) + seeds                --
-- ------------------------------------------------------------------ --

create table if not exists fasilitator_context (
    key   text primary key,
    value text
);

insert into fasilitator_context (key, value) values
    ('enable_reporting', 'true'),
    ('reporting_off_message',
     'Silakan isi form report atau hubungi fasilitator untuk submit reportmu :)'),
    ('reminder_delay_hours', '8'),
    ('enable_news_search', 'false')
on conflict (key) do nothing;
