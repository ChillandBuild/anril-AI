-- 306_home_layouts.sql
-- v9.2 Home (Today) › ✎ Edit Today: each person's own box order and which lists are on.
--   One row per (client, person). No row = the suggested set, picked by the modules the
--   client uses; "Back to the suggested set" deletes the row.
--   boxes: ordered list of box keys (max 12, checked by the backend).
--   lists: {"waiting": bool, "low_stock": bool}.
-- RLS on with no policies: only the backend's service key reads or writes it.
-- Additive. Undo: undo/306_home_layouts_undo.sql
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.home_layouts (
  tenant_id  uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id    uuid NOT NULL,
  boxes      jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(boxes) = 'array'),
  lists      jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(lists) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);
ALTER TABLE public.home_layouts ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.home_layouts IS
  'Home › Edit Today: one person''s box order and list switches. No row = suggested set. Service key only.';
