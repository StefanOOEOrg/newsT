# Feature Ideas

This document contains ideas for future features and improvements to the news trading system.

## Next
- the logging page shows only loggings for warnings if warnings are selected and not loglevel warning and above. so understand and handle log level als levels
- I'd like to be able to lear the log
- fix latest errors in log

## Backlog

### 1. Historical Initialization for New Companies

**Description:**
When adding a new asset to track, perform an initial analysis of historical data (e.g., last 6 months) instead of only collecting data going forward.

**Use Case:**
- User adds a new stock to monitor
- System automatically fetches and analyzes the past 6 months of news
- Provides immediate baseline metrics and historical context
- Enables trend detection from day one

**Implementation Ideas:**
- Add "initialization mode" flag when adding new asset via Settings page
- Modify collectors to support date range queries (where API supports it)
- Batch process historical articles with progress tracking
- Generate initial daily_metrics for the historical period
- Display initialization progress in dashboard

**API Considerations:**
- NewsAPI: Supports 30 days historical (free tier)
- Finnhub: Supports custom date ranges
- Alpha Vantage: Limited by daily quota (25 calls/day)
- RSS: Limited to recent feeds only

---

### 2. Event-Driven Analysis

**Description:**
Prioritize analysis based on upcoming events (e.g., earnings reports, product launches, regulatory filings) rather than purely time-based collection.

**Use Case:**
- Earnings report scheduled for asset X next week
- System increases collection frequency leading up to the event
- Alerts trigger based on event context (e.g., "Negative sentiment spike 2 days before earnings")
- Post-event analysis compares pre/post sentiment

**Implementation Ideas:**

#### 2.1 Event Calendar Collector ✅ **Implemented** (November 2025)

**Status:** Complete
- ✅ Created `EventCollector` base class for fetching financial events
- ✅ Implemented Alpha Vantage Earnings Calendar collector
- ✅ Created `asset_events` table with proper indexing
- ✅ Added event display in Dashboard Settings page with icons and metadata
- ✅ Events shown in chronological order with expandable cards
- ✅ Collection script: `collect_events.py` with rate limit tracking
- ✅ Test data populated successfully

**Data sources implemented:**
- ✅ Alpha Vantage: Earnings Calendar API (25 calls/day free tier)

**Data sources for future implementation:**
- Yahoo Finance Calendar: https://finance.yahoo.com/calendar
- SEC EDGAR: Filing deadlines

**Database schema:**
```sql
CREATE TABLE asset_events (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES asset(id),
    event_type VARCHAR(50),  -- 'earnings', 'product_launch', 'conference', etc.
    event_date DATE NOT NULL,
    event_time TIME,
    description TEXT,
    url TEXT,
    source VARCHAR(100),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Usage:**
```bash
# Collect events from all available sources
docker-compose exec collector python collect_events.py

