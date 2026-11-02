"""Track what an alert predicted against what the price then did.

The module ports ``analyzer/performance_tracker.py`` into the package: it stores the
price at alert time for every alert that has no record yet, and fills the later prices,
returns and directions of every record whose 30-day horizon is still open.

Neither a database nor a price loader is created here: the connection factory and the
:class:`PriceProvider` are injected, so the tracker is testable without a socket and
without ``yfinance``. The thresholds, the horizons, the SQL and the rounding are the
legacy ones, because old and new rows must stay comparable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any, Protocol

import psycopg2

from newstrading.config import Settings
from newstrading.db import Connector, connection
from newstrading.errors import NewsTradingError

logger = logging.getLogger(__name__)

HORIZONS = (1, 3, 7, 14, 30)
"""Days after the alert that a record stores a price and a return for."""

DIRECTION_HORIZONS = (1, 3, 7)
"""Horizons that also carry an actual direction — the legacy columns."""

DIRECTION_THRESHOLD = 0.005
"""Smallest return that counts as directional; anything smaller is ``neutral``."""

FULL_UPDATE_LIMIT = 100
"""Batch size of :meth:`PerformanceTracker.run_full_update`, as in the legacy script."""

BULLISH_TYPES = (
    "long_signal",
    "partnership",
    "product_launch",
    "analyst_upgrade",
    "market_share",
    "guidance",
    "insider_trading",
    "executive_change",
)
"""Legacy alert types that predict a rising price."""

BEARISH_TYPES = (
    "short_signal",
    "regulatory_risk",
    "analyst_downgrade",
    "customer_loss",
    "problem_detected",
    "negative_sentiment",
)
"""Legacy alert types that predict a falling price."""


class PerformanceError(NewsTradingError):
    """Raised when the tracker cannot read alerts or write performance records."""


class PriceProvider(Protocol):
    """What the tracker needs from the price side."""

    def price_at(self, ticker: str, day: date) -> float | None:
        """Closing price on ``day`` or the nearest earlier trading day; ``None`` when unknown."""
        ...

    def series(self, ticker: str, day: date, days: Sequence[int]) -> dict[int, float | None]:
        """Closing prices ``days`` trading days after ``day``; missing horizons are ``None``."""
        ...


UNTRACKED_SQL = """
    SELECT
        a.id,
        a.asset_id,
        a.alert_type,
        a.timestamp,
        a.confidence_score,
        c.ticker
    FROM alerts a
    JOIN asset c ON a.asset_id = c.id
    LEFT JOIN alert_performance ap ON a.id = ap.alert_id
    WHERE ap.id IS NULL
      AND a.timestamp < NOW() - INTERVAL '1 day'
      AND c.ticker IS NOT NULL
      AND c.ticker != ''
    ORDER BY a.timestamp ASC
    LIMIT %s
"""
"""Alerts without a record, oldest first; ``limit`` binds as the only parameter."""

OUTDATED_SQL = """
    SELECT
        ap.id,
        ap.alert_date,
        c.ticker,
        ap.price_at_alert
    FROM alert_performance ap
    JOIN asset c ON ap.asset_id = c.id
    WHERE (
        ap.price_30d_later IS NULL
        AND ap.alert_date < NOW() - INTERVAL '30 days'
    )
    OR (
        ap.price_14d_later IS NULL
        AND ap.alert_date < NOW() - INTERVAL '14 days'
    )
    OR (
        ap.price_7d_later IS NULL
        AND ap.alert_date < NOW() - INTERVAL '7 days'
    )
    OR (
        ap.price_3d_later IS NULL
        AND ap.alert_date < NOW() - INTERVAL '3 days'
    )
    ORDER BY ap.alert_date DESC
    LIMIT %s
