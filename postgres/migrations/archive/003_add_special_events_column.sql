-- Migration: Add special_events column to ai_analysis table
-- Date: 2025-11-19

-- Add special_events column to store detected special events
ALTER TABLE ai_analysis
ADD COLUMN IF NOT EXISTS special_events TEXT[] DEFAULT ARRAY[]::TEXT[];

-- Add comment explaining the column
COMMENT ON COLUMN ai_analysis.special_events IS 'Array of detected special event types from AI analysis';
