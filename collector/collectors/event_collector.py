"""
Event Collector Base Class

Abstract base for collecting financial calendar events (earnings, filings, product launches, etc.)
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime, date
import logging
import json
import psycopg2
from psycopg2.extras import execute_values, Json
import sys
from pathlib import Path

# Add shared directory to path
shared_path = Path(__file__).parent.parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

logger = logging.getLogger(__name__)


class EventCollector(ABC):
    """
    Abstract base class for event collectors.

    Each implementation collects financial calendar events from a specific source
    (Alpha Vantage, Yahoo Finance, SEC EDGAR, etc.)
    """

    def __init__(self, database_url: str):
        """
        Initialize the event collector.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.name = self.__class__.__name__
        logger.info(f"{self.name} initialized")

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def get_assets(self) -> List[tuple]:
        """
        Fetch all assets from database.

        Returns:
            List of tuples: (id, name, ticker)
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, ticker
                    FROM asset
                    WHERE initialization_status IN ('completed', 'in_progress')
                       OR initialization_status IS NULL
                    ORDER BY id
                """)
                return cur.fetchall()
        finally:
            conn.close()

    def event_exists(self, asset_id: int, event_type: str, event_date: date, source: str) -> bool:
        """
        Check if an event already exists in the database.

        Args:
            asset_id: Asset ID
            event_type: Type of event
            event_date: Date of event
            source: Event source

        Returns:
            True if event exists, False otherwise
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1
                    FROM asset_events
                    WHERE asset_id = %s
                      AND event_type = %s
                      AND event_date = %s
                      AND source = %s
                """, (asset_id, event_type, event_date, source))
                return cur.fetchone() is not None
        finally:
            conn.close()

    def save_events(self, events: List[Dict]) -> int:
        """
        Save events to the database.

        Args:
            events: List of event dictionaries with required fields:
                - asset_id: int
                - event_type: str
                - event_date: date
                - event_time: time (optional)
                - description: str
                - url: str (optional)
                - source: str
                - metadata: dict (optional)

        Returns:
            Number of events saved
        """
        if not events:
            return 0

        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                # Prepare data for batch insert
                # Convert metadata dict to JSON string for JSONB column
                values = [
                    (
                        event['asset_id'],
                        event['event_type'],
                        event['event_date'],
                        event.get('event_time'),
                        event.get('description'),
                        event.get('url'),
                        event['source'],
                        Json(event.get('metadata')) if event.get('metadata') else None
                    )
                    for event in events
                ]

                # Batch insert with ON CONFLICT DO NOTHING
                execute_values(
                    cur,
                    """
                    INSERT INTO asset_events
                    (asset_id, event_type, event_date, event_time, description, url, source, metadata)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                    """,
                    values,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s)"
                )

                saved_count = cur.rowcount
                conn.commit()
                logger.info(f"{self.name}: Saved {saved_count} events to database")
                return saved_count
        except Exception as e:
            conn.rollback()
            logger.error(f"{self.name}: Error saving events: {e}")
            raise
        finally:
            conn.close()

    def clean_old_events(self, days_old: int = 90):
        """
        Remove events older than specified days.

        Args:
            days_old: Number of days to keep (default: 90)
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM asset_events
                    WHERE event_date < CURRENT_DATE - INTERVAL '%s days'
                      AND source = %s
                """, (days_old, self.source_name))
                deleted_count = cur.rowcount
                conn.commit()

                if deleted_count > 0:
                    logger.info(f"{self.name}: Cleaned {deleted_count} old events (>{days_old} days)")
        except Exception as e:
            conn.rollback()
            logger.error(f"{self.name}: Error cleaning old events: {e}")
        finally:
            conn.close()

    @property
    def source_name(self) -> str:
        """Return the source identifier for this collector."""
        return self.__class__.__name__.replace('Collector', '').lower()

    @abstractmethod
    def collect_events_for_asset(self, asset_id: int, asset_name: str, ticker: str) -> List[Dict]:
        """
        Collect events for a specific asset.

        This method must be implemented by each collector subclass.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Stock ticker symbol

        Returns:
            List of event dictionaries
        """
        pass

    def collect_all_events(self) -> Dict[str, int]:
        """
        Main collection function - fetch events for all assets.

        Returns:
            Dictionary with statistics: {'total_events': int, 'total_saved': int}
        """
        logger.info(f"{self.name}: Starting event collection...")

        try:
            assets = self.get_assets()
            logger.info(f"{self.name}: Found {len(assets)} assets to track")

            total_events = 0
            total_saved = 0

            for asset_id, name, ticker in assets:
                logger.info(f"{self.name}: Collecting events for {name} ({ticker})")

                try:
                    events = self.collect_events_for_asset(asset_id, name, ticker)

                    if events:
                        saved = self.save_events(events)
                        total_events += len(events)
                        total_saved += saved
                        logger.info(f"{self.name}: Collected {len(events)} events for {name} ({saved} new)")
                    else:
                        logger.info(f"{self.name}: No events found for {name}")

                except Exception as e:
                    logger.error(f"{self.name}: Error collecting events for {name}: {e}")
                    continue

            # Clean old events after collection
            self.clean_old_events()

            logger.info(f"{self.name}: Collection complete. Total: {total_events} events ({total_saved} new)")

            return {
                'total_events': total_events,
                'total_saved': total_saved
            }

        except Exception as e:
            logger.error(f"{self.name}: Error in collect_all_events: {e}")
            raise
