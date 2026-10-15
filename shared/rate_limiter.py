"""
Rate Limiter - Common rate limiting for all collectors
Prevents exceeding API rate limits by tracking usage in database.
"""
import logging
from typing import Optional, Tuple
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter for API collectors.

    Tracks API usage in database and enforces rate limits to prevent
    exceeding free tier quotas.
    """

    def __init__(self, database_url: str, collector_name: str):
        """
        Initialize rate limiter.

        Args:
            database_url: PostgreSQL connection string
            collector_name: Name of the collector (e.g., 'NewsAPICollector')
        """
        self.database_url = database_url
        self.collector_name = collector_name

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def can_make_request(self) -> Tuple[bool, str, int]:
        """
        Check if collector can make an API request without exceeding rate limits.

        Returns:
            Tuple of (can_proceed, reason, wait_seconds)
            - can_proceed: True if request can be made
            - reason: Explanation message
            - wait_seconds: How long to wait if rate limited (0 if can proceed)
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT can_proceed, reason, wait_seconds
                    FROM check_rate_limit(%s)
                """, (self.collector_name,))

                result = cur.fetchone()

                if result:
                    return (
                        result['can_proceed'],
                        result['reason'],
                        result['wait_seconds']
                    )
                else:
                    # No rate limit configured, allow request
                    return (True, 'No rate limit configured', 0)

        except Exception as e:
            logger.error(f"Error checking rate limit for {self.collector_name}: {e}")
            # On error, allow request (fail open)
            return (True, f'Rate limit check failed: {e}', 0)
        finally:
            conn.close()

    def record_request(self, success: bool = True, status_code: Optional[int] = None,
                      error_message: Optional[str] = None, api_endpoint: Optional[str] = None):
        """
        Record an API request for rate limiting tracking.

        Args:
            success: Whether the request was successful
            status_code: HTTP status code (if applicable)
            error_message: Error message if request failed
            api_endpoint: API endpoint called (optional)
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO api_usage
                    (collector_name, api_endpoint, status_code, success, error_message)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    self.collector_name,
                    api_endpoint,
                    status_code,
                    success,
                    error_message[:500] if error_message else None
                ))
                conn.commit()
                logger.debug(f"Recorded API usage for {self.collector_name}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error recording API usage for {self.collector_name}: {e}")
        finally:
            conn.close()

    def get_usage_stats(self) -> dict:
        """
        Get current API usage statistics for this collector.

        Returns:
            Dictionary with usage stats (calls_today, calls_last_hour, etc.)
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM api_usage_stats
                    WHERE collector_name = %s
                """, (self.collector_name,))

                result = cur.fetchone()

                if result:
                    return dict(result)
                else:
                    return {
                        'collector_name': self.collector_name,
                        'calls_today': 0,
                        'calls_last_hour': 0,
                        'calls_last_minute': 0,
                        'errors_today': 0,
                        'last_call_time': None
                    }
        except Exception as e:
            logger.error(f"Error getting usage stats for {self.collector_name}: {e}")
            return {}
        finally:
            conn.close()

    def get_rate_limit_config(self) -> Optional[dict]:
        """
        Get rate limit configuration for this collector.

        Returns:
            Dictionary with rate limit config or None
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM rate_limit_config
                    WHERE collector_name = %s
                """, (self.collector_name,))

                result = cur.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error getting rate limit config for {self.collector_name}: {e}")
            return None
        finally:
            conn.close()

    def update_rate_limit_config(self, max_calls_per_day: Optional[int] = None,
                                 max_calls_per_hour: Optional[int] = None,
                                 max_calls_per_minute: Optional[int] = None,
                                 min_interval_seconds: Optional[int] = None,
                                 enabled: Optional[bool] = None):
        """
        Update rate limit configuration for this collector.

        Args:
            max_calls_per_day: Maximum API calls per day
            max_calls_per_hour: Maximum API calls per hour
            max_calls_per_minute: Maximum API calls per minute
            min_interval_seconds: Minimum seconds between requests
            enabled: Whether rate limiting is enabled
        """
        conn = self.get_db_connection()
        try:
            updates = []
            params = []

            if max_calls_per_day is not None:
                updates.append("max_calls_per_day = %s")
                params.append(max_calls_per_day)
            if max_calls_per_hour is not None:
                updates.append("max_calls_per_hour = %s")
                params.append(max_calls_per_hour)
            if max_calls_per_minute is not None:
                updates.append("max_calls_per_minute = %s")
                params.append(max_calls_per_minute)
            if min_interval_seconds is not None:
                updates.append("min_interval_seconds = %s")
                params.append(min_interval_seconds)
            if enabled is not None:
                updates.append("enabled = %s")
                params.append(enabled)

            if not updates:
                return

            updates.append("updated_at = NOW()")
            params.append(self.collector_name)

            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE rate_limit_config
                    SET {', '.join(updates)}
                    WHERE collector_name = %s
                """, params)
                conn.commit()
                logger.info(f"Updated rate limit config for {self.collector_name}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating rate limit config for {self.collector_name}: {e}")
        finally:
            conn.close()


def with_rate_limiting(func):
    """
    Decorator to add rate limiting to collector methods.

    Usage:
        @with_rate_limiting
        def collect_for_asset(self, ...):
            # Your collection code here
    """
    def wrapper(self, *args, **kwargs):
        # Assumes self has a rate_limiter attribute
        if not hasattr(self, 'rate_limiter'):
            logger.warning(f"{self.__class__.__name__} does not have rate_limiter")
            return func(self, *args, **kwargs)

        # Check rate limit
        can_proceed, reason, wait_seconds = self.rate_limiter.can_make_request()

        if not can_proceed:
            logger.warning(
                f"{self.rate_limiter.collector_name}: Rate limit hit - {reason}. "
                f"Wait {wait_seconds}s"
            )
            return []  # Return empty list when rate limited

        # Make request and record usage
        try:
            result = func(self, *args, **kwargs)
            self.rate_limiter.record_request(success=True)
            return result
        except Exception as e:
            self.rate_limiter.record_request(
                success=False,
                error_message=str(e)
            )
            raise

    return wrapper
