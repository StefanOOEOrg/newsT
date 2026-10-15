# API Rate Limiting Guide

## Overview

The News Trading System includes a comprehensive rate limiting system to prevent exceeding free tier API quotas and avoid service disruptions.

## How It Works

### Architecture

1. **Database Tracking**: All API calls are logged to the `api_usage` table
2. **Rate Limit Configuration**: Each collector has configurable limits in `rate_limit_config` table
3. **Pre-Request Checking**: Before making an API call, the system checks if limits would be exceeded
4. **Automatic Enforcement**: Collectors automatically skip requests when rate limits are hit

### Components

- **`rate_limiter.py`**: Core rate limiting module in `shared/`
- **`BaseCollector`**: All collectors inherit rate limiting support
- **Database Tables**:
  - `api_usage`: Tracks every API call with timestamp and status
  - `rate_limit_config`: Stores rate limit configuration per collector
  - `api_usage_stats`: View providing real-time usage statistics

## Current Rate Limits

| Collector | Daily Limit | Hourly Limit | Per-Minute Limit | Min Interval |
|-----------|-------------|--------------|------------------|--------------|
| NewsAPICollector | 100 | - | - | 1 second |
| FinnhubCollector | - | - | 60 | 1 second |
| AlphaVantageCollector | 25 | 5 | - | 12 seconds |
| RSSCollector | - | - | - | 10 seconds |
| CongressionalTradesCollector | - | - | - | 60 seconds |

## Usage

### For Collectors

Rate limiting is automatic for all collectors inheriting from `BaseCollector`. Example:

```python
def collect_for_asset(self, asset_id, asset_name, ticker, keywords):
    # Check rate limit
    can_proceed, reason, wait_seconds = self.rate_limiter.can_make_request()

    if not can_proceed:
        logger.warning(f"Rate limit hit - {reason}")
        return []

    # Make API request
    response = requests.get(API_URL, params=params)

    # Record usage
    self.rate_limiter.record_request(
        success=True,
        status_code=response.status_code,
        api_endpoint=API_URL
    )

    return posts
```

### Monitoring Usage

**Check current usage stats:**
```sql
SELECT * FROM api_usage_stats;
```

**View detailed API usage:**
```sql
SELECT
    collector_name,
    timestamp,
    status_code,
    success,
    error_message
FROM api_usage
WHERE timestamp >= NOW() - INTERVAL '1 day'
ORDER BY timestamp DESC
LIMIT 50;
```

**Check rate limit configuration:**
```sql
SELECT * FROM rate_limit_config;
```

### Adjusting Rate Limits

**Update via SQL:**
```sql
UPDATE rate_limit_config
SET max_calls_per_day = 50,
    min_interval_seconds = 2
WHERE collector_name = 'NewsAPICollector';
```

**Update via Python:**
```python
rate_limiter = RateLimiter(database_url, 'NewsAPICollector')
rate_limiter.update_rate_limit_config(
    max_calls_per_day=50,
    min_interval_seconds=2
)
```

**Disable rate limiting for a collector:**
```sql
UPDATE rate_limit_config
SET enabled = FALSE
WHERE collector_name = 'RSSCollector';
```

## Best Practices

### 1. Optimize Collection Frequency

Instead of collecting from all collectors every 15 minutes, stagger them:

**Option A: Disable expensive collectors**
```python
# In collector/config.py
ENABLED_COLLECTORS = [
    'rss',              # Free, always enabled
    # 'newsapi',       # Disable to save quota
    # 'finnhub',       # Disable if not needed
    'alphavantage',    # Keep if using sentiment
]
```

**Option B: Reduce collection frequency in smart scheduling**
```sql
-- Increase intervals to reduce API calls
UPDATE notification_settings
SET
    collection_interval_market_hours = 30,    -- Was 15
    collection_interval_after_hours = 60,     -- Was 30
    collection_interval_weekends = 240        -- Was 120
WHERE id = 1;
```

### 2. Prioritize High-Value Assets

Focus API quota on your most important assets:

```sql
-- Mark less important assets to skip certain collectors
UPDATE asset
SET notes = 'Skip NewsAPI collection'
WHERE name IN ('LessImportantCompany1', 'LessImportantCompany2');
```

### 3. Monitor Daily Usage

Create an alert when approaching limits:

```sql
-- Check if approaching daily limit
SELECT
    collector_name,
    calls_today,
    (SELECT max_calls_per_day FROM rate_limit_config r
     WHERE r.collector_name = s.collector_name) as limit,
    ROUND((calls_today::FLOAT / NULLIF((SELECT max_calls_per_day FROM rate_limit_config r
                                        WHERE r.collector_name = s.collector_name), 0) * 100), 1) as usage_percent
FROM api_usage_stats s
WHERE (SELECT max_calls_per_day FROM rate_limit_config r
       WHERE r.collector_name = s.collector_name) IS NOT NULL
ORDER BY usage_percent DESC;
```

