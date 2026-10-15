"""
Base collector interface - abstract class for all data collectors.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import logging
import psycopg2
from psycopg2.extras import execute_values
import sys
from pathlib import Path

# Add shared directory to path
shared_path = Path(__file__).parent.parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from keyword_tracker import KeywordTracker
from rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """
    Abstract base class for all collectors.

    Each collector implementation must:
    1. Implement collect_for_company() to fetch data from its source
    2. Return posts in the standard format (see collect_for_company docstring)
    """

    def __init__(self, database_url: str):
        """
        Initialize the collector.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.name = self.__class__.__name__
        self.keyword_tracker = KeywordTracker(database_url)

        # Initialize rate limiter for API usage tracking
        self.rate_limiter = RateLimiter(database_url, self.name)

        # Statistics tracking - initialize with defaults
        self._stats = {
            'last_run_started_at': None,
            'last_run_completed_at': None,
            'last_run_duration_seconds': None,
            'total_posts_collected': 0,
            'total_posts_saved': 0,
            'last_run_posts_collected': 0,
            'last_run_posts_saved': 0,
            'total_errors': 0,
            'last_error_message': None,
            'last_error_at': None
        }

        # Load existing statistics from database
        self._load_statistics_from_db()

        logger.info(f"{self.name} initialized")

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def get_statistics(self) -> Dict:
        """
        Get current statistics for this collector.

        Returns:
            Dictionary with collector statistics including:
            - collector_name: Name of the collector
            - last_run_started_at: Timestamp when last collection started
            - last_run_completed_at: Timestamp when last collection completed
            - last_run_duration_seconds: Duration of last collection in seconds
            - total_posts_collected: Total posts collected since initialization
            - total_posts_saved: Total new posts saved since initialization
            - last_run_posts_collected: Posts collected in last run
            - last_run_posts_saved: New posts saved in last run
            - total_errors: Total number of errors encountered
            - last_error_message: Message from last error
            - last_error_at: Timestamp of last error
        """
        stats = self._stats.copy()
        stats['collector_name'] = self.name
        return stats

    def _load_statistics_from_db(self):
        """Load statistics from database if they exist."""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        last_run_started_at,
                        last_run_completed_at,
                        last_run_duration_seconds,
                        total_posts_collected,
                        total_posts_saved,
                        last_run_posts_collected,
                        last_run_posts_saved,
                        total_errors,
                        last_error_message,
                        last_error_at
                    FROM collector_statistics
                    WHERE collector_name = %s
                """, (self.name,))
                result = cur.fetchone()
                if result:
                    self._stats = {
                        'last_run_started_at': result[0],
                        'last_run_completed_at': result[1],
                        'last_run_duration_seconds': float(result[2]) if result[2] is not None else None,
                        'total_posts_collected': result[3] or 0,
                        'total_posts_saved': result[4] or 0,
                        'last_run_posts_collected': result[5] or 0,
                        'last_run_posts_saved': result[6] or 0,
                        'total_errors': result[7] or 0,
                        'last_error_message': result[8],
                        'last_error_at': result[9]
                    }
                    logger.debug(f"{self.name}: Loaded statistics from database")
        except Exception as e:
            # Table might not exist yet or other error - use defaults
            logger.debug(f"{self.name}: Could not load statistics from DB: {e}")
        finally:
            conn.close()

    def _save_statistics_to_db(self):
        """Save current statistics to database."""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO collector_statistics (
                        collector_name,
                        last_run_started_at,
                        last_run_completed_at,
                        last_run_duration_seconds,
                        total_posts_collected,
                        total_posts_saved,
                        last_run_posts_collected,
                        last_run_posts_saved,
                        total_errors,
                        last_error_message,
                        last_error_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (collector_name) DO UPDATE SET
                        last_run_started_at = EXCLUDED.last_run_started_at,
                        last_run_completed_at = EXCLUDED.last_run_completed_at,
                        last_run_duration_seconds = EXCLUDED.last_run_duration_seconds,
                        total_posts_collected = EXCLUDED.total_posts_collected,
                        total_posts_saved = EXCLUDED.total_posts_saved,
                        last_run_posts_collected = EXCLUDED.last_run_posts_collected,
                        last_run_posts_saved = EXCLUDED.last_run_posts_saved,
                        total_errors = EXCLUDED.total_errors,
                        last_error_message = EXCLUDED.last_error_message,
                        last_error_at = EXCLUDED.last_error_at,
                        updated_at = NOW()
                """, (
                    self.name,
                    self._stats['last_run_started_at'],
                    self._stats['last_run_completed_at'],
                    self._stats['last_run_duration_seconds'],
                    self._stats['total_posts_collected'],
                    self._stats['total_posts_saved'],
                    self._stats['last_run_posts_collected'],
                    self._stats['last_run_posts_saved'],
                    self._stats['total_errors'],
                    self._stats['last_error_message'],
                    self._stats['last_error_at']
                ))
                conn.commit()
                logger.debug(f"{self.name}: Saved statistics to database")
        except Exception as e:
            conn.rollback()
            logger.error(f"{self.name}: Error saving statistics to DB: {e}")
        finally:
            conn.close()

    def _record_error(self, error_message: str):
        """Record an error in statistics."""
        self._stats['total_errors'] += 1
        self._stats['last_error_message'] = str(error_message)[:500]  # Limit length
        self._stats['last_error_at'] = datetime.now()
        self._save_statistics_to_db()

    def get_assets(self, include_pending_init: bool = False, prioritize_by_dss: bool = True) -> List[Tuple[int, str, str, List[str]]]:
        """
        Fetch all assets from database, optionally prioritized by DSS (Decision Signal Strength).

        DSS = (today's long signals - today's short signals)
        Assets with higher absolute DSS values are returned first, ensuring high-priority
        assets are collected before rate limits are hit.

        Args:
            include_pending_init: If True, only return assets pending initialization
            prioritize_by_dss: If True, order by absolute DSS descending (default: True)

        Returns:
            List of tuples: (id, name, ticker, search_keywords)
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                if include_pending_init:
                    cur.execute("""
                        SELECT id, name, ticker, search_keywords
                        FROM asset
                        WHERE initialization_status = 'pending'
                    """)
                else:
                    if prioritize_by_dss:
                        # Order by absolute DSS (Daily Signal Strength) descending
                        # DSS = long_signals - short_signals from today
                        cur.execute("""
                            SELECT
                                a.id,
                                a.name,
                                a.ticker,
                                a.search_keywords,
                                ABS(COALESCE(
                                    (SELECT COUNT(*) FROM alerts
                                     WHERE asset_id = a.id
                                       AND DATE(timestamp) = CURRENT_DATE
                                       AND alert_type = 'long_signal'),
                                    0
                                ) - COALESCE(
                                    (SELECT COUNT(*) FROM alerts
                                     WHERE asset_id = a.id
                                       AND DATE(timestamp) = CURRENT_DATE
                                       AND alert_type = 'short_signal'),
                                    0
                                )) as abs_dss
                            FROM asset a
                            WHERE initialization_status IN ('completed', 'in_progress')
                               OR initialization_status IS NULL
                            ORDER BY abs_dss DESC, a.name
                        """)
                        # Extract only the first 4 columns (id, name, ticker, keywords)
                        return [(row[0], row[1], row[2], row[3]) for row in cur.fetchall()]
                    else:
                        cur.execute("""
                            SELECT id, name, ticker, search_keywords
                            FROM asset
                            WHERE initialization_status IN ('completed', 'in_progress')
                               OR initialization_status IS NULL
                            ORDER BY name
                        """)
                        return cur.fetchall()
        finally:
            conn.close()

    def post_exists(self, post_id: str) -> bool:
        """
        Check if a post already exists in the database.

        Args:
            post_id: Unique identifier for the post

        Returns:
            True if post exists, False otherwise
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM social_posts WHERE post_id = %s",
                    (post_id,)
                )
                return cur.fetchone() is not None
        finally:
            conn.close()

    def save_posts(self, posts: List[Dict]) -> int:
        """
        Save posts to the database and track keyword performance.

        Args:
            posts: List of post dictionaries with required fields

        Returns:
            Number of posts saved
        """
        if not posts:
            return 0

        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                # Get asset keywords for each unique asset_id
                asset_ids = list(set(post['asset_id'] for post in posts))
                asset_keywords = {}

                for asset_id in asset_ids:
                    cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (asset_id,))
                    result = cur.fetchone()
                    if result:
                        asset_keywords[asset_id] = result[0]

                # For each post, identify matched keywords
                for post in posts:
                    asset_id = post['asset_id']
                    keywords = asset_keywords.get(asset_id, [])

                    # Combine title and content for keyword matching
                    text_to_search = f"{post.get('title', '')} {post.get('content', '')}"
                    matched_keywords = self.keyword_tracker.identify_keyword_matches(text_to_search, keywords)

                    # Add matched_keywords to post
                    post['matched_keywords'] = matched_keywords

                # Prepare data for batch insert
                values = [
                    (
                        post['asset_id'],
                        post['source'],
                        post['post_id'],
                        post['author'],
                        post['title'],
                        post['content'],
                        post['url'],
                        post['score'],
                        post['created_at'],
                        post.get('matched_keywords', [])
                    )
                    for post in posts
                ]

                # Batch insert with ON CONFLICT DO NOTHING
                execute_values(
                    cur,
                    """
                    INSERT INTO social_posts
                    (asset_id, source, post_id, author, title, content, url, score, created_at, matched_keywords)
                    VALUES %s
                    ON CONFLICT (post_id) DO NOTHING
                    """,
                    values
                )

                # Track keyword hits for successfully saved posts
                saved_count = cur.rowcount

                if saved_count > 0:
                    # Record keyword hits for each saved post
                    for post in posts:
                        matched_keywords = post.get('matched_keywords', [])
                        if matched_keywords:
                            self.keyword_tracker.record_keyword_hit(post['asset_id'], matched_keywords)

                conn.commit()
                logger.info(f"{self.name}: Saved {saved_count} posts to database")
                return saved_count
        except Exception as e:
            conn.rollback()
            logger.error(f"{self.name}: Error saving posts: {e}")
            raise
        finally:
            conn.close()

    @abstractmethod
    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect posts/articles for a specific asset.

        This method must be implemented by each collector subclass.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Stock ticker symbol
            keywords: List of keywords to search for

        Returns:
            List of post dictionaries with the following required fields:
            {
                'asset_id': int,
                'source': str,  # e.g., 'rss_google_news', 'twitter', 'reddit_r_stocks'
                'post_id': str,  # Unique identifier
                'author': str,
                'title': str,
                'content': str or None,
                'url': str,
                'score': int,  # Use 0 if not applicable
                'created_at': datetime  # With timezone
            }
        """
        pass

    def collect_all(self) -> Dict[str, int]:
        """
        Main collection function - fetch posts for all assets.

        Returns:
            Dictionary with statistics: {'total_posts': int, 'total_saved': int}
        """
        logger.info(f"{self.name}: Starting collection...")

        # Record start time
        start_time = datetime.now()
        self._stats['last_run_started_at'] = start_time

        try:
            assets = self.get_assets()
            logger.info(f"{self.name}: Found {len(assets)} assets to track")

            total_posts = 0
            total_saved = 0

            for asset_id, name, ticker, keywords in assets:
                logger.info(f"{self.name}: Collecting for {name} ({ticker})")

                try:
                    posts = self.collect_for_asset(asset_id, name, ticker, keywords)

                    if posts:
                        saved = self.save_posts(posts)
                        total_posts += len(posts)
                        total_saved += saved
                        logger.info(f"{self.name}: Collected {len(posts)} posts for {name} ({saved} new)")
                    else:
                        logger.info(f"{self.name}: No posts found for {name}")

                except Exception as e:
                    logger.error(f"{self.name}: Error collecting for {name}: {e}")
                    self._record_error(f"Error collecting for {name}: {e}")
                    continue

            logger.info(f"{self.name}: Collection complete. Total: {total_posts} posts ({total_saved} new)")

            # Update statistics
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            self._stats['last_run_completed_at'] = end_time
            self._stats['last_run_duration_seconds'] = duration
            self._stats['last_run_posts_collected'] = total_posts
            self._stats['last_run_posts_saved'] = total_saved
            self._stats['total_posts_collected'] += total_posts
            self._stats['total_posts_saved'] += total_saved

            # Save statistics to database
            self._save_statistics_to_db()

            return {
                'total_posts': total_posts,
                'total_saved': total_saved
            }

        except Exception as e:
            logger.error(f"{self.name}: Error in collect_all: {e}")
            self._record_error(f"Error in collect_all: {e}")
            raise

    def collect_for_asset_historical(self, asset_id: int, asset_name: str,
                                     ticker: str, keywords: List[str],
                                     days_back: int = 30) -> List[Dict]:
        """
        Collect historical posts for an asset (optional implementation).

        Subclasses can override this to provide historical data collection
        where supported by the data source.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Stock ticker symbol
            keywords: List of keywords to search for
            days_back: Number of days to go back

        Returns:
            List of post dictionaries (empty list if not supported)
        """
        logger.warning(f"{self.name}: Historical collection not implemented for this collector")
        return []

    def initialize_asset(self, asset_id: int, days_back: int = 30) -> Dict[str, int]:
        """
        Initialize historical data for an asset.

        Args:
            asset_id: Database ID of the asset
            days_back: Number of days of historical data to collect

        Returns:
            Dictionary with statistics: {'total_posts': int, 'total_saved': int}
        """
        logger.info(f"{self.name}: Starting historical initialization for asset {asset_id} ({days_back} days)")

        try:
            # Update status to in_progress
            conn = self.get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE asset
                        SET initialization_status = 'in_progress',
                            initialization_started_at = NOW()
                        WHERE id = %s
                    """, (asset_id,))
                    conn.commit()
            finally:
                conn.close()

            # Get asset details
            conn = self.get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT name, ticker, search_keywords
                        FROM asset
                        WHERE id = %s
                    """, (asset_id,))
                    result = cur.fetchone()
                    if not result:
                        raise ValueError(f"Asset {asset_id} not found")
                    name, ticker, keywords = result
            finally:
                conn.close()

            # Collect historical data
            posts = self.collect_for_asset_historical(
                asset_id, name, ticker, keywords, days_back
            )

            # Save posts
            saved = 0
            if posts:
                saved = self.save_posts(posts)
                logger.info(f"{self.name}: Collected {len(posts)} historical posts for {name} ({saved} new)")

            # Update status to completed
            conn = self.get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE asset
                        SET initialization_status = 'completed',
                            initialization_completed_at = NOW()
                        WHERE id = %s
                    """, (asset_id,))
                    conn.commit()
            finally:
                conn.close()

            logger.info(f"{self.name}: Historical initialization complete for asset {asset_id}")

            return {
                'total_posts': len(posts),
                'total_saved': saved
            }

        except Exception as e:
            logger.error(f"{self.name}: Error in historical initialization for asset {asset_id}: {e}")

            # Update status to failed
            try:
                conn = self.get_db_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE asset
                            SET initialization_status = 'failed'
                            WHERE id = %s
                        """, (asset_id,))
                        conn.commit()
                finally:
                    conn.close()
            except:
                pass

            raise

    @classmethod
    def get_collector_name(cls) -> str:
        """Get the human-readable name of this collector."""
        return cls.__name__.replace('Collector', '')
