# Historical Data Initialization

This feature allows you to automatically collect historical news data when adding a new company to track, or collect additional historical data for existing companies at any time.

## Feature Overview

When adding a new company or collecting historical data for existing companies via the Dashboard Settings page, you can:
- ✅ Automatically collect historical news (up to 60 days requested)
- ✅ Get immediate baseline metrics and context
- ✅ Enable trend detection from day one
- ✅ Track initialization progress in real-time
- ✅ Re-collect historical data for existing companies at any time

**Note:** The actual number of days collected depends on the collector's API limits. For example, NewsAPI free tier supports 30 days maximum, even if you request 60 days.

## How to Use

### 1. Add Company with Historical Data

1. Go to Dashboard → **Settings** page
2. Fill in company details:
   - Company Name (e.g., "Tesla")
   - Stock Ticker (e.g., "TSLA")
   - Search Keywords (one per line)
3. Check "**Collect historical data (recommended)**"
4. Select number of days (7-60 days)
5. Click "Add Company"

The company will be added with `initialization_status = 'pending'`.

### 1b. Collect Historical Data for Existing Companies

1. Go to Dashboard → **Settings** page
2. Scroll to "Existing Companies"
3. Expand the company you want to collect data for
4. In the "📊 Collect Historical Data" section:
   - Use the slider to select days (7-60)
   - Click "📥 Collect" button
5. Click "🚀 Start Historical Data Collection Now" button at the top

This allows you to:
- Re-collect data with a different date range
- Fill in gaps in historical data
- Refresh data for companies added without historical collection

### 2. Run Historical Initialization

**Option A: Automatic (via Collector Service)**

The collector service will automatically detect pending initializations and run them on next collection cycle.

**Option B: Manual (Standalone Script)**

Run the initialization script manually:

```bash
# In the collector container
docker exec -it newstrading_collector python init_companies.py
```

Or locally:
```bash
cd collector
python init_companies.py
```

### 3. Monitor Progress

**Via Dashboard:**
- Go to Settings page
- Companies show initialization status badges:
  - 🕐 Pending - Waiting to start
  - ⏳ In Progress - Currently collecting
  - ✅ Completed - Successfully finished
  - ❌ Failed - Error occurred

**Via Logs:**
- Check collector service logs:
  ```bash
  docker-compose logs -f collector
  ```
- Or query database logs:
  ```bash
  docker exec -it newstrading_postgres psql -U trading -d newstrading -c \
    "SELECT timestamp, level, message FROM system_logs WHERE service = 'collector_init' ORDER BY timestamp DESC LIMIT 20;"
  ```

## Database Schema

### Companies Table (Updated)

```sql
ALTER TABLE companies
ADD COLUMN initialization_status VARCHAR(20) DEFAULT 'completed',
ADD COLUMN initialization_days INTEGER DEFAULT 0,
ADD COLUMN initialization_started_at TIMESTAMP,
ADD COLUMN initialization_completed_at TIMESTAMP;
```

**Status Values:**
- `pending` - Waiting for historical collection
- `in_progress` - Currently collecting data
- `completed` - Successfully finished
- `failed` - Error occurred during collection

### Migration

Run the migration script:

```bash
docker exec -it newstrading_postgres psql -U trading -d newstrading -f /docker-entrypoint-initdb.d/../migrations/001_add_initialization_tracking.sql
```

Or manually:
```bash
psql -h localhost -U trading -d newstrading -f postgres/migrations/001_add_initialization_tracking.sql
```

## Implementation Details

### BaseCollector Methods

**New Methods:**

1. **`collect_for_company_historical()`** - Override in subclasses to support historical collection
   ```python
   def collect_for_company_historical(self, company_id: int, company_name: str,
                                      ticker: str, keywords: List[str],
                                      days_back: int = 30) -> List[Dict]:
       # Implement historical data collection
       pass
   ```

2. **`initialize_company()`** - Main initialization orchestrator
   - Updates status to `in_progress`
   - Calls `collect_for_company_historical()`
   - Saves posts to database
   - Updates status to `completed` or `failed`

### Collector Support

| Collector | Historical Support | Max Days | Behavior with 60+ day requests |
|-----------|-------------------|----------|-------------------------------|
| NewsAPI | ✅ Yes | 30 | Automatically caps at 30 days with warning log |
| Finnhub | ✅ Yes | 365+ | API dependent |
| Alpha Vantage | ✅ Yes | Varies | Rate limited (25/day) |
| RSS Feeds | ❌ No | - | Only recent feeds |

