"""
Keyword Performance Tracker
Tracks which keywords are finding posts and analyzes their performance.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class KeywordTracker:
    """Tracks keyword performance and provides analytics."""

    def __init__(self, database_url: str):
        """
        Initialize keyword tracker.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def record_keyword_hit(self, asset_id: int, matched_keywords: List[str]):
        """
        Record that certain keywords matched a post.

        Args:
            asset_id: Asset ID
            matched_keywords: List of keywords that matched
        """
        if not matched_keywords:
            return

        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                for keyword in matched_keywords:
                    # Update or insert keyword performance
                    cur.execute("""
                        INSERT INTO keyword_performance
                        (asset_id, keyword, posts_found, last_found_at, first_seen_at)
                        VALUES (%s, %s, 1, NOW(), NOW())
                        ON CONFLICT (asset_id, keyword)
                        DO UPDATE SET
                            posts_found = keyword_performance.posts_found + 1,
                            last_found_at = NOW()
                    """, (asset_id, keyword.lower()))
                conn.commit()
                logger.debug(f"Recorded {len(matched_keywords)} keyword hits for asset {asset_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error recording keyword hits: {e}")
        finally:
            conn.close()

    def get_keyword_performance(self, asset_id: int) -> List[Dict]:
        """
        Get keyword performance stats for an asset.

        Args:
            asset_id: Asset ID

        Returns:
            List of dicts with keyword stats
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        keyword,
                        posts_found,
                        last_found_at,
                        first_seen_at,
                        EXTRACT(DAY FROM (NOW() - last_found_at)) as days_since_last_hit,
                        EXTRACT(DAY FROM (NOW() - first_seen_at)) as days_tracked
                    FROM keyword_performance
                    WHERE asset_id = %s
                    ORDER BY posts_found DESC, last_found_at DESC NULLS LAST
                """, (asset_id,))
                return cur.fetchall()
        finally:
            conn.close()

    def get_underperforming_keywords(
        self,
        asset_id: int,
        min_days_inactive: int = 30,
        min_posts_threshold: int = 5
    ) -> List[Dict]:
        """
        Find keywords that haven't found posts recently or have low hit counts.

        Args:
            asset_id: Asset ID
            min_days_inactive: Days since last hit to consider inactive
            min_posts_threshold: Minimum posts to not be considered underperforming

        Returns:
            List of underperforming keyword dicts
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        keyword,
                        posts_found,
                        last_found_at,
                        first_seen_at,
                        EXTRACT(DAY FROM (NOW() - COALESCE(last_found_at, first_seen_at))) as days_since_last_hit
                    FROM keyword_performance
                    WHERE asset_id = %s
                      AND (
                          -- Never found any posts
                          (last_found_at IS NULL AND EXTRACT(DAY FROM (NOW() - first_seen_at)) > %s)
                          OR
                          -- Hasn't found posts in X days
                          (EXTRACT(DAY FROM (NOW() - last_found_at)) > %s)
                          OR
                          -- Low hit count after significant time
                          (posts_found < %s AND EXTRACT(DAY FROM (NOW() - first_seen_at)) > %s)
                      )
                    ORDER BY posts_found ASC, last_found_at ASC NULLS FIRST
                """, (asset_id, min_days_inactive, min_days_inactive, min_posts_threshold, min_days_inactive))
                return cur.fetchall()
        finally:
            conn.close()

    def remove_keywords_from_asset(self, asset_id: int, keywords: List[str]) -> int:
        """
        Remove keywords from an asset.

        Args:
            asset_id: Asset ID
            keywords: List of keywords to remove

        Returns:
            Number of keywords removed
        """
        if not keywords:
            return 0

        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                # Get current keywords
                cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (asset_id,))
                current_keywords = cur.fetchone()[0]

                # Remove specified keywords
                keywords_lower = [k.lower() for k in keywords]
                updated_keywords = [kw for kw in current_keywords if kw.lower() not in keywords_lower]

                # Update asset
                cur.execute(
                    "UPDATE asset SET search_keywords = %s WHERE id = %s",
                    (updated_keywords, asset_id)
                )

                # Archive the keyword performance records (don't delete, keep for history)
                # You could also delete them if preferred
                # cur.execute(
                #     "DELETE FROM keyword_performance WHERE asset_id = %s AND keyword = ANY(%s)",
                #     (asset_id, keywords_lower)
                # )

                conn.commit()
                removed_count = len(current_keywords) - len(updated_keywords)
                logger.info(f"Removed {removed_count} keywords from asset {asset_id}")
                return removed_count
        except Exception as e:
            conn.rollback()
            logger.error(f"Error removing keywords: {e}")
            return 0
        finally:
            conn.close()

    def initialize_keyword_tracking(self, asset_id: int):
        """
        Initialize keyword performance tracking for an asset's existing keywords.

        Args:
            asset_id: Asset ID
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                # Get asset keywords
                cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (asset_id,))
                keywords = cur.fetchone()[0]

                # Initialize performance tracking for each keyword
                for keyword in keywords:
                    cur.execute("""
                        INSERT INTO keyword_performance
                        (asset_id, keyword, posts_found, first_seen_at)
                        VALUES (%s, %s, 0, NOW())
                        ON CONFLICT (asset_id, keyword) DO NOTHING
                    """, (asset_id, keyword.lower()))

                conn.commit()
                logger.info(f"Initialized tracking for {len(keywords)} keywords on asset {asset_id}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error initializing keyword tracking: {e}")
        finally:
            conn.close()

    def get_keyword_stats_summary(self, asset_id: int) -> Dict:
        """
        Get summary statistics for an asset's keywords.

        Args:
            asset_id: Asset ID

        Returns:
            Dict with summary stats
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_keywords,
                        SUM(posts_found) as total_posts_found,
                        AVG(posts_found) as avg_posts_per_keyword,
                        MAX(posts_found) as max_posts,
                        COUNT(CASE WHEN posts_found = 0 THEN 1 END) as keywords_with_no_hits,
                        COUNT(CASE WHEN last_found_at IS NULL THEN 1 END) as never_matched,
                        COUNT(CASE WHEN EXTRACT(DAY FROM (NOW() - COALESCE(last_found_at, first_seen_at))) > 30 THEN 1 END) as inactive_30_days
                    FROM keyword_performance
                    WHERE asset_id = %s
                """, (asset_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def identify_keyword_matches(self, text: str, keywords: List[str]) -> List[str]:
        """
        Identify which keywords from a list match in the given text.

        Args:
            text: Text to search in (title + content)
            keywords: List of keywords to check

        Returns:
            List of matched keywords
        """
        if not text or not keywords:
            return []

        text_lower = text.lower()
        matched = []

        for keyword in keywords:
            if keyword.lower() in text_lower:
                matched.append(keyword)

        return matched
