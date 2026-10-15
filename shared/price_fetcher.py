"""
Price Fetcher Module
Fetches historical stock prices from database for alert performance tracking.
"""
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict
import psycopg2

# Add analyzer directory to path for config import
analyzer_dir = Path(__file__).resolve().parent.parent / 'analyzer'
if analyzer_dir.exists():
    sys.path.insert(0, str(analyzer_dir))
    from config import (
        ALERT_PRICE_TRACKING_DAYS,
        PRICE_DATE_BUFFER_DAYS,
        PRICE_MAX_DATE_DIFF_DAYS,
        PRICE_DIRECTION_THRESHOLD
    )
else:
    # Fallback defaults if config not found
    ALERT_PRICE_TRACKING_DAYS = [1, 3, 7, 14, 30]
    PRICE_DATE_BUFFER_DAYS = 7
    PRICE_MAX_DATE_DIFF_DAYS = 7
    PRICE_DIRECTION_THRESHOLD = 0.005

logger = logging.getLogger(__name__)


class PriceFetcher:
    """Fetches stock prices from database for performance tracking."""

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize PriceFetcher.

        Args:
            database_url: Database connection string (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not configured")

    def get_price_at_date(self, ticker: str, target_date: datetime) -> Optional[float]:
        """
        Get closing price for a ticker on a specific date from database.

        Args:
            ticker: Stock ticker symbol
            target_date: Target date to fetch price for

        Returns:
            Closing price or None if unavailable
        """
        conn = None

        try:
            conn = psycopg2.connect(self.database_url)

            with conn.cursor() as cur:
                # Add buffer days to handle weekends/holidays
                start_date = target_date - timedelta(days=PRICE_DATE_BUFFER_DAYS)
                end_date = target_date + timedelta(days=PRICE_DATE_BUFFER_DAYS)

                # Query price from database
                cur.execute(
                    """
                    SELECT
                        sp.timestamp::date as date,
                        sp.close
                    FROM stock_prices sp
                    JOIN asset a ON sp.asset_id = a.id
                    WHERE a.ticker = %s
                      AND sp.timestamp >= %s
                      AND sp.timestamp <= %s
                    ORDER BY ABS((sp.timestamp::date - %s::date))
                    LIMIT 1
                    """,
                    (ticker, start_date, end_date, target_date.date())
                )

                result = cur.fetchone()

                if not result:
                    logger.warning(f"No price data found for {ticker} around {target_date.date()}")
                    return None

                price_date, close_price = result

                # Check if date is too far from target
                days_diff = abs((price_date - target_date.date()).days)

                if days_diff > PRICE_MAX_DATE_DIFF_DAYS:
                    logger.warning(
                        f"Closest trading day for {ticker} is {days_diff} days from target {target_date.date()}"
                    )
                    return None

                logger.debug(
                    f"Fetched price for {ticker}: ${close_price:.2f} on {price_date} "
                    f"(target: {target_date.date()})"
                )
                return float(close_price)

        except Exception as e:
            logger.error(f"Error fetching price for {ticker} at {target_date}: {e}")
            return None

        finally:
            if conn:
                conn.close()

    def get_price_series(
        self,
        ticker: str,
        alert_date: datetime,
        days_list: list = None
    ) -> Dict[int, Optional[float]]:
        """
        Get prices at multiple intervals after an alert date.

        Args:
            ticker: Stock ticker symbol
            alert_date: Alert timestamp
            days_list: List of days to fetch prices for (defaults to ALERT_PRICE_TRACKING_DAYS)

        Returns:
            Dictionary mapping days to prices: {1: 150.25, 3: 152.10, 7: 148.50}
        """
        if days_list is None:
            days_list = ALERT_PRICE_TRACKING_DAYS

        prices = {}

        for days in days_list:
            target_date = alert_date + timedelta(days=days)

            # Skip future dates
            if target_date > datetime.now():
                prices[days] = None
                continue

            prices[days] = self.get_price_at_date(ticker, target_date)

        return prices

    @staticmethod
    def calculate_return(start_price: Optional[float], end_price: Optional[float]) -> Optional[float]:
        """
        Calculate percentage return between two prices.

        Args:
            start_price: Starting price
            end_price: Ending price

        Returns:
            Return as decimal (e.g., 0.05 = 5%) or None if either price is missing
        """
        if start_price is None or end_price is None or start_price == 0:
            return None

        return (end_price - start_price) / start_price

    @staticmethod
    def determine_direction(return_value: Optional[float], threshold: float = None) -> Optional[str]:
        """
        Determine price direction from return value.

        Args:
            return_value: Return as decimal
            threshold: Minimum return to consider directional (defaults to PRICE_DIRECTION_THRESHOLD)

        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        if threshold is None:
            threshold = PRICE_DIRECTION_THRESHOLD

        if return_value is None:
            return None

        if return_value > threshold:
            return 'bullish'
        elif return_value < -threshold:
            return 'bearish'
        else:
            return 'neutral'
