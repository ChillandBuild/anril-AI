-- 314: Staff tied to a place (plan: docs/plans/commerce-stock-plan.md, "The rest").
--
-- tenant_users.place_id: the shop / godown / branch a teammate works at (NULL = all places, as before).
-- Their counter bills take stock from there first (deals.place_id, set when the bill is made), and they
-- can tap Received only for moves coming to their place (Cancel only for moves leaving it). Owners are
-- never limited.

ALTER TABLE tenant_users ADD COLUMN IF NOT EXISTS place_id uuid REFERENCES stock_places(id) ON DELETE SET NULL;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS place_id uuid REFERENCES stock_places(id) ON DELETE SET NULL;
