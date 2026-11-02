-- ==============================================================================
-- News Trading Database - Reset
-- ==============================================================================
-- DESTRUCTIVE: this script drops every table of the schema, and with it all data.
-- It is never applied by default: ``newstrading init-db --reset`` runs it before
-- ``sql/schema.sql`` recreates the empty tables. Applying ``sql/schema.sql`` alone
-- keeps the data of a populated database.
-- ==============================================================================

DROP TABLE IF EXISTS asset CASCADE;
DROP TABLE IF EXISTS social_posts CASCADE;
DROP TABLE IF EXISTS ai_analysis CASCADE;
DROP TABLE IF EXISTS daily_metrics CASCADE;
DROP TABLE IF EXISTS keyword_performance CASCADE;
DROP TABLE IF EXISTS alerts CASCADE;
DROP TABLE IF EXISTS alert_notification_preferences CASCADE;
DROP TABLE IF EXISTS notification_log CASCADE;
DROP TABLE IF EXISTS notification_settings CASCADE;
DROP TABLE IF EXISTS system_logs CASCADE;
