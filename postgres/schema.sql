-- ==============================================================================
-- News Trading Database - Consolidated Schema
-- ==============================================================================
-- This is the complete database schema including all migrations merged into
-- a single file. This represents the full state of the database as of 2025-11-21.
--
-- Sections:
--   1. Core Tables (Asset, Social Posts, AI Analysis)
--   2. Metrics & Performance Tables
--   3. Alert System Tables
--   4. Notification System Tables
--   5. System Infrastructure Tables
--   6. Indexes
--   7. Sample Data
-- ==============================================================================

-- ==============================================================================
-- SECTION 1: CORE TABLES
-- ==============================================================================

-- Asset table: Stores assets to track for trading signals (stocks, crypto, currencies, etc.)
-- Includes initialization tracking for historical data collection
DROP TABLE IF EXISTS asset CASCADE;
CREATE TABLE asset (
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
DROP TABLE IF EXISTS social_posts CASCADE;
CREATE TABLE social_posts (
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
DROP TABLE IF EXISTS ai_analysis CASCADE;
CREATE TABLE ai_analysis (
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
DROP TABLE IF EXISTS daily_metrics CASCADE;
CREATE TABLE daily_metrics (
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
DROP TABLE IF EXISTS keyword_performance CASCADE;
CREATE TABLE keyword_performance (
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
DROP TABLE IF EXISTS alerts CASCADE;
CREATE TABLE alerts (
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

-- ==============================================================================
-- SECTION 4: NOTIFICATION SYSTEM TABLES
-- ==============================================================================

-- Alert notification preferences table: Per-asset notification settings
-- Controls when and how users receive alerts (from migration 001_add_notifications)
DROP TABLE IF EXISTS alert_notification_preferences CASCADE;
CREATE TABLE alert_notification_preferences (
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
DROP TABLE IF EXISTS notification_log CASCADE;
CREATE TABLE notification_log (
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
DROP TABLE IF EXISTS notification_settings CASCADE;
CREATE TABLE notification_settings (
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
DROP TABLE IF EXISTS system_logs CASCADE;
CREATE TABLE system_logs (
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
CREATE INDEX idx_asset_init_status ON asset(initialization_status);

-- Social posts indexes
CREATE INDEX idx_social_posts_asset ON social_posts(asset_id);
CREATE INDEX idx_social_posts_created ON social_posts(created_at);
CREATE INDEX idx_social_posts_matched_keywords ON social_posts USING GIN(matched_keywords);

-- AI analysis indexes
CREATE INDEX idx_ai_analysis_post ON ai_analysis(post_id);

-- Daily metrics indexes
CREATE INDEX idx_daily_metrics_asset_date ON daily_metrics(asset_id, date);

-- Keyword performance indexes
CREATE INDEX idx_keyword_performance_asset ON keyword_performance(asset_id);
CREATE INDEX idx_keyword_performance_posts ON keyword_performance(posts_found DESC);
CREATE INDEX idx_keyword_performance_last_found ON keyword_performance(last_found_at);

-- Alerts indexes
CREATE INDEX idx_alerts_asset ON alerts(asset_id);
CREATE INDEX idx_alerts_notified ON alerts(notified);

-- Notification preferences indexes
CREATE INDEX idx_alert_prefs_asset ON alert_notification_preferences(asset_id);

-- Notification log indexes
CREATE INDEX idx_notification_log_alert ON notification_log(alert_id);

-- System logs indexes
CREATE INDEX idx_system_logs_timestamp ON system_logs(timestamp);
CREATE INDEX idx_system_logs_level ON system_logs(level);
CREATE INDEX idx_system_logs_service ON system_logs(service);

-- ==============================================================================
-- SECTION 7: SAMPLE DATA
-- ==============================================================================

-- Insert sample assets for testing
INSERT INTO asset (name, ticker, search_keywords) VALUES
('Genpact', 'G', ARRAY['genpact', 'hiring', 'job opening']),
('Palantir', 'PLTR', ARRAY['palantir', 'pltr']),
('Snowflake', 'SNOW', ARRAY['snowflake', 'snow']);

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

Return ONLY valid JSON, no other text.');

-- ==============================================================================
-- END OF SCHEMA
-- ==============================================================================
