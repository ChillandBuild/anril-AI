-- 302: WhatsApp Forms, Phase 4 — live forms (they read the business's data while the customer
-- fills them, through Anril's encrypted Flows endpoint).
--
-- * whatsapp_form_designs.kind: 'standard' (Phase 2), 'order' (pick Catalogue items with live
--   price and stock, quantities, address, summary -> payment link) or 'booking' (only free
--   dates/slots from the business's weekly hours, slot length and capacity).
--   whatsapp_form_designs.settings: that kind's options (all editable).
-- * whatsapp_flow_keys: the RSA key pair Meta encrypts live-form requests with, per WhatsApp
--   number. The private key is stored encrypted with a server-derived key. RLS on and NO
--   member policy: only the backend (service role) ever reads it.
-- * whatsapp_form_bookings: one row per booked seat; a unique (design, slot, seat) rule on live bookings makes a slot
--   impossible to over-book even when two customers submit at the same moment.

ALTER TABLE whatsapp_form_designs ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'standard'
  CHECK (kind IN ('standard', 'order', 'booking'));
ALTER TABLE whatsapp_form_designs ADD COLUMN IF NOT EXISTS settings jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS whatsapp_flow_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  phone_number_id text NOT NULL,
  public_key text NOT NULL,
  private_key_enc text NOT NULL,
  uploaded_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, phone_number_id)
);
ALTER TABLE whatsapp_flow_keys ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS whatsapp_form_bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  design_id uuid NOT NULL REFERENCES whatsapp_form_designs(id) ON DELETE CASCADE,
  slot_start timestamptz NOT NULL,
  seat integer NOT NULL CHECK (seat BETWEEN 1 AND 50),
  lead_id uuid REFERENCES leads(id) ON DELETE SET NULL,
  response_id uuid REFERENCES whatsapp_form_responses(id) ON DELETE SET NULL,
  cancelled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
-- A cancelled booking frees its seat: the rule only covers live bookings.
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_form_bookings_seat_uq
  ON whatsapp_form_bookings (tenant_id, design_id, slot_start, seat) WHERE NOT cancelled;
ALTER TABLE whatsapp_form_bookings ENABLE ROW LEVEL SECURITY;
CREATE POLICY whatsapp_form_bookings_tenant_member_select ON whatsapp_form_bookings
  FOR SELECT TO authenticated USING (is_tenant_member(tenant_id));
