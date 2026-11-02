-- ==============================================================================
-- News Trading Database - Consolidated Schema
-- ==============================================================================
-- This is the complete database schema including all migrations merged into
-- a single file. This represents the full state of the database as of 2025-11-21.
--
-- Applying this file is non-destructive: every statement creates only what is
-- missing and keeps the rows of a populated database. To start from an empty
-- database, apply sql/reset.sql first (``newstrading init-db --reset``).
--
-- Sections:
--   1. Core Tables (Asset, Social Posts, AI Analysis)
--   2. Metrics & Performance Tables
--   3. Alert System Tables
--   4. Notification System Tables
--   5. System Infrastructure Tables
--   6. Indexes
--   7. Sample Data
--   8. Events
--   9. Market Data
--  10. Rate Limiting
--  11. Collector Statistics
-- ==============================================================================

-- ==============================================================================
-- SECTION 1: CORE TABLES
-- ==============================================================================

-- Asset table: Stores assets to track for trading signals (stocks, crypto, currencies, etc.)
-- Includes initialization tracking for historical data collection
CREATE TABLE IF NOT EXISTS asset (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    search_keywords TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    -- Initialization tracking fields (from migration 001_add_initialization_tracking)
    initialization_status VARCHAR(20) DEFAULT 'completed',
    initialization_days INTEGER,
    initialization_started_at TIMESTAMP,
    initialization_completed_at TIMESTAMP
);

COMMENT ON TABLE asset IS 'Assets being tracked for trading signals and social media mentions (stocks, crypto, currencies, etc.)';
COMMENT ON COLUMN asset.initialization_status IS 'Status of historical data initialization: pending, in_progress, completed, failed';
COMMENT ON COLUMN asset.initialization_days IS 'Number of days of historical data to collect during initialization';

-- Social posts table: Stores raw social media posts from Reddit, Twitter, etc.
-- Includes keyword tracking for performance analysis
CREATE TABLE IF NOT EXISTS social_posts (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,
    post_id VARCHAR(255) UNIQUE NOT NULL,
    author VARCHAR(255),
    title TEXT,
    content TEXT,
    url TEXT,
    score INTEGER,
    created_at TIMESTAMP NOT NULL,
    fetched_at TIMESTAMP DEFAULT NOW(),
    -- Keyword tracking (from migration 001_add_keyword_performance)
    matched_keywords TEXT[]
);

COMMENT ON TABLE social_posts IS 'Raw social media posts collected from various sources';
COMMENT ON COLUMN social_posts.matched_keywords IS 'Array of keywords that matched this post for tracking keyword effectiveness';

-- AI analysis table: Stores Claude AI analysis results for each post
-- Includes special event detection for enhanced trading signals
CREATE TABLE IF NOT EXISTS ai_analysis (
    id SERIAL PRIMARY KEY,
    post_id INTEGER REFERENCES social_posts(id) ON DELETE CASCADE,
    sentiment VARCHAR(20),
    sentiment_score FLOAT,
    category VARCHAR(50),
    key_topics TEXT[],
    summary TEXT,
    analyzed_at TIMESTAMP DEFAULT NOW(),
    -- Special events detection (from migration 003_add_special_events_column)
    special_events TEXT[] DEFAULT ARRAY[]::TEXT[]
);

COMMENT ON TABLE ai_analysis IS 'AI-powered analysis results for social media posts including sentiment and trading signals';
COMMENT ON COLUMN ai_analysis.special_events IS 'Array of detected special event types (partnerships, product launches, analyst upgrades, etc.)';

-- ==============================================================================
-- SECTION 2: METRICS & PERFORMANCE TABLES
-- ==============================================================================

-- Daily metrics table: Aggregated daily statistics per asset
CREATE TABLE IF NOT EXISTS daily_metrics (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    mention_count INTEGER,
    sentiment_avg FLOAT,
    hiring_mentions INTEGER,
    problem_mentions INTEGER,
    growth_mentions INTEGER,
    UNIQUE(asset_id, date)
);

