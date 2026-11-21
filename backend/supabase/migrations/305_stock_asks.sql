-- 305: "Asked but out of stock" (plan: docs/plans/commerce-stock-plan.md, part 1).
-- stock_waitlist (294) becomes the record of every customer who asked for an out-of-stock item
-- or size: staff add them from Orders, the AI adds them in chat. One OPEN row per customer per
-- item/size; "Mark back in stock" messages the ones who want it and closes the rows.

ALTER TABLE stock_waitlist
  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'staff' CHECK (source IN ('staff', 'ai')),
  ADD COLUMN IF NOT EXISTS wants_message boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS last_asked_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS price_paise bigint,          -- the price when asked: "sales missed"
  ADD COLUMN IF NOT EXISTS closed_at timestamptz,       -- told (or no longer waiting)
  ADD COLUMN IF NOT EXISTS notify_via text CHECK (notify_via IS NULL OR notify_via IN ('text', 'template'));

CREATE UNIQUE INDEX IF NOT EXISTS stock_waitlist_open_uq
  ON stock_waitlist (tenant_id, catalog_item_id,
                     (COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid)), lead_id)
  WHERE closed_at IS NULL AND lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS stock_waitlist_asked_idx ON stock_waitlist (tenant_id, last_asked_at DESC);
