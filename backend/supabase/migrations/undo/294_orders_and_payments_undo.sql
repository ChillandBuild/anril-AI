-- Undo 294. Orders made while it was live keep their deals rows; walk-in orders with no
-- customer (lead_id NULL) must be removed first or the NOT NULL comes back refused.
DROP TABLE IF EXISTS stock_waitlist;
DROP FUNCTION IF EXISTS apply_variant_stock_movement(uuid, uuid, integer, text, uuid, text, uuid);
ALTER TABLE stock_movements DROP COLUMN IF EXISTS variant_quantity_after, DROP COLUMN IF EXISTS variant_id;
ALTER TABLE deal_items DROP COLUMN IF EXISTS variant_label, DROP COLUMN IF EXISTS variant_id;
DROP TABLE IF EXISTS catalog_item_variants;
DROP FUNCTION IF EXISTS next_invoice_number(uuid, text);
DROP TABLE IF EXISTS invoice_counters;
DROP TABLE IF EXISTS deal_messages;
DROP TRIGGER IF EXISTS deal_payments_sync_paid_trg ON deal_payments;
DROP FUNCTION IF EXISTS deal_payments_sync_paid();
DROP TABLE IF EXISTS deal_payments;
DROP INDEX IF EXISTS deals_tenant_created_idx;
DROP INDEX IF EXISTS deals_bill_token_key;
DROP INDEX IF EXISTS deals_tenant_invoice_number_key;
ALTER TABLE deals
  DROP CONSTRAINT IF EXISTS deals_customer_needed,
  DROP CONSTRAINT IF EXISTS deals_buyer_gstin_check,
  DROP CONSTRAINT IF EXISTS deals_paid_paise_check,
  DROP CONSTRAINT IF EXISTS deals_bill_type_check,
  DROP CONSTRAINT IF EXISTS deals_gst_paise_check,
  DROP CONSTRAINT IF EXISTS deals_discount_check,
  DROP CONSTRAINT IF EXISTS deals_delivery_status_check,
  DROP CONSTRAINT IF EXISTS deals_handover_check,
  DROP CONSTRAINT IF EXISTS deals_channel_check;
ALTER TABLE deals
  DROP COLUMN IF EXISTS last_reminder_at, DROP COLUMN IF EXISTS reminders_from, DROP COLUMN IF EXISTS reminders_sent,
  DROP COLUMN IF EXISTS paid_paise, DROP COLUMN IF EXISTS bill_token, DROP COLUMN IF EXISTS invoice_issued_at,
  DROP COLUMN IF EXISTS invoice_number, DROP COLUMN IF EXISTS sold_by_ai, DROP COLUMN IF EXISTS customer_name, DROP COLUMN IF EXISTS buyer_business,
  DROP COLUMN IF EXISTS buyer_gstin, DROP COLUMN IF EXISTS bill_type, DROP COLUMN IF EXISTS gst_paise,
  DROP COLUMN IF EXISTS discount_paise, DROP COLUMN IF EXISTS tracking_id, DROP COLUMN IF EXISTS courier,
  DROP COLUMN IF EXISTS delivered_at, DROP COLUMN IF EXISTS shipped_at, DROP COLUMN IF EXISTS ready_at,
  DROP COLUMN IF EXISTS ready_by, DROP COLUMN IF EXISTS delivery_status, DROP COLUMN IF EXISTS handover,
  DROP COLUMN IF EXISTS channel;
ALTER TABLE deals ALTER COLUMN lead_id SET NOT NULL;
