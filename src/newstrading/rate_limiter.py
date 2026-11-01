"""Per-source API rate limiting, tracked in the database.

The quota itself lives in Postgres: ``check_rate_limit(name)`` answers whether another
call is allowed and ``api_usage`` records what was called. This module is the thin
client around those two, so a collector never talks to the tables directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg2

from newstrading.config import Settings
from newstrading.db import Connector, connect, connection

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of a quota check.

    Attributes:
        allowed: Whether the next API call may be made.
        reason: Human readable explanation, logged by the collector.
        wait_seconds: Seconds to wait when ``allowed`` is false, otherwise ``0``.
    """

    allowed: bool
    reason: str
    wait_seconds: int


class RateLimiter:
    """Tracks and enforces the API quota of one collector."""

    def __init__(
        self, settings: Settings, collector_name: str, *, connector: Connector = psycopg2.connect
    ):
        """Remember the database and the source this limiter belongs to.

        Args:
            settings: Settings holding ``database_url``.
            collector_name: Name stored in ``api_usage`` and used by
                ``check_rate_limit``.
            connector: Connection factory; tests inject a fake, production leaves it
                at :func:`psycopg2.connect`.
        """
        self._settings = settings
        self._collector_name = collector_name
        self._connector = connector

    def can_make_request(self) -> RateLimitDecision:
        """Ask the database whether another request is allowed.

        Returns:
            The decision from ``check_rate_limit``. When the function returns no row
            the source has no quota configured, which allows the request with the
            reason ``No rate limit configured``.

        Contract:
            A failing quota check never blocks collection: the request is allowed and
            the reason starts with ``Rate limit check failed:``, followed by the error.
            The error is logged as a warning; nothing is raised.
        """
        try:
            with connection(self._settings, connector=self._connector) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT can_proceed, reason, wait_seconds FROM check_rate_limit(%s)",
                        (self._collector_name,),
                    )
                    row = cursor.fetchone()
        # boundary: a broken quota check must not stop the collection
        except Exception as error:
            logger.warning("Rate limit check for %s failed: %s", self._collector_name, error)
            return RateLimitDecision(
                allowed=True, reason=f"Rate limit check failed: {error}", wait_seconds=0
            )

        if row is None:
            return RateLimitDecision(
                allowed=True, reason="No rate limit configured", wait_seconds=0
            )

        allowed, reason, wait_seconds = row
        return RateLimitDecision(allowed=allowed, reason=reason, wait_seconds=wait_seconds)

    def record_request(
        self,
        *,
        success: bool = True,
        status_code: int | None = None,
        error_message: str | None = None,
        api_endpoint: str | None = None,
    ) -> None:
        """Record one API call in ``api_usage``.

        Args:
            success: Whether the call succeeded.
            status_code: HTTP status, when the source has one.
            error_message: Failure text; truncated to
                :data:`MAX_ERROR_MESSAGE_LENGTH` characters.
            api_endpoint: URL called, when known.

        Contract:
            Recording is best effort: a database failure rolls the statement back, is
            logged as a warning, and does not raise — a broken audit table must not stop
            the collection run.
        """
        conn = None
        try:
            conn = connect(self._settings.database_url, connector=self._connector)
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO api_usage
                    (collector_name, api_endpoint, status_code, success, error_message)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        self._collector_name,
                        api_endpoint,
                        status_code,
                        success,
                        error_message[:MAX_ERROR_MESSAGE_LENGTH] if error_message else None,
                    ),
                )
            conn.commit()
            logger.debug("Recorded API usage for %s", self._collector_name)
        # boundary: the audit table must never abort a collection run
        except Exception as error:
            if conn is not None:
                conn.rollback()
            logger.warning("Error recording API usage for %s: %s", self._collector_name, error)
        finally:
            if conn is not None:
                conn.close()
