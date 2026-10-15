-- Migration: Add collection schedule settings to notification_settings
-- Date: 2025-11-19

-- Add collection scheduling columns
ALTER TABLE notification_settings
ADD COLUMN IF NOT EXISTS enable_smart_scheduling BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS collection_interval_market_hours INTEGER DEFAULT 15,
ADD COLUMN IF NOT EXISTS collection_interval_after_hours INTEGER DEFAULT 30,
ADD COLUMN IF NOT EXISTS collection_interval_weekends INTEGER DEFAULT 120,
ADD COLUMN IF NOT EXISTS collection_interval_fixed INTEGER DEFAULT 30,
ADD COLUMN IF NOT EXISTS market_open_hour INTEGER DEFAULT 9,
ADD COLUMN IF NOT EXISTS market_open_minute INTEGER DEFAULT 30,
ADD COLUMN IF NOT EXISTS market_close_hour INTEGER DEFAULT 16,
ADD COLUMN IF NOT EXISTS market_close_minute INTEGER DEFAULT 0;

-- Add comments
COMMENT ON COLUMN notification_settings.enable_smart_scheduling IS 'Enable market-hours-based collection scheduling';
COMMENT ON COLUMN notification_settings.collection_interval_market_hours IS 'Collection frequency during market hours (minutes)';
COMMENT ON COLUMN notification_settings.collection_interval_after_hours IS 'Collection frequency after market closes (minutes)';
COMMENT ON COLUMN notification_settings.collection_interval_weekends IS 'Collection frequency on weekends (minutes)';
COMMENT ON COLUMN notification_settings.collection_interval_fixed IS 'Fixed collection interval when smart scheduling is disabled (minutes)';
COMMENT ON COLUMN notification_settings.market_open_hour IS 'Market opening hour (ET, 0-23)';
COMMENT ON COLUMN notification_settings.market_open_minute IS 'Market opening minute (0-59)';
COMMENT ON COLUMN notification_settings.market_close_hour IS 'Market closing hour (ET, 0-23)';
COMMENT ON COLUMN notification_settings.market_close_minute IS 'Market closing minute (0-59)';
