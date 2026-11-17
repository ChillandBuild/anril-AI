-- 280_leads_purchase_computed_fields.sql
-- Lets the Customers page's "Repeat buyers" and "Not back in 90 days" cards work as
-- filters inside the database (no id lists in the URL; PostgREST refuses ~1000 ids).
-- Two PostgREST computed fields on leads, matching the numbers the cards show
-- (leads.py leads_summary / _buyer_facts):
--   won_deal_count(leads)   -> how many won deals the person has. Repeat buyer = 2 or more.
--   last_purchase_at(leads) -> latest of converted_at, booked_at and the won deals' won_at.
--                              Not back in 90 days = is_buyer and this is over 90 days ago.
-- Both are STABLE SQL and SECURITY INVOKER, so RLS on leads/deals still applies.
-- deals (lead_id, stage) is already indexed (deals_lead_stage_idx).

CREATE OR REPLACE FUNCTION won_deal_count(l leads) RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT count(*)::integer FROM deals d WHERE d.lead_id = l.id AND d.stage = 'won'
$$;

CREATE OR REPLACE FUNCTION last_purchase_at(l leads) RETURNS timestamptz LANGUAGE sql STABLE AS $$
  SELECT greatest(
    l.converted_at,
    l.booked_at,
    (SELECT max(d.won_at) FROM deals d WHERE d.lead_id = l.id AND d.stage = 'won')
  )
$$;
