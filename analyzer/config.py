"""
Analyzer configuration.
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
# Recommendation: Use INFO or WARNING in production to reduce database writes
DATABASE_LOG_LEVEL = 'INFO'

# Custom log format (optional)
# Default: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


# ============================================================================
# AI MODEL CONFIGURATION
# ============================================================================

# Claude API model to use for analysis
# Options: claude-sonnet-4-5-20250929, claude-opus-4-20250514, claude-3-5-haiku-20241022
# Haiku is 3x cheaper ($1/$5 vs $3/$15 per million tokens) and sufficient for structured analysis
AI_MODEL = 'claude-3-5-haiku-20241022'

# Maximum tokens for Claude API responses
# Recommendation: 512 for TOON responses (40-60% less than JSON), 1024 for longer summaries
# TOON format is more token-efficient than JSON, reducing both input prompts and output responses
MAX_TOKENS = 512


# ============================================================================
# CONTENT PROCESSING
# ============================================================================

# Maximum length of post content to analyze (characters)
# Longer content will be truncated to stay within API limits
CONTENT_MAX_LENGTH = 2000

# Maximum length of summary in alert descriptions (characters)
ALERT_SUMMARY_MAX_LENGTH = 180


# ============================================================================
# ANALYSIS CONFIGURATION
# ============================================================================

# Required fields in AI analysis response
REQUIRED_ANALYSIS_FIELDS = ['sentiment', 'sentiment_score', 'category', 'key_topics', 'summary', 'special_events']

# Valid sentiment values
VALID_SENTIMENTS = ['positive', 'negative', 'neutral']

# Valid category values
VALID_CATEGORIES = ['Hiring', 'Growth', 'Problems', 'Product', 'Earnings', 'Other']

# Categories that are considered bullish/long signals
BULLISH_CATEGORIES = ['Hiring', 'Growth', 'Earnings', 'Product']

# Categories that are considered bearish/short signals
BEARISH_CATEGORIES = ['Problems']

# Valid special event types
VALID_SPECIAL_EVENTS = [
    'partnership_announced',
    'product_launch',
    'regulatory_risk',
    'analyst_upgrade',
    'analyst_downgrade',
    'market_share_gain',
    'customer_loss',
    'executive_change',
    'guidance_raise',
    'guidance_cut',
    'insider_buying',
    'insider_selling'
]

# Event severity and type mapping
# Each event maps to (alert_type, default_severity, is_bullish)
EVENT_ALERT_CONFIG = {
    'partnership_announced': ('partnership', 'medium', True),
    'product_launch': ('product_launch', 'medium', True),
    'regulatory_risk': ('regulatory_risk', 'high', False),
    'analyst_upgrade': ('analyst_upgrade', 'medium', True),
    'analyst_downgrade': ('analyst_downgrade', 'medium', False),
    'market_share_gain': ('market_share', 'medium', True),
    'customer_loss': ('customer_loss', 'medium', False),
    'executive_change': ('executive_change', 'medium', None),  # Neutral - depends on context
    'guidance_raise': ('guidance', 'high', True),
    'guidance_cut': ('guidance', 'high', False),
    'insider_buying': ('insider_trading', 'low', True),
    'insider_selling': ('insider_trading', 'low', False),
}


# ============================================================================
# ALERT THRESHOLDS
# ============================================================================

# Short signal (bearish) thresholds
# Sentiment scores below these values trigger short signals with different severity levels
SHORT_SIGNAL_THRESHOLD = -0.3          # Minimum sentiment to trigger any short signal
SHORT_SIGNAL_LOW_THRESHOLD = -0.3      # Weak short signal
SHORT_SIGNAL_MEDIUM_THRESHOLD = -0.5   # Moderate short signal
SHORT_SIGNAL_HIGH_THRESHOLD = -0.7     # Strong short signal

# Special threshold for problem category (more sensitive)
SHORT_SIGNAL_PROBLEM_MEDIUM = -0.4     # Problems at -0.4 → medium severity
SHORT_SIGNAL_PROBLEM_HIGH = -0.5       # Problems at -0.5 → high severity

# Long signal (bullish) thresholds
# Sentiment scores above these values trigger long signals with different severity levels
LONG_SIGNAL_THRESHOLD = 0.3            # Minimum sentiment to trigger any long signal
LONG_SIGNAL_LOW_THRESHOLD = 0.3        # Weak long signal
LONG_SIGNAL_MEDIUM_THRESHOLD = 0.5     # Moderate long signal
LONG_SIGNAL_HIGH_THRESHOLD = 0.7       # Strong long signal


# ============================================================================
# BATCH PROCESSING
# ============================================================================

# Number of posts to process in each batch
# Larger batches are faster but use more API quota
BATCH_SIZE = 50

# Pause between batches (seconds) for rate limiting
# Increase if hitting rate limits
BATCH_SLEEP_SECONDS = 30


# ============================================================================
# SCHEDULING
# ============================================================================

# How often to run analysis (minutes)
# The analyzer processes all pending posts in batches
ANALYSIS_INTERVAL_MINUTES = 5


# ============================================================================
# PRICE TRACKING CONFIGURATION
# ============================================================================

# Intervals to track price changes after an alert (days)
# These determine which price points are fetched for alert performance tracking
# Default: [1, 3, 7, 14, 30] - tracks 1-day, 3-day, 7-day, 14-day, and 30-day returns
ALERT_PRICE_TRACKING_DAYS = [1, 3, 7, 14, 30]

# Date buffer for finding closest trading day (days)
# When looking for a price on a specific date, search within +/- this many days
# to handle weekends/holidays
# Default: 7 days
PRICE_DATE_BUFFER_DAYS = 7

# Maximum allowed date difference (days)
# If the closest trading day is more than this many days away, return None
# Default: 7 days
PRICE_MAX_DATE_DIFF_DAYS = 7

# Price movement threshold for directional classification
# Absolute return below this threshold is considered 'neutral'
# Default: 0.005 (0.5%)
PRICE_DIRECTION_THRESHOLD = 0.005
