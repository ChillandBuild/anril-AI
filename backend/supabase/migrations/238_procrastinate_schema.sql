-- Task queue (Procrastinate) lives in its own schema: PostgREST serves only `public`, so job
-- rows are never reachable with the anon or user keys. Procrastinate's own tables are created
-- into this schema by `python -m app.queue.schema`, which runs this file first.
CREATE SCHEMA IF NOT EXISTS procrastinate;
REVOKE ALL ON SCHEMA procrastinate FROM PUBLIC, anon, authenticated;

-- Operator console pause switch, one row per task (SPEC.md M4).
CREATE TABLE IF NOT EXISTS procrastinate.task_controls (
    task_name  text PRIMARY KEY,
    paused     boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
