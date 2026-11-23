-- 317_bookings_qr_google.sql
-- v9.2 #19 Bookings, #24 WhatsApp QR & links, #20 Google Ads (decided 2026-11-23, Prem: "Yes, build all three").
--
-- Bookings (Engage › Bookings, /dashboard/bookings):
--   booking_settings           one row per client: secret link token + the rules (14 days ahead, not within
--                              60 min, 1 booking per phone per day, cancel/move up to 180 min before,
--                              advance after 2 no-shows).
--   booking_services           what can be booked; each is also a catalogue item (item_type 'service') so an
--                              advance or "Came" makes a real order through the existing order code.
--   booking_resources          a column on By staff / chair: a person (user_id = their login) or a chair/room.
--                              hours = {"0".."6": [["10:00","13:00"],["16:00","20:00"]]}, 0 = Monday.
--   booking_service_resources  who can do which service.
--   booking_leave              days a column is off.
--   bookings                   the bookings. Two guards in the database:
--                                * no two live bookings overlap on one column (incl. the gap after), and
--                                * one live booking per phone per IST day when the switch is on (booking_date
--                                  and day_guard are set by the backend).
--                              Live = held (advance not paid yet, released at hold_until) / booked / came.
-- QR & links (WhatsApp › QR & links, /dashboard/qr-links):
--   qr_links     one per place; the printed QR points at /q/<code>, which forwards to the main number with
--                the first message + "(Q-<code>)". leads.qr_link_id = first-touch "Came from".
--   qr_events    'open' (someone opened /q/<code>) and 'chat' (a message with the tag arrived).
-- Google Ads (Leads › Google Ads, /dashboard/google-ads):
--   ad_campaigns.google_campaign_name   the campaign's name as Google's report spells it (CSV matching).
--   google_ads_spend                    spend + clicks per campaign per month, from the CSV upload or by hand.
-- leads.source / opt_in_source gain 'qr'.
-- Permissions: bookings.view + bookings.manage (new keys; no role gets them automatically).
--
-- All new tables: RLS on, no member policies — only the backend's service key reads or writes them.
-- Additive. Undo: undo/317_bookings_qr_google_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ── Bookings ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.booking_settings (
  tenant_id          uuid PRIMARY KEY REFERENCES public.tenants(id) ON DELETE CASCADE,
  link_token         text NOT NULL UNIQUE CHECK (length(link_token) BETWEEN 16 AND 64),
  link_on            boolean NOT NULL DEFAULT true,
  days_ahead         integer NOT NULL DEFAULT 14 CHECK (days_ahead BETWEEN 1 AND 90),
  min_notice_min     integer NOT NULL DEFAULT 60 CHECK (min_notice_min BETWEEN 0 AND 2880),
  cancel_cutoff_min  integer NOT NULL DEFAULT 180 CHECK (cancel_cutoff_min BETWEEN 0 AND 2880),
  one_per_day        boolean NOT NULL DEFAULT true,
  no_show_limit      integer NOT NULL DEFAULT 2 CHECK (no_show_limit BETWEEN 1 AND 10),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.booking_services (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  catalog_item_id  uuid REFERENCES public.catalog_items(id) ON DELETE SET NULL,
  name             text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
  duration_min     integer NOT NULL CHECK (duration_min BETWEEN 5 AND 600),
  price_paise      bigint NOT NULL DEFAULT 0 CHECK (price_paise >= 0),
  advance_paise    bigint NOT NULL DEFAULT 0 CHECK (advance_paise >= 0),
  gap_after_min    integer NOT NULL DEFAULT 0 CHECK (gap_after_min BETWEEN 0 AND 240),
  active           boolean NOT NULL DEFAULT true,
  sort             integer NOT NULL DEFAULT 0,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_booking_services_tenant ON public.booking_services (tenant_id, active, sort);

CREATE TABLE IF NOT EXISTS public.booking_resources (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  name        text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  kind        text NOT NULL DEFAULT 'person' CHECK (kind IN ('person', 'chair', 'room')),
  user_id     uuid,
  hours       jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(hours) = 'object'),
  active      boolean NOT NULL DEFAULT true,
  sort        integer NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_booking_resources_tenant ON public.booking_resources (tenant_id, active, sort);
CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_resources_user
  ON public.booking_resources (tenant_id, user_id) WHERE user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.booking_service_resources (
  service_id   uuid NOT NULL REFERENCES public.booking_services(id) ON DELETE CASCADE,
  resource_id  uuid NOT NULL REFERENCES public.booking_resources(id) ON DELETE CASCADE,
  tenant_id    uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  PRIMARY KEY (service_id, resource_id)
);
CREATE INDEX IF NOT EXISTS idx_bsr_tenant ON public.booking_service_resources (tenant_id);

CREATE TABLE IF NOT EXISTS public.booking_leave (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  resource_id  uuid NOT NULL REFERENCES public.booking_resources(id) ON DELETE CASCADE,
  from_date    date NOT NULL,
  to_date      date NOT NULL,
  note         text CHECK (note IS NULL OR length(note) <= 200),
  created_by   uuid,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (to_date >= from_date AND to_date - from_date <= 366)
);
CREATE INDEX IF NOT EXISTS idx_booking_leave_resource ON public.booking_leave (tenant_id, resource_id, to_date);

-- The old temple-booking table (devotee_name, rasi, nakshatram; migration 029) is still live
-- because 130_drop_legacy_booking_artifacts was never applied. It had 0 rows and no code reads it
-- (checked 2026-11-23). Nothing is deleted: it is RENAMED to bookings_legacy_029 (its indexes too,
-- so bookings_pkey is free), keeping its trigger and the lead_conversation_state.booking_id link.
-- Only when it is that old table, so re-running this file never touches real bookings.
-- Safe to drop bookings_legacy_029 later on purpose; undo renames it back.
DO $$
DECLARE r record;
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'bookings' AND column_name = 'devotee_name')
     AND to_regclass('public.bookings_legacy_029') IS NULL THEN
    ALTER TABLE public.bookings RENAME TO bookings_legacy_029;
    FOR r IN SELECT indexname FROM pg_indexes
             WHERE schemaname = 'public' AND tablename = 'bookings_legacy_029' AND indexname LIKE 'bookings\_%' LOOP
      EXECUTE format('ALTER INDEX public.%I RENAME TO %I', r.indexname, 'bookings_legacy_029_' || substr(r.indexname, 10));
    END LOOP;
    COMMENT ON TABLE public.bookings_legacy_029 IS
      'Old temple bookings (migration 029). Empty and unused; renamed by 317 on 2026-11-23. Safe to drop.';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.bookings (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  number                integer NOT NULL CHECK (number > 0),
  lead_id               uuid REFERENCES public.leads(id) ON DELETE SET NULL,
  phone                 text NOT NULL CHECK (length(phone) BETWEEN 6 AND 20),
  customer_name         text CHECK (customer_name IS NULL OR length(customer_name) <= 120),
  service_id            uuid NOT NULL REFERENCES public.booking_services(id) ON DELETE RESTRICT,
  resource_id           uuid NOT NULL REFERENCES public.booking_resources(id) ON DELETE RESTRICT,
  start_at              timestamptz NOT NULL,
  end_at                timestamptz NOT NULL,
  block_end_at          timestamptz NOT NULL,
  booking_date          date NOT NULL,
  status                text NOT NULL DEFAULT 'booked'
                        CHECK (status IN ('held', 'booked', 'came', 'no_show', 'cancelled')),
  source                text NOT NULL DEFAULT 'phone'
                        CHECK (source IN ('link', 'chat', 'phone', 'walk_in', 'ai')),
  phone_checked         boolean NOT NULL DEFAULT false,
  deal_id               uuid REFERENCES public.deals(id) ON DELETE SET NULL,
  advance_paise         bigint NOT NULL DEFAULT 0 CHECK (advance_paise >= 0),
  hold_until            timestamptz,
  confirmed_at          timestamptz,
  reminder_day_sent_at  timestamptz,
  reminder_2h_sent_at   timestamptz,
  reminder_wamid        text,
  call_now_at           timestamptz,
  came_at               timestamptz,
  cancelled_at          timestamptz,
  cancelled_by          text CHECK (cancelled_by IS NULL OR cancelled_by IN ('customer', 'staff', 'system')),
  cancel_reason         text CHECK (cancel_reason IS NULL OR length(cancel_reason) <= 200),
  moved_count           integer NOT NULL DEFAULT 0,
  day_guard             boolean NOT NULL DEFAULT true,
  note                  text CHECK (note IS NULL OR length(note) <= 500),
  created_by            uuid,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (end_at > start_at AND block_end_at >= end_at),
  CONSTRAINT bookings_no_overlap EXCLUDE USING gist (
    resource_id WITH =,
    tstzrange(start_at, block_end_at, '[)') WITH &&
  ) WHERE (status IN ('held', 'booked', 'came'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_number ON public.bookings (tenant_id, number);
-- day_guard = the business's "1 booking per phone per day" switch at the time the booking was made or
-- moved (set by the backend). Turning the switch off lets new bookings through; old ones keep theirs.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_phone_day
  ON public.bookings (tenant_id, phone, booking_date) WHERE status IN ('held', 'booked', 'came') AND day_guard;
CREATE INDEX IF NOT EXISTS idx_bookings_tenant_start ON public.bookings (tenant_id, start_at);
CREATE INDEX IF NOT EXISTS idx_bookings_lead ON public.bookings (tenant_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_bookings_phone ON public.bookings (tenant_id, phone);
CREATE INDEX IF NOT EXISTS idx_bookings_reminders ON public.bookings (start_at) WHERE status = 'booked';
CREATE INDEX IF NOT EXISTS idx_bookings_holds ON public.bookings (hold_until) WHERE status = 'held';

-- ── QR & links ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.qr_links (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  code           text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9]{4,8}$'),
  name           text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  first_message  text NOT NULL CHECK (length(btrim(first_message)) BETWEEN 1 AND 300),
  place_id       uuid REFERENCES public.stock_places(id) ON DELETE SET NULL,
  archived       boolean NOT NULL DEFAULT false,
  created_by     uuid,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qr_links_tenant ON public.qr_links (tenant_id, archived);

CREATE TABLE IF NOT EXISTS public.qr_events (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id   uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  qr_link_id  uuid NOT NULL REFERENCES public.qr_links(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('open', 'chat')),
  lead_id     uuid REFERENCES public.leads(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qr_events_link ON public.qr_events (tenant_id, qr_link_id, kind, created_at);

ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS qr_link_id uuid REFERENCES public.qr_links(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_leads_qr_link ON public.leads (tenant_id, qr_link_id) WHERE qr_link_id IS NOT NULL;

ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_source_check;
ALTER TABLE public.leads ADD CONSTRAINT leads_source_check CHECK (source = ANY (ARRAY[
  'whatsapp', 'instagram', 'upload', 'manual', 'telegram', 'facebook', 'indiamart', 'justdial',
  'website', 'api', 'store', 'meta_form', 'qr'
]));
ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_opt_in_source_check;
ALTER TABLE public.leads ADD CONSTRAINT leads_opt_in_source_check CHECK (opt_in_source = ANY (ARRAY[
  'click_to_wa_ad', 'website_form', 'offline_event', 'previous_enquiry', 'imported', 'manual', 'whatsapp',
  'instagram', 'facebook', 'telegram', 'csv', 'indiamart', 'justdial', 'api', 'meta_form', 'qr'
]));

-- ── Google Ads ──────────────────────────────────────────────────────────────
ALTER TABLE public.ad_campaigns ADD COLUMN IF NOT EXISTS google_campaign_name text;

CREATE TABLE IF NOT EXISTS public.google_ads_spend (
  tenant_id    uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  campaign_id  uuid NOT NULL REFERENCES public.ad_campaigns(id) ON DELETE CASCADE,
  month        date NOT NULL CHECK (extract(day FROM month) = 1),
  spend_paise  bigint NOT NULL DEFAULT 0 CHECK (spend_paise >= 0),
  clicks       integer NOT NULL DEFAULT 0 CHECK (clicks >= 0),
  source       text NOT NULL DEFAULT 'upload' CHECK (source IN ('upload', 'hand')),
  updated_by   uuid,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (campaign_id, month)
);
CREATE INDEX IF NOT EXISTS idx_google_ads_spend_tenant ON public.google_ads_spend (tenant_id, month);

-- ── RLS: service key only ───────────────────────────────────────────────────
ALTER TABLE public.booking_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_services ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_service_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.booking_leave ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qr_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qr_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.google_ads_spend ENABLE ROW LEVEL SECURITY;

-- ── Permissions ─────────────────────────────────────────────────────────────
-- bookings.view / bookings.manage are NOT given to any existing role: bookings show customers' names and
-- phones, so the owner ticks them in Team & roles (security review 2026-11-23). The owner passes all checks.

COMMENT ON TABLE public.bookings IS
  'Engage › Bookings. Live = held/booked/came; no overlap per column, 1 per phone per IST day. Service key only.';
COMMENT ON TABLE public.qr_links IS
  'WhatsApp › QR & links. Printed QR -> /q/<code> -> wa.me main number + first message + (Q-<code>).';
COMMENT ON TABLE public.google_ads_spend IS
  'Google Ads spend + clicks per campaign per month (CSV upload or by hand). Service key only.';
