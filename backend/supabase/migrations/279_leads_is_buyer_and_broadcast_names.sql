-- 279_leads_is_buyer_and_broadcast_names.sql
-- Lets the Customers page filter by "Buyers" and search by broadcast name inside the
-- database, instead of sending long id lists in the request URL. Measured on 2026-11-17:
-- PostgREST refuses `id=in.(...)` somewhere between 600 and 1000 uuids, so a business
-- with ~700+ buyers (or a broadcast sent to ~700+ people) got an error, not a list.
--
-- - leads.is_buyer: true when the lead paid (converted_at), booked (booked_at) or has a
--   won deal. Kept right by two triggers:
--     leads  BEFORE INSERT / UPDATE OF converted_at, booked_at  -> recomputed on the row
--     deals  AFTER INSERT / DELETE / UPDATE OF stage, lead_id   -> recomputed on the lead(s)
--   It follows the data both ways (a deal moved off "won" by mistake clears it).
--   The deals trigger only writes when the value changes, so leads.updated_at is not
--   bumped for nothing.
-- - sent_broadcast_names(leads): a PostgREST computed field, the names of the broadcasts
--   the lead was sent (send_status 'sent'). Every broadcast id lives in
--   scheduled_broadcasts (checked 2026-11-17: 9 of 9). Used in the search OR filter.
--
-- Both functions are SECURITY INVOKER, so RLS on leads/deals/broadcast_recipients still applies.

SET LOCAL lock_timeout = '5s';

ALTER TABLE leads ADD COLUMN IF NOT EXISTS is_buyer boolean NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION lead_is_buyer(p_lead uuid, p_converted timestamptz, p_booked timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT p_converted IS NOT NULL
      OR p_booked IS NOT NULL
      OR EXISTS (SELECT 1 FROM deals d WHERE d.lead_id = p_lead AND d.stage = 'won')
$$;

CREATE OR REPLACE FUNCTION leads_set_is_buyer() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.is_buyer := lead_is_buyer(NEW.id, NEW.converted_at, NEW.booked_at);
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS leads_is_buyer_trg ON leads;
CREATE TRIGGER leads_is_buyer_trg
  BEFORE INSERT OR UPDATE OF converted_at, booked_at ON leads
  FOR EACH ROW EXECUTE FUNCTION leads_set_is_buyer();

CREATE OR REPLACE FUNCTION deals_sync_lead_is_buyer() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  ids uuid[] := ARRAY[]::uuid[];
BEGIN
  IF TG_OP <> 'INSERT' AND OLD.lead_id IS NOT NULL THEN ids := ids || OLD.lead_id; END IF;
  IF TG_OP <> 'DELETE' AND NEW.lead_id IS NOT NULL THEN ids := ids || NEW.lead_id; END IF;
  UPDATE leads l
     SET is_buyer = lead_is_buyer(l.id, l.converted_at, l.booked_at)
   WHERE l.id = ANY (ids)
     AND l.is_buyer IS DISTINCT FROM lead_is_buyer(l.id, l.converted_at, l.booked_at);
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS deals_is_buyer_trg ON deals;
CREATE TRIGGER deals_is_buyer_trg
  AFTER INSERT OR DELETE OR UPDATE OF stage, lead_id ON deals
  FOR EACH ROW EXECUTE FUNCTION deals_sync_lead_is_buyer();

UPDATE leads SET is_buyer = true
 WHERE NOT is_buyer AND lead_is_buyer(id, converted_at, booked_at);

CREATE INDEX IF NOT EXISTS leads_tenant_buyer_idx ON leads (tenant_id) WHERE is_buyer;

CREATE OR REPLACE FUNCTION sent_broadcast_names(l leads) RETURNS text LANGUAGE sql STABLE AS $$
  SELECT string_agg(DISTINCT sb.template_name, ' | ')
    FROM broadcast_recipients br
    JOIN scheduled_broadcasts sb ON sb.id = br.broadcast_id
   WHERE br.lead_id = l.id AND br.send_status = 'sent'
$$;