"""
"""Records with an open horizon that is old enough to have a price; ``limit`` binds."""

INSERT_SQL = """
    INSERT INTO alert_performance (
        alert_id, asset_id, alert_type, alert_date, confidence_score,
        price_at_alert,
        price_1d_later, price_3d_later, price_7d_later,
        price_14d_later, price_30d_later,
        return_1d, return_3d, return_7d, return_14d, return_30d,
        predicted_direction,
        actual_direction_1d, actual_direction_3d, actual_direction_7d,
        correct_1d, correct_3d, correct_7d
    ) VALUES (
        %s, %s, %s, %s, %s,
        %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s,
        %s, %s, %s,
        %s, %s, %s
    )
"""
"""The legacy insert, column for column."""

UPDATE_SQL = """
    UPDATE alert_performance
    SET
        price_1d_later = %s,
        price_3d_later = %s,
        price_7d_later = %s,
        price_14d_later = %s,
        price_30d_later = %s,
        return_1d = %s,
        return_3d = %s,
        return_7d = %s,
        return_14d = %s,
        return_30d = %s,
        actual_direction_1d = %s,
        actual_direction_3d = %s,
        actual_direction_7d = %s,
        last_updated = NOW()
    WHERE id = %s
"""
"""The legacy update; the record id binds last."""


def _direction(value: float | None) -> str | None:
    """Return ``bullish``, ``bearish`` or ``neutral`` for a return, ``None`` without one.

    Args:
        value: Return as a decimal, already rounded.

    Returns:
        The direction of a return above ``DIRECTION_THRESHOLD``, below its negative, or
        inside that band; ``None`` when ``value`` is ``None``.
    """
    if value is None:
        return None
    if value > DIRECTION_THRESHOLD:
        return "bullish"
    if value < -DIRECTION_THRESHOLD:
        return "bearish"
    return "neutral"


def _measure(
    base: float, prices: dict[int, float | None]
) -> tuple[dict[int, float | None], dict[int, str | None]]:
    """Turn later prices into the legacy returns and actual directions.

    Args:
        base: The price at alert time.
        prices: Later prices keyed by horizon; a missing horizon is ``None``.

    Returns:
        Two dicts keyed by :data:`HORIZONS`: the returns rounded to four decimals and
        their directions. A horizon without a price gives ``None`` in both.
    """
    returns: dict[int, float | None] = {}
    directions: dict[int, str | None] = {}
    for horizon in HORIZONS:
        price = prices.get(horizon)
        # legacy: no return from a missing price or a zero base
        value = None if price is None or not base else round((price - base) / base, 4)
        returns[horizon] = value
        directions[horizon] = _direction(value)
    return returns, directions


class PerformanceTracker:
    """Creates and completes the rows of ``alert_performance``."""

    def __init__(
        self,
        settings: Settings,
        *,
        connector: Connector = psycopg2.connect,
        prices: PriceProvider,
    ) -> None:
        """Remember where the records live and where the prices come from.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
            prices: Price provider; injected, this module never imports ``yfinance``
                and never opens a socket for prices.
        """
        self._settings = settings
        self._connector = connector
        self._prices = prices

    def determine_predicted_direction(self, alert_type: str) -> str:
        """Map the alert type to ``bullish``, ``bearish`` or ``neutral``.

        Legacy lists: bullish = long_signal, partnership, product_launch, analyst_upgrade,
        market_share, guidance, insider_trading, executive_change; bearish = short_signal,
        regulatory_risk, analyst_downgrade, customer_loss, problem_detected,
        negative_sentiment; a substring match on the lower-cased type, bullish first.
        """
        lowered = alert_type.lower()
        if any(name in lowered for name in BULLISH_TYPES):
            return "bullish"
        if any(name in lowered for name in BEARISH_TYPES):
            return "bearish"
        return "neutral"

    def track_new_alerts(self, limit: int = 50) -> int:
        """Create a record for every untracked alert that has a base price.

        Args:
            limit: Maximum number of alerts to look at; binds into the select.

        Returns:
            Number of records created. An alert whose ``price_at`` is ``None`` is
            logged and skipped, so the next run tries it again — it is never written
            with a ``NULL`` base.

        Contract:
            * One connection, one commit; a failure rolls back and raises
              :class:`PerformanceError`.
        """
        created = 0
        with self._session() as db:
            with db.cursor() as cursor:
                cursor.execute(UNTRACKED_SQL, (limit,))
                alerts = cursor.fetchall()
            for alert in alerts:
                row = self._new_record(alert)
                if row is None:
                    continue
                with db.cursor() as cursor:
                    cursor.execute(INSERT_SQL, row)
                created += 1
        return created

    def update_existing_records(self, limit: int = 50) -> int:
        """Fill the open horizons of existing records.

        Args:
            limit: Maximum number of records to look at; binds into the select.

        Returns:
            Number of records updated. A horizon the provider cannot price stays
            ``NULL`` and is retried on a later run.

        Contract:
            * One connection, one commit; a failure rolls back and raises
              :class:`PerformanceError`.
        """
        updated = 0
        with self._session() as db:
            with db.cursor() as cursor:
                cursor.execute(OUTDATED_SQL, (limit,))
                records = cursor.fetchall()
            for record_id, alert_date, ticker, base in records:
                row = self._updated_row(record_id, alert_date, ticker, base)
                if row is None:
                    continue
                with db.cursor() as cursor:
                    cursor.execute(UPDATE_SQL, row)
                updated += 1
        return updated

    def run_full_update(self) -> tuple[int, int]:
        """Track new alerts then update open records; return ``(created, updated)``."""
        created = self.track_new_alerts(limit=FULL_UPDATE_LIMIT)
        updated = self.update_existing_records(limit=FULL_UPDATE_LIMIT)
        logger.info("performance update: %d created, %d updated", created, updated)
        return created, updated

    @contextmanager
    def _session(self) -> Iterator[Any]:
        """Yield one open connection and settle it around the block.

        Yields:
            The connection from :func:`newstrading.db.connection`; a normal exit
            commits it, an exception rolls it back and closes it.

        Raises:
            PerformanceError: For any failure inside the block, including a connection
                that cannot be opened. The original exception stays as ``__cause__``.
        """
        try:
            with connection(self._settings, connector=self._connector) as db:
                yield db
        # boundary: driver and programming failures become the tracker's error type
        except Exception as error:
            raise PerformanceError("performance tracking failed") from error

    def _new_record(self, alert: tuple) -> tuple | None:
        """Build the insert row of one untracked alert, or ``None`` without a price."""
        alert_id, asset_id, alert_type, alert_date, confidence_score, ticker = alert
        day = alert_date.date()
        base = self._prices.price_at(ticker, day)
        if base is None:
            logger.warning("no price for %s on %s; alert %s stays untracked", ticker, day, alert_id)
            return None
        prices = self._prices.series(ticker, day, HORIZONS)
        returns, directions = _measure(base, prices)
        predicted = self.determine_predicted_direction(alert_type)
        correct = {
            horizon: None
            if predicted == "neutral" or directions[horizon] is None
            else directions[horizon] == predicted
            for horizon in DIRECTION_HORIZONS
        }
        return (
            alert_id,
            asset_id,
            alert_type,
            alert_date,
            confidence_score,
            base,
            *(prices.get(horizon) for horizon in HORIZONS),
            *(returns.get(horizon) for horizon in HORIZONS),
            predicted,
            *(directions.get(horizon) for horizon in DIRECTION_HORIZONS),
            *(correct.get(horizon) for horizon in DIRECTION_HORIZONS),
        )

    def _updated_row(
        self, record_id: int, alert_date: Any, ticker: str, base: float | None
    ) -> tuple | None:
        """Build the update row of one record, or ``None`` without a base price."""
        if base is None:
            logger.warning("record %s has no price at alert time; skipped", record_id)
            return None
        prices = self._prices.series(ticker, alert_date.date(), HORIZONS)
        returns, directions = _measure(float(base), prices)
        return (
            *(prices.get(horizon) for horizon in HORIZONS),
            *(returns.get(horizon) for horizon in HORIZONS),
            *(directions.get(horizon) for horizon in DIRECTION_HORIZONS),
            record_id,
        )
