-- Migration: Add stock_prices table for centralized price data
-- Purpose: Store historical stock prices collected via yfinance
-- Single source of truth for stock price data used by dashboard and analyzer

-- Stock prices table
CREATE TABLE IF NOT EXISTS stock_prices (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    timestamp TIMESTAMP NOT NULL,
    open DECIMAL(12, 4),
    high DECIMAL(12, 4),
    low DECIMAL(12, 4),
    close DECIMAL(12, 4) NOT NULL,
    volume BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset_id, timestamp)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_stock_prices_asset_timestamp
    ON stock_prices(asset_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_stock_prices_timestamp
    ON stock_prices(timestamp DESC);

-- Add rate limiting configuration for StockPriceCollector
INSERT INTO rate_limit_config (
    collector_name,
    max_calls_per_day,
    max_calls_per_hour,
    max_calls_per_minute,
    min_interval_seconds,
    enabled,
    notes
) VALUES (
    'StockPriceCollector',
    NULL,  -- No daily limit (yfinance free tier is generous)
    100,   -- Max 100 calls per hour (well below yfinance limit)
    NULL,  -- No per-minute limit
    300,   -- Minimum 300 seconds (5 minutes) between calls - matches collection interval
    true,
    'Fetches stock prices from Yahoo Finance. Updates every 5 minutes during market hours.'
) ON CONFLICT (collector_name) DO NOTHING;

-- Add comment
COMMENT ON TABLE stock_prices IS 'Historical stock price data collected via yfinance. Single source of truth for price data used across services.';
