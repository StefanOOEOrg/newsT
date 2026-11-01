"""Reading the assets a collection run should cover."""

from __future__ import annotations

from typing import Any

import psycopg2

from newstrading.collectors.models import Asset
from newstrading.config import Settings
from newstrading.db import Connector, connect

_PENDING_INIT = """
    SELECT id, name, ticker, search_keywords
    FROM asset
    WHERE initialization_status = 'pending'
"""

_BY_NAME = """
    SELECT id, name, ticker, search_keywords
    FROM asset
    WHERE initialization_status IN ('completed', 'in_progress')
       OR initialization_status IS NULL
    ORDER BY name
"""

_BY_DSS = """
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
"""

_STORED_POST = "SELECT 1 FROM social_posts WHERE post_id = %s"


class AssetStore:
    """Reads the tracked assets and answers whether a post is already stored."""

    def __init__(self, settings: Settings, *, connector: Connector = psycopg2.connect):
        """Remember the database.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._connector = connector

    def list_for_collection(
        self, *, include_pending_init: bool = False, prioritize_by_dss: bool = True
    ) -> list[Asset]:
        """Return the assets a run should collect for.

        Args:
            include_pending_init: Only assets whose ``initialization_status`` is
                ``pending``, i.e. the ones waiting for their historical backfill.
            prioritize_by_dss: Order by the absolute decision signal strength — the
                difference between today's long and short signals — descending, with
                the asset name as tiebreaker. Irrelevant when ``include_pending_init``
                is set.

        Returns:
            The assets, keywords as a tuple.

        Contract:
            * Default call collects the regular set: ``initialization_status`` in
              (``completed``, ``in_progress``) or ``NULL``.
            * ``include_pending_init=True`` selects only ``pending`` assets and applies
              no ordering.
            * ``prioritize_by_dss=False`` orders by name instead.
            * Keywords arrive as a tuple, never as a list.
            * A database failure is **not** swallowed: without assets there is nothing
              to collect. A failed connection arrives as
              :class:`~newstrading.db.DatabaseError`, a failing statement as the driver
              error — both reach the caller.
        """
        if include_pending_init:
            statement = _PENDING_INIT
        elif prioritize_by_dss:
            statement = _BY_DSS
        else:
            statement = _BY_NAME
        # ``newstrading.db.Connection`` names only commit/rollback/close, so the cursor
        # is not visible to a type checker here.
        connection: Any = None
        try:
            connection = connect(self._settings.database_url, connector=self._connector)
            with connection.cursor() as cursor:
                cursor.execute(statement)
                rows = cursor.fetchall()
        finally:
            if connection is not None:
                connection.close()
        return [
            Asset(id=row[0], name=row[1], ticker=row[2], keywords=tuple(row[3] or ()))
            for row in rows
        ]

    def exists(self, post_id: str) -> bool:
        """Return whether a post with ``post_id`` is already stored.

        Args:
            post_id: Source identifier of the post.

        Returns:
            ``True`` if ``social_posts`` already holds that id.
        """
        # ``newstrading.db.Connection`` names only commit/rollback/close, so the cursor
        # is not visible to a type checker here.
        connection: Any = None
        try:
            connection = connect(self._settings.database_url, connector=self._connector)
            with connection.cursor() as cursor:
                cursor.execute(_STORED_POST, (post_id,))
                return cursor.fetchone() is not None
        finally:
            if connection is not None:
                connection.close()
