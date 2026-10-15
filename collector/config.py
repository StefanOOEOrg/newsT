"""
Collector configuration - enable/disable collectors here.

Instead of importing classes, we now use collector names (strings).
The factory pattern handles instantiation and dependency management.
"""

# ============================================================================
# COLLECTOR CONFIGURATION
# ============================================================================

# List of enabled collectors (by name)
# Available collectors:
#   - 'rss'                    : RSS feeds (Google News, Yahoo Finance, Seeking Alpha) - no API key needed
#   - 'newsapi'                : NewsAPI.org - requires NEWSAPI_KEY (100 calls/day free)
#   - 'finnhub'                : Finnhub.io - requires FINNHUB_API_KEY (60 calls/min free)
#   - 'alphavantage'           : Alpha Vantage - requires ALPHAVANTAGE_API_KEY (25 calls/day free, includes sentiment!)
#   - 'congressional_trades'   : Congressional trading data (House Stock Watcher + Capitol Trades) - free tier available
#   - 'stock_price'            : Stock prices from Yahoo Finance via yfinance - no API key needed
#   - 'reddit'                 : Reddit (template for future use)
#   - 'twitter'                : Twitter (template for future use)

ENABLED_COLLECTORS = [
    'rss',  # ✅ Always enabled - no API key needed

    # Financial News APIs - uncomment and add API keys to .env to enable:
    'newsapi',       # Requires NEWSAPI_KEY (100 calls/day free)
    'finnhub',       # Requires FINNHUB_API_KEY (60 calls/min free)
    'alphavantage',  # Requires ALPHAVANTAGE_API_KEY (25 calls/day free)

    # Stock Price Data:
    'stock_price',   # ✅ Enabled - fetches prices from Yahoo Finance (free, no API key)

    # Government Data - free public sources:
    'congressional_trades',  # Optional: CAPITOL_TRADES_API_KEY for enhanced data (free tier)

    # Social Media - templates for future use:
    # 'reddit',   # Requires Reddit API credentials
    # 'twitter',  # Requires Twitter API credentials
]


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Console logging level
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
CONSOLE_LOG_LEVEL = 'INFO'

# Database logging level
# Logs at this level and above will be written to the system_logs table
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
# Recommendation: Use INFO or WARNING in production to reduce database writes
DATABASE_LOG_LEVEL = 'INFO'

# Custom log format (optional)
# Default: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


# ============================================================================
# SCHEDULING CONFIGURATION
# ============================================================================

# Smart collection frequency based on market hours
# These are default values - can be overridden via database settings

# Market hours (US Eastern Time)
MARKET_OPEN_HOUR = 9    # 9:30 AM ET
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16  # 4:00 PM ET
MARKET_CLOSE_MINUTE = 0

# Collection intervals (in minutes)
COLLECTION_INTERVAL_MARKET_HOURS = 15      # Every 15 minutes during market hours
COLLECTION_INTERVAL_AFTER_HOURS = 30      # Every 30 minutes after market closes
COLLECTION_INTERVAL_WEEKENDS = 120        # Every 2 hours on weekends

# Enable smart scheduling (True) or use fixed interval (False)
ENABLE_SMART_SCHEDULING = True

# Fixed interval if smart scheduling is disabled (minutes)
COLLECTION_INTERVAL_FIXED = 30


# ============================================================================
# STOCK PRICE COLLECTION CONFIGURATION
# ============================================================================

# Stock price update interval (in minutes)
# Default: 5 minutes for near real-time price data during market hours
# Note: Can be adjusted based on needs (e.g., 1 min for high frequency, 15 min for reduced API calls)
STOCK_PRICE_UPDATE_INTERVAL_MINUTES = 5

# Stock price collection data granularity
# yfinance interval options: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
# Note: Minute intervals (1m, 2m, 5m, etc.) only available for last 60 days
# Default: "5m" - 5-minute intervals provide ~78 data points per trading day
STOCK_PRICE_INTERVAL = "5m"

# Stock price collection period per request
# yfinance period options: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
# Default: "1d" - fetches last day of data at specified interval
STOCK_PRICE_PERIOD = "1d"

# Historical data initialization (days)
# Maximum days of historical price data to load when initializing a new asset
# Note: Limited by yfinance availability (e.g., 5-min interval only available for 60 days)
# Default: 90 days (will be capped at 60 for minute intervals)
STOCK_PRICE_HISTORICAL_DAYS = 90
