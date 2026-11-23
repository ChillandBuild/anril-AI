-- 324_password_help.sql
-- v9.2 #27: "Forgot password" is a request to the Anril team, not an email link (owner, 15 Nov).
-- One small table. A person types their login email or phone (+ optional business name and a note);
-- the Anril team checks it is really them and gives the new password in person or on a call.
--   tenant_id  stays NULL: the public form never says whether an account exists, so nothing is matched.
--   ip_hash    a salted hash of the caller's address (for the 10-per-hour limit and abuse checks), never the address.
-- RLS on, no policies: only the backend (service key) reads or writes it. Additive. Undo: undo/324_password_help_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.password_help_requests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid REFERENCES public.tenants(id) ON DELETE SET NULL,
  identifier    text NOT NULL CHECK (length(identifier) BETWEEN 1 AND 120),
  business_name text CHECK (business_name IS NULL OR length(business_name) <= 120),
  note          text CHECK (note IS NULL OR length(note) <= 300),
  ip_hash       text,
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  done_at       timestamptz
);
CREATE INDEX IF NOT EXISTS idx_password_help_open ON public.password_help_requests (created_at DESC) WHERE status = 'open';

ALTER TABLE public.password_help_requests ENABLE ROW LEVEL SECURITY;
