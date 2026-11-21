-- Undo 308.
DROP FUNCTION IF EXISTS add_po_line_received(uuid, uuid, integer);
DROP INDEX IF EXISTS stock_ins_request_uq;
ALTER TABLE stock_ins DROP COLUMN IF EXISTS request_id;
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['suppliers', 'purchase_orders', 'purchase_order_lines', 'stock_ins', 'stock_in_lines',
                           'supplier_payments'] LOOP
    EXECUTE format('CREATE POLICY %I ON %I FOR SELECT TO authenticated USING (is_tenant_member(tenant_id))',
                   t || '_tenant_member_select', t);
  END LOOP;
END $$;
-- record_catalog_file_send: re-create the 306 version if wanted (it counted without the tenant check).