COMMENT ON TABLE daily_metrics IS 'Daily aggregated metrics for each asset including mentions and sentiment';

-- Keyword performance table: Tracks which keywords are finding posts
-- Helps optimize search keywords for each asset (from migration 001_add_keyword_performance)
CREATE TABLE IF NOT EXISTS keyword_performance (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    keyword VARCHAR(255) NOT NULL,
    posts_found INTEGER DEFAULT 0,
    last_found_at TIMESTAMP,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(asset_id, keyword)
);

COMMENT ON TABLE keyword_performance IS 'Tracks effectiveness of search keywords in finding relevant posts';

-- ==============================================================================
-- SECTION 3: ALERT SYSTEM TABLES
-- ==============================================================================

-- Alerts table: Stores generated alerts for unusual activity or trading signals
-- Includes notification tracking
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT NOW(),
    alert_type VARCHAR(50),
    severity VARCHAR(20) DEFAULT 'medium',
    description TEXT,
    confidence_score FLOAT,
    -- Notification tracking (from migration 001_add_notifications)
    notified BOOLEAN DEFAULT FALSE,
    notified_at TIMESTAMP
);

COMMENT ON TABLE alerts IS 'Trading alerts generated from social media analysis (bullish/bearish signals)';
COMMENT ON COLUMN alerts.severity IS 'Alert severity: low, medium, high, critical';
COMMENT ON COLUMN alerts.notified IS 'Whether notification has been sent for this alert';