### 4. Batch Historical Data Collection

When adding new assets, run historical collection separately with careful rate limiting:

```bash
# Run historical collection with longer intervals
docker-compose exec collector python -c "
from collectors.newsapi_collector import NewsAPICollector
import time

collector = NewsAPICollector(os.getenv('DATABASE_URL'))
assets = collector.get_assets()

for asset in assets:
    collector.initialize_asset(asset[0], days_back=30)
    time.sleep(60)  # Wait 1 minute between assets
"
```

## Troubleshooting

### "Rate limit exceeded" even with low usage

**Cause**: Historical API calls from previous runs still count toward daily limit

**Solution**: Wait for the limit to reset (midnight UTC for daily limits) or check actual usage:

```sql
SELECT
    collector_name,
    COUNT(*) as calls_since_midnight
FROM api_usage
WHERE timestamp >= DATE_TRUNC('day', NOW())
GROUP BY collector_name;
```

### Rate limiter not working

**Check if migration was applied:**
```sql
SELECT EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_name = 'api_usage'
);
```

**Verify rate limiter is initialized:**
```python
# In collector __init__
assert hasattr(self, 'rate_limiter'), "Rate limiter not initialized"
```

### High error rates

**Check error messages:**
```sql
SELECT
    collector_name,
    error_message,
    COUNT(*) as occurrences
FROM api_usage
WHERE success = FALSE
    AND timestamp >= NOW() - INTERVAL '1 day'
GROUP BY collector_name, error_message
ORDER BY occurrences DESC;
```

## API Cost Optimization

### Free Tier Optimization Strategy

With 5 assets and 15-minute intervals during market hours:

**Without Rate Limiting:**
- NewsAPI: 5 assets × 4 calls/hour × 7 hours = **140 calls/day** ❌ (exceeds 100)
- Finnhub: 5 assets × 4 calls/hour × 7 hours = **140 calls/hour** ❌ (exceeds 60/min)
- AlphaVantage: 5 assets × 4 calls/hour × 7 hours = **140 calls/day** ❌ (exceeds 25)

**With Rate Limiting:**
- NewsAPI: Stops at 100 calls ✅
- Finnhub: Enforces 1 call/second max ✅
- AlphaVantage: Stops at 25 calls ✅

**Recommended Configuration for 5 Assets:**

1. **Keep RSS enabled** (unlimited, free)
2. **Use NewsAPI sparingly**: ~20 calls/day (4 calls × 5 assets)
3. **Use AlphaVantage for 1-2 priority assets**: 5 calls/day
4. **Disable Finnhub** or use for 1 asset only

## Advanced: Custom Rate Limiting

### Add rate limiting to custom collectors

```python
class MyCustomCollector(BaseCollector):
    def __init__(self, database_url: str):
        super().__init__(database_url)

        # Rate limiter is automatically available via BaseCollector
        # Optionally override default config
        self.rate_limiter.update_rate_limit_config(
            max_calls_per_day=50,
            min_interval_seconds=5
        )

    def collect_for_asset(self, ...):
        # Check before making external API call
        can_proceed, reason, wait_seconds = self.rate_limiter.can_make_request()

        if not can_proceed:
            logger.warning(f"Skipping due to rate limit: {reason}")
            return []

        # Make API call
        # ...

        # Record the call
        self.rate_limiter.record_request(success=True, status_code=200)
```

### Database function for custom logic

```sql
-- Add custom rate limiting rules
CREATE OR REPLACE FUNCTION check_custom_rate_limit(
    p_collector VARCHAR,
    p_asset_id INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    v_asset_priority INTEGER;
BEGIN
    -- Get asset priority
    SELECT priority INTO v_asset_priority
    FROM asset
    WHERE id = p_asset_id;

    -- High priority assets bypass some limits
    IF v_asset_priority >= 9 THEN
        RETURN TRUE;
    END IF;

    -- Regular rate limit check
    RETURN (SELECT can_proceed FROM check_rate_limit(p_collector));
END;
$$ LANGUAGE plpgsql;
```

## Dashboard Integration

View API usage in the Dashboard:

1. Go to **Settings** page
2. Scroll to "API Usage" section
3. View real-time statistics per collector
4. See remaining quota and reset times

## Summary

Rate limiting is essential for staying within free tier limits. The system automatically:

- ✅ Tracks all API calls
- ✅ Enforces configured limits
- ✅ Prevents service disruptions
- ✅ Provides visibility into usage
- ✅ Supports custom configurations

For most users, the default configuration works well with 3-5 tracked assets.
