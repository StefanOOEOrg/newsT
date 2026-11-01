"""Keyword matching and keyword performance tracking.

Matching is deliberately the same rule the legacy collector used: a keyword matches
when it appears as a substring of the lower-cased text. That is what the stored
``keyword_performance`` numbers were produced with, so a stricter rule would make the
history incomparable.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import psycopg2

from newstrading.config import Settings
from newstrading.db import Connector, connect

logger = logging.getLogger(__name__)


class KeywordTracker:
    """Matches keywords against post text and records the hits."""

    def __init__(self, settings: Settings, *, connector: Connector = psycopg2.connect):
        """Remember the database this tracker writes to.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._connector = connector

    @staticmethod
    def identify_keyword_matches(text: str, keywords: Sequence[str]) -> list[str]:
        """Return the keywords that occur in ``text``.

        Args:
            text: Title and content of a post, usually joined with a space.
            keywords: Candidate keywords, in the spelling stored on the asset.

        Returns:
            The matching keywords in the order of ``keywords``, each in its original
            spelling. Matching is case insensitive and by substring — ``snow`` matches
            inside ``snowflake``. Empty ``text`` or an empty ``keywords`` sequence
            returns an empty list.
        """
        if not text or not keywords:
            return []

        text_lower = text.lower()
        return [keyword for keyword in keywords if keyword.lower() in text_lower]

    def record_keyword_hit(self, asset_id: int, keywords: Sequence[str]) -> None:
        """Count one hit per keyword for ``asset_id``.

        Args:
            asset_id: Asset the post belongs to.
            keywords: Keywords that matched; each is stored lower-cased.

        Contract:
            * An empty ``keywords`` sequence opens no connection and writes nothing.
            * One upsert per keyword into ``keyword_performance``: first hit inserts
              with ``posts_found = 1``, later hits increment it and refresh
              ``last_found_at``.
            * Best effort: a database failure rolls back, is logged as a warning and
              does not raise — a broken statistics table must not abort a collection.
        """
        if not keywords:
            return

        conn = None
        try:
            conn = connect(self._settings.database_url, connector=self._connector)
            with conn.cursor() as cursor:
                for keyword in keywords:
                    cursor.execute(
                        """
                        INSERT INTO keyword_performance
                        (asset_id, keyword, posts_found, last_found_at, first_seen_at)
                        VALUES (%s, %s, 1, NOW(), NOW())
                        ON CONFLICT (asset_id, keyword)
                        DO UPDATE SET
                            posts_found = keyword_performance.posts_found + 1,
                            last_found_at = NOW()
                        """,
                        (asset_id, keyword.lower()),
                    )
            conn.commit()
            logger.debug("Recorded %d keyword hits for asset %s", len(keywords), asset_id)
        # boundary: a broken statistics table must not abort a collection run
        except Exception as error:
            if conn is not None:
                conn.rollback()
            logger.warning("Error recording keyword hits for asset %s: %s", asset_id, error)
        finally:
            if conn is not None:
                conn.close()
