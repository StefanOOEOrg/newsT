"""Storing collected posts and counting the keyword hits they carry."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from newstrading.collectors.models import Post
from newstrading.config import Settings
from newstrading.db import Connector, connect
from newstrading.keywords import KeywordTracker

logger = logging.getLogger(__name__)

INSERT_SQL = """
    INSERT INTO social_posts
    (asset_id, source, post_id, author, title, content, url, score, created_at, matched_keywords)
    VALUES %s
    ON CONFLICT (post_id) DO NOTHING
"""

InsertMany = Callable[[Any, Sequence[tuple]], int]


def insert_many(cursor: Any, values: Sequence[tuple]) -> int:
    """Insert all rows in one statement and return how many were new.

    Args:
        cursor: Open cursor of a psycopg2 connection.
        values: Rows in the column order of :data:`INSERT_SQL`.

    Returns:
        The row count of the statement — posts that already existed are not counted
        because of the ``ON CONFLICT DO NOTHING``.
    """
    execute_values(cursor, INSERT_SQL, values)
    return int(cursor.rowcount)


def _keywords(cursor: Any, asset_id: int) -> tuple[str, ...]:
    """Return the keywords stored on ``asset`` for ``asset_id``.

    Args:
        cursor: Open cursor, used for the one query that belongs to this asset.
        asset_id: Primary key in the ``asset`` table.

    Returns:
        The stored keywords in their original spelling; empty when the column is
        ``NULL`` or the asset has no row.
    """
    cursor.execute("SELECT keywords FROM asset WHERE id = %s", (asset_id,))
    row = cursor.fetchone()
    return tuple(row[0]) if row and row[0] else ()


class PostStore:
    """Writes posts to ``social_posts`` and books their keyword hits."""

    def __init__(
        self,
        settings: Settings,
        *,
        keyword_tracker: KeywordTracker,
        insert: InsertMany = insert_many,
        connector: Connector = psycopg2.connect,
    ):
        """Remember the database, the tracker and the insert strategy.

        Args:
            settings: Settings holding ``database_url``.
            keyword_tracker: Used to match keywords and to record the hits.
            insert: Inserts the prepared rows; injected in tests so no database and no
                real cursor is needed.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._keyword_tracker = keyword_tracker
        self._insert = insert
        self._connector = connector

    def save(self, posts: Sequence[Post]) -> int:
        """Persist ``posts`` and count their keyword hits.

        Args:
            posts: Posts collected for one or more assets.

        Returns:
            Number of posts that were new; ``0`` for an empty sequence.

        Contract:
            * An empty sequence opens no connection and writes nothing.
            * The keywords of every distinct ``asset_id`` are read from ``asset``
              before inserting; each post is matched against the keywords of its own
              asset (title and content, joined with a space).
            * Rows are inserted in the column order of :data:`INSERT_SQL`; the matched
              keywords travel as the last column.
            * Keyword hits are recorded **only** when the insert reported new posts,
              one call per post that carried a match.
            * A database failure rolls back and is re-raised — a post that was fetched
              but not stored is a real loss, unlike a statistics row.
        """
        if not posts:
            return 0

        connection: Any = None
        try:
            connection = connect(self._settings.database_url, connector=self._connector)
            keywords_by_asset: dict[int, tuple[str, ...]] = {}
            with connection.cursor() as cursor:
                for asset_id in sorted({post.asset_id for post in posts}):
                    keywords_by_asset[asset_id] = _keywords(cursor, asset_id)
            rows, hits = self._prepare_rows(posts, keywords_by_asset)
            with connection.cursor() as cursor:
                saved = self._insert(cursor, rows)
            connection.commit()
        # boundary: rollback and re-raise — a lost post is a real loss
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

        if saved > 0:
            for asset_id, matched in hits:
                self._keyword_tracker.record_keyword_hit(asset_id, matched)
        return saved

    def _prepare_rows(
        self, posts: Sequence[Post], keywords_by_asset: dict[int, tuple[str, ...]]
    ) -> tuple[list[tuple], list[tuple[int, list[str]]]]:
        """Build the insert rows and the keyword hits that go with them.

        Args:
            posts: Posts to store, in the order they should be inserted.
            keywords_by_asset: Keywords of every distinct asset, keyed by ``asset_id``.

        Returns:
            The rows in the column order of :data:`INSERT_SQL`, and for every post that
            matched at least one keyword the ``(asset_id, keywords)`` pair to book.
        """
        rows: list[tuple] = []
        hits: list[tuple[int, list[str]]] = []
        for post in posts:
            text = f"{post.title} {post.content or ''}".strip()
            matched = self._keyword_tracker.identify_keyword_matches(
                text, keywords_by_asset[post.asset_id]
            )
            rows.append(
                (
                    post.asset_id,
                    post.source,
                    post.post_id,
                    post.author,
                    post.title,
                    post.content,
                    post.url,
                    post.score,
                    post.created_at,
                    matched,
                )
            )
            if matched:
                hits.append((post.asset_id, matched))
        return rows, hits
