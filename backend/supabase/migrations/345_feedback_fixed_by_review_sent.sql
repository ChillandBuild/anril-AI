-- 345_feedback_fixed_by_review_sent.sql  (v9.2 Customers > Feedback: "Fixed by", "Google review sent")
-- Additive only. fixed_by (uuid) already says who; the name is kept so the list can say "Fixed by Selvi"
-- even after that teammate leaves. review_link_sent marks a 4-5 star thank-you that carried the
-- Google review link.
-- Undo: undo/345_feedback_fixed_by_review_sent_undo.sql
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.customer_feedback ADD COLUMN IF NOT EXISTS fixed_by_name text;
ALTER TABLE public.customer_feedback ADD COLUMN IF NOT EXISTS review_link_sent boolean NOT NULL DEFAULT false;
