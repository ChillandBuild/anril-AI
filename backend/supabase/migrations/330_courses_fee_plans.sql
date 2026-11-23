-- 330_courses_fee_plans.sql  (Education: Courses & batches + fee instalments)
-- Additive only. RLS on, no policies: the backend uses the service key. Assumes 329 ran first only for the
-- catalog item_type 'course' (nothing constrains item_type today, so this file does not depend on it).
--   course_batches       one run of a course: start date, timing, mode, seats, fee, teacher, open|full|closed
--   batch_enrolments     a student in a batch (one seat); deal_id is the order that carries the money.
--                        Seats filled = active enrolments whose order has money paid (or is won).
--   batch_waitlist       people waiting for a seat in a full batch
--   fee_plans            one per order: parts [{due_on, amount_paise}] adding up to the order total
--   fee_plan_payments    one row per part paid (unique per part), with its receipt number
--   fee_plan_reminders   one row per reminder (plan, part, kind): inserted BEFORE sending, so a re-run never double-sends
-- The fee reminder switch is an app_settings row (fee_reminders_enabled, default off): no table.
-- Undo: undo/330_courses_fee_plans_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.course_batches (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  course_item_id  uuid NOT NULL REFERENCES public.catalog_items(id) ON DELETE CASCADE,
  name            text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
  starts_on       date,
  timing_text     text CHECK (timing_text IS NULL OR length(timing_text) <= 200),
  mode            text NOT NULL DEFAULT 'offline' CHECK (mode IN ('online', 'offline', 'both')),
  seats_total     integer NOT NULL DEFAULT 20 CHECK (seats_total BETWEEN 0 AND 10000),
  fee_paise       bigint NOT NULL DEFAULT 0 CHECK (fee_paise >= 0),
  teacher_name    text CHECK (teacher_name IS NULL OR length(teacher_name) <= 120),
  status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'full', 'closed')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_course_batches_course ON public.course_batches (tenant_id, course_item_id);
CREATE INDEX IF NOT EXISTS idx_course_batches_open ON public.course_batches (tenant_id, status, starts_on);

CREATE TABLE IF NOT EXISTS public.batch_enrolments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  batch_id      uuid NOT NULL REFERENCES public.course_batches(id) ON DELETE CASCADE,
  lead_id       uuid NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  deal_id       uuid REFERENCES public.deals(id) ON DELETE SET NULL,
  student_name  text CHECK (student_name IS NULL OR length(student_name) <= 120),
  phone         text NOT NULL,
  parent_phone  text,          -- optional second number, used ONLY for fee reminders
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dropped')),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_enrolments_student ON public.batch_enrolments (batch_id, lead_id) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_enrolments_deal ON public.batch_enrolments (deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_batch_enrolments_batch ON public.batch_enrolments (tenant_id, batch_id, status);

CREATE TABLE IF NOT EXISTS public.batch_waitlist (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  batch_id    uuid NOT NULL REFERENCES public.course_batches(id) ON DELETE CASCADE,
  lead_id     uuid REFERENCES public.leads(id) ON DELETE SET NULL,
  phone       text NOT NULL,
  name        text CHECK (name IS NULL OR length(name) <= 120),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (batch_id, phone)
);
CREATE INDEX IF NOT EXISTS idx_batch_waitlist_batch ON public.batch_waitlist (tenant_id, batch_id, created_at);

CREATE TABLE IF NOT EXISTS public.fee_plans (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  deal_id       uuid NOT NULL REFERENCES public.deals(id) ON DELETE CASCADE,
  parts         jsonb NOT NULL CHECK (jsonb_typeof(parts) = 'array' AND jsonb_array_length(parts) BETWEEN 1 AND 24),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (deal_id)
);
CREATE INDEX IF NOT EXISTS idx_fee_plans_tenant ON public.fee_plans (tenant_id);

CREATE TABLE IF NOT EXISTS public.fee_plan_payments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  fee_plan_id   uuid NOT NULL REFERENCES public.fee_plans(id) ON DELETE CASCADE,
  part_index    integer NOT NULL CHECK (part_index >= 0),
  paid_paise    bigint NOT NULL CHECK (paid_paise > 0),
  method        text NOT NULL DEFAULT 'cash',
  paid_at       timestamptz NOT NULL DEFAULT now(),
  receipt_no    text NOT NULL,
  by_user_id    uuid,
  UNIQUE (fee_plan_id, part_index)
);
CREATE INDEX IF NOT EXISTS idx_fee_plan_payments_tenant ON public.fee_plan_payments (tenant_id, paid_at DESC);

CREATE TABLE IF NOT EXISTS public.fee_plan_reminders (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  fee_plan_id   uuid NOT NULL REFERENCES public.fee_plans(id) ON DELETE CASCADE,
  part_index    integer NOT NULL CHECK (part_index >= 0),
  kind          text NOT NULL CHECK (kind IN ('before', 'due', 'late')),
  wamid         text,
  sent_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fee_plan_id, part_index, kind)
);

DROP TRIGGER IF EXISTS course_batches_updated_at ON public.course_batches;
CREATE TRIGGER course_batches_updated_at BEFORE UPDATE ON public.course_batches
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
DROP TRIGGER IF EXISTS fee_plans_updated_at ON public.fee_plans;
CREATE TRIGGER fee_plans_updated_at BEFORE UPDATE ON public.fee_plans
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.course_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.batch_enrolments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.batch_waitlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fee_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fee_plan_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fee_plan_reminders ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.course_batches IS
  'Education: one run of a course (catalog item_type course). Seats filled = paid enrolments. Service key only.';
COMMENT ON TABLE public.fee_plans IS
  'Education: an order''s fee in parts [{due_on, amount_paise}]. Money itself lives in deal_payments. Service key only.';
COMMENT ON TABLE public.fee_plan_reminders IS
  'One row per fee reminder, inserted before the send: the unique key is what stops a double send. Service key only.';
