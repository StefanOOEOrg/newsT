"""Prices over ``stock_prices``, for the performance tracker.

The tracker asks two questions: which close had a day (or the nearest earlier trading
day before it), and which closes came n trading days later. This module owns the two
queries behind them, so the tracker itself stays free of SQL and of ``yfinance``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg2

from newstrading.config import Settings
from newstrading.db import Connector, connection

logger = logging.getLogger(__name__)

PRICE_AT_SQL = """
    SELECT s.close
    FROM stock_prices s
    JOIN asset a ON s.asset_id = a.id
    WHERE a.ticker = %s
      AND s.timestamp::date <= %s
    ORDER BY s.timestamp DESC
    LIMIT 1
"""
"""Newest close of the asset on or before the day; ``(ticker, day)`` bind."""

SERIES_SQL = """
    SELECT s.timestamp, s.close
    FROM stock_prices s
    JOIN asset a ON s.asset_id = a.id
    WHERE a.ticker = %s
      AND s.timestamp::date > %s
    ORDER BY s.timestamp ASC
"""
"""Every close after the day, oldest first; ``(ticker, day)`` bind."""


def _close(value: Any) -> float:
    """Return a stored ``DECIMAL`` close as a float."""
    return float(value)


class DatabasePriceProvider:
    """`PriceProvider` over ``stock_prices`` for the performance tracker."""

    def __init__(self, settings: Settings, *, connector: Connector = psycopg2.connect) -> None:
        """Remember the database.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._connector = connector

    def price_at(self, ticker: str, day: date) -> float | None:
        """Return the close of ``day``, or of the nearest earlier trading day.

        Args:
            ticker: Exchange symbol of the asset.
            day: The day the price is asked for.

        Returns:
            The last stored close on ``day``; when that day has no bar, the close of the
            nearest earlier day with one; ``None`` when the asset has no earlier bar.
        """
        with connection(self._settings, connector=self._connector) as db:
            with db.cursor() as cursor:
                cursor.execute(PRICE_AT_SQL, (ticker, day))
                row = cursor.fetchone()
        return None if row is None else _close(row[0])

    def series(self, ticker: str, day: date, days: Sequence[int]) -> dict[int, float | None]:
        """Return the close ``n`` trading days after ``day`` for every ``n`` in ``days``.

        The trading days after ``day`` are the days ``stock_prices`` holds a bar for;
        a day with several bars counts once, with its last close.

        Args:
            ticker: Exchange symbol of the asset.
            day: The day the horizons start after.
            days: Horizons in trading days, e.g. the tracker's ``HORIZONS``.

        Returns:
            One entry per horizon: the last close of the n-th trading day after ``day``,
            or ``None`` when that many trading days are not stored yet. An empty
            ``days`` reads nothing.
        """
        if not days:
            return {}
        with connection(self._settings, connector=self._connector) as db:
            with db.cursor() as cursor:
                cursor.execute(SERIES_SQL, (ticker, day))
                rows = cursor.fetchall()
        closes: dict[date, float] = {}
        # rows arrive oldest first, so the last write of a day is its closing price
        for timestamp, close in rows:
            closes[timestamp.date()] = _close(close)
        trading_days = sorted(closes)
        return {
            horizon: closes[trading_days[horizon - 1]]
            if 1 <= horizon <= len(trading_days)
            else None
            for horizon in days
        }
