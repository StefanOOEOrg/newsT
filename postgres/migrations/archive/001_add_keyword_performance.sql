-- Migration: Add keyword performance tracking
-- Created: 2025-11-19
-- Description: Track which keywords are finding posts and their performance metrics

-- Create keyword_performance table
CREATE TABLE IF NOT EXISTS keyword_performance (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
    keyword VARCHAR(255) NOT NULL,
    posts_found INTEGER DEFAULT 0,
    last_found_at TIMESTAMP,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(asset_id, keyword)
);

-- Create index for better query performance
CREATE INDEX IF NOT EXISTS idx_keyword_performance_asset ON keyword_performance(asset_id);
CREATE INDEX IF NOT EXISTS idx_keyword_performance_posts ON keyword_performance(posts_found DESC);
CREATE INDEX IF NOT EXISTS idx_keyword_performance_last_found ON keyword_performance(last_found_at);

-- Add matched_keywords column to social_posts to track which keywords matched
ALTER TABLE social_posts ADD COLUMN IF NOT EXISTS matched_keywords TEXT[];

-- Create index on matched_keywords for analysis
CREATE INDEX IF NOT EXISTS idx_social_posts_matched_keywords ON social_posts USING GIN(matched_keywords);
