"""
News Trading Dashboard
Streamlit application for monitoring and analyzing trading signals.
"""
import os
import sys
from pathlib import Path

# Version
__version__ = "1.0"
from typing import Optional
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import yfinance as yf

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

# Add collector directory to path for direct initialization
# Try same directory first (when running in container with volumes)
collector_path = Path(__file__).parent / 'collector'
if not collector_path.exists():
    # Try parent directory (when running locally)
    collector_path = Path(__file__).parent.parent / 'collector'
if collector_path.exists():
    sys.path.insert(0, str(collector_path))

from logging_config import setup_logging
import logging

# Load environment variables
load_dotenv()

# Import config
from config import CONSOLE_LOG_LEVEL, DATABASE_LOG_LEVEL, LOG_FORMAT

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Set up logging (only once)
if 'logger_initialized' not in st.session_state:
    setup_logging(
        service_name='dashboard',
        database_url=DATABASE_URL,
        console_level=CONSOLE_LOG_LEVEL,
        database_level=DATABASE_LOG_LEVEL,
        log_format=LOG_FORMAT
    )
    st.session_state.logger_initialized = True

# Get module-level logger
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="News Trading Dashboard",
    page_icon="📊",
    layout="wide"
)


def get_db_connection():
    """
    Create a fresh database connection with error handling.

    Returns:
        Database connection object

    Raises:
        psycopg2.Error: If connection fails

    Note: Caller is responsible for closing the connection.
    """
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise


def fetch_data(query, params=None):
    """
    Execute a SELECT query and return results as a pandas DataFrame.

    Args:
        query: SQL query string
        params: Query parameters (optional)

    Returns:
        DataFrame with query results, empty DataFrame on error
    """
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            results = cur.fetchall()
            return pd.DataFrame(results) if results else pd.DataFrame()
    except psycopg2.Error as e:
        logger.error(f"Database query error: {e}")
        st.error(f"Database error: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()


def get_sentiment_color(sentiment_score: Optional[float]) -> str:
    """Return color based on sentiment score.

    Args:
        sentiment_score: Sentiment score between -1 and 1, or None

    Returns:
        Color name as string (gray, green, red, or orange)
    """
    if sentiment_score is None:
        return "gray"
    elif sentiment_score > 0.3:
        return "green"
    elif sentiment_score < -0.3:
        return "red"
    else:
        return "orange"


def get_sentiment_emoji(sentiment: str) -> str:
    """Return emoji based on sentiment.

    Args:
        sentiment: Sentiment category (positive, negative, or neutral)

    Returns:
        Emoji string (🟢 for positive, 🔴 for negative, 🟡 for neutral)
    """
    if sentiment == "positive":
        return "🟢"
    elif sentiment == "negative":
        return "🔴"
    else:
        return "🟡"


def create_multi_overlay_chart(
    stock_data: Optional[pd.DataFrame],
    metrics_df: pd.DataFrame,
    alerts_df: pd.DataFrame,
    ticker: str,
    start_date: datetime,
    end_date: datetime,
    show_volume: bool = True,
    show_sentiment: bool = True,
    show_mentions: bool = True,
    show_alerts: bool = True,
    show_signal_strength: bool = True
) -> go.Figure:
    """
    Create an advanced multi-overlay chart similar to Garmin Connect.

    Args:
        stock_data: Stock price and volume data (always displayed)
        metrics_df: Daily metrics (mentions, sentiment)
        alerts_df: Trading alerts
        ticker: Stock ticker symbol
        start_date: Chart start date
        end_date: Chart end date
        show_volume: Toggle trading volume overlay
        show_sentiment: Toggle sentiment overlay
        show_mentions: Toggle mentions overlay
        show_alerts: Toggle alert markers
        show_signal_strength: Toggle daily signal strength bars

    Returns:
        Plotly figure with multiple overlays
    """
    from plotly.subplots import make_subplots

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 1. Stock Price (primary y-axis, left) - ALWAYS DISPLAYED
    if stock_data is not None and not stock_data.empty:
        fig.add_trace(
            go.Scatter(
                x=stock_data['Date'],
                y=stock_data['Close'],
                name='Stock Price',
                line=dict(color='#2ca02c', width=2),
                hovertemplate='<b>Price:</b> $%{y:.2f}<extra></extra>'
            ),
            secondary_y=False
        )

    # 2. Trading Volume (secondary y-axis, right) - as bars with transparency
    if show_volume and stock_data is not None and not stock_data.empty:
        fig.add_trace(
            go.Bar(
                x=stock_data['Date'],
                y=stock_data['Volume'],
                name='Volume',
                marker=dict(color='rgba(31, 119, 180, 0.2)'),
                hovertemplate='<b>Volume:</b> %{y:,.0f}<extra></extra>',
                yaxis='y3'  # Will create third y-axis
            ),
            secondary_y=True
        )

    # 3. Sentiment Score (secondary y-axis, right)
    if show_sentiment and not metrics_df.empty:
        # Add sentiment line
        fig.add_trace(
            go.Scatter(
                x=metrics_df['date'],
                y=metrics_df['sentiment_avg'],
                name='Sentiment',
                line=dict(color='#ff7f0e', width=2),
                hovertemplate='<b>Sentiment:</b> %{y:.2f}<extra></extra>'
            ),
            secondary_y=True
        )

        # Add 7-day moving average
        if 'sentiment_ma7' in metrics_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=metrics_df['date'],
                    y=metrics_df['sentiment_ma7'],
                    name='Sentiment (7-day MA)',
                    line=dict(color='#ff7f0e', width=1, dash='dash'),
                    opacity=0.6,
                    hovertemplate='<b>Sentiment MA:</b> %{y:.2f}<extra></extra>'
                ),
                secondary_y=True
            )

    # 4. Mention Count (secondary y-axis, right)
    if show_mentions and not metrics_df.empty:
        fig.add_trace(
            go.Scatter(
                x=metrics_df['date'],
                y=metrics_df['mention_count'],
                name='Mentions',
                line=dict(color='#9467bd', width=2),
                hovertemplate='<b>Mentions:</b> %{y}<extra></extra>'
            ),
            secondary_y=True
        )

    # 5. Alert Markers (overlaid on chart)
    if show_alerts and not alerts_df.empty:
        alerts_df['alert_timestamp'] = pd.to_datetime(alerts_df['alert_timestamp'])

        # Long signals (green triangles pointing up)
        long_signals = alerts_df[alerts_df['alert_type'] == 'long_signal']
        if not long_signals.empty and stock_data is not None and not stock_data.empty:
            # Find stock prices at alert times
            long_with_prices = pd.merge_asof(
                long_signals.sort_values('alert_timestamp'),
                stock_data.sort_values('Date'),
                left_on='alert_timestamp',
                right_on='Date',
                direction='nearest',
                tolerance=pd.Timedelta('1day')
            )

            fig.add_trace(
                go.Scatter(
                    x=long_with_prices['alert_timestamp'],
                    y=long_with_prices['Close'],
                    mode='markers',
                    marker=dict(
                        size=15,
                        color='#28a745',
                        symbol='triangle-up',
                        line=dict(width=2, color='white')
                    ),
                    name='Long Signal',
                    hovertemplate='<b>Long Signal</b><br>' +
                                 'Date: %{x}<br>' +
                                 'Price: $%{y:.2f}<br>' +
                                 '<extra></extra>'
                ),
                secondary_y=False
            )

        # Short signals (red triangles pointing down)
        short_signals = alerts_df[alerts_df['alert_type'] == 'short_signal']
        if not short_signals.empty and stock_data is not None and not stock_data.empty:
            short_with_prices = pd.merge_asof(
                short_signals.sort_values('alert_timestamp'),
                stock_data.sort_values('Date'),
                left_on='alert_timestamp',
                right_on='Date',
                direction='nearest',
                tolerance=pd.Timedelta('1day')
            )

            fig.add_trace(
                go.Scatter(
                    x=short_with_prices['alert_timestamp'],
                    y=short_with_prices['Close'],
                    mode='markers',
                    marker=dict(
                        size=15,
                        color='#dc3545',
                        symbol='triangle-down',
                        line=dict(width=2, color='white')
                    ),
                    name='Short Signal',
                    hovertemplate='<b>Short Signal</b><br>' +
                                 'Date: %{x}<br>' +
                                 'Price: $%{y:.2f}<br>' +
                                 '<extra></extra>'
                ),
                secondary_y=False
            )

    # 6. Daily Signal Strength (as bars, secondary y-axis)
    if show_signal_strength and not alerts_df.empty:
        # Aggregate signals by date
        alerts_df_copy = alerts_df.copy()
        alerts_df_copy['alert_timestamp'] = pd.to_datetime(alerts_df_copy['alert_timestamp'])
        alerts_df_copy['date'] = alerts_df_copy['alert_timestamp'].dt.date

        # Calculate daily aggregates
        daily_agg = alerts_df_copy.groupby(['date', 'alert_type']).agg({
            'confidence_score': 'sum'
        }).reset_index()

        # Pivot to get long and short signals in separate columns
        daily_pivot = daily_agg.pivot(index='date', columns='alert_type', values='confidence_score').fillna(0)

        # Create net confidence (positive for long, negative for short)
        daily_summary = pd.DataFrame({
            'date': pd.to_datetime(daily_pivot.index),
            'long_confidence': daily_pivot.get('long_signal', 0),
            'short_confidence': daily_pivot.get('short_signal', 0)
        })
        daily_summary['net_confidence'] = daily_summary['long_confidence'] - daily_summary['short_confidence']
        daily_summary['color'] = daily_summary['net_confidence'].apply(
            lambda x: 'rgba(40, 167, 69, 0.4)' if x > 0 else 'rgba(220, 53, 69, 0.4)'
        )

        # Add bar chart
        fig.add_trace(
            go.Bar(
                x=daily_summary['date'],
                y=daily_summary['net_confidence'],
                name='Signal Strength',
                marker=dict(
                    color=daily_summary['color'],
                    line=dict(width=0.5, color='rgba(0,0,0,0.2)')
                ),
                hovertemplate='<b>Net Signal Strength:</b> %{y:.2f}<br>' +
                             '<b>Date:</b> %{x}<extra></extra>',
                yaxis='y4'  # Fourth y-axis for signal strength
            ),
            secondary_y=True
        )

    # Configure layout with dark theme to match dashboard
    fig.update_layout(
        title=dict(
            text=f"{ticker} - Multi-Metric Analysis",
            font=dict(size=20, color='#ffffff')
        ),
        height=800,
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(20, 20, 20, 0.95)",
            bordercolor="#444444",
            borderwidth=1,
            font=dict(size=11, color='#ffffff')
        ),
        xaxis=dict(
            title='Date',
            title_font=dict(color='#ffffff'),
            range=[start_date, end_date],
            showgrid=True,
            gridcolor='rgba(80, 80, 80, 0.3)',
            gridwidth=1,
            tickfont=dict(color='#cccccc')
        ),
        plot_bgcolor='#000000',  # Black background to match dashboard
        paper_bgcolor='#0e1117'  # Dark background to match Streamlit dark theme
    )

    # Set y-axis titles with dark theme colors
    fig.update_yaxes(
        title_text="Stock Price (USD)",
        title_font=dict(color='#ffffff'),
        secondary_y=False,
        showgrid=True,
        gridcolor='rgba(80, 80, 80, 0.3)',
        gridwidth=1,
        tickfont=dict(color='#cccccc')
    )
    fig.update_yaxes(
        title_text="Metrics (Sentiment / Mentions / Volume)",
        title_font=dict(color='#ffffff'),
        secondary_y=True,
        showgrid=False,
        tickfont=dict(color='#cccccc')
    )

    # Add range slider with dark theme colors
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeslider=dict(
            bgcolor='#1a1a1a',
            bordercolor='#444444',
            borderwidth=1
        ),
        rangeselector=dict(
            buttons=list([
                dict(count=7, label="1w", step="day", stepmode="backward"),
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=3, label="3m", step="month", stepmode="backward"),
                dict(step="all", label="All")
            ]),
            bgcolor="rgba(20, 20, 20, 0.95)",
            activecolor="#4CAF50",
            bordercolor='#444444',
            borderwidth=1,
            font=dict(color='#ffffff')
        )
    )

    return fig


