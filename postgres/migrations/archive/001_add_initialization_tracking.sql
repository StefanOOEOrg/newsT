-- Migration: Add initialization tracking for companies
-- This allows tracking of historical data collection status

-- Add columns to companies table
ALTER TABLE companies
ADD COLUMN initialization_status VARCHAR(20) DEFAULT 'completed',
ADD COLUMN initialization_days INTEGER DEFAULT 0,
ADD COLUMN initialization_started_at TIMESTAMP,
ADD COLUMN initialization_completed_at TIMESTAMP;

-- Add comment for documentation
COMMENT ON COLUMN companies.initialization_status IS
'Status of historical data initialization: pending, in_progress, completed, failed';

COMMENT ON COLUMN companies.initialization_days IS
'Number of days of historical data to collect during initialization';

-- Update existing companies to 'completed' (they were added before this feature)
UPDATE companies
SET initialization_status = 'completed',
    initialization_completed_at = created_at
WHERE initialization_status IS NULL;

-- Create index for querying pending initializations
CREATE INDEX idx_companies_init_status ON companies(initialization_status);