-- Alert performance table: Tracks stock price movements after alerts for backtesting
-- (from migration 007_add_alert_performance; lives here because it references alerts(id))
CREATE TABLE IF NOT EXISTS alert_performance (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,
    alert_date TIMESTAMP NOT NULL,
    confidence_score DECIMAL(5,2),

    -- Price data at alert time
    price_at_alert DECIMAL(10,2),

    -- Price data at future intervals
    price_1d_later DECIMAL(10,2),
    price_3d_later DECIMAL(10,2),
    price_7d_later DECIMAL(10,2),
    price_14d_later DECIMAL(10,2),
    price_30d_later DECIMAL(10,2),

    -- Return calculations
    return_1d DECIMAL(10,4),
    return_3d DECIMAL(10,4),
    return_7d DECIMAL(10,4),
    return_14d DECIMAL(10,4),
    return_30d DECIMAL(10,4),

    -- Directional analysis
    predicted_direction VARCHAR(10), -- 'bullish', 'bearish', 'neutral'
    actual_direction_1d VARCHAR(10),
    actual_direction_3d VARCHAR(10),
    actual_direction_7d VARCHAR(10),

    -- Accuracy tracking
    correct_1d BOOLEAN,
    correct_3d BOOLEAN,
    correct_7d BOOLEAN,

    -- Tracking metadata
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_alert_performance_alert_id ON alert_performance(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_performance_asset_id ON alert_performance(asset_id);
CREATE INDEX IF NOT EXISTS idx_alert_performance_alert_type ON alert_performance(alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_performance_alert_date ON alert_performance(alert_date);
CREATE INDEX IF NOT EXISTS idx_alert_performance_confidence ON alert_performance(confidence_score);

-- Comments
COMMENT ON TABLE alert_performance IS 'Tracks stock price movements after alerts for backtesting and validation';
COMMENT ON COLUMN alert_performance.predicted_direction IS 'Direction predicted by alert: bullish (long), bearish (short), neutral';
COMMENT ON COLUMN alert_performance.return_1d IS 'Price return 1 day after alert as decimal (e.g., 0.05 = 5%)';
COMMENT ON COLUMN alert_performance.correct_1d IS 'True if predicted direction matches actual price movement';

-- ==============================================================================
-- SECTION 4: NOTIFICATION SYSTEM TABLES
-- ==============================================================================

-- Alert notification preferences table: Per-asset notification settings
-- Controls when and how users receive alerts (from migration 001_add_notifications)
CREATE TABLE IF NOT EXISTS alert_notification_preferences (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    alert_type VARCHAR(50),
    min_confidence DECIMAL(3,2) DEFAULT 0.80,
    notification_channels TEXT[] DEFAULT ARRAY['email'],
    quiet_hours_start TIME DEFAULT '22:00',
    quiet_hours_end TIME DEFAULT '07:00',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(asset_id, alert_type)
);

COMMENT ON TABLE alert_notification_preferences IS 'Per-asset notification preferences for different alert types';

-- Notification log table: Tracks all sent notifications
-- Provides audit trail (from migration 001_add_notifications)
CREATE TABLE IF NOT EXISTS notification_log (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id),
    channel VARCHAR(20) NOT NULL,
    recipient TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    sent_at TIMESTAMP DEFAULT NOW(),
    error_message TEXT
);

COMMENT ON TABLE notification_log IS 'Audit log of all notification attempts (successful and failed)';

-- Global notification settings table: Stores SMTP, Twilio, and other global configs
-- Single-row table with system-wide settings
CREATE TABLE IF NOT EXISTS notification_settings (
    id SERIAL PRIMARY KEY,
    notification_email VARCHAR(255),
    notification_phone VARCHAR(20),
    smtp_host VARCHAR(255),
    smtp_port INTEGER DEFAULT 587,
    smtp_user VARCHAR(255),
    smtp_password VARCHAR(255),
    smtp_from VARCHAR(255),
    twilio_account_sid VARCHAR(255),
    twilio_auth_token VARCHAR(255),
    twilio_from_number VARCHAR(20),
    pushover_token VARCHAR(255),
    pushover_user VARCHAR(255),
    webhook_url VARCHAR(500),
    check_interval INTEGER DEFAULT 5,
    analysis_prompt TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    -- Collection scheduling settings (from migration 004_add_collection_schedule_settings)
    enable_smart_scheduling BOOLEAN DEFAULT TRUE,
    collection_interval_market_hours INTEGER DEFAULT 15,
    collection_interval_after_hours INTEGER DEFAULT 30,
    collection_interval_weekends INTEGER DEFAULT 120,
    collection_interval_fixed INTEGER DEFAULT 30,
    market_open_hour INTEGER DEFAULT 9,
    market_open_minute INTEGER DEFAULT 30,
    market_close_hour INTEGER DEFAULT 16,
    market_close_minute INTEGER DEFAULT 0
);

COMMENT ON TABLE notification_settings IS 'Global notification and system settings (single-row table)';
COMMENT ON COLUMN notification_settings.enable_smart_scheduling IS 'Enable market-hours-based collection scheduling';
COMMENT ON COLUMN notification_settings.collection_interval_market_hours IS 'Collection frequency during market hours (minutes)';
COMMENT ON COLUMN notification_settings.collection_interval_after_hours IS 'Collection frequency after market closes (minutes)';
COMMENT ON COLUMN notification_settings.collection_interval_weekends IS 'Collection frequency on weekends (minutes)';
COMMENT ON COLUMN notification_settings.collection_interval_fixed IS 'Fixed collection interval when smart scheduling is disabled (minutes)';
COMMENT ON COLUMN notification_settings.market_open_hour IS 'Market opening hour (ET, 0-23)';
COMMENT ON COLUMN notification_settings.market_open_minute IS 'Market opening minute (0-59)';
COMMENT ON COLUMN notification_settings.market_close_hour IS 'Market closing hour (ET, 0-23)';
COMMENT ON COLUMN notification_settings.market_close_minute IS 'Market closing minute (0-59)';

-- ==============================================================================
-- SECTION 5: SYSTEM INFRASTRUCTURE TABLES
-- ==============================================================================

-- System logs table: Stores application logs for debugging and monitoring
CREATE TABLE IF NOT EXISTS system_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    level VARCHAR(20) NOT NULL,
    logger VARCHAR(100) NOT NULL,
    service VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    function VARCHAR(100),
    line_number INTEGER,
    exception TEXT,
    metadata JSONB
);

COMMENT ON TABLE system_logs IS 'Centralized application logs with structured metadata';

-- ==============================================================================
-- SECTION 6: INDEXES FOR QUERY PERFORMANCE
-- ==============================================================================

-- Asset indexes
CREATE INDEX IF NOT EXISTS idx_asset_init_status ON asset(initialization_status);

-- Social posts indexes
CREATE INDEX IF NOT EXISTS idx_social_posts_asset ON social_posts(asset_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_created ON social_posts(created_at);
CREATE INDEX IF NOT EXISTS idx_social_posts_matched_keywords ON social_posts USING GIN(matched_keywords);

-- AI analysis indexes
CREATE INDEX IF NOT EXISTS idx_ai_analysis_post ON ai_analysis(post_id);

-- Daily metrics indexes
CREATE INDEX IF NOT EXISTS idx_daily_metrics_asset_date ON daily_metrics(asset_id, date);

-- Keyword performance indexes
CREATE INDEX IF NOT EXISTS idx_keyword_performance_asset ON keyword_performance(asset_id);
CREATE INDEX IF NOT EXISTS idx_keyword_performance_posts ON keyword_performance(posts_found DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_performance_last_found ON keyword_performance(last_found_at);

-- Alerts indexes
CREATE INDEX IF NOT EXISTS idx_alerts_asset ON alerts(asset_id);
CREATE INDEX IF NOT EXISTS idx_alerts_notified ON alerts(notified);

-- Notification preferences indexes
CREATE INDEX IF NOT EXISTS idx_alert_prefs_asset ON alert_notification_preferences(asset_id);

-- Notification log indexes
CREATE INDEX IF NOT EXISTS idx_notification_log_alert ON notification_log(alert_id);

-- System logs indexes
CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_system_logs_service ON system_logs(service);

-- ==============================================================================
-- SECTION 7: SAMPLE DATA
-- ==============================================================================

-- Insert sample assets for testing
-- ``asset`` has no unique key on ``ticker`` (an old database may violate one), so the seed
-- guards every row instead: a second ``init-db`` neither fails nor duplicates them.
INSERT INTO asset (name, ticker, search_keywords)
SELECT * FROM (VALUES
    ('Genpact', 'G', ARRAY['genpact', 'hiring', 'job opening']),
    ('Palantir', 'PLTR', ARRAY['palantir', 'pltr']),
    ('Snowflake', 'SNOW', ARRAY['snowflake', 'snow'])
) AS seed(name, ticker, keywords)
WHERE NOT EXISTS (SELECT 1 FROM asset a WHERE a.ticker = seed.ticker);

-- Insert default notification settings with comprehensive AI analysis prompt
-- Includes special event detection (from migrations 002 & 003)
INSERT INTO notification_settings (id, check_interval, analysis_prompt) VALUES (1, 5, 'Analyze this social media post about {asset_name} ({ticker}) from a trading perspective.

{text_to_analyze}

Provide your analysis in JSON format with these fields:
- sentiment: one of "positive", "negative", or "neutral"
- sentiment_score: a number between -1.0 (very bearish/short signal) and 1.0 (very bullish/long signal)
- category: one of "Hiring", "Growth", "Problems", "Product", "Earnings", "Other"
- key_topics: array of 2-5 key topics or themes (as strings)
- summary: brief summary in 1-2 sentences (max 100 words)
- special_events: array of detected special events (if any), each event should be one of:
  * "partnership_announced"
  * "product_launch"
  * "regulatory_risk"
  * "analyst_upgrade"
  * "analyst_downgrade"
  * "market_share_gain"
  * "customer_loss"
  * "executive_change"
  * "guidance_raise"
  * "guidance_cut"
  * "insider_buying"
  * "insider_selling"
  Leave empty array [] if no special events detected.

Focus on identifying trading signals:
- BULLISH (long signals): hiring, partnerships, product launches, earnings beats, growth indicators, positive guidance, analyst upgrades, insider buying, market share gains
- BEARISH (short signals): problems, layoffs, negative sentiment, downgrades, missed earnings, legal issues, regulatory risks, guidance cuts, insider selling, customer losses

Return ONLY valid JSON, no other text.') ON CONFLICT (id) DO NOTHING;

-- ==============================================================================
-- SECTION 8: EVENTS
-- ==============================================================================

-- Asset events table: Financial calendar events for tracked assets
-- (from migration 007_add_asset_events)
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
    updated_at TIMESTAMP DEFAULT NOW(),
    -- Unique key the event store relies on for its idempotent ON CONFLICT insert
    UNIQUE(asset_id, event_type, event_date, description)
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

-- ==============================================================================
-- SECTION 9: MARKET DATA
-- ==============================================================================

-- Stock prices table: Historical stock price data collected via yfinance
-- Single source of truth for price data used by dashboard and analyzer
-- (from migration 009_add_stock_prices)
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

COMMENT ON TABLE stock_prices IS 'Historical stock price data collected via yfinance. Single source of truth for price data used across services.';

-- ==============================================================================
-- SECTION 10: RATE LIMITING
-- ==============================================================================

-- API usage tracking table
-- (from migration 008_add_api_rate_limiting)
CREATE TABLE IF NOT EXISTS api_usage (
    id SERIAL PRIMARY KEY,
    collector_name VARCHAR(100) NOT NULL,
    api_endpoint VARCHAR(255),
    timestamp TIMESTAMP DEFAULT NOW(),
    status_code INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_api_usage_collector_time
    ON api_usage(collector_name, timestamp DESC);

-- Rate limit configuration table
CREATE TABLE IF NOT EXISTS rate_limit_config (
    id SERIAL PRIMARY KEY,
    collector_name VARCHAR(100) UNIQUE NOT NULL,
    max_calls_per_day INTEGER DEFAULT 100,
    max_calls_per_hour INTEGER,
    max_calls_per_minute INTEGER,
    min_interval_seconds INTEGER DEFAULT 1,
    enabled BOOLEAN DEFAULT TRUE,
    last_reset TIMESTAMP DEFAULT NOW(),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Repair the quota rows of a database created before the rows were keyed by source name.
-- These UPDATEs must run *before* the seeds below: on an old database the seed would
-- otherwise insert the new row first, the ``NOT EXISTS`` guard would then be false and the
-- legacy class row would stay behind as a dead duplicate. Renaming first lets the seed hit
-- ``ON CONFLICT DO NOTHING``. ``collector_name`` is UNIQUE, so the guard is also what makes
-- a second ``init-db`` run a no-op instead of a duplicate-key error.
UPDATE rate_limit_config SET collector_name = 'newsapi'
WHERE collector_name = 'NewsAPICollector'
  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = 'newsapi');

UPDATE rate_limit_config SET collector_name = 'finnhub'
WHERE collector_name = 'FinnhubCollector'
  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = 'finnhub');

UPDATE rate_limit_config SET collector_name = 'alphavantage'
WHERE collector_name = 'AlphaVantageCollector'
  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = 'alphavantage');

UPDATE rate_limit_config SET collector_name = 'rss'
WHERE collector_name = 'RSSCollector'
  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = 'rss');

UPDATE rate_limit_config SET collector_name = 'congressional_trades'
WHERE collector_name = 'CongressionalTradesCollector'
  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = 'congressional_trades');

UPDATE rate_limit_config SET collector_name = 'stock_prices'
WHERE collector_name = 'StockPriceCollector'
  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = 'stock_prices');