@st.cache_data(ttl=900)  # Cache for 15 minutes
def fetch_stock_data(ticker: str, days: int) -> Optional[pd.DataFrame]:
    """Fetch stock price data from Yahoo Finance using download method.

    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'GOOG')
        days: Number of days of historical data to fetch

    Returns:
        DataFrame with columns [Date, Close] or None if fetch fails
    """
    try:
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=max(days + 5, 30))  # Fetch a bit more to ensure coverage

        # Use yf.download which is more reliable than Ticker().history()
        # Suppress yfinance warnings/errors and disable yfinance logger
        import warnings
        import logging
        yf_logger = logging.getLogger('yfinance')
        original_level = yf_logger.level
        yf_logger.setLevel(logging.CRITICAL)  # Suppress all yfinance logs except CRITICAL

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                hist = yf.download(
                    ticker,
                    start=start_date,
                    end=end_date,
                    progress=False
                )
        finally:
            yf_logger.setLevel(original_level)  # Restore original level

        if hist.empty:
            return None

        # Flatten multi-level columns (new yfinance returns MultiIndex)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = [col[0] for col in hist.columns]

        # Reset index to get date as column
        hist.reset_index(inplace=True)

        # Filter to requested days
        cutoff_date = end_date - timedelta(days=days)
        hist = hist[hist['Date'] >= cutoff_date]

        return hist if not hist.empty else None

    except Exception as e:
        # Silently fail - stock data is optional
        return None


# Sidebar navigation
st.sidebar.title("📊 News Trading")

# Initialize page in session state if not exists
if 'page' not in st.session_state:
    st.session_state.page = "Overview"

# Define callback for radio button changes
def on_nav_change():
    """Callback when user clicks navigation radio button."""
    st.session_state.page = st.session_state.nav_radio

# Get current page index for radio button
pages = ["Overview", "Asset Detail", "Alerts", "Settings"]
current_index = pages.index(st.session_state.page) if st.session_state.page in pages else 0

# Radio button with callback - this ensures changes only happen when user clicks
st.sidebar.radio(
    "Navigation",
    pages,
    index=current_index,
    key="nav_radio",
    on_change=on_nav_change
)

page = st.session_state.page

# ============================================================================
# PAGE 1: OVERVIEW
# ============================================================================
if page == "Overview":
    # Custom CSS for Overview page - reduce font sizes to 2 levels
    st.markdown("""
        <style>
        /* Overview page: limit to 2 font sizes */
        [data-testid="stAppViewContainer"] h3 {
            font-size: 1.2rem !important;  /* Smaller subheaders */
            margin-top: 0.5rem !important;
            margin-bottom: 0.5rem !important;
        }
        /* Align all metric values to same font size */
        [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.875rem !important;
        }
        /* Regular text stays default size */
        </style>
    """, unsafe_allow_html=True)

    # ========================================================================
    # SYSTEM HEALTH STATUS
    # ========================================================================
    st.subheader("⚙️ System Health")

    # Fetch system health metrics
    health_query = """
        SELECT
            (
                SELECT MAX(timestamp)
                FROM system_logs
                WHERE service = 'collector'
            ) as last_collector_run,
            (
                SELECT MAX(timestamp)
                FROM system_logs
                WHERE service = 'analyzer'
            ) as last_analyzer_run,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE service = 'collector'
                  AND level = 'ERROR'
                  AND timestamp >= NOW() - INTERVAL '1 hour'
            ) as collector_errors_1h,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE service = 'analyzer'
                  AND level = 'ERROR'
                  AND timestamp >= NOW() - INTERVAL '1 hour'
            ) as analyzer_errors_1h,
            (
                SELECT MAX(fetched_at)
                FROM social_posts
            ) as last_post_collected,
            (
                SELECT MAX(analyzed_at)
                FROM ai_analysis
            ) as last_post_analyzed,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE level = 'WARNING'
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            ) as total_warnings_24h,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE level = 'ERROR'
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            ) as total_errors_24h
    """

    health_df = fetch_data(health_query)

    if not health_df.empty:
        health = health_df.iloc[0]

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            # Collector status
            last_collector = health['last_collector_run']
            collector_errors = int(health['collector_errors_1h']) if pd.notna(health['collector_errors_1h']) else 0

            if pd.notna(last_collector):
                time_diff = datetime.now() - last_collector.replace(tzinfo=None)
                minutes_ago = int(time_diff.total_seconds() / 60)

                if minutes_ago < 60:
                    collector_status = f"✅ Active ({minutes_ago}m ago)"
                    collector_color = "normal"
                elif minutes_ago < 180:
                    collector_status = f"⚠️ Delayed ({minutes_ago}m ago)"
                    collector_color = "inverse"
                else:
                    collector_status = f"🔴 Stale ({minutes_ago}m ago)"
                    collector_color = "off"
            else:
                collector_status = "⚪ No data"
                collector_color = "off"

            st.metric("Collector", collector_status)
            if collector_errors > 0:
                st.error(f"⚠️ {collector_errors} errors in last hour")

        with col2:
            # Analyzer status
            last_analyzer = health['last_analyzer_run']
            analyzer_errors = int(health['analyzer_errors_1h']) if pd.notna(health['analyzer_errors_1h']) else 0

            if pd.notna(last_analyzer):
                time_diff = datetime.now() - last_analyzer.replace(tzinfo=None)
                minutes_ago = int(time_diff.total_seconds() / 60)

                if minutes_ago < 60:
                    analyzer_status = f"✅ Active ({minutes_ago}m ago)"
                elif minutes_ago < 180:
                    analyzer_status = f"⚠️ Delayed ({minutes_ago}m ago)"
                else:
                    analyzer_status = f"🔴 Stale ({minutes_ago}m ago)"
            else:
                analyzer_status = "⚪ No data"

            st.metric("Analyzer", analyzer_status)
            if analyzer_errors > 0:
                # Check for API credit errors
                api_credit_error_query = """
                    SELECT COUNT(*)
                    FROM system_logs
                    WHERE service = 'analyzer'
                      AND level = 'ERROR'
                      AND timestamp >= NOW() - INTERVAL '1 hour'
                      AND (message LIKE '%insufficient_quota%'
                           OR message LIKE '%rate_limit%'
                           OR message LIKE '%quota%'
                           OR message LIKE '%credit%')
                """
                api_error_df = fetch_data(api_credit_error_query)
                api_errors = int(api_error_df.iloc[0, 0]) if not api_error_df.empty else 0

                if api_errors > 0:
                    st.error(f"🚨 Claude API Credits Low/Exhausted!")
                    st.error(f"Check API credits at console.anthropic.com")
                else:
                    st.error(f"⚠️ {analyzer_errors} errors in last hour")

        with col3:
            # Last data collection
            last_post = health['last_post_collected']
            if pd.notna(last_post):
                time_diff = datetime.now() - last_post.replace(tzinfo=None)
                minutes_ago = int(time_diff.total_seconds() / 60)
                st.metric("Last Collection", f"{minutes_ago}m ago")
            else:
                st.metric("Last Collection", "No data")

        with col4:
            # Last analysis
            last_analysis = health['last_post_analyzed']
            if pd.notna(last_analysis):
                time_diff = datetime.now() - last_analysis.replace(tzinfo=None)
                minutes_ago = int(time_diff.total_seconds() / 60)
                st.metric("Last Analysis", f"{minutes_ago}m ago")
            else:
                st.metric("Last Analysis", "No data")

        # Second row: Log statistics
        st.markdown("")  # Small spacing
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            total_warnings = int(health['total_warnings_24h']) if pd.notna(health['total_warnings_24h']) else 0
            warning_color = "normal" if total_warnings == 0 else "inverse"
            st.metric("⚠️ Warnings (24h)", total_warnings, delta=None if total_warnings == 0 else f"{total_warnings} issues")

        with col2:
            total_errors = int(health['total_errors_24h']) if pd.notna(health['total_errors_24h']) else 0
            error_color = "normal" if total_errors == 0 else "off"
            st.metric("🔴 Errors (24h)", total_errors, delta=None if total_errors == 0 else f"{total_errors} issues", delta_color="inverse")

        with col3:
            # Empty for now - could add more metrics later
            pass

        with col4:
            # Empty for now - could add more metrics later
            pass

    st.markdown("---")

    # ========================================================================
    # ASSET METRICS
    # ========================================================================

    # Fetch asset metrics with recent alerts
    query = """
        SELECT
            c.id,
            c.name,
            c.ticker,
            dm.mention_count,
            dm.sentiment_avg,
            dm.hiring_mentions,
            dm.problem_mentions,
            dm.growth_mentions,
            (
                SELECT MAX(fetched_at)
                FROM social_posts
                WHERE asset_id = c.id
            ) as last_collection,
            (
                SELECT COUNT(*)
                FROM social_posts
                WHERE asset_id = c.id
            ) as total_posts,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE asset_id = c.id
                  AND DATE(timestamp) = CURRENT_DATE
                  AND alert_type = 'long_signal'
            ) as today_long_signals,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE asset_id = c.id
                  AND DATE(timestamp) = CURRENT_DATE
                  AND alert_type = 'short_signal'
            ) as today_short_signals,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE asset_id = c.id
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            ) as alerts_24h
        FROM asset c
        LEFT JOIN LATERAL (
            SELECT *
            FROM daily_metrics
            WHERE asset_id = c.id
              AND date >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY date DESC
        ) dm ON true
        ORDER BY c.name
    """

    df = fetch_data(query)

    if not df.empty:
        # Aggregate metrics by company
        asset_metrics = df.groupby(['id', 'name', 'ticker']).agg({
            'mention_count': 'sum',
            'sentiment_avg': 'mean',
            'hiring_mentions': 'sum',
            'problem_mentions': 'sum',
            'growth_mentions': 'sum',
            'last_collection': 'first',
            'total_posts': 'first',
            'today_long_signals': 'first',
            'today_short_signals': 'first',
            'alerts_24h': 'first'
        }).reset_index()

        # Summary metrics at the top
        st.subheader("Today's Summary")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            total_assets = len(asset_metrics)
            st.metric("Tracked Assets", total_assets)

        with col2:
            total_long = int(asset_metrics['today_long_signals'].sum())
            st.metric("Long Signals Today", total_long, delta="Bullish", delta_color="normal")

        with col3:
            total_short = int(asset_metrics['today_short_signals'].sum())
            st.metric("Short Signals Today", total_short, delta="Bearish", delta_color="inverse")

        with col4:
            total_alerts_24h = int(asset_metrics['alerts_24h'].sum())
            st.metric("Total Alerts (24h)", total_alerts_24h)

        st.markdown("---")

        # Detailed table view
        st.subheader("Detailed Metrics Table")

        # Prepare display dataframe
        display_df = asset_metrics.copy()

        # Calculate Daily Signal Strength (long signals - short signals)
        display_df['daily_signal_strength'] = (
            display_df['today_long_signals'].fillna(0).astype(int) -
            display_df['today_short_signals'].fillna(0).astype(int)
        )

        # Sort by absolute value of Daily Signal Strength descending (highest magnitude first)
        display_df['abs_signal_strength'] = display_df['daily_signal_strength'].abs()
        display_df = display_df.sort_values('abs_signal_strength', ascending=False)

        # Format columns
        display_df['DSS'] = display_df['daily_signal_strength'].astype(int)
        display_df['Asset'] = display_df['name'] + " (" + display_df['ticker'] + ")"
        display_df['Sentiment'] = display_df['sentiment_avg'].apply(
            lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
        )
        display_df['Mentions'] = display_df['mention_count'].fillna(0).astype(int)
        display_df['Long'] = display_df['today_long_signals'].fillna(0).astype(int)
        display_df['Short'] = display_df['today_short_signals'].fillna(0).astype(int)
        display_df['Alerts (24h)'] = display_df['alerts_24h'].fillna(0).astype(int)

        # Create a mapping of signal strength for each row index
        signal_strength_map = display_df['daily_signal_strength'].to_dict()

        # Create final display dataframe with only visible columns (no internal column)
        final_df = display_df[['DSS', 'Asset', 'Mentions', 'Sentiment', 'Long', 'Short', 'Alerts (24h)']].copy()

        # Apply row-wise text color styling using the mapping
        def style_rows(row):
            """Style rows based on signal strength from mapping"""
            # Get signal strength from the mapping using row index
            signal_strength = signal_strength_map.get(row.name, 0)

            if signal_strength > 0:
                color = 'color: #00AA00; font-weight: bold'  # Green text for positive
            elif signal_strength < 0:
                color = 'color: #DD0000; font-weight: bold'  # Red text for negative
            else:
                color = ''  # No color for neutral

            # Return style for all columns
            return [color] * len(row)

        # Display table with clickable asset names
        st.markdown("##### Detailed Metrics (Click asset name to view details)")

        # Display header row
        col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 3, 1, 1, 1, 1, 1])
        with col1:
            st.markdown("**DSS**")
        with col2:
            st.markdown("**Asset**")
        with col3:
            st.markdown("**Mentions**")
        with col4:
            st.markdown("**Sentiment**")
        with col5:
            st.markdown("**Long**")
        with col6:
            st.markdown("**Short**")
        with col7:
            st.markdown("**Alerts (24h)**")

        st.markdown("---")

        # Create a container for the table with clickable rows
        for idx, row in final_df.iterrows():
            col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 3, 1, 1, 1, 1, 1])

            # Get signal strength for coloring
            signal_strength = signal_strength_map.get(idx, 0)
            if signal_strength > 0:
                color = '#00AA00'  # Green for positive
            elif signal_strength < 0:
                color = '#DD0000'  # Red for negative
            else:
                color = '#FFFFFF'  # White for neutral

            with col1:
                st.markdown(f"<span style='color: {color}; font-weight: bold;'>{row['DSS']}</span>", unsafe_allow_html=True)
            with col2:
                # Extract asset name without ticker for button and session state
                asset_full = row['Asset']
                asset_name = asset_full.split(' (')[0]
                if st.button(asset_full, key=f"asset_{idx}", use_container_width=True):
                    # Set selected asset and switch to Asset Detail page
                    st.session_state.selected_asset = asset_name
                    st.session_state.page = "Asset Detail"
                    st.rerun()
            with col3:
                st.markdown(f"<span style='color: {color};'>{row['Mentions']}</span>", unsafe_allow_html=True)
            with col4:
                st.markdown(f"<span style='color: {color};'>{row['Sentiment']}</span>", unsafe_allow_html=True)
            with col5:
                st.markdown(f"<span style='color: {color};'>{row['Long']}</span>", unsafe_allow_html=True)
            with col6:
                st.markdown(f"<span style='color: {color};'>{row['Short']}</span>", unsafe_allow_html=True)
            with col7:
                st.markdown(f"<span style='color: {color};'>{row['Alerts (24h)']}</span>", unsafe_allow_html=True)
    else:
        st.info("No data available yet. The collector service is gathering data.")

