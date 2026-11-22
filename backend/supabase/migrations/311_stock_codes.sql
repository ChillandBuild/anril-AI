-- 311: Barcodes (plan: docs/plans/commerce-stock-plan.md, "The rest").
--
-- stock_codes: one code per item (no sizes) or per size/colour. Either Anril's own short code
-- (DS-KP-RM, made by itself, printed on labels) or a company barcode (EAN/UPC) typed or scanned on
-- the item, which is kept and never printed. Scanning looks a code up here (case-insensitive).

CREATE TABLE IF NOT EXISTS stock_codes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  catalog_item_id uuid NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  variant_id uuid REFERENCES catalog_item_variants(id) ON DELETE CASCADE,
  code text NOT NULL CHECK (code ~ '^[A-Za-z0-9-]{3,40}$'),
  company boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS stock_codes_code_uq ON stock_codes (tenant_id, upper(code));
CREATE UNIQUE INDEX IF NOT EXISTS stock_codes_line_uq
  ON stock_codes (catalog_item_id, (COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid)));
ALTER TABLE stock_codes ENABLE ROW LEVEL SECURITY;
CREATE POLICY stock_codes_tenant_member_select ON stock_codes
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));
