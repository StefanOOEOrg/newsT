"""
Stock Price Collector - Fetches stock prices from Yahoo Finance via yfinance.
Stores prices in database for use by dashboard and analyzer services.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import yfinance as yf

from collectors.base import BaseCollector

# Add parent directory to path for config import
parent_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_dir))

from config import (
    STOCK_PRICE_INTERVAL,
    STOCK_PRICE_PERIOD,
    STOCK_PRICE_HISTORICAL_DAYS
)

logger = logging.getLogger(__name__)


class StockPriceCollector(BaseCollector):
    """Collects stock price data from Yahoo Finance and stores in database."""

    def __init__(self, database_url: str):
        """Initialize StockPriceCollector with database connection."""
        super().__init__(database_url)
        self.collector_name = "StockPriceCollector"

    def collect(self) -> Tuple[int, int]:
        """
        Collect stock prices for all tracked assets.

        Returns:
            Tuple of (total_prices, new_prices)
        """
        logger.info(f"{self.collector_name}: Starting price collection...")

        assets = self.get_assets()
        total_prices = 0
        new_prices = 0

        for asset_id, asset_name, ticker, _ in assets:
            logger.info(f"{self.collector_name}: Collecting prices for {asset_name} ({ticker})")

            prices = self.collect_for_asset(asset_id, asset_name, ticker)
            total_prices += len(prices)

            if prices:
                inserted = self._store_prices(asset_id, prices)
                new_prices += inserted
                logger.info(f"{self.collector_name}: Stored {inserted}/{len(prices)} new prices for {asset_name}")

        logger.info(
            f"{self.collector_name}: Collection complete. "
            f"Total: {total_prices} prices ({new_prices} new)"
        )

        return total_prices, new_prices

    def collect_for_asset(
        self,
        asset_id: int,
        asset_name: str,
        ticker: str,
        period: str = None
    ) -> List[dict]:
        """
        Collect recent stock prices for a single asset.

        Args:
            asset_id: Asset ID
            asset_name: Asset name
            ticker: Stock ticker symbol
            period: Period to fetch (defaults to STOCK_PRICE_PERIOD from config)

        Returns:
            List of price dictionaries
        """
        if period is None:
            period = STOCK_PRICE_PERIOD

        prices = []

        try:
            # Check rate limit before making request
            can_proceed, reason, wait_seconds = self.rate_limiter.can_make_request()

            if not can_proceed:
                logger.warning(
                    f"{self.collector_name}: Rate limit hit for {asset_name} - {reason}. "
                    f"Skipping this collection cycle"
                )
                return []

            # Fetch price data from yfinance
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period, interval=STOCK_PRICE_INTERVAL)

            # Record API usage
            if hist.empty:
                logger.warning(f"{self.collector_name}: No price data returned for {ticker}")
                self.rate_limiter.record_request(
                    success=False,
                    status_code=200,
                    error_message="Empty response"
                )
                return []

            self.rate_limiter.record_request(success=True, status_code=200)

            # Convert DataFrame to list of dicts
            for timestamp, row in hist.iterrows():
                try:
                    prices.append({
                        'timestamp': timestamp.to_pydatetime(),
                        'open': float(row['Open']) if 'Open' in row and row['Open'] else None,
                        'high': float(row['High']) if 'High' in row and row['High'] else None,
                        'low': float(row['Low']) if 'Low' in row and row['Low'] else None,
                        'close': float(row['Close']),
                        'volume': int(row['Volume']) if 'Volume' in row and row['Volume'] else None
                    })
                except (ValueError, KeyError) as e:
                    logger.error(f"Error parsing price data for {ticker}: {e}")
                    continue

            logger.info(f"{self.collector_name}: Fetched {len(prices)} prices for {ticker}")

        except Exception as e:
            logger.error(f"{self.collector_name}: Error fetching prices for {ticker}: {e}")
            self.rate_limiter.record_request(
                success=False,
                status_code=0,
                error_message=str(e)
            )

        return prices

    def _store_prices(self, asset_id: int, prices: List[dict]) -> int:
        """
        Store price data in database.

        Args:
            asset_id: Asset ID
            prices: List of price dictionaries

        Returns:
            Number of prices inserted (duplicates ignored)
        """
        if not prices:
            return 0

        conn = None
        inserted_count = 0

        try:
            conn = self.get_db_connection()

            with conn.cursor() as cur:
                for price in prices:
                    try:
                        cur.execute(
                            """
                            INSERT INTO stock_prices (
                                asset_id, timestamp, open, high, low, close, volume
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (asset_id, timestamp) DO NOTHING
                            RETURNING id
                            """,
                            (
                                asset_id,
                                price['timestamp'],
                                price.get('open'),
                                price.get('high'),
                                price.get('low'),
                                price['close'],
                                price.get('volume')
                            )
                        )

                        # Count successful inserts (RETURNING id returns None for conflicts)
                        if cur.fetchone() is not None:
                            inserted_count += 1

                    except Exception as e:
                        logger.error(f"Error inserting price: {e}")
                        continue

            conn.commit()

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error storing prices: {e}")

        finally:
            if conn:
                conn.close()

        return inserted_count

    def initialize_asset(self, asset_id: int, days_back: int = None) -> None:
        """
        Initialize historical price data for an asset.

        Args:
            asset_id: Asset ID
            days_back: Number of days of historical data to fetch (defaults to STOCK_PRICE_HISTORICAL_DAYS)
        """
        if days_back is None:
            days_back = STOCK_PRICE_HISTORICAL_DAYS
        conn = None

        try:
            conn = self.get_db_connection()

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name, ticker FROM asset WHERE id = %s",
                    (asset_id,)
                )
                result = cur.fetchone()

                if not result:
                    logger.error(f"Asset {asset_id} not found")
                    return

                asset_name, ticker = result

            logger.info(
                f"{self.collector_name}: Initializing {days_back} days of "
                f"historical data for {asset_name} ({ticker})"
            )

            # Fetch historical data
            # Note: yfinance minute intervals (1m, 2m, 5m, etc.) only available for last 60 days
            try:
                stock = yf.Ticker(ticker)
                end_date = datetime.now()
                start_date = end_date - timedelta(days=min(days_back, 60))

                # Use configured interval for consistency with ongoing collection
                hist = stock.history(start=start_date, end=end_date, interval=STOCK_PRICE_INTERVAL)

                if hist.empty:
                    logger.warning(f"No historical data available for {ticker}")
                    return

                # Convert to price dictionaries
                prices = []
                for timestamp, row in hist.iterrows():
                    try:
                        prices.append({
                            'timestamp': timestamp.to_pydatetime(),
                            'open': float(row['Open']) if 'Open' in row and row['Open'] else None,
                            'high': float(row['High']) if 'High' in row and row['High'] else None,
                            'low': float(row['Low']) if 'Low' in row and row['Low'] else None,
                            'close': float(row['Close']),
                            'volume': int(row['Volume']) if 'Volume' in row and row['Volume'] else None
                        })
                    except (ValueError, KeyError) as e:
                        logger.error(f"Error parsing historical price: {e}")
                        continue

                # Store prices
                inserted = self._store_prices(asset_id, prices)
                logger.info(
                    f"{self.collector_name}: Initialized {inserted}/{len(prices)} "
                    f"historical prices for {asset_name}"
                )

            except Exception as e:
                logger.error(f"Error fetching historical data for {ticker}: {e}")

        except Exception as e:
            logger.error(f"Error initializing asset {asset_id}: {e}")

        finally:
            if conn:
                conn.close()
