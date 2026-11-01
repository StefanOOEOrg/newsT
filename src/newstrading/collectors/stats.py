"""Collector run statistics, persisted in ``collector_statistics``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg2

from newstrading.config import Settings
from newstrading.db import Connector, connect

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 500

_COLUMNS = (
    "last_run_started_at, last_run_completed_at, last_run_duration_seconds, "
    "total_posts_collected, total_posts_saved, last_run_posts_collected, "
    "last_run_posts_saved, total_errors, last_error_message, last_error_at"
)

_UPSERT = f"""
    INSERT INTO collector_statistics (collector_name, {_COLUMNS}, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
"""


@dataclass(frozen=True, slots=True)
class CollectorStats:
    """What one collector did so far.

    Attributes:
        collector_name: Key the row is stored under.
        last_run_started_at: Start of the last run, ``None`` before the first run.
        last_run_completed_at: End of the last run.
        last_run_duration_seconds: Wall time of the last run.
        total_posts_collected: Posts found since the collector existed.
        total_posts_saved: Posts actually new in the database.
        last_run_posts_collected: Posts found in the last run.
        last_run_posts_saved: Posts saved in the last run.
        total_errors: Errors counted since the collector existed.
        last_error_message: Last error text, truncated to 500 characters.
        last_error_at: When that error happened.
    """

    collector_name: str
    last_run_started_at: datetime | None = None
    last_run_completed_at: datetime | None = None
    last_run_duration_seconds: float | None = None
    total_posts_collected: int = 0
    total_posts_saved: int = 0
    last_run_posts_collected: int = 0
    last_run_posts_saved: int = 0
    total_errors: int = 0
    last_error_message: str | None = None
    last_error_at: datetime | None = None


class CollectorStatsStore:
    """Reads and writes :class:`CollectorStats` rows."""

    def __init__(self, settings: Settings, *, connector: Connector = psycopg2.connect):
        """Remember the database.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._connector = connector

    def load(self, collector_name: str) -> CollectorStats:
        """Return the stored statistics of one collector.

        Args:
            collector_name: Key the row is stored under.

        Returns:
            The stored statistics, or :class:`CollectorStats` holding only the name
            when there is no row yet.

        Contract:
            A failing read does not abort a collection run: the defaults are returned
            and the error is logged as a warning.
        """
        defaults = CollectorStats(collector_name=collector_name)
        row = None
        # ``newstrading.db.Connection`` names only commit/rollback/close, so the cursor
        # is not visible to a type checker here.
        connection: Any = None
        try:
            connection = connect(self._settings.database_url, connector=self._connector)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_COLUMNS} FROM collector_statistics WHERE collector_name = %s",
                    (collector_name,),
                )
                row = cursor.fetchone()
        # boundary: a broken statistics read must not abort a collection run
        except Exception as error:
            logger.warning("%s: could not load statistics: %s", collector_name, error)
            return defaults
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return defaults
        return CollectorStats(collector_name, *row)

    def save(self, stats: CollectorStats) -> None:
        """Insert or update the row of ``stats.collector_name``.

        Args:
            stats: The values to persist; a message longer than
                :data:`MAX_ERROR_MESSAGE_LENGTH` is truncated.

        Contract:
            One upsert on ``collector_name``, then a commit. A failing write rolls back,
            is logged as a warning and does not raise — a broken statistics table must
            not stop the collection.
        """
        params = (
            stats.collector_name,
            stats.last_run_started_at,
            stats.last_run_completed_at,
            stats.last_run_duration_seconds,
            stats.total_posts_collected,
            stats.total_posts_saved,
            stats.last_run_posts_collected,
            stats.last_run_posts_saved,
            stats.total_errors,
            _truncate(stats.last_error_message),
            stats.last_error_at,
        )
        connection: Any = None
        try:
            connection = connect(self._settings.database_url, connector=self._connector)
            with connection.cursor() as cursor:
                cursor.execute(_UPSERT, params)
            connection.commit()
        # boundary: a broken statistics write must not stop the collection
        except Exception as error:
            logger.warning("%s: could not save statistics: %s", stats.collector_name, error)
            if connection is not None:
                connection.rollback()
        finally:
            if connection is not None:
                connection.close()


def _truncate(message: str | None) -> str | None:
    """Return ``message`` cut to :data:`MAX_ERROR_MESSAGE_LENGTH` characters.

    Args:
        message: Error text to store, or ``None``.

    Returns:
        The message unchanged when it fits, otherwise its first
        :data:`MAX_ERROR_MESSAGE_LENGTH` characters; ``None`` stays ``None``.
    """
    if message is None:
        return None
    return message[:MAX_ERROR_MESSAGE_LENGTH]
