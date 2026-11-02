-- 236_scheduled_overview.sql
-- Backs the "Scheduled templates" page (ANRIL ENGAGE): one place to see and manage every scheduled
-- template and broadcast. Additive only.
--
--   scheduled_template_sends  batch_id / batch_label: messages scheduled together from Leads (for
--                             example 20 Hot leads) share a batch_id so the page can show one batch.
--   scheduled_broadcasts      created_by: who scheduled it. drip_group_id: a drip is stored as one row
--                             per day; the rows of one drip share this id. recipient_count: the number
--                             of leads, so the page doesn't have to load leads_json to count them.
--
-- Must be applied BEFORE the backend that writes these columns is deployed.

SET LOCAL lock_timeout = '5s';

ALTER TABLE scheduled_template_sends
  ADD COLUMN IF NOT EXISTS batch_id    uuid,
  ADD COLUMN IF NOT EXISTS batch_label text;

CREATE INDEX IF NOT EXISTS scheduled_template_sends_batch_idx
  ON scheduled_template_sends (tenant_id, batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS scheduled_template_sends_tenant_status_idx
  ON scheduled_template_sends (tenant_id, status, send_at);

ALTER TABLE scheduled_broadcasts
  ADD COLUMN IF NOT EXISTS created_by       uuid,
  ADD COLUMN IF NOT EXISTS drip_group_id    uuid,
  ADD COLUMN IF NOT EXISTS recipient_count  integer;

UPDATE scheduled_broadcasts
   SET recipient_count = jsonb_array_length(leads_json)
 WHERE recipient_count IS NULL
   AND leads_json IS NOT NULL
   AND jsonb_typeof(leads_json) = 'array';

CREATE INDEX IF NOT EXISTS scheduled_broadcasts_drip_group_idx
  ON scheduled_broadcasts (tenant_id, drip_group_id) WHERE drip_group_id IS NOT NULL;
