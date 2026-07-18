-- Migration: election result columns (ketua/wakil name + phone)
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Filled at "sahkan hasil" (finalize). 0008 created plain ketua/wakil text
-- columns; this adds the name+phone pair the finalize step writes.

alter table elections add column if not exists ketua_name  text;
alter table elections add column if not exists ketua_phone text;
alter table elections add column if not exists wakil_name  text;
alter table elections add column if not exists wakil_phone text;
