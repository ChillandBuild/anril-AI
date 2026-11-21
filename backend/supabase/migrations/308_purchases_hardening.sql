-- 308: Security review fixes for 306 / 307 (2026-11-21).
-- * stock_ins.request_id: the screen sends one id per Save; a double click / retry finds the
--   first stock-in instead of adding the stock again.
-- * add_po_line_received: "came" counts go up in one statement (two receipts never lose one).
-- * Purchase money (suppliers, orders, stock-ins, payments) is read only through the API, which
--   checks purchases.view: no direct member reads.
-- * record_catalog_file_send only counts a file of that business.

ALTER TABLE stock_ins ADD COLUMN IF NOT EXISTS request_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS stock_ins_request_uq ON stock_ins (tenant_id, request_id) WHERE request_id IS NOT NULL;

CREATE OR REPLACE FUNCTION add_po_line_received(p_tenant_id uuid, p_line_id uuid, p_qty integer)
RETURNS integer
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
  UPDATE purchase_order_lines SET qty_received = qty_received + GREATEST(p_qty, 0)
   WHERE id = p_line_id AND tenant_id = p_tenant_id
  RETURNING qty_received;
$$;
REVOKE EXECUTE ON FUNCTION add_po_line_received(uuid, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION add_po_line_received(uuid, uuid, integer) TO service_role;

DROP POLICY IF EXISTS suppliers_tenant_member_select ON suppliers;
DROP POLICY IF EXISTS purchase_orders_tenant_member_select ON purchase_orders;
DROP POLICY IF EXISTS purchase_order_lines_tenant_member_select ON purchase_order_lines;
DROP POLICY IF EXISTS stock_ins_tenant_member_select ON stock_ins;
DROP POLICY IF EXISTS stock_in_lines_tenant_member_select ON stock_in_lines;
DROP POLICY IF EXISTS supplier_payments_tenant_member_select ON supplier_payments;

CREATE OR REPLACE FUNCTION record_catalog_file_send(p_tenant_id uuid, p_file_id uuid, p_lead_id uuid)
RETURNS void
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
  INSERT INTO catalog_file_sends (tenant_id, file_id, lead_id)
  SELECT p_tenant_id, f.id, p_lead_id FROM catalog_files f WHERE f.id = p_file_id AND f.tenant_id = p_tenant_id;
  UPDATE catalog_files SET sent_count = sent_count + 1, last_sent_at = now()
   WHERE id = p_file_id AND tenant_id = p_tenant_id;
$$;
