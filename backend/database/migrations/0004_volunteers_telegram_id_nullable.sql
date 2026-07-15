-- Migration: allow volunteers without a Telegram ID
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- WhatsApp is the primary channel (keyed by phone); ``telegram_id`` is optional.
-- The legacy schema declared it NOT NULL, so registering a WhatsApp-only
-- volunteer (no Telegram) failed with 23502. Drop the constraint.

alter table volunteers
    alter column telegram_id drop not null;
