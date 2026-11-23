-- Undo 330_courses_fee_plans.sql. Drops every batch, enrolment, waitlist entry, fee plan, fee payment record and
-- fee reminder row. The orders and their payments stay (they live in deals / deal_payments).
SET LOCAL lock_timeout = '5s';

DROP TABLE IF EXISTS public.fee_plan_reminders;
DROP TABLE IF EXISTS public.fee_plan_payments;
DROP TABLE IF EXISTS public.fee_plans;
DROP TABLE IF EXISTS public.batch_waitlist;
DROP TABLE IF EXISTS public.batch_enrolments;
DROP TABLE IF EXISTS public.course_batches;
-- App setting rows are left alone: DELETE FROM app_settings WHERE key = 'fee_reminders_enabled' to clear the switch.
