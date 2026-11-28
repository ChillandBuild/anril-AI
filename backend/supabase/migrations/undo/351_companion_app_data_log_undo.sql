-- Undo 351_companion_app_data_log.sql: drop the 7-day app data log.
-- Deploy a backend that no longer writes it first (the write only logs a warning without the table). The logged rows are lost.
DROP TABLE IF EXISTS companion_app_data_log;
