-- 300: the new Catalogue page and the push to the shop's Meta catalogue.
--
-- * catalog_items gets cost price (stock value), HSN and its own
--   low-stock alert level.
-- * Meta sync: every change that Meta shows (name, description, price, stock, status, sizes and
--   colours, photos) bumps meta_change_seq. The sync job pushes items whose meta_change_seq is
--   ahead of meta_synced_seq (meta_pending), then sets meta_synced_seq to the number it pushed.
--   A change made while a push is on its way bumps the number again, so it is never lost.
--   meta_retailer_ids are the ids Meta knows the item by (the item, or one per size/colour),
--   so a removed size or a deleted item is deleted from Meta too.

ALTER TABLE catalog_items
  ADD COLUMN IF NOT EXISTS cost_price_paise bigint CHECK (cost_price_paise IS NULL OR cost_price_paise >= 0),
  ADD COLUMN IF NOT EXISTS hsn_code text CHECK (hsn_code IS NULL OR hsn_code ~ '^[0-9]{4,8}$'),
  ADD COLUMN IF NOT EXISTS low_stock_at integer CHECK (low_stock_at IS NULL OR low_stock_at >= 0),
  ADD COLUMN IF NOT EXISTS meta_change_seq bigint NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS meta_synced_seq bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS meta_sync_state text CHECK (meta_sync_state IN ('sending', 'synced', 'error', 'skipped')),
  ADD COLUMN IF NOT EXISTS meta_sync_error text,
  ADD COLUMN IF NOT EXISTS meta_synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS meta_batch_handle text,
  ADD COLUMN IF NOT EXISTS meta_retailer_ids text[] NOT NULL DEFAULT '{}';

ALTER TABLE catalog_items
  ADD COLUMN IF NOT EXISTS meta_pending boolean GENERATED ALWAYS AS (meta_change_seq > meta_synced_seq) STORED;

CREATE INDEX IF NOT EXISTS catalog_items_meta_pending ON catalog_items (tenant_id) WHERE meta_pending;
CREATE INDEX IF NOT EXISTS catalog_items_meta_sending ON catalog_items (tenant_id) WHERE meta_sync_state = 'sending';

-- The item's own fields that Meta shows.
CREATE OR REPLACE FUNCTION catalog_items_meta_touch() RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
BEGIN
  IF (NEW.name, NEW.description, NEW.status, NEW.item_type, NEW.price_paise, NEW.price_note, NEW.stock_quantity)
     IS DISTINCT FROM
     (OLD.name, OLD.description, OLD.status, OLD.item_type, OLD.price_paise, OLD.price_note, OLD.stock_quantity) THEN
    NEW.meta_change_seq := OLD.meta_change_seq + 1;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS catalog_items_meta_touch ON catalog_items;
CREATE TRIGGER catalog_items_meta_touch BEFORE UPDATE ON catalog_items
  FOR EACH ROW EXECUTE FUNCTION catalog_items_meta_touch();

-- A size/colour or a photo changed: the item goes again.
CREATE OR REPLACE FUNCTION catalog_child_meta_touch() RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_item uuid := COALESCE(CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE NEW.catalog_item_id END, OLD.catalog_item_id);
BEGIN
  IF v_item IS NOT NULL THEN
    UPDATE catalog_items SET meta_change_seq = meta_change_seq + 1 WHERE id = v_item;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.catalog_item_id IS DISTINCT FROM NEW.catalog_item_id AND OLD.catalog_item_id IS NOT NULL THEN
    UPDATE catalog_items SET meta_change_seq = meta_change_seq + 1 WHERE id = OLD.catalog_item_id;
  END IF;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS catalog_item_variants_meta_touch ON catalog_item_variants;
CREATE TRIGGER catalog_item_variants_meta_touch AFTER INSERT OR UPDATE OR DELETE ON catalog_item_variants
  FOR EACH ROW EXECUTE FUNCTION catalog_child_meta_touch();

DROP TRIGGER IF EXISTS catalog_media_meta_touch ON catalog_media;
CREATE TRIGGER catalog_media_meta_touch AFTER INSERT OR UPDATE OR DELETE ON catalog_media
  FOR EACH ROW EXECUTE FUNCTION catalog_child_meta_touch();
