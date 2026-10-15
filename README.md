# News Trading System

**Version 1.2**

A prototype system that monitors financial news and congressional trading data to identify potential trading signals. Built with Docker, PostgreSQL, Python, and Claude AI.

## Features

- **Automated Data Collection**: Monitors RSS feeds, NewsAPI, Finnhub, Alpha Vantage, and congressional trades
- **Congressional Trading Tracker**: Track insider trading by US Congress members for early signals
- **Smart Rate Limiting**: Automatic API quota management to stay within free tier limits
- **Alert Performance Backtesting**: Track and analyze historical alert accuracy with win rates and returns
- **Historical Data Backfill**: Populate database with up to 30 days of historical data for new assets
- **Smart Market-Hours Scheduling**: Automatically adjusts collection frequency based on market hours
- **AI-Powered Analysis**: Uses Claude AI to analyze sentiment, categorize news, and extract key topics
- **Real-time Dashboard**: Streamlit-based interface with 5 pages (Overview, Detail, Alerts, Performance, Events, Settings)
- **Trading Signals**: Detects hiring trends, sentiment shifts, problems, and congressional trading patterns
- **Alerting System**: Generates alerts for significant events with confidence scores

## Architecture

The system consists of 4 Docker containers:

1. **PostgreSQL Database** (port 5432): Stores assets, news articles, AI analysis, and metrics
2. **Collector Service**: Python service that fetches news with smart market-hours-based scheduling (configurable via Settings)
3. **Analyzer Service**: Python service that analyzes articles with Claude AI every hour
4. **Dashboard**: Streamlit web interface (port 8501) for visualization

## Prerequisites

