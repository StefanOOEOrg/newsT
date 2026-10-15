-- Migration: Add notification system tables and columns
-- Run this on existing databases to add notification features

-- Add notification columns to alerts table
ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS notified BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS notified_at TIMESTAMP;

-- Create alert notification preferences table
CREATE TABLE IF NOT EXISTS alert_notification_preferences (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    alert_type VARCHAR(50),
    min_confidence DECIMAL(3,2) DEFAULT 0.80,
    notification_channels TEXT[] DEFAULT ARRAY['email'],
    quiet_hours_start TIME DEFAULT '22:00',
    quiet_hours_end TIME DEFAULT '07:00',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(company_id, alert_type)
);

-- Create notification log table
CREATE TABLE IF NOT EXISTS notification_log (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id),
    channel VARCHAR(20) NOT NULL,
    recipient TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    sent_at TIMESTAMP DEFAULT NOW(),
    error_message TEXT
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_alerts_notified ON alerts(notified);
CREATE INDEX IF NOT EXISTS idx_alert_prefs_company ON alert_notification_preferences(company_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_alert ON notification_log(alert_id);

-- Insert default notification preferences for all existing companies
-- Only for high-confidence hiring signals and problem alerts
INSERT INTO alert_notification_preferences (company_id, alert_type, min_confidence, notification_channels, enabled)
SELECT id, 'hiring_signal', 0.85, ARRAY['email'], TRUE
FROM companies
ON CONFLICT (company_id, alert_type) DO NOTHING;

INSERT INTO alert_notification_preferences (company_id, alert_type, min_confidence, notification_channels, enabled)
SELECT id, 'problem_detected', 0.80, ARRAY['email'], TRUE
FROM companies
ON CONFLICT (company_id, alert_type) DO NOTHING;

INSERT INTO alert_notification_preferences (company_id, alert_type, min_confidence, notification_channels, enabled)
SELECT id, 'negative_sentiment', 0.85, ARRAY['email'], TRUE
FROM companies
ON CONFLICT (company_id, alert_type) DO NOTHING;
