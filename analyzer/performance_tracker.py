"""
Alert Performance Tracker
Fetches price data and calculates returns for alerts to enable backtesting.
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from price_fetcher import PriceFetcher

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """Tracks alert performance by fetching price data and calculating returns."""

    def __init__(self, database_url: str):
        """
        Initialize performance tracker.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.price_fetcher = PriceFetcher()

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def get_untracked_alerts(self, limit: int = 50):
        """
        Get alerts that don't have performance tracking yet.

        Args:
            limit: Maximum number of alerts to process

        Returns:
            List of alert dictionaries
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        a.id,
                        a.asset_id,
                        a.alert_type,
                        a.timestamp as alert_date,
                        a.confidence_score,
                        c.ticker
                    FROM alerts a
                    JOIN asset c ON a.asset_id = c.id
                    LEFT JOIN alert_performance ap ON a.id = ap.alert_id
                    WHERE ap.id IS NULL
                      AND a.timestamp < NOW() - INTERVAL '1 day'
                      AND c.ticker IS NOT NULL
                      AND c.ticker != ''
                    ORDER BY a.timestamp DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        finally:
            conn.close()

    def get_outdated_performance_records(self, limit: int = 50):
        """
        Get performance records that need updating (missing future price data).

        Args:
            limit: Maximum number of records to update

        Returns:
            List of performance record dictionaries
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        ap.id,
                        ap.alert_id,
                        ap.asset_id,
                        ap.alert_date,
                        c.ticker,
                        ap.price_at_alert,
                        ap.price_30d_later
                    FROM alert_performance ap
                    JOIN asset c ON ap.asset_id = c.id
                    WHERE (
                        ap.price_30d_later IS NULL
                        AND ap.alert_date < NOW() - INTERVAL '30 days'
                    )
                    OR (
                        ap.price_14d_later IS NULL
                        AND ap.alert_date < NOW() - INTERVAL '14 days'
                    )
                    OR (
                        ap.price_7d_later IS NULL
                        AND ap.alert_date < NOW() - INTERVAL '7 days'
                    )
                    OR (
                        ap.price_3d_later IS NULL
                        AND ap.alert_date < NOW() - INTERVAL '3 days'
                    )
                    ORDER BY ap.alert_date DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        finally:
            conn.close()

    def determine_predicted_direction(self, alert_type: str) -> str:
        """
        Determine predicted direction based on alert type.

        Args:
            alert_type: Type of alert

        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        # Bullish alert types
        bullish_types = [
            'long_signal', 'partnership', 'product_launch',
            'analyst_upgrade', 'market_share', 'guidance',
            'insider_trading', 'executive_change'
        ]

        # Bearish alert types
        bearish_types = [
            'short_signal', 'regulatory_risk', 'analyst_downgrade',
            'customer_loss', 'problem_detected', 'negative_sentiment'
        ]

        # Check for bullish
        for btype in bullish_types:
            if btype in alert_type.lower():
                return 'bullish'

        # Check for bearish
        for btype in bearish_types:
            if btype in alert_type.lower():
                return 'bearish'

        return 'neutral'

    def create_performance_record(self, alert: dict):
        """
        Create a new performance tracking record for an alert.

        Args:
            alert: Alert dictionary with id, asset_id, ticker, etc.
        """
        conn = self.get_db_connection()
        try:
            # Fetch price at alert time
            price_at_alert = self.price_fetcher.get_price_at_date(
                alert['ticker'],
                alert['alert_date']
            )

            if price_at_alert is None:
                logger.warning(f"Could not fetch price for {alert['ticker']} at alert time, skipping")
                return

            # Fetch prices at future intervals
            prices = self.price_fetcher.get_price_series(
                alert['ticker'],
                alert['alert_date'],
                days_list=[1, 3, 7, 14, 30]
            )

            # Calculate returns
            returns = {}
            directions = {}
            correctness = {}

            predicted_direction = self.determine_predicted_direction(alert['alert_type'])

            for days, price in prices.items():
                ret = self.price_fetcher.calculate_return(price_at_alert, price)
                returns[days] = ret
                directions[days] = self.price_fetcher.determine_direction(ret)

                # Check correctness
                if directions[days] and predicted_direction != 'neutral':
                    correctness[days] = (directions[days] == predicted_direction)
                else:
                    correctness[days] = None

            # Insert record
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alert_performance (
                        alert_id, asset_id, alert_type, alert_date, confidence_score,
                        price_at_alert,
                        price_1d_later, price_3d_later, price_7d_later,
                        price_14d_later, price_30d_later,
                        return_1d, return_3d, return_7d, return_14d, return_30d,
                        predicted_direction,
                        actual_direction_1d, actual_direction_3d, actual_direction_7d,
                        correct_1d, correct_3d, correct_7d
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    alert['id'], alert['asset_id'], alert['alert_type'],
                    alert['alert_date'], alert['confidence_score'],
                    price_at_alert,
                    prices.get(1), prices.get(3), prices.get(7), prices.get(14), prices.get(30),
                    returns.get(1), returns.get(3), returns.get(7), returns.get(14), returns.get(30),
                    predicted_direction,
                    directions.get(1), directions.get(3), directions.get(7),
                    correctness.get(1), correctness.get(3), correctness.get(7)
                ))
                conn.commit()
                logger.info(
                    f"Created performance record for alert {alert['id']} ({alert['ticker']}) "
                    f"- 7d return: {returns.get(7) * 100 if returns.get(7) else 'N/A'}%"
                )

        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating performance record for alert {alert['id']}: {e}")
        finally:
            conn.close()

    def update_performance_record(self, record: dict):
        """
        Update an existing performance record with newer price data.

        Args:
            record: Performance record dictionary
        """
        conn = self.get_db_connection()
        try:
            # Fetch updated prices
            prices = self.price_fetcher.get_price_series(
                record['ticker'],
                record['alert_date'],
                days_list=[1, 3, 7, 14, 30]
            )

            # Calculate returns
            returns = {}
            directions = {}
            for days, price in prices.items():
                ret = self.price_fetcher.calculate_return(record['price_at_alert'], price)
                returns[days] = ret
                directions[days] = self.price_fetcher.determine_direction(ret)

            # Update record
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE alert_performance
                    SET
                        price_1d_later = %s,
                        price_3d_later = %s,
                        price_7d_later = %s,
                        price_14d_later = %s,
                        price_30d_later = %s,
                        return_1d = %s,
                        return_3d = %s,
                        return_7d = %s,
                        return_14d = %s,
                        return_30d = %s,
                        actual_direction_1d = %s,
                        actual_direction_3d = %s,
                        actual_direction_7d = %s,
                        last_updated = NOW()
                    WHERE id = %s
                """, (
                    prices.get(1), prices.get(3), prices.get(7), prices.get(14), prices.get(30),
                    returns.get(1), returns.get(3), returns.get(7), returns.get(14), returns.get(30),
                    directions.get(1), directions.get(3), directions.get(7),
                    record['id']
                ))
                conn.commit()
                logger.info(f"Updated performance record {record['id']}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating performance record {record['id']}: {e}")
        finally:
            conn.close()

    def track_new_alerts(self, limit: int = 50) -> int:
        """
        Track performance for new alerts that don't have records yet.

        Args:
            limit: Maximum number of alerts to process

        Returns:
            Number of alerts processed
        """
        alerts = self.get_untracked_alerts(limit)
        logger.info(f"Found {len(alerts)} untracked alerts")

        for alert in alerts:
            self.create_performance_record(alert)

        return len(alerts)

    def update_existing_records(self, limit: int = 50) -> int:
        """
        Update existing performance records with newer price data.

        Args:
            limit: Maximum number of records to update

        Returns:
            Number of records updated
        """
        records = self.get_outdated_performance_records(limit)
        logger.info(f"Found {len(records)} outdated performance records")

        for record in records:
            self.update_performance_record(record)

        return len(records)

    def run_full_update(self):
        """Run complete performance tracking update."""
        logger.info("=" * 60)
        logger.info("Starting Alert Performance Tracking")
        logger.info("=" * 60)

        # Track new alerts
        new_count = self.track_new_alerts(limit=100)
        logger.info(f"Processed {new_count} new alerts")

        # Update existing records
        updated_count = self.update_existing_records(limit=100)
        logger.info(f"Updated {updated_count} existing records")

        logger.info("=" * 60)
        logger.info(f"Alert Performance Tracking Complete (New: {new_count}, Updated: {updated_count})")
        logger.info("=" * 60)


def main():
    """Main entry point for standalone execution."""
    from logging_config import setup_logging

    DATABASE_URL = os.getenv('DATABASE_URL')

    # Set up logging
    logger = setup_logging(
        service_name='performance_tracker',
        database_url=DATABASE_URL,
        console_level='INFO',
        database_level='INFO'
    )

    if not DATABASE_URL:
        logger.error("Missing DATABASE_URL environment variable")
        return

    tracker = PerformanceTracker(DATABASE_URL)
    tracker.run_full_update()


if __name__ == "__main__":
    main()