-- Insert default rate limit configurations
-- The names are the source keys the collectors report (and write into ``posts.source``),
-- not their class names: ``check_rate_limit`` treats an unknown name as "no limit".
INSERT INTO rate_limit_config (collector_name, max_calls_per_day, max_calls_per_hour, max_calls_per_minute, min_interval_seconds, notes)
VALUES
    ('newsapi', 100, NULL, NULL, 1, 'Free tier: 100 requests/day'),
    ('finnhub', NULL, NULL, 60, 1, 'Free tier: 60 calls/minute'),
    ('alphavantage', 25, 5, NULL, 12, 'Free tier: 25 calls/day, 5 per minute recommended'),
    ('rss', NULL, NULL, NULL, 10, 'No hard limit, but respect servers'),
    ('congressional_trades', NULL, NULL, NULL, 60, 'No hard limit, fetch once per minute'),
    ('stock_prices', NULL, 100, NULL, 300, 'Fetches stock prices from Yahoo Finance. Updates every 5 minutes during market hours.')
ON CONFLICT (collector_name) DO NOTHING;

-- View for API usage stats
CREATE OR REPLACE VIEW api_usage_stats AS
SELECT
    collector_name,
    COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '1 day') as calls_today,
    COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '1 hour') as calls_last_hour,
    COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '1 minute') as calls_last_minute,
    COUNT(*) FILTER (WHERE success = FALSE AND timestamp >= NOW() - INTERVAL '1 day') as errors_today,
    MAX(timestamp) as last_call_time
