"""Stock data fetching service - reads from database."""
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import streamlit as st
import psycopg2
import os
import sys
from pathlib import Path

# Import config from dashboard directory
dashboard_dir = Path(__file__).resolve().parent.parent
config_path = dashboard_dir / 'config.py'

# Load config module explicitly
import importlib.util
spec = importlib.util.spec_from_file_location("dashboard_config", config_path)
dashboard_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard_config)

STOCK_DATA_CACHE_TTL_SECONDS = dashboard_config.STOCK_DATA_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)


@st.cache_data(ttl=STOCK_DATA_CACHE_TTL_SECONDS)
def fetch_stock_data(ticker: str, days: int) -> Optional[pd.DataFrame]:
    """Fetch stock price data from database.

    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'GOOG')
        days: Number of days of historical data to fetch

    Returns:
        DataFrame with columns [Date, Close, Open, High, Low, Volume] or None if no data
    """
    try:
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Connect to database
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("DATABASE_URL not configured")
            return None

        conn = psycopg2.connect(database_url)

        try:
            # Query stock prices from database
            query = """
                SELECT
                    sp.timestamp as "Date",
                    sp.close as "Close",
                    sp.open as "Open",
                    sp.high as "High",
                    sp.low as "Low",
                    sp.volume as "Volume"
                FROM stock_prices sp
                JOIN asset a ON sp.asset_id = a.id
                WHERE a.ticker = %s
                  AND sp.timestamp >= %s
                  AND sp.timestamp <= %s
                ORDER BY sp.timestamp ASC
            """

            df = pd.read_sql_query(query, conn, params=(ticker, start_date, end_date))

            if df.empty:
                logger.debug(f"No stock price data found for {ticker}")
                return None

            # Convert timestamp to datetime
            df['Date'] = pd.to_datetime(df['Date'])

            return df

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error fetching stock data for {ticker}: {e}")
        return None
