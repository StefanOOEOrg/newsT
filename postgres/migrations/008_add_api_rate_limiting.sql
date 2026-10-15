-- Migration 008: Add API rate limiting tables
-- Track API usage to prevent exceeding rate limits

-- API usage tracking table
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

-- Insert default rate limit configurations
INSERT INTO rate_limit_config (collector_name, max_calls_per_day, max_calls_per_hour, max_calls_per_minute, min_interval_seconds, notes)
VALUES
    ('NewsAPICollector', 100, NULL, NULL, 1, 'Free tier: 100 requests/day'),
    ('FinnhubCollector', NULL, NULL, 60, 1, 'Free tier: 60 calls/minute'),
    ('AlphaVantageCollector', 25, 5, NULL, 12, 'Free tier: 25 calls/day, 5 per minute recommended'),
    ('RSSCollector', NULL, NULL, NULL, 10, 'No hard limit, but respect servers'),
    ('CongressionalTradesCollector', NULL, NULL, NULL, 60, 'No hard limit, fetch once per minute')
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