FROM api_usage
GROUP BY collector_name;

-- Function to check if rate limit is exceeded
CREATE OR REPLACE FUNCTION check_rate_limit(p_collector_name VARCHAR)
RETURNS TABLE(
    can_proceed BOOLEAN,
    reason TEXT,
    wait_seconds INTEGER
) AS $$
DECLARE
    v_config RECORD;
    v_calls_today INTEGER;
    v_calls_hour INTEGER;
    v_calls_minute INTEGER;
    v_last_call TIMESTAMP;
    v_min_interval INTEGER;
BEGIN
    -- Get rate limit config
    SELECT * INTO v_config
    FROM rate_limit_config
    WHERE collector_name = p_collector_name;

    IF NOT FOUND OR NOT v_config.enabled THEN
        RETURN QUERY SELECT TRUE, 'No rate limit configured'::TEXT, 0;
        RETURN;
    END IF;

    -- Get current usage
    SELECT
        COALESCE(calls_today, 0),
        COALESCE(calls_last_hour, 0),
        COALESCE(calls_last_minute, 0),
        last_call_time
    INTO v_calls_today, v_calls_hour, v_calls_minute, v_last_call
    FROM api_usage_stats
    WHERE collector_name = p_collector_name;

    -- Check daily limit
    IF v_config.max_calls_per_day IS NOT NULL AND v_calls_today >= v_config.max_calls_per_day THEN
        RETURN QUERY SELECT
            FALSE,
            format('Daily limit exceeded (%s/%s)', v_calls_today, v_config.max_calls_per_day)::TEXT,
            EXTRACT(EPOCH FROM (DATE_TRUNC('day', NOW()) + INTERVAL '1 day' - NOW()))::INTEGER;
        RETURN;
    END IF;

    -- Check hourly limit
    IF v_config.max_calls_per_hour IS NOT NULL AND v_calls_hour >= v_config.max_calls_per_hour THEN
        RETURN QUERY SELECT
            FALSE,
            format('Hourly limit exceeded (%s/%s)', v_calls_hour, v_config.max_calls_per_hour)::TEXT,
            EXTRACT(EPOCH FROM (DATE_TRUNC('hour', NOW()) + INTERVAL '1 hour' - NOW()))::INTEGER;
        RETURN;
    END IF;

    -- Check per-minute limit
    IF v_config.max_calls_per_minute IS NOT NULL AND v_calls_minute >= v_config.max_calls_per_minute THEN
        RETURN QUERY SELECT
            FALSE,
            format('Per-minute limit exceeded (%s/%s)', v_calls_minute, v_config.max_calls_per_minute)::TEXT,
            60;
        RETURN;
    END IF;

    -- Check minimum interval
    IF v_config.min_interval_seconds IS NOT NULL AND v_last_call IS NOT NULL THEN
        IF NOW() - v_last_call < (v_config.min_interval_seconds || ' seconds')::INTERVAL THEN
            RETURN QUERY SELECT
                FALSE,
                format('Minimum interval not met (wait %s seconds)', v_config.min_interval_seconds)::TEXT,
                v_config.min_interval_seconds;
            RETURN;
        END IF;
    END IF;

    -- All checks passed
    RETURN QUERY SELECT TRUE, 'OK'::TEXT, 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE api_usage IS 'Tracks all API calls made by collectors for rate limiting';
