-- 244_sms_credit_cap.sql
-- At most 3 open Add-credit requests per client, enforced in the database. The API counts first,
-- but two requests at the same moment could both see 2 open and both insert. This trigger takes a
-- per-tenant advisory lock (held until the insert commits), so the second insert waits, then counts
-- the first one and is refused. The API (app/services/sms_setup.request_credit) turns the
-- "sms_credit_cap" error into the usual 409.

SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION sms_credit_requests_cap() RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  IF NEW.status = 'open' THEN
    PERFORM pg_advisory_xact_lock(hashtextextended('sms_credit_requests:' || NEW.tenant_id::text, 0));
    IF (SELECT count(*) FROM sms_credit_requests WHERE tenant_id = NEW.tenant_id AND status = 'open') >= 3 THEN
      RAISE EXCEPTION 'sms_credit_cap: 3 open credit requests' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END
$$;

-- CREATE OR REPLACE TRIGGER (PG14+), not DROP + CREATE: the Supabase MCP refuses DROP statements.
CREATE OR REPLACE TRIGGER sms_credit_requests_cap
  BEFORE INSERT ON sms_credit_requests
  FOR EACH ROW EXECUTE FUNCTION sms_credit_requests_cap();
