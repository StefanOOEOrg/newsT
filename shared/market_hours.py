"""
Market Hours Detection and Smart Scheduling

Determines appropriate collection frequency based on market hours and day of week.
"""
from datetime import datetime, time
from typing import Tuple
import pytz
import logging

logger = logging.getLogger(__name__)


class MarketHoursScheduler:
    """Smart scheduler based on market hours."""

    def __init__(self, database_url: str):
        """
        Initialize market hours scheduler.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.market_timezone = pytz.timezone('America/New_York')  # US Eastern Time

        # Default values (will be overridden by database settings)
        self.enable_smart_scheduling = True
        self.market_open_hour = 9
        self.market_open_minute = 30
        self.market_close_hour = 16
        self.market_close_minute = 0
        self.interval_market_hours = 15
        self.interval_after_hours = 30
        self.interval_weekends = 120
        self.interval_fixed = 30

        # Load settings from database
        self._load_settings()

    def _load_settings(self):
        """Load scheduling settings from database."""
        import psycopg2

        conn = None
        try:
            conn = psycopg2.connect(self.database_url)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        enable_smart_scheduling,
                        market_open_hour,
                        market_open_minute,
                        market_close_hour,
                        market_close_minute,
                        collection_interval_market_hours,
                        collection_interval_after_hours,
                        collection_interval_weekends,
                        collection_interval_fixed
                    FROM notification_settings
                    WHERE id = 1
                """)
                result = cur.fetchone()

                if result:
                    (
                        self.enable_smart_scheduling,
                        self.market_open_hour,
                        self.market_open_minute,
                        self.market_close_hour,
                        self.market_close_minute,
                        self.interval_market_hours,
                        self.interval_after_hours,
                        self.interval_weekends,
                        self.interval_fixed
                    ) = result

                    logger.info(f"Loaded scheduling settings from database:")
                    logger.info(f"  Smart scheduling: {self.enable_smart_scheduling}")
                    logger.info(f"  Market hours: {self.market_open_hour}:{self.market_open_minute:02d} - {self.market_close_hour}:{self.market_close_minute:02d} ET")
                    logger.info(f"  Intervals: Market={self.interval_market_hours}min, After={self.interval_after_hours}min, Weekend={self.interval_weekends}min")
                else:
                    logger.warning("No settings found in database, using defaults")

        except psycopg2.Error as e:
            logger.error(f"Database error loading settings: {e}")
            logger.info("Using default scheduling settings")
        except Exception as e:
            logger.error(f"Unexpected error loading settings from database: {e}")
            logger.info("Using default scheduling settings")
        finally:
            if conn:
                conn.close()

    def is_market_hours(self, dt: datetime = None) -> bool:
        """
        Check if given datetime is during market hours.

        Args:
            dt: Datetime to check (defaults to now in ET)

        Returns:
            True if market is open, False otherwise
        """
        if dt is None:
            dt = datetime.now(self.market_timezone)
        elif dt.tzinfo is None:
            # Assume UTC and convert to ET
            dt = pytz.utc.localize(dt).astimezone(self.market_timezone)
        else:
            dt = dt.astimezone(self.market_timezone)

        # Check if weekend
        if dt.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check if within market hours
        market_open = time(self.market_open_hour, self.market_open_minute)
        market_close = time(self.market_close_hour, self.market_close_minute)
        current_time = dt.time()

        return market_open <= current_time < market_close

    def is_weekend(self, dt: datetime = None) -> bool:
        """
        Check if given datetime is on a weekend.

        Args:
            dt: Datetime to check (defaults to now in ET)

        Returns:
            True if weekend, False otherwise
        """
        if dt is None:
            dt = datetime.now(self.market_timezone)
        elif dt.tzinfo is None:
            dt = pytz.utc.localize(dt).astimezone(self.market_timezone)
        else:
            dt = dt.astimezone(self.market_timezone)

        return dt.weekday() >= 5

    def get_current_interval(self) -> int:
        """
        Get the appropriate collection interval for current time.

        Returns:
            Collection interval in minutes
        """
        if not self.enable_smart_scheduling:
            return self.interval_fixed

        now = datetime.now(self.market_timezone)

        if self.is_weekend(now):
            return self.interval_weekends
        elif self.is_market_hours(now):
            return self.interval_market_hours
        else:
            return self.interval_after_hours

    def get_schedule_description(self) -> str:
        """
        Get human-readable description of current schedule.

        Returns:
            Description string
        """
        if not self.enable_smart_scheduling:
            return f"Fixed interval: Every {self.interval_fixed} minutes"

        now = datetime.now(self.market_timezone)
        current_interval = self.get_current_interval()

        if self.is_weekend(now):
            status = "Weekend"
        elif self.is_market_hours(now):
            status = "Market Hours"
        else:
            status = "After Hours"

        return (
            f"{status}: Collecting every {current_interval} minutes\n"
            f"Market hours: {self.market_open_hour}:{self.market_open_minute:02d} - "
            f"{self.market_close_hour}:{self.market_close_minute:02d} ET\n"
            f"Intervals: Market={self.interval_market_hours}min, "
            f"After={self.interval_after_hours}min, Weekend={self.interval_weekends}min"
        )
