-- 315_notification_links.sql — v9.2 Batch F (bell).
--   app_notifications.url   the page the alert's action button opens (was only sent with the
--                           web push and then lost), e.g. /dashboard/conversations?lead=...
-- Additive. Code works without it (inserts retry without url; the bell falls back to its type map).
-- Undo: undo/315_notification_links_undo.sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.app_notifications ADD COLUMN IF NOT EXISTS url text;
