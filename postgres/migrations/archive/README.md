# Archived Migration Files

These migration files have been consolidated into the main schema file (`/postgres/schema.sql`) as of 2025-11-21.

## Archived Migrations

### 001_add_initialization_tracking.sql
- Added initialization tracking columns to companies table
- Columns: initialization_status, initialization_days, initialization_started_at, initialization_completed_at
- Added index: idx_companies_init_status

### 001_add_notifications.sql
- Added notification system tables and columns
- Added notified and notified_at columns to alerts table
- Created alert_notification_preferences table
- Created notification_log table
- Added related indexes

### 001_add_keyword_performance.sql
- Created keyword_performance table to track keyword effectiveness
- Added matched_keywords column to social_posts table
- Added GIN index on matched_keywords
- Note: References asset_id which should be company_id (handled in consolidated schema)

### 002_add_special_events_to_prompt.sql
- Updated analysis_prompt in notification_settings to include special event detection
- Added detection for: partnerships, product launches, regulatory risks, analyst upgrades/downgrades, etc.

### 003_add_special_events_column.sql
- Added special_events TEXT[] column to ai_analysis table
- Stores detected special events from AI analysis

### 004_add_collection_schedule_settings.sql
- Added collection scheduling columns to notification_settings
- Fields: enable_smart_scheduling, collection intervals for different time periods, market hours settings

## Consolidated Schema

All these changes have been merged into `/postgres/schema.sql`, which is now the single source of truth for the database schema. The init.sql file now simply sources schema.sql.

## Why Consolidated?

- Easier to understand the full database structure
- No need to apply migrations sequentially
- Cleaner deployment process
- Single file for schema documentation
- Reduced complexity for new developers

## If You Need to Reference Old Migrations

These files are kept for historical reference. If you need to understand when a feature was added or how the schema evolved, you can review these files. However, for creating a new database, always use the consolidated schema.sql file.