# Collect from specific source
docker-compose exec collector python collect_events.py --collectors AlphaVantageEventsCollector
```

#### 2.2 Event Schema
```sql
CREATE TABLE asset_events (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER REFERENCES companies(id),
    event_type VARCHAR(50),  -- 'earnings', 'product_launch', 'filing', etc.
    event_date DATE NOT NULL,
    description TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 2.3 Event-Aware Collection
- Adjust collection frequency based on event proximity
- Example:
  - Normal: every 6 hours
  - 7 days before event: every 2 hours
  - Day of event: every 30 minutes
  - 3 days after event: every 2 hours

#### 2.4 Event Context in Analysis
- Pass event context to AI analyzer
- Example prompt enhancement: "Analyze this article in the context of asset X's upcoming earnings report on Nov 20, 2025"
- Generate event-specific alerts

#### 2.5 Dashboard Enhancements ✅ **Implemented** (November 2025)

**Status:** Complete
- ✅ Created dedicated Events page ([events.py](dashboard/pages/events.py:1))
- ✅ Event timeline visualization with Plotly showing all events by type and date
- ✅ Calendar view with filtering by time range and event type
- ✅ Event detail analysis showing:
  - News coverage charts (volume over time with event date marker)
  - Recent articles list with sentiment indicators
  - Sentiment trends pre/post event (14 days before, 7 days after)
  - Pre-event, event-day, and post-event sentiment metrics
  - Alert history around event with timing context
- ✅ Interactive event cards grouped by date with time indicators
- ✅ Session state management for event detail view
- ✅ Color-coded event types (earnings, product_launch, conference, etc.)

**Features Implemented:**
- Timeline chart with event type grouping and ticker labels
- Time range filters: Next 7/30/90 Days, All Upcoming, Past & Upcoming
- Event type multiselect filter
- Expandable event cards with metadata display
- "View Analysis" button for detailed event breakdown
- News volume chart with event date vertical line
- Sentiment score line graph with neutral reference
- Sentiment delta calculation (post vs pre-event)
- Alert timeline with relative timing (X days before/after event)

**Technical Challenges:**
- Rate limiting when increasing collection frequency
- Event date accuracy and timezone handling
- Determining event relevance/importance
- Avoiding false positives from event speculation

---

## 3. Alert System Enhancements

**Description:**
Improvements to the alert system to make it more actionable and valuable for trading decisions.

### 3.1 Alert Aggregation & Clustering

**Use Case:**
Multiple alerts of the same type within a short time window create a "mega signal" with higher confidence.

**Implementation:**
```python
# Detect alert clusters
if count_alerts(type='hiring_signal', asset_id=X, window='24h') >= 3:
    create_meta_alert(
        type='hiring_cluster',
        confidence=0.95,
        description='3+ hiring signals in 24h - Strong expansion indication'
    )
```

**Benefits:**
- Stronger signal confirmation
- Reduces noise from single alerts
- Higher confidence for position sizing

**Example:**
- 3 hiring alerts for Genpact in 24h → Strong buy signal before earnings

### 3.2 Email/SMS/Push Notifications

**Use Case:**
Get notified immediately when high-confidence alerts are generated, even when not watching the dashboard.

**Implementation Options:**
- **Email**: SendGrid, AWS SES, SMTP
- **SMS**: Twilio
- **Push**: Pushover, Telegram Bot, Discord
- **Webhook**: Custom HTTP endpoints

**Features:**
- Configurable thresholds (e.g., only alerts with confidence > 0.85)
- Per-asset subscriptions
- Quiet hours (no notifications 22:00-07:00)
- Daily digest email option

**Schema Addition:**
```sql
CREATE TABLE user_alert_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    asset_id INTEGER REFERENCES companies(id),
    alert_type VARCHAR(50),
    min_confidence DECIMAL(3,2),
    notification_channels TEXT[], -- ['email', 'sms', 'push']
    quiet_hours_start TIME,
    quiet_hours_end TIME
);
```

### 3.3 Alert Backtesting & Performance Tracking

**Status:** ✅ Complete
**Completed:** November 2025

**Use Case:**
Validate alert quality by analyzing historical performance.

**Implemented Features:**
- ✅ Database schema with alert_performance table
- ✅ Price fetching module using yfinance
- ✅ Performance tracker service with scheduled daily updates
- ✅ Dashboard page with comprehensive metrics and charts
- ✅ Win rate calculation (7-day primary metric)
- ✅ Performance breakdown by alert type and asset
- ✅ Cumulative returns visualization
- ✅ Confidence threshold optimizer
- ✅ Multi-timeframe tracking (1, 3, 7, 14, 30 days)

**Metrics Tracked:**
- Stock price movement after alert (+1, +3, +7, +14, +30 days)
- Alert accuracy (win rate) by comparing predicted vs actual direction
- Best performing alert types
- Performance by asset
- Average returns per timeframe
- Cumulative ROI simulation

**Implementation:**
```sql
CREATE TABLE alert_performance (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id),
    price_at_alert DECIMAL(10,2),
    price_1d_later DECIMAL(10,2),
    price_3d_later DECIMAL(10,2),
    price_7d_later DECIMAL(10,2),
    return_1d DECIMAL(5,2),
    return_3d DECIMAL(5,2),
    return_7d DECIMAL(5,2),
    predicted_direction VARCHAR(10), -- 'bullish', 'bearish'
    actual_direction VARCHAR(10),
    accuracy BOOLEAN
);
```

**Dashboard View:**
- Alert Performance Table showing win rates by type
- Historical ROI chart ("If you traded all alerts...")
- Best/Worst performing companies
- Confidence threshold optimizer

**Example Analysis:**
```sql
SELECT
    alert_type,
    AVG(return_7d) as avg_7d_return,
    COUNT(*) as total_alerts,
    SUM(CASE WHEN return_7d > 0 THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as win_rate
FROM alert_performance
WHERE confidence_score > 0.80
GROUP BY alert_type;

-- Result:
-- hiring_signal     | +8.3%  | 23 | 78.3%
-- problem_detected  | -5.7%  | 15 | 73.3%
-- negative_sentiment| -3.2%  | 31 | 64.5%
```

### 3.4 Multi-Factor Alert Scoring

**Use Case:**
Combine multiple factors to create a composite alert score (0-100) for easier decision-making.

**Scoring Factors:**
1. **AI Confidence** (30%) - Claude's confidence score
2. **Timing** (20%) - Before earnings = higher score
3. **Historical Performance** (25%) - Backtested win rate
4. **Alert Clustering** (15%) - Multiple alerts boost score
5. **Source Quality** (10%) - Official PR > Reddit post

**Formula:**
```python
def calculate_alert_score(alert):
    confidence_score = alert.confidence * 0.30

    # Timing: Higher score if within 7 days of earnings
    days_to_earnings = get_days_to_next_earnings(alert.asset_id)
    timing_score = max(0, (7 - days_to_earnings) / 7) * 0.20 if days_to_earnings <= 7 else 0

    # Historical: Use backtested win rate for this alert type
    hist_score = get_win_rate(alert.alert_type, alert.asset_id) * 0.25

    # Clustering: Bonus if 2+ similar alerts in 48h
    cluster_count = count_recent_alerts(alert.alert_type, alert.asset_id, hours=48)
    cluster_score = min(cluster_count / 3, 1.0) * 0.15

    # Source: Official sources score higher
    source_score = 1.0 if alert.source_type == 'official' else 0.5
    source_score *= 0.10

    total_score = (confidence_score + timing_score + hist_score + cluster_score + source_score) * 100
    return round(total_score, 1)
```

**Display:**
- Alert score badge (0-100)
- Color-coded:
  - Green (80-100): Strong signal, high priority
  - Yellow (60-79): Moderate signal
  - Red (0-59): Weak signal, monitor only

### 3.5 Alert Correlation Analysis

**Use Case:**
Statistical analysis to understand which alerts actually predict stock movements.

**Analysis Types:**
- Correlation between hiring alerts and 7-day returns
- Lead time analysis (alerts appear X days before price moves)
- Sector-specific performance (tech vs healthcare)
- Market regime impact (bull market vs bear market)

**Example Insights:**
```
"Hiring alerts for tech companies correlate with +8.3% avg return
after 5 days during bull markets (p<0.05, n=47)"

"Problem alerts have 72% accuracy for predicting >5% drops
within 3 days (95% CI: 64%-80%)"

"Negative sentiment alerts are 2.3x more accurate when
combined with technical breakdown signals"
```

**Implementation:**
- Periodic batch job (weekly) runs statistical tests
- Stores insights in `alert_insights` table
- Displays in "Alert Analytics" dashboard section

---

## 4. Additional Alert Types

**Status:** ✅ Complete
**Priority:** High
**Effort:** Medium
**Completed:** November 2025

**Description:**
Expand beyond the current 2 basic alert types (long_signal, short_signal) to cover specific trading-relevant events.

**Implemented Alert Types:**

| Alert Type | Description | Trading Implication | Severity |
|------------|-------------|---------------------|----------|
| `insider_trading` | Insider buys/sells detected | Bullish if buying, bearish if selling | Low |
| `partnership` | Strategic partnerships | Potentially bullish | Medium |
| `product_launch` | Major product releases | Bullish if well-received | Medium |
| `regulatory_risk` | FDA rejection, SEC investigation | Very bearish | High |
| `analyst_upgrade` | Analyst upgrades | Bullish | Medium |
| `analyst_downgrade` | Analyst downgrades | Bearish | Medium |
| `market_share` | Market share gains | Bullish | Medium |
| `customer_loss` | Major customer churn | Bearish | Medium |
| `executive_change` | CEO/CFO departure/hire | Depends on context | Medium |
| `guidance` | Guidance raises or cuts | Very bullish/bearish | High |

**Implemented Features:**
- ✅ Enhanced AI analysis prompt to detect 12 special event types
- ✅ Added `special_events` field to AI analysis schema
- ✅ Updated `AlertGenerator` to create event-specific alerts
- ✅ Severity adjustment based on sentiment strength
- ✅ Human-readable alert descriptions per event type
- ✅ Database schema updated to store special_events in `ai_analysis` table
- ✅ Event configuration mapping in `config.py` with alert types, severities, and directionality

**Implementation Details:**
```python
# analyzer/config.py - Event configuration
EVENT_ALERT_CONFIG = {
    'partnership_announced': ('partnership', 'medium', True),
    'product_launch': ('product_launch', 'medium', True),
    'regulatory_risk': ('regulatory_risk', 'high', False),
    'analyst_upgrade': ('analyst_upgrade', 'medium', True),
    'analyst_downgrade': ('analyst_downgrade', 'medium', False),
    'market_share_gain': ('market_share', 'medium', True),
    'customer_loss': ('customer_loss', 'medium', False),
    'executive_change': ('executive_change', 'medium', None),
    'guidance_raise': ('guidance', 'high', True),
    'guidance_cut': ('guidance', 'high', False),
    'insider_buying': ('insider_trading', 'low', True),
    'insider_selling': ('insider_trading', 'low', False),
}

# analyzer/analysis_helpers.py - Alert generation
class AlertGenerator:
    def _generate_special_event_alerts(self, cur, analysis, special_events, sentiment):
        for event in special_events:
            alert_type, default_severity, is_bullish = EVENT_ALERT_CONFIG[event]
            severity = self._adjust_event_severity(default_severity, sentiment, is_bullish)
            description = self._format_event_description(event, analysis['summary'])
            # Insert alert with event-specific type and severity
```

**Benefits:**
- ✅ More granular and actionable trading alerts
- ✅ Better signal-to-noise ratio with event categorization
- ✅ Automatic severity adjustment based on sentiment
- ✅ Enhanced decision-making with specific event context
- ✅ Future-ready for event-specific backtesting and performance tracking

---

## 5. Real-Time Price Integration

**Status:** ✅ Complete
**Priority:** Medium
**Effort:** Low
**Completed:** November 2025

**Description:**
Show current stock prices alongside trading signals to provide immediate context for decision-making.

**Implemented Features:**
- ✅ Stock price charts on Asset Detail page with synchronized timelines
- ✅ Trading volume charts
- ✅ Price data integrated with yfinance
- ✅ All charts synchronized to selected Time Range dropdown (7/30/90 days, All Time)
- ✅ Visual correlation between price movements and trading signals

**Remaining Features:**
- Display current stock price on Market Overview page
- Show price change % (daily, weekly, monthly)
- Calculate potential P&L if you acted on historical signals

**Implementation:**
```python
import yfinance as yf

def get_current_price(ticker):
    stock = yf.Ticker(ticker)
    data = stock.history(period='1d')
    return data['Close'].iloc[-1]

def get_price_at_date(ticker, date):
    stock = yf.Ticker(ticker)
    data = stock.history(start=date, end=date + timedelta(days=1))
    return data['Close'].iloc[0] if not data.empty else None
```

**Benefits:**
- Immediate trading context
- See correlation between signals and price movement
- Quick validation of signal quality
- Better timing for entries/exits

---

## 6. Signal Backtesting & Performance Dashboard

**Status:** Not Started
**Priority:** High
**Effort:** High

**Description:**
Track and analyze the profitability of trading signals over time to validate system effectiveness.

**Database Schema:**
```sql
CREATE TABLE signal_trades (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id),
    asset_id INTEGER REFERENCES assets(id),
    signal_type VARCHAR(20),  -- 'long_signal', 'short_signal'
    signal_date TIMESTAMP,
    confidence_score FLOAT,
    entry_price DECIMAL(10,2),
    exit_price DECIMAL(10,2),
    holding_period_days INTEGER,
    profit_loss_pct DECIMAL(10,4),
    profit_loss_amount DECIMAL(10,2),
    was_profitable BOOLEAN,
    exit_reason VARCHAR(50),  -- 'time_based', 'stop_loss', 'take_profit'
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Metrics to Track:**
- Win rate by signal type
- Average return per signal
- Best/worst performing assets
- Optimal holding period (1d, 3d, 7d, 30d)
- Risk-adjusted returns (Sharpe ratio)
- Maximum drawdown

**Dashboard Features:**
- Performance summary table
- Equity curve chart
- Win/loss distribution
- Signal type breakdown
- Asset performance comparison
- Confidence threshold optimizer

**Benefits:**
- Validate signal quality before real trading
- Identify most profitable patterns
- Optimize confidence thresholds
- Build confidence in the system

---

## 7. Additional Data Sources

**Status:** Not Started
**Priority:** High
**Effort:** High

**Description:**
Expand data collection beyond Reddit to get more comprehensive market sentiment.

### 7.1 Twitter/X Integration

**Implementation:**
- Use Twitter API v2 or web scraping
- Track influential accounts (CEOs, analysts, journalists)
- Search for company mentions and hashtags
- Monitor verified accounts more heavily

**Benefits:**
- Real-time breaking news (often posted on Twitter first)
- CEO announcements and company updates
- Analyst opinions and market commentary

### 7.2 Financial News RSS Feeds

**Sources:**
- Bloomberg RSS feeds
- Reuters Business
- Financial Times
- Wall Street Journal
- MarketWatch
- Seeking Alpha

**Implementation:**
- Extend existing RSS collector
- Add source credibility scoring
- Prioritize authoritative sources in analysis

### 7.3 Earnings Call Transcripts

**Sources:**
- Seeking Alpha transcripts
- Yahoo Finance earnings calls
- SEC Edgar filings

**Benefits:**
- Direct insight from management
- Tone analysis (CEO confidence, hesitation)
- Forward guidance detection
- Q&A sentiment analysis

---

## 8. Dashboard UX Improvements

**Status:** Not Started
**Priority:** Low
**Effort:** Low

### 8.1 Date Range Filters
- Add date picker to Overview and Alerts pages
- Preset ranges: Last 7 days, Last 30 days, Last 90 days, YTD, Custom
- Persist filter selection in session state

### 8.2 Export Functionality
- CSV export for alerts and analysis data
- PDF report generation
- Scheduled email reports (daily digest)
- Excel export with formatted charts

### 8.3 Dark Mode
- Toggle between light/dark themes
- Save preference in browser localStorage
- Better for extended monitoring sessions
- Reduce eye strain for night trading

### 8.4 Other Improvements
- Add search/filter on all tables
- Sortable columns
- Pagination for large datasets
- Responsive design for mobile viewing

---

## 9. Smart Keyword Auto-Discovery & Performance Tracking

**Status:** ✅ Complete
**Priority:** Medium
**Effort:** Medium
**Completed:** November 2025

**Description:**
Automatically discover and suggest new keywords based on collected posts, and track keyword performance to optimize search coverage.

**Implemented Features:**
- ✅ AI-powered keyword suggestion using Claude (KeywordSuggester module)
- ✅ Smart Keyword Suggestions UI in Settings page with one-click add
- ✅ Keyword performance tracking (KeywordTracker module)
- ✅ Track which keywords match each post (matched_keywords column)
- ✅ Database table for keyword performance metrics (keyword_performance)
- ✅ Keyword Performance section showing stats per asset:
  - Posts found per keyword
  - Last found date
  - Days since last hit
  - Days tracked
- ✅ Identify underperforming keywords automatically
- ✅ Auto-remove underperforming keywords with one click
- ✅ GIN index on matched_keywords for fast queries

**Implementation:**
- `shared/keyword_suggester.py`: AI-powered keyword suggestions
- `shared/keyword_tracker.py`: Performance tracking and analytics
- `collector/collectors/base.py`: Automatic keyword matching on save
- `postgres/migrations/001_add_keyword_performance.sql`: Database schema

**Benefits:**
- ✅ Discover emerging topics automatically with AI assistance
- ✅ Better coverage without manual effort
- ✅ Data-driven keyword optimization
- ✅ Remove low-performing keywords to reduce noise
- ✅ Track keyword effectiveness over time

---

## 10. Alert Notification Testing Suite

**Status:** Partially Complete (notifier exists but untested)
**Priority:** High
**Effort:** Low

**Tasks:**
1. Test email notifications end-to-end
2. Test SMS via Twilio
3. Test push notifications (Pushover)
4. Test webhook delivery
5. Add "Send Test Notification" button in Settings
6. Monitor notifier service logs for failures
7. Add retry logic for failed deliveries
8. Track delivery success rate in database

**Benefits:**
- Ensure critical alerts are actually delivered
- Catch configuration errors early
- Build confidence in notification reliability

---

## 11. Synchronized Chart Timelines

**Status:** ✅ Complete
**Priority:** High
**Effort:** Low
**Completed:** November 2025

**Description:**
Synchronize all chart timelines on the Asset Detail page to the same time range for easy visual correlation analysis.

**Problem Solved:**
Previously, each chart (stock price, volume, signals, sentiment, mentions) had different x-axis ranges based on available data, making it extremely difficult to:
- Compare stock price movements with trading signals
- Analyze correlation between sentiment and price
- Investigate timing and relevance of signals

**Implemented Features:**
- ✅ Common date range calculation based on selected Time Range dropdown
- ✅ Synchronized x-axis ranges across all 6 time-based charts:
  - Stock Price chart
  - Trading Volume chart
  - Trading Signals chart
  - Daily Signal Strength (Aggregated) chart
  - Mention Count Over Time chart
  - Average Sentiment Over Time chart
- ✅ Time Range dropdown with options: 7 Days, 30 Days, 90 Days, All Time
- ✅ Instant visual alignment when changing time range

**Implementation:**
```python
# Calculate common date range for all charts
end_date = datetime.now()
start_date = end_date - timedelta(days=days)

# Apply to all chart layouts
fig.update_layout(
    xaxis_range=[start_date, end_date]
)
```

**Benefits:**
- ✅ Perfect visual alignment across all charts
- ✅ Easy correlation analysis between metrics
- ✅ Clear investigation of signal timing and effectiveness
- ✅ Better UX for trading decision analysis
- ✅ Immediate feedback when changing time ranges

---

## 12. Smart Market-Hours-Based Collection Scheduling

**Completed:** November 2025

**Description:**
Automatically adjusts news collection frequency based on market hours to optimize data freshness during trading hours while reducing API usage during off-hours.

**Use Case:**
- During market hours (9:30 AM - 4:00 PM ET), news is more likely to be market-moving, so collect more frequently
- After hours and weekends, news volume is lower and less time-sensitive, so reduce collection frequency
- User can customize market hours and intervals via Settings page
- System automatically adjusts schedule without requiring restart

**Implemented Features:**
- ✅ Smart scheduling based on US Eastern Time market hours
- ✅ Configurable collection intervals:
  - Market hours: 15 minutes (default)
  - After hours: 30 minutes (default)
  - Weekends: 2 hours (default)
- ✅ Settings UI for customizing schedule parameters
- ✅ Dynamic job rescheduling when settings change
- ✅ Fixed interval mode for users who prefer consistent collection
- ✅ Automatic timezone handling with pytz
- ✅ Database-driven configuration with fallback defaults

**Technical Implementation:**
- `shared/market_hours.py`: MarketHoursScheduler class for market hours detection
- `collector/config.py`: Scheduling configuration constants
- `collector/main.py`: Dynamic interval adjustment with APScheduler
- `postgres/migrations/004_add_collection_schedule_settings.sql`: Database schema
- `dashboard/app.py`: Settings UI for configuration

**Benefits:**
- ✅ Better data freshness during market hours
- ✅ Reduced API costs during off-hours
- ✅ User-configurable without code changes
- ✅ Automatic adaptation to time of day
- ✅ No container restart required for schedule changes

---

## 13. MCP Server for Claude Desktop Integration

**Status:** 📋 Planned
**Priority:** Medium
**Effort:** Medium
**Target:** v2.0

**Description:**
Implement a Model Context Protocol (MCP) server to provide Claude Desktop with direct access to trading signals, news sentiment, and alerts through natural language queries.

**Use Case:**
- Personal use with Claude Desktop for interactive trading analysis
- Query trading data without opening the dashboard: "What are the latest alerts for PLTR?"
- AI-augmented analysis: "Compare sentiment patterns before the last 3 earnings reports"
- Natural language access to all trading data during market hours

**Proposed MCP Tools:**

**Core Trading Tools:**
1. `get_asset_overview` - Get asset data, current signals, and recent alerts
2. `search_news` - Search recent news with sentiment for a ticker and time period
3. `get_alerts` - Filter alerts by severity, type, and time range
4. `get_sentiment_trend` - Time-series sentiment data for a ticker
5. `compare_assets` - Side-by-side comparison of multiple tickers
6. `get_signal_strength` - Current DSS and signal breakdown

**Analysis Tools:**
7. `get_top_movers` - Assets with biggest signal changes recently
8. `search_by_category` - All news in a specific category (Hiring, Growth, etc.)
9. `get_portfolio_summary` - Aggregated signals for a list of tickers

**Implementation Approach:**

```python
# mcp_server/main.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
import psycopg2
from typing import Optional, List

app = Server("news-trading")

@app.tool()
async def get_asset_overview(ticker: str) -> dict:
    """Get comprehensive overview of an asset including latest signals and alerts."""
    # Reuse dashboard query functions
    # Return structured data for Claude to analyze
    pass

@app.tool()
async def get_alerts(
    severity: Optional[str] = None,
    hours: int = 24,
    ticker: Optional[str] = None
) -> List[dict]:
    """Get filtered alerts from the system."""
    pass

# More tools...

if __name__ == "__main__":
    stdio_server(app)
```

**Technical Implementation:**
- New `mcp_server/` directory with standalone Python service
- Shared database query module (used by both dashboard and MCP server)
- Read-only PostgreSQL access
- Run via `uvx` or as optional Docker service
- Configuration in Claude Desktop's `claude_desktop_config.json`

**Benefits:**
- Natural language access to all trading data
- AI-augmented pattern recognition and correlation analysis
- Faster insights during market hours without opening dashboard
- Programmatic access foundation for future automation
- Standardized API layer using modern MCP protocol

**Challenges:**
- Security: Ensure read-only access, no sensitive data exposure
- Performance: Optimize queries for real-time interaction
- Deployment: Additional service to manage (though lightweight)
- Documentation: Clear examples for Claude Desktop setup

**Example Interactions:**

```
User: "Claude, check if there are any high-severity alerts in the last hour"
Claude: [calls get_alerts(severity='high', hours=1)]
        "You have 2 high-severity alerts:
         - PLTR: Guidance raise detected (confidence: 0.87)
         - SNOW: Regulatory risk identified (confidence: 0.73)"

User: "Show me the sentiment trend for Palantir over the last 30 days"
Claude: [calls get_sentiment_trend(ticker='PLTR', period='30d')]
        [Analyzes data and presents insights with trend analysis]

User: "Compare signal strength for my tech watchlist: PLTR, SNOW, GOOGL"
Claude: [calls compare_assets(tickers=['PLTR', 'SNOW', 'GOOGL'])]
        [Provides comparative analysis with current DSS scores]
```

**Dependencies:**
- `mcp` Python package
- Existing PostgreSQL database (read-only access)
- Shared query logic module

**Estimated Effort:** 4-6 hours for MVP with 5-10 core tools

**Notes:**
- Start with read-only tools; write operations (if any) in future versions
- Personal use only initially; multi-user auth for later versions
- Optional feature - can be disabled for dashboard-only users

---

## Implemented Features

### Congressional Trading Tracker ✅ **Implemented** (November 2025)

**Status:** Complete

**Description:**
Track insider trading by US Congress members to identify potential trading signals. Congressional representatives and senators are required to disclose stock trades, which can provide early indicators of potential market movements.

**Implementation:**
- ✅ Created `CongressionalTradesCollector` using existing `social_posts` data structure
- ✅ Integrated with House Stock Watcher (free public data source)
- ✅ Optional Capitol Trades API support for enhanced data
- ✅ Automatic filtering by tracked tickers
- ✅ Enabled by default in collector configuration

**Data Sources:**
- **House Stock Watcher** (primary): Free JSON API with US House trades - no API key needed
- **Alternative premium sources** (optional):
  - [Benzinga Government Trades API](https://www.benzinga.com/apis/cloud-product/government-trades/)
  - [Financial Modeling Prep Senate Trading API](https://site.financialmodelingprep.com/developer/docs/senate-trading-api)

**Features:**
- Tracks purchases and sales by Congress members
- Includes politician party, state, and chamber information
- Shows transaction amount ranges (as disclosed)
- Links to original disclosure sources
- AI analysis identifies trading patterns and potential conflicts

**Why It Works:**
- Research shows congressional trades often precede major price movements
- STOCK Act (2012) requires timely disclosure of trades
- Committee assignments can indicate sector-specific knowledge
- High conviction signals when multiple members trade same stock

**Alert Types Generated:**
- `congressional_buy_signal`: Notable purchase by congressman
- `congressional_sell_signal`: Notable sale by congressman
- `congressional_cluster`: Multiple congresspeople trading same stock

**Example Data:**
```
🟢 Nancy Pelosi (D-CA) Purchase $NVDA - $500,000-$1,000,000
Transaction Date: 2025-11-15
Disclosure Date: 2025-11-18
Chamber: House
```

**Usage:**
Already enabled by default in `collector/config.py`. Data appears in:
- Overview page: Mixed with other news sources
- Asset Detail page: Filter by source = "congressional_trades"
- Alerts page: Filter by alert type

**Optional Configuration:**
```env
# .env file
CAPITOL_TRADES_API_KEY=your_key  # Optional - works without it
```

**Architecture Decision:**
Used existing `social_posts` table rather than creating separate `congressional_trades` table. This approach:
- Reuses existing infrastructure (collectors, analyzers, dashboard)
- Allows AI to analyze trades alongside news for context
- Maintains architectural consistency
- Reduces complexity and development time

---

## Future Ideas (Not Yet Detailed)

- **Machine Learning Models**: Train models on historical data to predict stock movements based on news patterns
- **Multi-Language Support**: Analyze news in languages other than English
- **Real-time Streaming**: Move from 6-hour intervals to real-time streaming data
- **Competitor Analysis**: Automatically track competitors when adding an asset
- **Portfolio Integration**: Connect to brokerage APIs for automated trading signals
- **Custom Alert Rules Engine**: User-defined alert conditions with complex logic
- **RESTful API**: Programmatic access to all analysis data
- **Paper Trading Bot**: Automated virtual trading based on alerts to validate strategies
- **Mobile App**: iOS/Android app for on-the-go monitoring
- **Multi-Factor Correlation**: Detect correlation between multiple assets
- **Sentiment Momentum Tracking**: Alert on accelerating sentiment trends
- **Production Deployment**: Cloud deployment with monitoring, backups, SSL
- **Scalability**: Connection pooling, Redis caching, queue systems
- **Advanced Analytics**: Correlation analysis, statistical significance testing

---

## Contributing

Feel free to add your own ideas to this document! For each idea, try to include:
- Clear description of the feature
- Use case / user story
- Implementation approach (if known)
- Technical considerations
