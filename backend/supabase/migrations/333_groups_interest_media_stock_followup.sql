-- 333_groups_interest_media_stock_followup.sql
-- v9.2 medium items 38, 32, 211, 220, 43. Everything is additive and idempotent.
--
--  38  total_spent_paise(leads)        computed field: what the person has paid, net of refunds,
--                                      across all their deals. Lets a Customers group rule filter
--                                      "spent at least / at most" inside the database (no id lists
--                                      in the URL), the same way 280 did won_deal_count.
--  32  leads.interested_item_ids       the Catalogue items the person is interested in (many).
--  211 catalog_media.colour            a photo can be linked to one colour of the item; the AI will
--                                      not send it while every size of that colour is out of stock.
--  220 stock_movements.photo_path      optional photo of damaged pieces (catalog-media bucket).
--  43  reengagement_steps.type         adds 'campaign_reply' (replied to a Reach campaign, no order).

-- 38. Net paid per person. deals.paid_paise follows deal_payments by trigger (294);
--     refunded_paise follows deal_refunds (295). A deal never counts below zero.
CREATE OR REPLACE FUNCTION total_spent_paise(l leads) RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT COALESCE(SUM(GREATEST(d.paid_paise - d.refunded_paise, 0)), 0)::bigint
  FROM deals d WHERE d.lead_id = l.id
$$;

-- 32. Interested in (Catalogue item ids; names are looked up when shown, so a renamed or deleted item is never stale).
ALTER TABLE leads ADD COLUMN IF NOT EXISTS interested_item_ids uuid[] NOT NULL DEFAULT '{}';

-- 211. A photo linked to a colour (text, matched ignoring case against catalog_item_variants.colour).
ALTER TABLE catalog_media ADD COLUMN IF NOT EXISTS colour text;

-- 220. Photo kept with a stock movement (a path in the catalog-media bucket).
ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS photo_path text;

-- 43. A third kind of follow-up step.
ALTER TABLE reengagement_steps DROP CONSTRAINT IF EXISTS reengagement_steps_type_check;
ALTER TABLE reengagement_steps ADD CONSTRAINT reengagement_steps_type_check
  CHECK (type IN ('broadcast', 'inbound', 'campaign_reply'));