**Important:** You can request up to 60 days in the UI, but each collector will automatically limit to its maximum supported range. For example, requesting 60 days with NewsAPI will collect 30 days and log a warning.

### NewsAPICollector Implementation

```python
def collect_for_company_historical(self, company_id: int, company_name: str,
                                   ticker: str, keywords: List[str],
                                   days_back: int = 30) -> List[Dict]:
    """Collect historical news from NewsAPI (max 30 days)."""
    # Free tier limit - automatically cap at 30 days
    if days_back > 30:
        logger.warning(f"NewsAPI free tier limited to 30 days, using 30 instead of {days_back}")
        days_back = 30

    # Build query
    query = ' OR '.join(f'"{part}"' for part in [company_name, ticker] + keywords[:3])

    # Date range
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    to_date = datetime.now().strftime('%Y-%m-%d')

    # API request with date range
    params = {
        'q': query,
        'from': from_date,
        'to': to_date,
        # ... other params
    }
    # Fetch and process articles
```

## Limitations

### API Limitations

**NewsAPI (Free Tier):**
- 100 requests/day
- 30 days historical maximum
- No commercial use

**Finnhub (Free Tier):**
- 60 calls/minute
- Supports longer historical ranges
- Requires API key

**Alpha Vantage (Free Tier):**
- 25 requests/day (very limited!)
- Use sparingly for initialization

### RSS Feeds

RSS feeds typically only provide recent articles (last few days to weeks). Historical collection is **not supported** for RSS-based collectors.

## Best Practices

1. **Use NewsAPI for Initialization** - Best historical support (30 days free)
2. **Stagger Additions** - Add companies one at a time to avoid rate limits
3. **Monitor Logs** - Check logs for progress and errors
4. **Be Patient** - Large historical collections may take several minutes
5. **Retry Failed** - Re-run init_companies.py if initialization fails

## Troubleshooting

### Company stuck in "Pending"

```bash
# Manually run initialization
docker exec -it newstrading_collector python init_companies.py
```

### Company status "Failed"

Check logs for error:
```sql
SELECT timestamp, message, exception
FROM system_logs
WHERE service = 'collector_init'
  AND level = 'ERROR'
ORDER BY timestamp DESC
LIMIT 10;
```

Common causes:
- Missing API key
- Rate limit exceeded
- Network error
- Invalid company data

**Reset and retry:**
```sql
UPDATE companies
SET initialization_status = 'pending',
    initialization_started_at = NULL
WHERE id = YOUR_COMPANY_ID;
```

Then run `python init_companies.py` again.

### No data collected

- Check if NewsAPI key is configured in `.env`
- Verify search keywords are relevant
- Check rate limits haven't been exceeded
- Try with fewer days (7 instead of 30)

## Example: Adding Tesla with Historical Data

1. **Via Dashboard:**
   - Name: Tesla
   - Ticker: TSLA
   - Keywords: `tesla`, `tsla`, `elon musk`
   - Historical data: ✅ (30 days)

2. **Database will show:**
   ```sql
   SELECT name, initialization_status, initialization_days
   FROM companies
   WHERE ticker = 'TSLA';
   ```
   ```
   name  | initialization_status | initialization_days
   ------|-----------------------|--------------------
   Tesla | pending               | 30
   ```

3. **Run initialization:**
   ```bash
   docker exec -it newstrading_collector python init_companies.py
   ```

4. **Results:**
   - Historical news articles collected (30 days back)
   - Status updated to `completed`
   - Articles available for AI analysis
   - Metrics generated immediately

## Future Enhancements

- [ ] Progress percentage tracking
- [ ] Batch initialization UI
- [ ] Automatic retry on failure
- [ ] Email notification on completion
- [ ] Support for custom date ranges
- [ ] Parallel initialization for multiple companies
- [ ] Integration with more data sources

## API Documentation

### Initialize Single Company (Python)

```python
from collectors.newsapi_collector import NewsAPICollector

collector = NewsAPICollector(database_url="postgresql://...")
result = collector.initialize_company(
    company_id=1,
    days_back=30
)

print(f"Collected {result['total_posts']} posts, {result['total_saved']} new")
```

### Check Pending Companies (SQL)

```sql
SELECT id, name, ticker, initialization_days, created_at
FROM companies
WHERE initialization_status = 'pending'
ORDER BY created_at;
```

### Update Initialization Status (SQL)

```sql
-- Mark as pending for retry
UPDATE companies
SET initialization_status = 'pending'
WHERE id = 4;

-- Mark as completed (skip initialization)
UPDATE companies
SET initialization_status = 'completed',
    initialization_completed_at = NOW()
WHERE id = 4;
```