COMMENT ON TABLE rate_limit_config IS 'Configuration for rate limits per collector';
COMMENT ON FUNCTION check_rate_limit IS 'Checks if a collector can make an API call without exceeding rate limits';

-- ==============================================================================
-- SECTION 11: COLLECTOR STATISTICS
-- ==============================================================================

-- Collector statistics table: Runtime statistics for each collector service
-- (from migration 011_add_collector_statistics)
CREATE TABLE IF NOT EXISTS collector_statistics (
    id SERIAL PRIMARY KEY,
    collector_name VARCHAR(100) UNIQUE NOT NULL,
    last_run_started_at TIMESTAMP WITH TIME ZONE,
    last_run_completed_at TIMESTAMP WITH TIME ZONE,
    last_run_duration_seconds NUMERIC(10, 2),
    total_posts_collected INTEGER DEFAULT 0,
    total_posts_saved INTEGER DEFAULT 0,
    last_run_posts_collected INTEGER DEFAULT 0,
    last_run_posts_saved INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    last_error_message TEXT,
    last_error_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index on collector_name for faster lookups
CREATE INDEX IF NOT EXISTS idx_collector_statistics_name ON collector_statistics(collector_name);

-- Create index on last_run_completed_at for sorting
CREATE INDEX IF NOT EXISTS idx_collector_statistics_last_run ON collector_statistics(last_run_completed_at DESC);

-- Add comment to table
COMMENT ON TABLE collector_statistics IS 'Runtime statistics for data collector services';
COMMENT ON COLUMN collector_statistics.collector_name IS 'Unique name of the collector (e.g., RSSCollector, NewsAPICollector)';
COMMENT ON COLUMN collector_statistics.last_run_started_at IS 'When the last collection run started';
COMMENT ON COLUMN collector_statistics.last_run_completed_at IS 'When the last collection run completed successfully';
COMMENT ON COLUMN collector_statistics.last_run_duration_seconds IS 'Duration of last run in seconds';
COMMENT ON COLUMN collector_statistics.total_posts_collected IS 'Total posts collected across all runs';
COMMENT ON COLUMN collector_statistics.total_posts_saved IS 'Total new posts saved across all runs';
COMMENT ON COLUMN collector_statistics.last_run_posts_collected IS 'Posts collected in the most recent run';
COMMENT ON COLUMN collector_statistics.last_run_posts_saved IS 'New posts saved in the most recent run';
COMMENT ON COLUMN collector_statistics.total_errors IS 'Total errors encountered across all runs';
COMMENT ON COLUMN collector_statistics.last_error_message IS 'Message from most recent error (max 500 chars)';
COMMENT ON COLUMN collector_statistics.last_error_at IS 'When the last error occurred';

-- ==============================================================================
-- END OF SCHEMA
-- ==============================================================================
