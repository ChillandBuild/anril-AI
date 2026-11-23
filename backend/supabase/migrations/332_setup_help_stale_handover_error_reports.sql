-- 332_setup_help_stale_handover_error_reports.sql
-- v9.2 batch 3 (items 80, 157, 24). Three small additive changes, nothing existing is touched.
--   1. setup_help_requests: "Let the Anril team do it" on first setup step 2. One OPEN request per business
--      per kind (partial unique index). The operator sees open ones on the Operator Console home.
--   2. chat_handovers.stale_alerted_at: set once when the owner has been told "nobody replied in 15 minutes",
--      so a handover is only ever alerted once.
--   3. client_error_reports: the app's error page sends its error code (digest) and page path here. No names,
--      no phone numbers, no error text, no query string. For Anril support.
-- RLS on, no policies: only the backend (service key) reads or writes these.
-- Undo: undo/332_setup_help_stale_handover_error_reports_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.setup_help_requests (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  kind         text NOT NULL DEFAULT 'catalogue' CHECK (kind IN ('catalogue')),
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'cancelled')),
  requested_by uuid,
  created_at   timestamptz NOT NULL DEFAULT now(),
  done_at      timestamptz,
  done_by      uuid
);
CREATE UNIQUE INDEX IF NOT EXISTS setup_help_requests_one_open
  ON public.setup_help_requests (tenant_id, kind) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS setup_help_requests_open_idx
  ON public.setup_help_requests (created_at DESC) WHERE status = 'open';
ALTER TABLE public.setup_help_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.setup_help_requests FROM anon, authenticated;
GRANT ALL ON public.setup_help_requests TO service_role;

ALTER TABLE public.chat_handovers ADD COLUMN IF NOT EXISTS stale_alerted_at timestamptz;
-- The 5-minute sweep only looks at open handovers that have not been alerted yet.
CREATE INDEX IF NOT EXISTS idx_chat_handovers_stale_sweep
  ON public.chat_handovers (opened_at) WHERE status = 'pending' AND stale_alerted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.client_error_reports (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid REFERENCES public.tenants(id) ON DELETE SET NULL,
  digest     text CHECK (digest IS NULL OR length(digest) <= 80),
  path       text CHECK (path IS NULL OR length(path) <= 200),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_error_reports_recent_idx ON public.client_error_reports (created_at DESC);
ALTER TABLE public.client_error_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.client_error_reports FROM anon, authenticated;
GRANT ALL ON public.client_error_reports TO service_role;
