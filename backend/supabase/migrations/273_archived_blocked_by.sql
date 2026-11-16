-- 273_archived_blocked_by.sql
-- Chats > Archived & blocked (2026-11-17): show who archived or blocked a chat.
-- A name snapshot (like chat_handovers.resolved_by_name), so it survives a teammate
-- being renamed or removed. Null on rows archived/blocked before this column existed.
SET LOCAL lock_timeout = '5s';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS archived_by_name text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS blocked_by_name text;
