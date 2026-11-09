-- Meta Ads schedule and edit metadata for the Messaging Ads report.
-- These are read-only copies from the existing ads_read sync; current RLS applies.

ALTER TABLE public.ad_campaigns
  ADD COLUMN IF NOT EXISTS meta_updated_at timestamptz;

ALTER TABLE public.ad_sets
  ADD COLUMN IF NOT EXISTS start_time timestamptz,
  ADD COLUMN IF NOT EXISTS end_time timestamptz,
  ADD COLUMN IF NOT EXISTS meta_updated_at timestamptz;
