-- 315: Item page bits (plan: docs/plans/commerce-stock-plan.md, part 8).
--
-- * advance_rule: NULL = the shop's rule (Settings › Payments & advance); else the item's own
--   {"kind": "none"} | {"kind": "percent", "value": 30} | {"kind": "fixed", "value": 1000 (rupees per piece)}.
--   Bills, quotes and the AI's payment link ask for the advance of what is ordered.
-- * ai_share_price: off = the AI talks about the item but never says its price, sends no photo and
--   makes no payment link for it (the team shares the price).
-- * ai_max_discount_pct: 0 = the AI never offers a discount; else it may go down by up to this %
--   when a customer asks for less (the link uses that price; more is refused in code).

ALTER TABLE catalog_items ADD COLUMN IF NOT EXISTS advance_rule jsonb
  CHECK (advance_rule IS NULL OR (advance_rule->>'kind') IN ('none', 'percent', 'fixed'));
ALTER TABLE catalog_items ADD COLUMN IF NOT EXISTS ai_share_price boolean NOT NULL DEFAULT true;
ALTER TABLE catalog_items ADD COLUMN IF NOT EXISTS ai_max_discount_pct integer NOT NULL DEFAULT 0
  CHECK (ai_max_discount_pct BETWEEN 0 AND 50);