# ============================================================================
# PAGE 2: COMPANY DETAIL
# ============================================================================
elif page == "Asset Detail":
    # Fetch assets
    assets_df = fetch_data("SELECT id, name, ticker FROM asset ORDER BY name")

    if assets_df.empty:
        st.warning("No assets found.")
    else:
        # Initialize session state for selected asset if not exists
        if 'selected_asset' not in st.session_state:
            st.session_state.selected_asset = assets_df['name'].tolist()[0]

        # Track previous company to detect changes
        if 'previous_asset' not in st.session_state:
            st.session_state.previous_asset = st.session_state.selected_asset

        # Compact layout: Asset selector + Metric toggles in one row
        asset_names = assets_df['name'].tolist()
        # Find index of previously selected asset (or use first if not found)
        try:
            default_asset_index = asset_names.index(st.session_state.selected_asset)
        except ValueError:
            default_asset_index = 0
            st.session_state.selected_asset = asset_names[0]

        # Create compact row with asset selector and toggles
        col_asset, col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1, 1])

        with col_asset:
            selected_asset = st.selectbox(
                "Asset",
                options=asset_names,
                index=default_asset_index,
                format_func=lambda x: f"{x} ({assets_df[assets_df['name']==x]['ticker'].values[0]})",
                key="asset_selector",
                label_visibility="collapsed"
            )

        with col1:
            show_volume = st.checkbox("Volume", value=False, key="toggle_volume")
        with col2:
            show_sentiment = st.checkbox("Sentiment", value=False, key="toggle_sentiment")
        with col3:
            show_mentions = st.checkbox("Mentions", value=False, key="toggle_mentions")
        with col4:
            show_alerts = st.checkbox("Alert Signals", value=True, key="toggle_alerts")
        with col5:
            show_signal_strength = st.checkbox("Signal Strength", value=True, key="toggle_signal_strength")

        # Update session state when company changes
        if selected_asset != st.session_state.selected_asset:
            st.session_state.selected_asset = selected_asset
            st.session_state.previous_asset = selected_asset

        asset_id = int(assets_df[assets_df['name'] == selected_asset]['id'].values[0])

        # Fixed time range - user can adjust via chart's range selector
        days = 90  # Load last 90 days by default

        # Calculate common date range for all charts to ensure synchronized x-axis
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Fetch data for multi-overlay chart
        ticker = assets_df[assets_df['name'] == selected_asset]['ticker'].values[0]
        stock_data = fetch_stock_data(ticker, days)

        # Fetch metrics
        metrics_query = """
            SELECT date, mention_count, sentiment_avg
            FROM daily_metrics
            WHERE asset_id = %s
              AND date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY date
        """
        metrics_df = fetch_data(metrics_query, (asset_id, days))

        # Convert date column and calculate moving average
        if not metrics_df.empty:
            metrics_df['date'] = pd.to_datetime(metrics_df['date'])
            metrics_df['sentiment_ma7'] = metrics_df['sentiment_avg'].rolling(window=7, min_periods=1).mean()

        # Fetch alerts
        alerts_query = """
            SELECT
                timestamp as alert_timestamp,
                alert_type,
                confidence_score,
                description
            FROM alerts
            WHERE asset_id = %s
              AND timestamp >= CURRENT_DATE - INTERVAL '%s days'
              AND alert_type IN ('long_signal', 'short_signal')
            ORDER BY timestamp
        """
        alerts_df = fetch_data(alerts_query, (asset_id, days))

        # Create and display multi-overlay chart
        multi_fig = create_multi_overlay_chart(
            stock_data=stock_data,
            metrics_df=metrics_df,
            alerts_df=alerts_df,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            show_volume=show_volume,
            show_sentiment=show_sentiment,
            show_mentions=show_mentions,
            show_alerts=show_alerts,
            show_signal_strength=show_signal_strength
        )

        st.plotly_chart(multi_fig, use_container_width=True)

        # Stock price data availability info (only shown if data fetch failed)
        if stock_data is None or stock_data.empty:
            st.info(f"📊 Stock price data not available for ticker '{ticker}'. This is optional - news analysis continues normally.")

        # Alert signals chart - positioned after volume chart
        alerts_query = """
            SELECT
                timestamp as alert_timestamp,
                alert_type,
                confidence_score,
                description
            FROM alerts
            WHERE asset_id = %s
              AND timestamp >= CURRENT_DATE - INTERVAL '%s days'
              AND alert_type IN ('long_signal', 'short_signal')
            ORDER BY timestamp
        """
        alerts_df = fetch_data(alerts_query, (asset_id, days))

        # Fetch metrics based on selected time range
        metrics_query = """
            SELECT date, mention_count, sentiment_avg
            FROM daily_metrics
            WHERE asset_id = %s
              AND date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY date
        """
        metrics_df = fetch_data(metrics_query, (asset_id, days))

        # Convert date column to datetime for proper plotting
        if not metrics_df.empty:
            metrics_df['date'] = pd.to_datetime(metrics_df['date'])

            # Calculate 7-day moving average for sentiment
            metrics_df['sentiment_ma7'] = metrics_df['sentiment_avg'].rolling(window=7, min_periods=1).mean()

        # Category breakdown
        category_query = """
            SELECT aa.category, COUNT(*) as count
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            WHERE sp.asset_id = %s
            GROUP BY aa.category
        """
        category_df = fetch_data(category_query, (asset_id,))

        if not category_df.empty:
            st.subheader("Category Breakdown")

            # Show pie chart
            fig_pie = px.pie(
                category_df,
                values='count',
                names='category',
                title='Post Categories'
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        # Recent posts with pagination
        active_filter = st.session_state.get(f'category_filter_{asset_id}')
        if active_filter:
            st.subheader(f"Recent Posts - {active_filter}")
        else:
            st.subheader("Recent Posts with Analysis")

        # Category filter buttons (directly above posts list)
        if not category_df.empty:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown("**Filter by category:**")
            with col2:
                if st.button("🔄 Reset Filter", key=f"reset_filter_{asset_id}"):
                    if f'category_filter_{asset_id}' in st.session_state:
                        del st.session_state[f'category_filter_{asset_id}']
                    st.rerun()

            # Create category buttons
            categories = category_df.to_dict('records')
            cols = st.columns(len(categories))
            for idx, (col, cat_data) in enumerate(zip(cols, categories)):
                with col:
                    category = cat_data['category']
                    count = cat_data['count']
                    is_active = st.session_state.get(f'category_filter_{asset_id}') == category
                    button_type = "primary" if is_active else "secondary"
                    if st.button(f"{category} ({count})", key=f"cat_{asset_id}_{category}", type=button_type):
                        st.session_state[f'category_filter_{asset_id}'] = category
                        st.session_state[f'posts_limit_{asset_id}'] = 20  # Reset pagination
                        st.rerun()

        # Initialize session state for pagination
        if f'posts_limit_{asset_id}' not in st.session_state:
            st.session_state[f'posts_limit_{asset_id}'] = 20

        # Build query with optional category filter
        where_clause = "WHERE sp.asset_id = %s"
        query_params = [asset_id]

        if active_filter:
            where_clause += " AND aa.category = %s"
            query_params.append(active_filter)

        # Get total count of posts
        count_query = f"""
            SELECT COUNT(*) as total
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            {where_clause}
        """
        total_posts = fetch_data(count_query, tuple(query_params))['total'].values[0]

        # Fetch posts with current limit
        posts_query = f"""
            SELECT
                sp.title,
                sp.url,
                sp.created_at,
                aa.sentiment,
                aa.sentiment_score,
                aa.category,
                aa.summary
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            {where_clause}
            ORDER BY sp.created_at DESC
            LIMIT %s
        """
        query_params.append(st.session_state[f'posts_limit_{asset_id}'])
        posts_df = fetch_data(posts_query, tuple(query_params))

        if not posts_df.empty:
            # Display posts
            for _, post in posts_df.iterrows():
                # Create header with title, score, and category
                col1, col2, col3 = st.columns([6, 1.5, 1.5])
                with col1:
                    # Use expander for the title
                    expander_label = f"{get_sentiment_emoji(post['sentiment'])} {post['title'][:80]}..."
                with col2:
                    # Show sentiment score on the right
                    st.markdown(f"<div style='text-align: right; padding-top: 10px;'><strong>{post['sentiment_score']:+.2f}</strong></div>", unsafe_allow_html=True)
                with col3:
                    # Show category badge on the right
                    category_colors = {
                        'Hiring': '#28a745',
                        'Growth': '#17a2b8',
                        'Problems': '#dc3545',
                        'Product': '#ffc107',
                        'Earnings': '#6f42c1',
                        'Other': '#6c757d'
                    }
                    color = category_colors.get(post['category'], '#6c757d')
                    st.markdown(f"<div style='text-align: right; padding-top: 10px;'><span style='background-color: {color}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 0.85em;'>{post['category']}</span></div>", unsafe_allow_html=True)

                # Expander for details
                with st.expander(expander_label):
                    st.markdown(f"**Summary:** {post['summary']}")
                    st.markdown(f"[View Original Post]({post['url']})")
                    st.caption(f"Posted: {post['created_at']}")

            # Show "Load More" button if there are more posts
            if len(posts_df) < total_posts:
                remaining = total_posts - len(posts_df)
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if st.button(f"📥 Load More ({remaining} remaining)", key=f"load_more_{asset_id}", use_container_width=True):
                        st.session_state[f'posts_limit_{asset_id}'] += 20
                        st.rerun()
            else:
                st.caption(f"Showing all {total_posts} posts")
        else:
            st.info("No analyzed posts yet.")

# ============================================================================
# PAGE 3: ALERTS
# ============================================================================
elif page == "Alerts":
    # Filters
    col1, col2 = st.columns(2)

    with col1:
        assets_df = fetch_data("SELECT id, name FROM asset ORDER BY name")
        asset_filter = st.selectbox(
            "Filter by Asset",
            options=["All"] + assets_df['name'].tolist() if not assets_df.empty else ["All"]
        )

    with col2:
        alert_types = ["All", "long_signal", "short_signal", "hiring_signal", "risk_detected"]
        alert_type_filter = st.selectbox("Filter by Alert Type", options=alert_types)

    # Build query
    alerts_query = """
        SELECT
            a.timestamp,
            c.name as asset_name,
            c.ticker,
            a.alert_type,
            a.severity,
            a.description,
            a.confidence_score
        FROM alerts a
        JOIN asset c ON a.asset_id = c.id
        WHERE 1=1
    """
    params = []

    if asset_filter != "All":
        alerts_query += " AND c.name = %s"
        params.append(asset_filter)

    if alert_type_filter != "All":
        alerts_query += " AND a.alert_type = %s"
        params.append(alert_type_filter)

    alerts_query += " ORDER BY a.timestamp DESC LIMIT 100"

    alerts_df = fetch_data(alerts_query, tuple(params) if params else None)

    if not alerts_df.empty:
        st.subheader(f"Recent Alerts ({len(alerts_df)})")

        for _, alert in alerts_df.iterrows():
            # Get severity (default to 'medium' for backward compatibility)
            severity = alert.get('severity', 'medium')

            # Color code by alert type and severity
            # Using dark background to match dashboard theme
            bg_color = "#1E1E1E"  # Dark background for all alerts

            if alert['alert_type'] == 'long_signal':
                # Long signal (bullish) - green/blue colors
                if severity == 'high':
                    icon = "📈"
                    border_color = "#28a745"
                    severity_badge = "<span style='background-color: #28a745; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>STRONG LONG</span>"
                elif severity == 'medium':
                    icon = "📊"
                    border_color = "#20c997"
                    severity_badge = "<span style='background-color: #20c997; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>MODERATE LONG</span>"
                else:  # low
                    icon = "📊"
                    border_color = "#17a2b8"
                    severity_badge = "<span style='background-color: #17a2b8; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>WEAK LONG</span>"
            elif alert['alert_type'] == 'short_signal':
                # Short signal (bearish) - red/orange colors
                if severity == 'high':
                    icon = "📉"
                    border_color = "#dc3545"
                    severity_badge = "<span style='background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>STRONG SHORT</span>"
                elif severity == 'medium':
                    icon = "⚠️"
                    border_color = "#fd7e14"
                    severity_badge = "<span style='background-color: #fd7e14; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>MODERATE SHORT</span>"
                else:  # low
                    icon = "⚠️"
                    border_color = "#ffc107"
                    severity_badge = "<span style='background-color: #ffc107; color: #212529; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>WEAK SHORT</span>"
            # Special event alert types
            elif alert['alert_type'] == 'partnership':
                icon = "🤝"
                border_color = "#17a2b8"
                severity_badge = f"<span style='background-color: #17a2b8; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'product_launch':
                icon = "🚀"
                border_color = "#28a745"
                severity_badge = f"<span style='background-color: #28a745; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'regulatory_risk':
                icon = "⚖️"
                border_color = "#dc3545"
                severity_badge = f"<span style='background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'analyst_upgrade':
                icon = "📈"
                border_color = "#28a745"
                severity_badge = f"<span style='background-color: #28a745; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'analyst_downgrade':
                icon = "📉"
                border_color = "#dc3545"
                severity_badge = f"<span style='background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'market_share':
                icon = "📊"
                border_color = "#20c997"
                severity_badge = f"<span style='background-color: #20c997; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'customer_loss':
                icon = "👥"
                border_color = "#fd7e14"
                severity_badge = f"<span style='background-color: #fd7e14; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'executive_change':
                icon = "👔"
                border_color = "#6f42c1"
                severity_badge = f"<span style='background-color: #6f42c1; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'guidance':
                icon = "🎯"
                border_color = "#ffc107"
                severity_badge = f"<span style='background-color: #ffc107; color: #212529; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'insider_trading':
                icon = "💼"
                border_color = "#007bff"
                severity_badge = f"<span style='background-color: #007bff; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            # Legacy alert types (for backward compatibility)
            elif alert['alert_type'] == 'hiring_signal':
                icon = "💼"
                border_color = "#007bff"
                severity_badge = ""
            elif alert['alert_type'] == 'risk_detected':
                icon = "⚠️"
                border_color = "#dc3545"
                severity_badge = ""
            elif alert['alert_type'] == 'negative_sentiment':
                icon = "⚠️"
                border_color = "#dc3545"
                severity_badge = ""
            elif alert['alert_type'] == 'problem_detected':
                icon = "🔴"
                border_color = "#fd7e14"
                severity_badge = ""
            else:
                icon = "ℹ️"
                border_color = "#6c757d"
                severity_badge = ""

            with st.container():
                timestamp_str = alert['timestamp'].strftime('%Y-%m-%d %H:%M') if hasattr(alert['timestamp'], 'strftime') else alert['timestamp']
                st.markdown(f"""
                <div style="
                    padding: 15px;
                    border-left: 5px solid {border_color};
                    background-color: {bg_color};
                    margin-bottom: 15px;
                    border-radius: 5px;
                    color: #E0E0E0;
                ">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                        <div style="font-size: 16px; font-weight: bold; color: #FFFFFF;">
                            {icon} {alert['asset_name']} ({alert['ticker']}) {severity_badge}
                        </div>
                        <div style="font-size: 14px; font-weight: bold; text-align: right; color: #B0B0B0;">
                            Confidence: {alert['confidence_score']:.2f}<br>
                            {timestamp_str}
                        </div>
                    </div>
                    <div style="font-style: italic; color: #888888; margin-bottom: 8px;">
                        {alert['alert_type'].replace('_', ' ').title()}
                    </div>
                    <div style="color: #E0E0E0;">
                        {alert['description']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("No alerts found.")

# ============================================================================
# PAGE 4: SETTINGS
# ============================================================================
elif page == "Settings":
    # System status
    st.subheader("System Status")

    # Check database stats
    stats_query = """
        SELECT
            (SELECT COUNT(*) FROM asset) as asset_count,
            (SELECT COUNT(*) FROM social_posts) as post_count,
            (SELECT COUNT(*) FROM ai_analysis) as analyzed_count,
            (SELECT COUNT(*) FROM alerts) as alert_count
    """
    stats_df = fetch_data(stats_query)

    if not stats_df.empty:
        stats = stats_df.iloc[0]
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Assets", stats['asset_count'])
        with col2:
            st.metric("Posts Collected", stats['post_count'])
        with col3:
            st.metric("Posts Analyzed", stats['analyzed_count'])
        with col4:
            st.metric("Alerts Generated", stats['alert_count'])

    # Display existing companies
    st.markdown("---")
    st.subheader("Existing Assets")

    assets_df = fetch_data("""
        SELECT id, name, ticker, search_keywords, created_at,
               initialization_status, initialization_days,
               initialization_started_at, initialization_completed_at
        FROM asset
        ORDER BY name
    """)

    if not assets_df.empty:
        for _, asset in assets_df.iterrows():
            # Status badge
            status = asset.get('initialization_status', 'completed')
            if status == 'pending':
                status_badge = "🕐 Pending"
                status_color = "orange"
            elif status == 'in_progress':
                status_badge = "⏳ In Progress"
                status_color = "blue"
            elif status == 'completed':
                status_badge = "✅ Completed"
                status_color = "green"
            elif status == 'failed':
                status_badge = "❌ Failed"
                status_color = "red"
            else:
                status_badge = "❓ Unknown"
                status_color = "gray"

            with st.expander(f"{asset['name']} ({asset['ticker']}) - {status_badge}"):
                st.write(f"**Keywords:** {', '.join(asset['search_keywords'])}")
                st.caption(f"Added: {asset['created_at']}")

                # Edit Keywords
                st.markdown("---")
                st.markdown("**✏️ Edit Keywords**")

                with st.form(f"edit_keywords_form_{asset['id']}"):
                    current_keywords = '\n'.join(asset['search_keywords'])
                    new_keywords = st.text_area(
                        "Search Keywords (one per line)",
                        value=current_keywords,
                        height=100,
                        key=f"keywords_{asset['id']}",
                        help="Edit the keywords used to search for this asset in social media"
                    )

                    if st.form_submit_button("💾 Update Keywords", type="primary"):
                        if not new_keywords.strip():
                            st.error("Keywords cannot be empty.")
                        else:
                            # Parse keywords
                            keyword_list = [k.strip() for k in new_keywords.split('\n') if k.strip()]

                            # Update in database
                            conn = get_db_connection()
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        UPDATE asset
                                        SET search_keywords = %s
                                        WHERE id = %s
                                    """, (keyword_list, int(asset['id'])))
                                    conn.commit()
                                    st.success(f"Keywords updated for '{asset['name']}'!")
                            except Exception as e:
                                conn.rollback()
                                st.error(f"Error updating keywords: {e}")
                            finally:
                                conn.close()

                # Initialization info
                if status != 'completed':
                    st.markdown(f"**Initialization Status:** {status_badge}")
                    if asset.get('initialization_days'):
                        st.write(f"Historical days: {asset['initialization_days']}")
                    if asset.get('initialization_started_at'):
                        st.write(f"Started: {asset['initialization_started_at']}")

                    # Retry button for failed initializations
                    if status == 'failed':
                        if st.button(f"🔄 Retry Initialization", key=f"retry_{asset['id']}"):
                            conn = get_db_connection()
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        UPDATE asset
                                        SET initialization_status = 'pending',
                                            initialization_started_at = NULL
                                        WHERE id = %s
                                    """, (int(asset['id']),))
                                    conn.commit()
                                    st.success("✅ Asset marked for retry. Click 'Start Historical Data Collection' button above.")
                            except Exception as e:
                                conn.rollback()
                                st.error(f"Error: {e}")
                            finally:
                                conn.close()

                if asset.get('initialization_completed_at'):
                    st.caption(f"Initialization completed: {asset['initialization_completed_at']}")

                # Historical Data Collection for existing assets
                st.markdown("---")
                st.markdown("**📊 Collect Historical Data**")

                col1, col2 = st.columns([2, 1])
                with col1:
                    hist_days = st.slider(
                        "Days to collect",
                        min_value=7,
                        max_value=60,
                        value=30,
                        key=f"hist_days_{asset['id']}",
                        help="Collectors will use their maximum supported range if requested days exceed their limits"
                    )
                with col2:
                    st.write("")  # Spacer
                    st.write("")  # Spacer
                    if st.button("📥 Collect", key=f"collect_hist_{asset['id']}", type="primary"):
                        with st.spinner(f"Collecting {hist_days} days of historical data for {asset['name']}..."):
                            try:
                                # Import collector modules
                                from collector_factory import get_factory
                                import logging

                                # Get factory and collectors
                                factory = get_factory()
                                factory.auto_discover()

                                available_names = factory.list_available()

                                collectors_to_use = []
                                collector_errors = []

                                if 'newsapi' in available_names:
                                    collector = factory.create('newsapi', DATABASE_URL)
                                    if collector:
                                        collectors_to_use.append(collector)
                                    else:
                                        collector_errors.append("NewsAPI: Failed to initialize (check NEWSAPI_KEY in .env)")

                                if not collectors_to_use:
                                    st.error("❌ No collectors available for historical data collection")
                                    if collector_errors:
                                        st.warning("**Configuration issues:**")
                                        for error in collector_errors:
                                            st.write(f"• {error}")
                                    st.info("💡 **To enable NewsAPI collector:**\n"
                                          "1. Get a free API key from https://newsapi.org/register\n"
                                          "2. Add `NEWSAPI_KEY=your_key_here` to the `.env` file\n"
                                          "3. Restart the dashboard container: `docker-compose restart dashboard`")
                                else:
                                    # Mark asset as pending before starting
                                    conn = get_db_connection()
                                    try:
                                        with conn.cursor() as cur:
                                            cur.execute("""
                                                UPDATE asset
                                                SET initialization_status = 'in_progress',
                                                    initialization_days = %s,
                                                    initialization_started_at = NOW()
                                                WHERE id = %s
                                            """, (hist_days, int(asset['id'])))
                                            conn.commit()
                                    finally:
                                        conn.close()

                                    # Collect data
                                    total_saved = 0
                                    for collector in collectors_to_use:
                                        try:
                                            result = collector.initialize_asset(int(asset['id']), hist_days)
                                            total_saved += result['total_saved']
                                        except Exception as e:
                                            st.error(f"❌ Error during collection: {e}")
                                            # Mark as failed
                                            conn = get_db_connection()
                                            try:
                                                with conn.cursor() as cur:
                                                    cur.execute("""
                                                        UPDATE asset
                                                        SET initialization_status = 'failed'
                                                        WHERE id = %s
                                                    """, (int(asset['id']),))
                                                    conn.commit()
                                            finally:
                                                conn.close()
                                            raise

                                    # Mark as completed
                                    conn = get_db_connection()
                                    try:
                                        with conn.cursor() as cur:
                                            cur.execute("""
                                                UPDATE asset
                                                SET initialization_status = 'completed',
                                                    initialization_completed_at = NOW()
                                                WHERE id = %s
                                            """, (int(asset['id']),))
                                            conn.commit()
                                    finally:
                                        conn.close()

                                    st.success(f"✅ Collected {total_saved} new posts for {asset['name']}!")
                                    st.info("🔄 Refresh the page to see updated data")

                            except Exception as e:
                                st.error(f"❌ Collection failed: {e}")
                                import traceback
                                with st.expander("View Error Details"):
                                    st.code(traceback.format_exc())

                # Delete asset button
                st.markdown("---")
                col1, col2 = st.columns([3, 1])
                with col2:
                    if st.button("🗑️ Delete", key=f"delete_{asset['id']}", type="secondary"):
                        # Confirmation using session state
                        st.session_state[f"confirm_delete_{asset['id']}"] = True

                # Show confirmation dialog
                if st.session_state.get(f"confirm_delete_{asset['id']}", False):
                    st.warning(f"⚠️ Are you sure you want to delete **{asset['name']}**? This will also delete all related posts, analysis, metrics, and alerts.")
                    col1, col2, col3 = st.columns([1, 1, 2])

                    with col1:
                        if st.button("✓ Yes, Delete", key=f"confirm_yes_{asset['id']}", type="primary"):
                            conn = get_db_connection()
                            try:
                                with conn.cursor() as cur:
                                    # Delete in correct order (dependencies first)
                                    # 1. Notification preferences
                                    cur.execute("DELETE FROM alert_notification_preferences WHERE asset_id = %s", (int(asset['id']),))

                                    # 2. AI analysis (references social_posts)
                                    cur.execute("DELETE FROM ai_analysis WHERE post_id IN (SELECT id FROM social_posts WHERE asset_id = %s)", (int(asset['id']),))

                                    # 3. Social posts
                                    cur.execute("DELETE FROM social_posts WHERE asset_id = %s", (int(asset['id']),))

                                    # 4. Daily metrics
                                    cur.execute("DELETE FROM daily_metrics WHERE asset_id = %s", (int(asset['id']),))

                                    # 5. Alerts (and their notification logs via CASCADE)
                                    cur.execute("DELETE FROM notification_log WHERE alert_id IN (SELECT id FROM alerts WHERE asset_id = %s)", (int(asset['id']),))
                                    cur.execute("DELETE FROM alerts WHERE asset_id = %s", (int(asset['id']),))

                                    # 6. Finally delete the asset
                                    cur.execute("DELETE FROM asset WHERE id = %s", (int(asset['id']),))

                                    conn.commit()
                                    st.success(f"✅ Asset '{asset['name']}' deleted successfully!")
                                    st.info("🔄 Refresh the page to see updated list")
                                    # Clear confirmation state
                                    del st.session_state[f"confirm_delete_{asset['id']}"]
                            except Exception as e:
                                conn.rollback()
                                st.error(f"❌ Error deleting asset: {e}")
                            finally:
                                conn.close()

                    with col2:
                        if st.button("✗ Cancel", key=f"confirm_no_{asset['id']}"):
                            # Clear confirmation state
                            del st.session_state[f"confirm_delete_{asset['id']}"]
                            st.rerun()
    else:
        st.info("No assets configured yet.")

    st.markdown("---")
    st.subheader("📊 Keyword Performance")
    st.markdown("""
    Track which keywords are finding posts and identify underperforming ones.
    Remove keywords that haven't found posts recently to keep your searches efficient.
    """)

    # Show keyword performance for existing assets
    if not assets_df.empty:
        with st.expander("📈 View Keyword Performance", expanded=False):
            # Select asset for performance view
            asset_options = {row['name']: row['id'] for _, row in assets_df.iterrows()}
            selected_perf_asset_name = st.selectbox(
                "Select asset to view keyword performance",
                options=list(asset_options.keys()),
                key="keyword_perf_asset"
            )
            selected_perf_asset_id = asset_options[selected_perf_asset_name]

            # Import KeywordTracker
            import sys
            from pathlib import Path
            shared_path = Path(__file__).parent / 'shared'
            if not shared_path.exists():
                shared_path = Path(__file__).parent.parent / 'shared'
            sys.path.insert(0, str(shared_path))

            from keyword_tracker import KeywordTracker
            keyword_tracker = KeywordTracker(database_url=DATABASE_URL)

            # Initialize tracking for this asset if not already done
            keyword_tracker.initialize_keyword_tracking(selected_perf_asset_id)

            # Get performance stats
            performance = keyword_tracker.get_keyword_performance(selected_perf_asset_id)
            summary = keyword_tracker.get_keyword_stats_summary(selected_perf_asset_id)

            if summary and summary['total_keywords'] > 0:
                # Show summary stats
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Keywords", summary['total_keywords'])
                with col2:
                    st.metric("Total Posts Found", summary['total_posts_found'] or 0)
                with col3:
                    st.metric("Avg Posts/Keyword", f"{summary['avg_posts_per_keyword']:.1f}" if summary['avg_posts_per_keyword'] else "0.0")
                with col4:
                    st.metric("Never Matched", summary['never_matched'] or 0)

                st.markdown("---")

                # Show performance table
                if performance:
                    import pandas as pd

                    perf_df = pd.DataFrame(performance)
                    perf_df['last_found_at'] = pd.to_datetime(perf_df['last_found_at'])
                    perf_df['days_since_last_hit'] = perf_df['days_since_last_hit'].fillna(perf_df['days_tracked'])

                    # Format for display
                    display_df = perf_df[['keyword', 'posts_found', 'days_since_last_hit', 'last_found_at']].copy()
                    display_df['last_found_at'] = display_df['last_found_at'].apply(
                        lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notna(x) else 'Never'
                    )
                    display_df['days_since_last_hit'] = display_df['days_since_last_hit'].apply(
                        lambda x: f"{int(x)} days" if pd.notna(x) else 'N/A'
                    )
                    display_df.columns = ['Keyword', 'Posts Found', 'Days Since Last Hit', 'Last Found']

                    st.dataframe(display_df, use_container_width=True, hide_index=True)

                    # Identify underperforming keywords
                    st.markdown("---")
                    st.markdown("#### 🔴 Underperforming Keywords")

                    min_days_inactive = st.slider(
                        "Days inactive to consider underperforming",
                        min_value=7,
                        max_value=90,
                        value=30,
                        help="Keywords that haven't found posts in this many days"
                    )

                    underperforming = keyword_tracker.get_underperforming_keywords(
                        selected_perf_asset_id,
                        min_days_inactive=min_days_inactive,
                        min_posts_threshold=5
                    )

                    if underperforming:
                        st.warning(f"Found {len(underperforming)} underperforming keywords")

                        underperf_df = pd.DataFrame(underperforming)
                        underperf_df['days_since_last_hit'] = underperf_df['days_since_last_hit'].apply(
                            lambda x: f"{int(x)} days" if pd.notna(x) else 'Never'
                        )
                        display_underperf = underperf_df[['keyword', 'posts_found', 'days_since_last_hit']].copy()
                        display_underperf.columns = ['Keyword', 'Posts Found', 'Days Since Last Hit']

                        st.dataframe(display_underperf, use_container_width=True, hide_index=True)

                        # Auto-remove button
                        st.markdown("---")
                        if st.button(f"🗑️ Remove All {len(underperforming)} Underperforming Keywords", type="primary"):
                            keywords_to_remove = [kw['keyword'] for kw in underperforming]
                            removed_count = keyword_tracker.remove_keywords_from_asset(
                                selected_perf_asset_id,
                                keywords_to_remove
                            )
                            if removed_count > 0:
                                st.success(f"✅ Removed {removed_count} underperforming keywords from {selected_perf_asset_name}")
                                st.info("🔄 Refresh the page to see updated keywords")
                            else:
                                st.error("Failed to remove keywords")
                    else:
                        st.success("✅ All keywords are performing well!")

                else:
                    st.info("No keyword performance data yet. Keywords will be tracked as posts are collected.")
            else:
                st.info("No keywords configured for this asset yet.")
    else:
        st.info("Add an asset first to view keyword performance.")

    st.markdown("---")
    st.subheader("🔍 Smart Keyword Suggestions")
    st.markdown("""
    Use AI to automatically discover new keywords based on collected posts.
    Claude will analyze your posts and suggest relevant terms you might be missing.
    """)

    # Show keyword suggestions for existing assets
    if not assets_df.empty:
        with st.expander("🤖 Get AI-Powered Keyword Suggestions", expanded=False):
            # Select asset for suggestions
            asset_options = {row['name']: row['id'] for _, row in assets_df.iterrows()}
            selected_asset_name = st.selectbox(
                "Select asset to get keyword suggestions",
                options=list(asset_options.keys()),
                key="keyword_suggest_asset"
            )

            max_suggestions = st.slider(
                "Number of keywords to suggest",
                min_value=5,
                max_value=20,
                value=10,
                help="Maximum number of keyword suggestions"
            )

            if st.button("🔍 Generate Keyword Suggestions", type="primary"):
                selected_asset_id = asset_options[selected_asset_name]

                with st.spinner(f"Analyzing posts for {selected_asset_name}..."):
                    try:
                        # Import and use KeywordSuggester
                        import sys
                        from pathlib import Path
                        shared_path = Path(__file__).parent / 'shared'
                        if not shared_path.exists():
                            shared_path = Path(__file__).parent.parent / 'shared'
                        sys.path.insert(0, str(shared_path))

                        from keyword_suggester import KeywordSuggester

                        suggester = KeywordSuggester(
                            database_url=DATABASE_URL,
                            anthropic_api_key=ANTHROPIC_API_KEY
                        )

                        suggested_keywords = suggester.suggest_keywords(
                            selected_asset_id,
                            max_keywords=max_suggestions
                        )

                        if suggested_keywords:
                            st.success(f"✅ Found {len(suggested_keywords)} keyword suggestions!")

                            # Display suggestions with add buttons
                            st.markdown("**Suggested Keywords:**")

                            # Store suggestions in session state for adding
                            if 'keyword_suggestions' not in st.session_state:
                                st.session_state.keyword_suggestions = {}
                            st.session_state.keyword_suggestions[selected_asset_id] = suggested_keywords

                            # Display in columns
                            cols_per_row = 3
                            for i in range(0, len(suggested_keywords), cols_per_row):
                                cols = st.columns(cols_per_row)
                                for j, keyword in enumerate(suggested_keywords[i:i+cols_per_row]):
                                    with cols[j]:
                                        # Create unique key for each button
                                        button_key = f"add_kw_{selected_asset_id}_{keyword.replace(' ', '_')}"
                                        if st.button(f"➕ {keyword}", key=button_key, use_container_width=True):
                                            # Add keyword to asset
                                            conn = get_db_connection()
                                            try:
                                                with conn.cursor() as cur:
                                                    # Get current keywords
                                                    cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (selected_asset_id,))
                                                    current_keywords = cur.fetchone()[0]

                                                    # Add new keyword if not already present
                                                    if keyword.lower() not in [kw.lower() for kw in current_keywords]:
                                                        current_keywords.append(keyword.lower())
                                                        cur.execute(
                                                            "UPDATE asset SET search_keywords = %s WHERE id = %s",
                                                            (current_keywords, selected_asset_id)
                                                        )
                                                        conn.commit()
                                                        st.success(f"✅ Added '{keyword}' to {selected_asset_name}")
                                                        st.rerun()
                                                    else:
                                                        st.info(f"'{keyword}' already exists")
                                            except Exception as e:
                                                conn.rollback()
                                                st.error(f"Error adding keyword: {e}")
                                            finally:
                                                conn.close()

                            # Add all button
                            if st.button("➕ Add All Suggestions", type="secondary"):
                                conn = get_db_connection()
                                try:
                                    with conn.cursor() as cur:
                                        # Get current keywords
                                        cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (selected_asset_id,))
                                        current_keywords = cur.fetchone()[0]
                                        current_keywords_lower = [kw.lower() for kw in current_keywords]

                                        # Add all new keywords
                                        new_count = 0
                                        for keyword in suggested_keywords:
                                            if keyword.lower() not in current_keywords_lower:
                                                current_keywords.append(keyword.lower())
                                                new_count += 1

                                        if new_count > 0:
                                            cur.execute(
                                                "UPDATE asset SET search_keywords = %s WHERE id = %s",
                                                (current_keywords, selected_asset_id)
                                            )
                                            conn.commit()
                                            st.success(f"✅ Added {new_count} new keywords to {selected_asset_name}")
                                            st.rerun()
                                        else:
                                            st.info("All suggested keywords already exist")
                                except Exception as e:
                                    conn.rollback()
                                    st.error(f"Error adding keywords: {e}")
                                finally:
                                    conn.close()

                        else:
                            st.warning("No new keyword suggestions found. The asset might need more posts, or all relevant keywords may already be configured.")

                    except Exception as e:
                        st.error(f"Error generating suggestions: {e}")
                        import traceback
                        with st.expander("View Error Details"):
                            st.code(traceback.format_exc())
    else:
        st.info("Add an asset first to get keyword suggestions.")

    st.markdown("---")
    st.markdown("#### 📊 Add New Asset")
    with st.expander("Add New Asset to Track", expanded=False):
        st.markdown("""
        Add a new company or asset to monitor. The system will start collecting and analyzing news for this asset.
        """)

        with st.form("add_asset_form"):
            asset_name = st.text_input("Asset Name", placeholder="e.g., Tesla")
            ticker = st.text_input("Stock Ticker", placeholder="e.g., TSLA")
            keywords = st.text_area(
                "Search Keywords (one per line)",
                placeholder="tesla\ntsla\nelon musk"
            )

            st.markdown("**Historical Data Collection**")
            collect_historical = st.checkbox(
                "Collect historical data (recommended)",
                value=True,
                help="Automatically collect and analyze news from the past 30 days"
            )

            if collect_historical:
                historical_days = st.slider(
                    "Days of historical data",
                    min_value=7,
                    max_value=60,
                    value=30,
                    help="Collectors will use their maximum supported range if requested days exceed their limits"
                )
            else:
                historical_days = 0

            submitted = st.form_submit_button("Add Asset", type="primary")

            if submitted:
                if not asset_name or not ticker or not keywords:
                    st.error("All fields are required.")
                else:
                    # Parse keywords
                    keyword_list = [k.strip() for k in keywords.split('\n') if k.strip()]

                    # Insert into database
                    conn = get_db_connection()
                    try:
                        with conn.cursor() as cur:
                            if collect_historical:
                                # Add with pending initialization status
                                cur.execute("""
                                    INSERT INTO asset (name, ticker, search_keywords,
                                                         initialization_status, initialization_days)
                                    VALUES (%s, %s, %s, 'pending', %s)
                                """, (asset_name, ticker, keyword_list, historical_days))
                            else:
                                # Add as completed (no historical collection)
                                cur.execute("""
                                    INSERT INTO asset (name, ticker, search_keywords,
                                                         initialization_status)
                                    VALUES (%s, %s, %s, 'completed')
                                """, (asset_name, ticker, keyword_list))
                            conn.commit()

                            if collect_historical:
                                st.success(f"Asset '{asset_name}' added! Historical data collection will begin automatically.")
                                st.info(f"📊 The system will collect news from the past {historical_days} days. Check the collector logs for progress.")
                            else:
                                st.success(f"Asset '{asset_name}' added successfully!")
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error adding asset: {e}")
                    finally:
                        conn.close()

    st.markdown("---")

    # Notification Settings
    st.subheader("🔔 Notification Settings")

    st.markdown("""
    Configure how you want to be notified when high-confidence alerts are generated.
    Supported channels: Email, SMS, Push (Pushover), Webhook
    """)

    # Get all assets for notification preferences
    assets_for_notif = fetch_data("SELECT id, name, ticker FROM asset ORDER BY name")

    # Load existing notification settings from database
    existing_settings = fetch_data("SELECT * FROM notification_settings WHERE id = 1")
    current_email = existing_settings['notification_email'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['notification_email'].iloc[0]) else ''
    current_phone = existing_settings['notification_phone'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['notification_phone'].iloc[0]) else ''
    current_smtp_user = existing_settings['smtp_user'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['smtp_user'].iloc[0]) else ''
    current_smtp_password = existing_settings['smtp_password'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['smtp_password'].iloc[0]) else ''
    current_check_interval = int(existing_settings['check_interval'].iloc[0]) if not existing_settings.empty and pd.notna(existing_settings['check_interval'].iloc[0]) else 5

    # Load collection schedule settings
    current_smart_scheduling = bool(existing_settings['enable_smart_scheduling'].iloc[0]) if not existing_settings.empty and 'enable_smart_scheduling' in existing_settings.columns and pd.notna(existing_settings['enable_smart_scheduling'].iloc[0]) else True
    current_interval_market = int(existing_settings['collection_interval_market_hours'].iloc[0]) if not existing_settings.empty and 'collection_interval_market_hours' in existing_settings.columns and pd.notna(existing_settings['collection_interval_market_hours'].iloc[0]) else 15
    current_interval_after = int(existing_settings['collection_interval_after_hours'].iloc[0]) if not existing_settings.empty and 'collection_interval_after_hours' in existing_settings.columns and pd.notna(existing_settings['collection_interval_after_hours'].iloc[0]) else 30
    current_interval_weekend = int(existing_settings['collection_interval_weekends'].iloc[0]) if not existing_settings.empty and 'collection_interval_weekends' in existing_settings.columns and pd.notna(existing_settings['collection_interval_weekends'].iloc[0]) else 120
    current_interval_fixed = int(existing_settings['collection_interval_fixed'].iloc[0]) if not existing_settings.empty and 'collection_interval_fixed' in existing_settings.columns and pd.notna(existing_settings['collection_interval_fixed'].iloc[0]) else 30
    current_market_open_hour = int(existing_settings['market_open_hour'].iloc[0]) if not existing_settings.empty and 'market_open_hour' in existing_settings.columns and pd.notna(existing_settings['market_open_hour'].iloc[0]) else 9
    current_market_open_minute = int(existing_settings['market_open_minute'].iloc[0]) if not existing_settings.empty and 'market_open_minute' in existing_settings.columns and pd.notna(existing_settings['market_open_minute'].iloc[0]) else 30
    current_market_close_hour = int(existing_settings['market_close_hour'].iloc[0]) if not existing_settings.empty and 'market_close_hour' in existing_settings.columns and pd.notna(existing_settings['market_close_hour'].iloc[0]) else 16
    current_market_close_minute = int(existing_settings['market_close_minute'].iloc[0]) if not existing_settings.empty and 'market_close_minute' in existing_settings.columns and pd.notna(existing_settings['market_close_minute'].iloc[0]) else 0

    # Load existing alert preferences (get first asset's settings as default)
    existing_prefs = fetch_data("""
        SELECT alert_type, min_confidence, notification_channels, quiet_hours_start, quiet_hours_end, enabled
        FROM alert_notification_preferences
        ORDER BY id
        LIMIT 3
    """)

    # Parse existing preferences
    long_prefs = existing_prefs[existing_prefs['alert_type'] == 'long_signal'].iloc[0] if not existing_prefs.empty and 'long_signal' in existing_prefs['alert_type'].values else None
    short_prefs = existing_prefs[existing_prefs['alert_type'] == 'short_signal'].iloc[0] if not existing_prefs.empty and 'short_signal' in existing_prefs['alert_type'].values else None

    # Legacy support - migrate old preferences to new format
    if long_prefs is None:
        hiring_prefs = existing_prefs[existing_prefs['alert_type'] == 'hiring_signal'].iloc[0] if not existing_prefs.empty and 'hiring_signal' in existing_prefs['alert_type'].values else None
        long_prefs = hiring_prefs  # Use hiring_signal as fallback for long_signal

    if short_prefs is None:
        risk_prefs = existing_prefs[existing_prefs['alert_type'] == 'risk_detected'].iloc[0] if not existing_prefs.empty and 'risk_detected' in existing_prefs['alert_type'].values else None
        if risk_prefs is None:
            negative_prefs = existing_prefs[existing_prefs['alert_type'] == 'negative_sentiment'].iloc[0] if not existing_prefs.empty and 'negative_sentiment' in existing_prefs['alert_type'].values else None
            problem_prefs = existing_prefs[existing_prefs['alert_type'] == 'problem_detected'].iloc[0] if not existing_prefs.empty and 'problem_detected' in existing_prefs['alert_type'].values else None
            risk_prefs = negative_prefs if negative_prefs is not None else problem_prefs
        short_prefs = risk_prefs  # Use risk_detected as fallback for short_signal

    if not assets_for_notif.empty:
        with st.form("notification_settings_form"):
            # Check Interval (global setting outside expanders)
            check_interval = st.number_input(
                "Check Interval (minutes)",
                min_value=1,
                max_value=60,
                value=current_check_interval,
                help="How often to check for new alerts"
            )

            st.markdown("---")

            # Collection Schedule Settings
            st.markdown("#### 📅 Collection Schedule")
            with st.expander("Configure News Collection Frequency", expanded=False):
                st.markdown("""
                Control how often the collector fetches new posts from social media sources.
                Smart scheduling adjusts collection frequency based on market hours.
                """)

                enable_smart_scheduling = st.checkbox(
                    "Enable Smart Scheduling",
                    value=current_smart_scheduling,
                    help="Automatically adjust collection frequency based on market hours"
                )

                if enable_smart_scheduling:
                    st.markdown("**Market Hours** (US Eastern Time)")
                    col_mkt1, col_mkt2 = st.columns(2)
                    with col_mkt1:
                        market_open_hour = st.number_input(
                            "Market Open Hour (0-23)",
                            min_value=0,
                            max_value=23,
                            value=current_market_open_hour,
                            help="Hour when market opens (ET)"
                        )
                        market_open_minute = st.number_input(
                            "Market Open Minute (0-59)",
                            min_value=0,
                            max_value=59,
                            value=current_market_open_minute,
                            help="Minute when market opens"
                        )
                    with col_mkt2:
                        market_close_hour = st.number_input(
                            "Market Close Hour (0-23)",
                            min_value=0,
                            max_value=23,
                            value=current_market_close_hour,
                            help="Hour when market closes (ET)"
                        )
                        market_close_minute = st.number_input(
                            "Market Close Minute (0-59)",
                            min_value=0,
                            max_value=59,
                            value=current_market_close_minute,
                            help="Minute when market closes"
                        )

                    st.markdown("**Collection Intervals** (minutes)")
                    col_int1, col_int2, col_int3 = st.columns(3)
                    with col_int1:
                        interval_market_hours = st.number_input(
                            "During Market Hours",
                            min_value=5,
                            max_value=120,
                            value=current_interval_market,
                            help="Collection frequency during market hours"
                        )
                    with col_int2:
                        interval_after_hours = st.number_input(
                            "After Market Hours",
                            min_value=5,
                            max_value=240,
                            value=current_interval_after,
                            help="Collection frequency after market closes"
                        )
                    with col_int3:
                        interval_weekends = st.number_input(
                            "Weekends",
                            min_value=15,
                            max_value=480,
                            value=current_interval_weekend,
                            help="Collection frequency on weekends"
                        )
                else:
                    # Use fixed interval when smart scheduling disabled
                    interval_fixed = st.number_input(
                        "Fixed Collection Interval (minutes)",
                        min_value=5,
                        max_value=240,
                        value=current_interval_fixed,
                        help="Collection frequency (same at all times)"
                    )
                    # Set other values to defaults to satisfy database requirements
                    market_open_hour = current_market_open_hour
                    market_open_minute = current_market_open_minute
                    market_close_hour = current_market_close_hour
                    market_close_minute = current_market_close_minute
                    interval_market_hours = current_interval_market
                    interval_after_hours = current_interval_after
                    interval_weekends = current_interval_weekend

            st.markdown("---")

            # Email Settings
            st.markdown("#### Email Settings (SMTP)")
            with st.expander("Configure Email Notifications", expanded=False):
                col1, col2 = st.columns(2)

                with col1:
                    notification_email = st.text_input(
                        "Email Address",
                        value=current_email,
                        help="Email address to receive alerts"
                    )

                    smtp_user = st.text_input(
                        "SMTP Username (for sending email)",
                        value=current_smtp_user,
                        help="Your SMTP username (often your email address)"
                    )

                with col2:
                    smtp_password = st.text_input(
                        "SMTP Password",
                        value=current_smtp_password,
                        type="password",
                        help="Your SMTP password or app-specific password"
                    )

            # SMS/Twilio Settings
            st.markdown("#### SMS Settings (Twilio)")
            with st.expander("Configure SMS Notifications", expanded=False):
                col_sms1, col_sms2 = st.columns(2)

                # Load current Twilio settings
                current_twilio_sid = existing_settings['twilio_account_sid'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('twilio_account_sid', pd.Series([None])).iloc[0]) else ''
                current_twilio_token = existing_settings['twilio_auth_token'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('twilio_auth_token', pd.Series([None])).iloc[0]) else ''
                current_twilio_from = existing_settings['twilio_from_number'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('twilio_from_number', pd.Series([None])).iloc[0]) else ''

                with col_sms1:
                    notification_phone = st.text_input(
                        "Your Phone Number (To)",
                        value=current_phone,
                        help="Phone number to receive SMS (e.g., +1234567890)"
                    )

                    twilio_account_sid = st.text_input(
                        "Twilio Account SID",
                        value=current_twilio_sid,
                        help="Get from https://www.twilio.com/console"
                    )

                with col_sms2:
                    twilio_from_number = st.text_input(
                        "Twilio Phone Number (From)",
                        value=current_twilio_from,
                        help="Your Twilio phone number (e.g., +1987654321)"
                    )

                    twilio_auth_token = st.text_input(
                        "Twilio Auth Token",
                        value=current_twilio_token,
                        type="password",
                        help="Your Twilio auth token"
                    )

            # Push/Pushover Settings
            st.markdown("#### Push Notifications (Pushover)")
            with st.expander("Configure Push Notifications", expanded=False):
                col_push1, col_push2 = st.columns(2)

                # Load current Pushover settings
                current_pushover_token = existing_settings['pushover_token'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('pushover_token', pd.Series([None])).iloc[0]) else ''
                current_pushover_user = existing_settings['pushover_user'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('pushover_user', pd.Series([None])).iloc[0]) else ''

                with col_push1:
                    pushover_token = st.text_input(
                        "Pushover App Token",
                        value=current_pushover_token,
                        type="password",
                        help="Get from https://pushover.net/"
                    )

                with col_push2:
                    pushover_user = st.text_input(
                        "Pushover User Key",
                        value=current_pushover_user,
                        help="Your Pushover user/group key"
                    )

            # Webhook Settings
            st.markdown("#### Webhook Notifications")
            with st.expander("Configure Webhook", expanded=False):
                # Load current webhook settings
                current_webhook_url = existing_settings['webhook_url'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('webhook_url', pd.Series([None])).iloc[0]) else ''

                webhook_url = st.text_input(
                    "Webhook URL",
                    value=current_webhook_url,
                    help="Custom HTTP endpoint to receive alert notifications (POST requests with JSON payload)"
                )

            st.markdown("#### 🔔 Alert Type Preferences")
            with st.expander("Configure Alert Types and Thresholds", expanded=False):
                st.markdown("""
                Configure which alert types to receive and set minimum confidence thresholds for each type.
                """)

                col_long, col_short = st.columns(2)

                with col_long:
                    st.markdown("**📈 Long Signal (Bullish)**")
                    st.caption("Hiring, growth, earnings beats, positive indicators")
                    long_enabled = st.checkbox(
                        "Enable",
                        value=long_prefs['enabled'] if long_prefs is not None else True,
                        key="long_enabled"
                    )
                    long_confidence = st.slider(
                        "Min Confidence",
                        0.0, 1.0,
                        float(long_prefs['min_confidence']) if long_prefs is not None else 0.85,
                        0.05,
                        key="long_conf",
                        disabled=not long_enabled
                    )
                    long_channels = st.multiselect(
                        "Channels",
                        ['email', 'sms', 'push', 'webhook'],
                        default=long_prefs['notification_channels'] if long_prefs is not None else ['email'],
                        key="long_channels",
                        disabled=not long_enabled
                    )

                with col_short:
                    st.markdown("**📉 Short Signal (Bearish)**")
                    st.caption("Problems, negative sentiment, downgrades (severity: weak/moderate/strong)")
                    short_enabled = st.checkbox(
                        "Enable",
                        value=short_prefs['enabled'] if short_prefs is not None else True,
                        key="short_enabled"
                    )
                    short_confidence = st.slider(
                        "Min Confidence",
                        0.0, 1.0,
                        float(short_prefs['min_confidence']) if short_prefs is not None else 0.80,
                        0.05,
                        key="short_conf",
                        disabled=not short_enabled
                    )
                    short_channels = st.multiselect(
                        "Channels",
                        ['email', 'sms', 'push', 'webhook'],
                        default=short_prefs['notification_channels'] if short_prefs is not None else ['email'],
                        key="short_channels",
                        disabled=not short_enabled
                    )

            # AI Analysis Prompt Configuration
            st.markdown("---")
            st.markdown("#### 🤖 AI Analysis Prompt")
            with st.expander("Configure Claude AI Analysis Prompt", expanded=False):
                st.markdown("""
                Customize the prompt sent to Claude AI for analyzing social media posts.

                **Available placeholders:**
                - `{asset_name}`: Company name
                - `{ticker}`: Stock ticker symbol
                - `{text_to_analyze}`: The post title and content

                The prompt should instruct Claude to return JSON with: sentiment, sentiment_score, category, key_topics, and summary.
                """)

                # Load current prompt from database
                current_prompt_df = fetch_data("SELECT analysis_prompt FROM notification_settings WHERE id = 1")
                current_prompt = current_prompt_df['analysis_prompt'].iloc[0] if not current_prompt_df.empty and pd.notna(current_prompt_df['analysis_prompt'].iloc[0]) else """Analyze this social media post about {asset_name} ({ticker}) from a trading perspective.

{text_to_analyze}

Provide your analysis in JSON format with these fields:
- sentiment: one of "positive", "negative", or "neutral"
- sentiment_score: a number between -1.0 (very bearish/short signal) and 1.0 (very bullish/long signal)
- category: one of "Hiring", "Growth", "Problems", "Product", "Earnings", "Other"
- key_topics: array of 2-5 key topics or themes (as strings)
- summary: brief summary in 1-2 sentences (max 100 words)

Focus on identifying trading signals:
- BULLISH (long signals): hiring, partnerships, product launches, earnings beats, growth indicators, positive guidance
- BEARISH (short signals): problems, layoffs, negative sentiment, downgrades, missed earnings, legal issues

Return ONLY valid JSON, no other text."""

                analysis_prompt = st.text_area(
                    "Analysis Prompt Template",
                    value=current_prompt,
                    height=400,
                    help="The prompt template for Claude AI analysis. Use {asset_name}, {ticker}, and {text_to_analyze} as placeholders."
                )

                st.caption("Changes will take effect for new analyses after saving.")

            st.markdown("#### 🌙 Quiet Hours")
            with st.expander("Configure Quiet Hours", expanded=False):
                st.markdown("""
                Set time periods when you don't want to receive notifications. Alerts will still be generated but not sent during quiet hours.
                """)

                quiet_col1, quiet_col2 = st.columns(2)

                # Get quiet hours from existing prefs (use first available)
                current_quiet_start = long_prefs['quiet_hours_start'] if long_prefs is not None else None
                current_quiet_end = long_prefs['quiet_hours_end'] if long_prefs is not None else None

                with quiet_col1:
                    quiet_start = st.time_input(
                        "Quiet Hours Start",
                        value=current_quiet_start if current_quiet_start else datetime.strptime("22:00", "%H:%M").time(),
                        help="Don't send notifications after this time"
                    )

                with quiet_col2:
                    quiet_end = st.time_input(
                        "Quiet Hours End",
                        value=current_quiet_end if current_quiet_end else datetime.strptime("07:00", "%H:%M").time(),
                        help="Resume notifications after this time"
                    )

            submit_notif = st.form_submit_button("💾 Save All Settings", type="primary")

            if submit_notif:
                conn1 = None
                conn2 = None
                try:
                    # Update global notification settings in database
                    conn1 = get_db_connection()
                    with conn1.cursor() as cur:
                        # Update or insert notification settings
                        cur.execute("""
                            INSERT INTO notification_settings
                            (id, notification_email, notification_phone, smtp_host, smtp_port,
                             smtp_user, smtp_password, smtp_from,
                             twilio_account_sid, twilio_auth_token, twilio_from_number,
                             pushover_token, pushover_user, webhook_url,
                             check_interval, analysis_prompt,
                             enable_smart_scheduling, collection_interval_market_hours,
                             collection_interval_after_hours, collection_interval_weekends,
                             collection_interval_fixed, market_open_hour, market_open_minute,
                             market_close_hour, market_close_minute,
                             updated_at)
                            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                notification_email = EXCLUDED.notification_email,
                                notification_phone = EXCLUDED.notification_phone,
                                smtp_host = EXCLUDED.smtp_host,
                                smtp_port = EXCLUDED.smtp_port,
                                smtp_user = EXCLUDED.smtp_user,
                                smtp_password = EXCLUDED.smtp_password,
                                smtp_from = EXCLUDED.smtp_from,
                                twilio_account_sid = EXCLUDED.twilio_account_sid,
                                twilio_auth_token = EXCLUDED.twilio_auth_token,
                                twilio_from_number = EXCLUDED.twilio_from_number,
                                pushover_token = EXCLUDED.pushover_token,
                                pushover_user = EXCLUDED.pushover_user,
                                webhook_url = EXCLUDED.webhook_url,
                                check_interval = EXCLUDED.check_interval,
                                analysis_prompt = EXCLUDED.analysis_prompt,
                                enable_smart_scheduling = EXCLUDED.enable_smart_scheduling,
                                collection_interval_market_hours = EXCLUDED.collection_interval_market_hours,
                                collection_interval_after_hours = EXCLUDED.collection_interval_after_hours,
                                collection_interval_weekends = EXCLUDED.collection_interval_weekends,
                                collection_interval_fixed = EXCLUDED.collection_interval_fixed,
                                market_open_hour = EXCLUDED.market_open_hour,
                                market_open_minute = EXCLUDED.market_open_minute,
                                market_close_hour = EXCLUDED.market_close_hour,
                                market_close_minute = EXCLUDED.market_close_minute,
                                updated_at = NOW()
                        """, (notification_email, notification_phone,
                              'smtp.gmail.com', 587, smtp_user, smtp_password, smtp_user,
                              twilio_account_sid or None, twilio_auth_token or None, twilio_from_number or None,
                              pushover_token or None, pushover_user or None, webhook_url or None,
                              check_interval, analysis_prompt,
                              enable_smart_scheduling, interval_market_hours,
                              interval_after_hours, interval_weekends,
                              interval_fixed, market_open_hour, market_open_minute,
                              market_close_hour, market_close_minute))
                        conn1.commit()

                    # Update database preferences for all companies
                    conn2 = get_db_connection()
                    with conn2.cursor() as cur:
                        # Delete existing preferences
                        cur.execute("DELETE FROM alert_notification_preferences")

                        # Insert new preferences for each asset
                        for _, asset in assets_for_notif.iterrows():
                            asset_id = asset['id']

                            # Long signal (bullish)
                            if long_enabled:
                                cur.execute("""
                                    INSERT INTO alert_notification_preferences
                                    (asset_id, alert_type, min_confidence, notification_channels,
                                     quiet_hours_start, quiet_hours_end, enabled)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """, (asset_id, 'long_signal', long_confidence,
                                      long_channels, quiet_start, quiet_end, True))

                            # Short signal (bearish)
                            if short_enabled:
                                cur.execute("""
                                    INSERT INTO alert_notification_preferences
                                    (asset_id, alert_type, min_confidence, notification_channels,
                                     quiet_hours_start, quiet_hours_end, enabled)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """, (asset_id, 'short_signal', short_confidence,
                                      short_channels, quiet_start, quiet_end, True))

                        conn2.commit()

                    st.success("✅ Notification settings saved! Changes will take effect within 60 seconds (no restart needed).")

                except Exception as e:
                    if conn1:
                        conn1.rollback()
                    if conn2:
                        conn2.rollback()
                    st.error(f"Error saving notification settings: {e}")
                    import traceback
                    with st.expander("Error Details"):
                        st.code(traceback.format_exc())
                finally:
                    if conn1:
                        conn1.close()
                    if conn2:
                        conn2.close()
    else:
        st.info("Add assets first to configure notifications.")

# Footer
st.sidebar.markdown("---")
st.sidebar.caption(f"News Trading Dashboard v{__version__}")
st.sidebar.caption("Powered by Claude AI")
