-- Undo 317_bookings_qr_google.sql. Drops every booking, QR and Google spend row.
SET LOCAL lock_timeout = '5s';

UPDATE public.tenant_roles
   SET permissions = array_remove(array_remove(permissions, 'bookings.view'), 'bookings.manage'), updated_at = now()
 WHERE 'bookings.view' = ANY (coalesce(permissions, '{}'::text[]))
    OR 'bookings.manage' = ANY (coalesce(permissions, '{}'::text[]));

DROP TABLE IF EXISTS public.google_ads_spend;
ALTER TABLE public.ad_campaigns DROP COLUMN IF EXISTS google_campaign_name;

UPDATE public.leads SET source = 'whatsapp' WHERE source = 'qr';
UPDATE public.leads SET opt_in_source = 'whatsapp' WHERE opt_in_source = 'qr';
ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_source_check;
ALTER TABLE public.leads ADD CONSTRAINT leads_source_check CHECK (source = ANY (ARRAY[
  'whatsapp', 'instagram', 'upload', 'manual', 'telegram', 'facebook', 'indiamart', 'justdial',
  'website', 'api', 'store', 'meta_form'
]));
ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_opt_in_source_check;
ALTER TABLE public.leads ADD CONSTRAINT leads_opt_in_source_check CHECK (opt_in_source = ANY (ARRAY[
  'click_to_wa_ad', 'website_form', 'offline_event', 'previous_enquiry', 'imported', 'manual', 'whatsapp',
  'instagram', 'facebook', 'telegram', 'csv', 'indiamart', 'justdial', 'api', 'meta_form'
]));
DROP INDEX IF EXISTS public.idx_leads_qr_link;
ALTER TABLE public.leads DROP COLUMN IF EXISTS qr_link_id;
DROP TABLE IF EXISTS public.qr_events;
DROP TABLE IF EXISTS public.qr_links;

DROP TABLE IF EXISTS public.bookings;
DROP TABLE IF EXISTS public.booking_leave;
DROP TABLE IF EXISTS public.booking_service_resources;
DROP TABLE IF EXISTS public.booking_resources;
DROP TABLE IF EXISTS public.booking_services;
DROP TABLE IF EXISTS public.booking_settings;

-- Put the old temple table back under its old name (317 renamed it, indexes too).
DO $$
DECLARE r record;
BEGIN
  IF to_regclass('public.bookings_legacy_029') IS NOT NULL AND to_regclass('public.bookings') IS NULL THEN
    ALTER TABLE public.bookings_legacy_029 RENAME TO bookings;
    FOR r IN SELECT indexname FROM pg_indexes
             WHERE schemaname = 'public' AND tablename = 'bookings' AND indexname LIKE 'bookings\_legacy\_029\_%' LOOP
      EXECUTE format('ALTER INDEX public.%I RENAME TO %I', r.indexname, 'bookings_' || substr(r.indexname, 21));
    END LOOP;
  END IF;
END $$;
-- btree_gist is left installed (harmless; other code may use it).
