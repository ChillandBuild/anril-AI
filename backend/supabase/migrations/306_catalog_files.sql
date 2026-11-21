-- 306: Shop files for the AI to send (plan: docs/plans/commerce-stock-plan.md, part 2).
-- Price list PDFs, size charts, shop map photos, reels. Separate from catalog_media (item photos),
-- which thumbnails, the Meta catalogue sync and the AI's photo sending all read as images.
-- send_when: the business's own words for when the AI sends it ("asks for the price list").

CREATE TABLE IF NOT EXISTS catalog_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  catalog_item_id uuid REFERENCES catalog_items(id) ON DELETE SET NULL,
  title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 80),
  kind text NOT NULL CHECK (kind IN ('image', 'video', 'document')),
  mime_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  storage_path text NOT NULL,
  pages integer,
  send_when text CHECK (send_when IS NULL OR length(send_when) <= 200),
  ai_enabled boolean NOT NULL DEFAULT true,
  sent_count integer NOT NULL DEFAULT 0,
  last_sent_at timestamptz,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS catalog_files_tenant_idx ON catalog_files (tenant_id, created_at DESC);
ALTER TABLE catalog_files ENABLE ROW LEVEL SECURITY;
CREATE POLICY catalog_files_tenant_member_select ON catalog_files
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

-- One row per file sent, so "sent this month" is countable.
CREATE TABLE IF NOT EXISTS catalog_file_sends (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  file_id uuid NOT NULL REFERENCES catalog_files(id) ON DELETE CASCADE,
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  sent_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS catalog_file_sends_idx ON catalog_file_sends (tenant_id, sent_at DESC);
ALTER TABLE catalog_file_sends ENABLE ROW LEVEL SECURITY;
CREATE POLICY catalog_file_sends_tenant_member_select ON catalog_file_sends
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));

-- Count a send and bump the file's total in one statement.
CREATE OR REPLACE FUNCTION record_catalog_file_send(p_tenant_id uuid, p_file_id uuid, p_lead_id uuid)
RETURNS void
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
  INSERT INTO catalog_file_sends (tenant_id, file_id, lead_id) VALUES (p_tenant_id, p_file_id, p_lead_id);
  UPDATE catalog_files SET sent_count = sent_count + 1, last_sent_at = now()
   WHERE id = p_file_id AND tenant_id = p_tenant_id;
$$;
REVOKE EXECUTE ON FUNCTION record_catalog_file_send(uuid, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION record_catalog_file_send(uuid, uuid, uuid) TO service_role;
