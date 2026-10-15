-- Migration: Add asset_events table for tracking financial calendar events
-- Created: 2025-11-23
-- Purpose: Store earnings reports, product launches, regulatory filings, and other financial events

CREATE TABLE IF NOT EXISTS asset_events (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,  -- 'earnings', 'product_launch', 'filing', 'conference', 'dividend', etc.
    event_date DATE NOT NULL,
    event_time TIME,  -- Optional: For intraday events
    description TEXT,
    url TEXT,
    source VARCHAR(100),  -- 'alphavantage', 'yahoo', 'sec_edgar', 'manual'
    metadata JSONB,  -- Additional event-specific data
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_asset_events_asset_id ON asset_events(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_events_event_date ON asset_events(event_date);
CREATE INDEX IF NOT EXISTS idx_asset_events_event_type ON asset_events(event_type);
CREATE INDEX IF NOT EXISTS idx_asset_events_upcoming ON asset_events(event_date DESC);

-- Composite index for common queries (upcoming events for specific asset)
CREATE INDEX IF NOT EXISTS idx_asset_events_asset_upcoming ON asset_events(asset_id, event_date DESC);

COMMENT ON TABLE asset_events IS 'Financial calendar events for tracked assets';
COMMENT ON COLUMN asset_events.event_type IS 'Type of event: earnings, product_launch, filing, conference, dividend, etc.';
COMMENT ON COLUMN asset_events.metadata IS 'JSON field for additional event-specific data (e.g., EPS estimates, filing type)';
