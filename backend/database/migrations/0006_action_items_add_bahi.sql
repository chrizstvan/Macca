-- Migration: allow action_items type 'bahi' (Belajar Apa Hari Ini)
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- The type CHECK constraint from 0001 enumerates the allowed types; add 'bahi'
-- so the new daily-learning action item can be inserted. Drop-then-recreate
-- (the inline constraint is auto-named ``action_items_type_check``).

alter table action_items drop constraint if exists action_items_type_check;
alter table action_items add constraint action_items_type_check
    check (type in (
        'challenge', 'submission', 'kelas', 'presensi',
        'pre_test', 'post_test', 'tautan', 'buku_saku', 'bahi'
    ));
