-- Undo 345_feedback_fixed_by_review_sent.sql
ALTER TABLE public.customer_feedback DROP COLUMN IF EXISTS review_link_sent;
ALTER TABLE public.customer_feedback DROP COLUMN IF EXISTS fixed_by_name;
