"""
Dashboard configuration.
"""

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Console logging level
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
CONSOLE_LOG_LEVEL = 'INFO'

# Database logging level
# Logs at this level and above will be written to the system_logs table
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
# Recommendation: Use WARNING or ERROR for dashboard to reduce log volume
DATABASE_LOG_LEVEL = 'WARNING'

# Custom log format (optional)
# Default: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


# ============================================================================
# STOCK DATA CACHING
# ============================================================================

# Cache TTL for stock price data (seconds)
# Should match or be slightly longer than stock price collection interval
# Default: 300 seconds (5 minutes) - aligns with STOCK_PRICE_UPDATE_INTERVAL_MINUTES
STOCK_DATA_CACHE_TTL_SECONDS = 300
