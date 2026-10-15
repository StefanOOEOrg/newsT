-- Migration: Add collector_statistics table
-- Purpose: Store runtime statistics for each collector service
-- Date: 2025-11-23

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