- Docker and Docker Compose
- **Anthropic API key** (REQUIRED) - [get key here](https://console.anthropic.com/)

**Data Sources** (mix and match based on your needs):

**Free RSS Feeds** (enabled by default, no API key needed):
- Google News - Asset-specific news
- Yahoo Finance - Stock ticker news
- Seeking Alpha - Financial analysis

**Optional Premium APIs** (add API keys to unlock):
- **NewsAPI** - 100 requests/day free - [get key](https://newsapi.org/register)
- **Finnhub** - 60 calls/minute free - [get key](https://finnhub.io/register)
- **Alpha Vantage** - 25 calls/day free with sentiment scores! - [get key](https://www.alphavantage.co/support/#api-key)

**Government Data Sources** (free public data):
- **Congressional Trades** - Track insider trading by US Congress members from [House Stock Watcher](https://housestockwatcher.com) (free, no API key needed)

## Quick Start

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd newsT
```

### 2. Set up environment variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```env
DATABASE_URL=postgresql://trading:trading123@postgres:5432/newstrading

# Get from https://console.anthropic.com/
ANTHROPIC_API_KEY=your_anthropic_key
```

### 3. Start the system

```bash
docker-compose up --build
```

This will:
- Build all Docker images
- Start PostgreSQL and initialize the database schema
- Start the collector service (smart scheduling: 15min during market hours, 30min after hours, 2h on weekends)
- Start the analyzer service (runs every 5 minutes)
- Start the dashboard on http://localhost:8501

### 4. Access the dashboard

Open your browser and navigate to:

```
http://localhost:8501
```

## Getting API Credentials

### Anthropic API (Required)

1. Go to https://console.anthropic.com/
2. Sign up or log in
3. Navigate to API Keys
4. Create a new API key
5. Copy the key (starts with `sk-ant-`)
6. Add to `.env`: `ANTHROPIC_API_KEY=sk-ant-...`

### Optional Data Source APIs

#### NewsAPI (100 requests/day free)
1. Go to https://newsapi.org/register
2. Sign up for a free account
3. Copy your API key
4. Add to `.env`: `NEWSAPI_KEY=your_key`
5. Enable in `collector/config.py`: Uncomment `NewsAPICollector`

#### Finnhub (60 calls/minute free)
1. Go to https://finnhub.io/register
2. Sign up for a free account
3. Copy your API key
4. Add to `.env`: `FINNHUB_API_KEY=your_key`
5. Enable in `collector/config.py`: Uncomment `FinnhubCollector`

#### Alpha Vantage (25 calls/day free + sentiment!)
1. Go to https://www.alphavantage.co/support/#api-key
2. Get your free API key
3. Add to `.env`: `ALPHAVANTAGE_API_KEY=your_key`
4. Enable in `collector/config.py`: Uncomment `AlphaVantageCollector`

#### Congressional Trades (Free - No API Key Required)
1. **Works out of the box** using House Stock Watcher public data
2. Already enabled by default in `collector/config.py`
3. No configuration needed - data collection starts automatically

**Alternative premium APIs** (if you need enhanced data):
- [Benzinga Government Trades API](https://www.benzinga.com/apis/cloud-product/government-trades/)
- [Financial Modeling Prep Senate Trading API](https://site.financialmodelingprep.com/developer/docs/senate-trading-api)

**Why Congressional Trades?**
- Track insider trading by US Congress members
- Detect early signals before major stock movements
- Identify potential conflicts of interest
- Free, public data from official government disclosures (STOCK Act 2012)

### Enabling/Disabling Collectors

Edit `collector/config.py` to enable or disable collectors:

```python
ENABLED_COLLECTORS = [
    'rss',                    # ✅ Always enabled (no API key needed)
    'newsapi',                # Requires NEWSAPI_KEY
    'finnhub',                # Requires FINNHUB_API_KEY
    'alphavantage',           # Requires ALPHAVANTAGE_API_KEY
    'congressional_trades',   # ✅ Enabled by default (works without API key)
    # 'reddit',               # Requires Reddit API credentials (future)
    # 'twitter',              # Requires Twitter API credentials (future)
]
```

## Usage

### Dashboard Pages

1. **Overview**: View all assets with recent metrics and sentiment
2. **Asset Detail**: Deep dive into a specific asset with charts and recent posts
3. **Alerts**: View generated alerts filtered by asset and type
4. **Settings**: Add new assets to track and view system status

### Adding New Assets

1. Navigate to the Settings page
2. Fill in the form:
   - Asset Name: Full company name (e.g., "Tesla")
   - Stock Ticker: Trading symbol (e.g., "TSLA")
   - Search Keywords: One per line (e.g., "tesla", "tsla", "elon musk")
3. Click "Add Asset"

The collector will start gathering posts for the new asset on its next run.

### Historical Data Backfill

When you add a new asset or want to populate historical data, use the backfill script:

```bash
# Backfill 30 days of data for all assets (default)
docker-compose exec collector python backfill.py

# Backfill 7 days for a specific asset (by ID)
docker-compose exec collector python backfill.py --assets 1 --days 7

# Backfill for specific assets with specific collectors
docker-compose exec collector python backfill.py --assets 1,2,3 --collectors NewsAPICollector

# View help and all options
docker-compose exec collector python backfill.py --help
```

**Available Options:**
- `--days DAYS`: Number of days to backfill (default: 30)
- `--assets IDS`: Comma-separated asset IDs (default: all assets)
- `--collectors NAMES`: Comma-separated collector names (default: all enabled)

**Important Notes:**
- NewsAPI free tier supports 30 days of historical data
- RSS feeds don't support historical collection (only current feed items)
- After backfilling, restart the analyzer to process new posts immediately:
  ```bash
  docker-compose restart analyzer
  ```

**Example Workflow:**
```bash
# 1. Add a new asset in the Dashboard Settings page
# 2. Find the asset ID (shown in the asset list)
# 3. Backfill 30 days of historical data
docker-compose exec collector python backfill.py --assets 8 --days 30

# 4. Trigger immediate analysis
docker-compose restart analyzer

# 5. View results in the Dashboard
```

### Configuring Collection Schedule

The collector automatically adjusts collection frequency based on market hours. You can customize this in the Settings page:

1. Navigate to the **Settings** page
2. Expand "**Configure News Collection Frequency**"
3. Choose your scheduling mode:
   - **Smart Scheduling** (recommended): Automatically adjusts based on market hours
     - During market hours (9:30 AM - 4:00 PM ET): Collect every 15 minutes
     - After market hours: Collect every 30 minutes
     - Weekends: Collect every 2 hours
   - **Fixed Interval**: Use the same collection frequency at all times
4. Customize intervals and market hours as needed
5. Click "Save All Settings"

The collector will automatically reload settings and adjust its schedule on the next collection run.

## Project Structure

```
newsT/
├── docker-compose.yml          # Docker services configuration
├── .env.example                # Environment variables template
├── postgres/
│   └── init.sql               # Database schema and sample data
├── collector/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                # RSS news collector
├── analyzer/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                # AI analysis service
└── dashboard/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py                 # Streamlit dashboard
```

## Database Schema

- **assets**: Assets to track with search keywords
- **social_posts**: Raw social media posts
- **ai_analysis**: AI-generated sentiment and category analysis
- **daily_metrics**: Aggregated daily statistics per asset
- **alerts**: Generated alerts for unusual activity
- **system_logs**: Application logs from all services (structured logging)

## Development

### Running services individually

```bash
# Start only the database
docker-compose up postgres

# Start collector
docker-compose up collector

# Start analyzer
docker-compose up analyzer

# Start dashboard
docker-compose up dashboard
```

### Viewing logs

**Option 1: Docker logs (Console output)**

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f collector
docker-compose logs -f analyzer
docker-compose logs -f dashboard
```

**Option 2: Database logs (via Dashboard)**

Open the dashboard at http://localhost:8501 and navigate to "System Logs" page to view:
- Structured logs from all services
- Filter by service, log level, and time range
- Search through log messages
- View exceptions and metadata
- Auto-refresh for real-time monitoring

**Option 3: Database query**

```bash
docker exec -it newst-postgres-1 psql -U trading -d newstrading -c \
  "SELECT timestamp, service, level, message FROM system_logs ORDER BY timestamp DESC LIMIT 20;"
```

### Stopping the system

```bash
docker-compose down
```

### Resetting the database

```bash
docker-compose down -v  # Removes volumes
docker-compose up --build
```

## Testing

The project includes a comprehensive test suite with unit tests for all collector modules.

### Running Tests

**Recommended: Docker (no local setup required):**
```bash
# Run all tests in Docker container
./test-docker.sh

# Run with coverage report
./test-docker.sh --coverage

# Run with extra verbose output
./test-docker.sh -vv

# Run specific test file
./test-docker.sh tests/test_collectors/test_base_collector.py
```

**Using Make (runs in Docker):**
```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run verbose
make test-verbose

# Check code quality
make lint
make format
make check  # Run all checks (lint, type-check, test)
```

**Local execution (requires venv and dependencies):**
```bash
# Setup (first time only)
python3 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt

# Run tests
pytest tests/test_collectors/ -v

# Run with coverage
pytest tests/test_collectors/ --cov --cov-report=html

# Or use make
make test-local
```

### Test Structure

```
tests/
├── conftest.py                      # Pytest fixtures and mocks
├── test_collectors/
│   ├── test_base_collector.py      # BaseCollector tests (15 tests)
│   ├── test_rss_collector.py       # RSSCollector tests (13 tests)
│   └── test_collector_factory.py   # Factory pattern tests (13 tests)
└── README.md                        # Detailed testing guide
```

### CI/CD

Tests run automatically on:
- Push to `main` or `develop` branches
- Pull requests

See `.github/workflows/test.yml` for configuration.

### Coverage

Target: 80%+ code coverage

View coverage report:
```bash
make test-coverage
open htmlcov/index.html  # Opens in browser
```

For more details, see [tests/README.md](tests/README.md).

## Configuration

### Logging Configuration

The system includes a comprehensive logging framework with configurable log levels. Logs are written to both console (stdout) and database (`system_logs` table).

**Collector Configuration** (`collector/config.py`):
```python
CONSOLE_LOG_LEVEL = 'INFO'     # Console output level
DATABASE_LOG_LEVEL = 'INFO'    # Database logging level
```

**Analyzer Configuration** (`analyzer/config.py`):
```python
CONSOLE_LOG_LEVEL = 'INFO'
DATABASE_LOG_LEVEL = 'INFO'
```

**Dashboard Configuration** (`dashboard/config.py`):
```python
CONSOLE_LOG_LEVEL = 'INFO'
DATABASE_LOG_LEVEL = 'WARNING'  # Less verbose for dashboard
```

**Available Log Levels** (from most to least verbose):
- `DEBUG`: Detailed diagnostic information
- `INFO`: General informational messages (default)
- `WARNING`: Warning messages for potentially problematic situations
- `ERROR`: Error messages for failures
- `CRITICAL`: Critical errors that may cause system failure

**Best Practices**:
- **Development**: Use `DEBUG` for console, `INFO` for database
- **Production**: Use `INFO` for console, `WARNING` for database (reduces DB writes)
- **Troubleshooting**: Temporarily set both to `DEBUG`

### Collector Configuration

Enable/disable data sources in `collector/config.py`:

```python
ENABLED_COLLECTORS = [
    'rss',          # Always enabled - no API key needed
    # 'newsapi',    # Uncomment after adding NEWSAPI_KEY to .env
    # 'finnhub',    # Uncomment after adding FINNHUB_API_KEY to .env
    # 'alphavantage', # Uncomment after adding ALPHAVANTAGE_API_KEY to .env
]
```

## How It Works

### 1. Data Collection

The collector service:
- Fetches news articles from RSS feeds every 30 minutes
- Sources: Google News, Yahoo Finance, Seeking Alpha
- Searches for asset keywords and ticker symbols
- Stores new articles in the database
- Handles duplicate detection via URL hashing

### 2. AI Analysis

The analyzer service:
- Processes unanalyzed posts every 5 minutes
- Calls Claude AI to determine:
  - Sentiment (positive/negative/neutral) with score -1 to 1
  - Category (Hiring/Growth/Problems/Product/Earnings/Other)
  - Key topics and brief summary
- Stores analysis results
- Updates daily metrics
- Generates alerts for significant events

### 3. Alert Generation

Alerts are generated for:
- **Hiring Signals**: Positive hiring-related posts (potential growth indicator)
- **Negative Sentiment**: Strong negative sentiment (< -0.7)
- **Problem Detection**: Posts about problems with negative sentiment

### 4. Dashboard

The Streamlit dashboard provides:
- Real-time metrics and visualizations
- Historical trend analysis
- Post-level detail with AI analysis
- Alert monitoring
- Asset management

## Example Use Case: Genpact

The system is pre-configured to track Genpact (ticker: G) for hiring signals:

1. Collector finds news articles mentioning "genpact", "hiring", or "job opening"
2. Analyzer processes articles and identifies hiring-related content
3. System generates alerts when hiring activity increases
4. Dashboard shows trends that may correlate with stock movements

This same approach can be applied to any asset and signal type.

**News Sources:**
- **Google News**: Asset-specific news from past 7 days
- **Yahoo Finance**: Stock-specific news by ticker
- **Seeking Alpha**: Financial analysis and insights

## Troubleshooting

### Collector not finding articles

- Verify RSS feeds are accessible (Google News, Yahoo Finance, Seeking Alpha)
- Check internet connection
- Check logs: `docker-compose logs collector`
- Some feeds may be temporarily unavailable - the collector will skip and continue

### Analyzer not processing posts

- Check Anthropic API key in `.env`
- Verify API quota/limits
- Check logs: `docker-compose logs analyzer`

### Dashboard not loading

- Ensure port 8501 is not in use
- Check database connection
- Check logs: `docker-compose logs dashboard`

### Database connection errors

- Ensure PostgreSQL container is healthy
- Check DATABASE_URL in `.env`
- Wait for database initialization (may take 10-20 seconds on first run)

## Limitations

This is a prototype system with the following limitations:

- RSS feeds only (can be extended to APIs, Twitter, etc.)
- Simple alerting logic (can be enhanced with ML models)
- No backtesting or performance tracking
- No actual trading execution (signals only)
- Depends on RSS feed availability

## Future Enhancements

- Add more data sources (Twitter, financial news, SEC filings)
- Implement backtesting to validate signals
- Add more sophisticated alert algorithms
- Integrate with trading platforms
- Add email/SMS notifications
- Implement caching and performance optimizations
- Add user authentication and multi-tenancy

## License

MIT License - feel free to use and modify for your own projects.

## Disclaimer

This is a prototype for educational purposes. Always do your own research before making investment decisions. Past performance does not guarantee future results. Trading carries risk of financial loss.
