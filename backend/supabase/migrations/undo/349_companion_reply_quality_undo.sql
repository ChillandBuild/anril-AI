-- Undo 349_companion_reply_quality.sql: drop the reply trace and the thumbs up/down table.
-- Deploy a backend without the feedback endpoints first. All collected traces and ratings are lost.
DROP TABLE IF EXISTS companion_reply_feedback;
DROP TABLE IF EXISTS companion_reply_trace;
