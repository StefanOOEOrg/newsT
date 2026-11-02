"""Stock prices: Yahoo Finance bars in, ``stock_prices`` rows out.

The collector ports ``collector/collectors/stock_price_collector.py``: one five minute
bar per row, idempotently stored per asset and timestamp. ``yfinance`` is imported only
when the default history is actually called, so the package imports without it and the
tests never touch the network.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from newstrading.collectors.models import Asset
from newstrading.config import Settings
from newstrading.db import Connector, connection
from newstrading.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

PERIOD = "1d"
"""Period yfinance is asked for: the current trading day of five minute bars."""

INTERVAL = "5m"
"""Bar interval yfinance is asked for; one bar is one row of ``stock_prices``."""

API_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
"""Endpoint yfinance calls, recorded in ``api_usage``."""

INSERT_SQL = """
    INSERT INTO stock_prices (asset_id, timestamp, open, high, low, close, volume)
    VALUES %s
    ON CONFLICT (asset_id, timestamp) DO NOTHING
"""
"""One row per bar; the unique key makes a repeated run a no-op."""

History = Callable[[str, str, str], Any]


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One bar of one asset.

    Attributes:
        asset_id: Asset the bar belongs to.
        timestamp: Bar start, timezone aware UTC.
        open / high / low / close: Prices; ``close`` is always present.
        volume: Traded volume, ``None`` when the source omits it.
    """

    asset_id: int
    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: int | None


def yfinance_history(ticker: str, period: str, interval: str) -> Any:
    """Fetch the bars of ``ticker`` from Yahoo Finance through ``yfinance``.

    Args:
        ticker: Exchange symbol, e.g. ``TSLA``.
        period: yfinance period string, e.g. ``1d``.
        interval: yfinance interval string, e.g. ``5m``.

    Returns:
        The frame yfinance returns: a datetime index and the OHLCV columns.

    Contract:
        The import is deferred, so importing this module never needs ``yfinance``.
    """
    import yfinance

    return yfinance.Ticker(ticker).history(period=period, interval=interval)


def _value(row: Any, column: str) -> Any:
    """Read one column of a frame row, ``None`` when the row does not carry it.

    Raises:
        TypeError: When ``row`` is not a mapping, i.e. a malformed frame.
    """
    getter = getattr(row, "get", None)
    if not callable(getter):
        raise TypeError(f"price row {type(row).__name__} is not a mapping")
    return getter(column)


def _number(value: Any) -> float | None:
    """Convert a cell to a number; blanks, ``NaN`` and junk read as missing."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _price(value: Any) -> float | None:
    """Read a price cell as a float, ``None`` when it is missing or not a number."""
    number = _number(value)
    return None if number is None else float(number)


def _volume(value: Any) -> int | None:
    """Read a volume cell as an int, ``None`` when it is missing or not a number."""
    number = _number(value)
    return None if number is None else int(number)


def _utc(value: Any) -> datetime:
    """Return a frame index value as a timezone aware UTC ``datetime``.

    A naive index is read as UTC, an aware one is converted.

    Raises:
        TypeError: When ``value`` is not a timestamp.
    """
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        value = to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"{type(value).__name__} is not a timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class StockPriceCollector:
    """Collects the recent bars of Yahoo Finance, one asset at a time."""

    name = "stock_prices"

    def __init__(
        self,
        settings: Settings,
        *,
        history: History | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Remember the seams; nothing is fetched here.

        Args:
            settings: Settings of the process; prices need no API key from it.
            history: Fetches ``(ticker, period, interval)`` and returns the frame.
                ``None`` wraps ``yfinance``, imported on the first call; tests pass a
                fake.
            limiter: Quota tracker; ``None`` disables quota tracking, not the call.
        """
        self._settings = settings
        self._history = history or yfinance_history
        self._limiter = limiter

    def collect_for_asset(self, asset: Asset) -> list[PriceBar]:
        """Collect the bars Yahoo Finance carries for ``asset``.

        Args:
            asset: The asset to fetch, matched by its ticker.

        Returns:
            The frame's bars as :class:`PriceBar` values; empty when the quota denies
            the call, the request fails or the frame holds no usable row.
        """
        if not self._allowed(asset):
            return []
        try:
            frame = self._history(asset.ticker, PERIOD, INTERVAL)
        # boundary: a transport failure is a failed call, not an exception of the run
        except Exception as error:
            logger.warning("Stock price request for %s failed: %s", asset.ticker, error)
            self._record(success=False, error_message=str(error))
            return []
        try:
            bars = self._bars(frame, asset)
        # boundary: an unreadable frame is a failed call, not an exception of the run
        except Exception as error:
            logger.warning("Stock price frame for %s could not be read: %s", asset.ticker, error)
            self._record(success=False, status_code=200, error_message=str(error))
            return []
        if not bars:
            logger.warning("Stock price frame for %s held no bar", asset.ticker)
            self._record(success=False, status_code=200, error_message="Empty response")
            return []
        self._record(success=True, status_code=200)
        logger.info("Stock prices collected %s bar(s) for %s", len(bars), asset.ticker)
        return bars

    def _allowed(self, asset: Asset) -> bool:
        """Check the quota; log and answer ``False`` when the call is denied."""
        if self._limiter is None:
            return True
        decision = self._limiter.can_make_request()
        if decision.allowed:
            return True
        logger.warning("Stock price quota exhausted for %s: %s", asset.ticker, decision.reason)
        return False

    def _bars(self, frame: Any, asset: Asset) -> list[PriceBar]:
        """Turn one frame into bars, skipping the rows without a close.

        Args:
            frame: A yfinance frame: a datetime index and the OHLCV columns.
            asset: The asset the bars belong to.

        Returns:
            One bar per readable row, timestamps in UTC.

        Raises:
            TypeError: When ``frame`` is not a frame or a row is not a mapping.
        """
        iterrows = getattr(frame, "iterrows", None)
        if not callable(iterrows):
            raise TypeError(f"{type(frame).__name__} is not a price frame")
        bars: list[PriceBar] = []
        for timestamp, row in iterrows():
            close = _price(_value(row, "Close"))
            if close is None:
                continue
            bars.append(
                PriceBar(
                    asset_id=asset.id,
                    timestamp=_utc(timestamp),
                    open=_price(_value(row, "Open")),
                    high=_price(_value(row, "High")),
                    low=_price(_value(row, "Low")),
                    close=close,
                    volume=_volume(_value(row, "Volume")),
                )
            )
        return bars

    def _record(
        self,
        *,
        success: bool,
        status_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Book the call in the limiter, when one is configured."""
        if self._limiter is None:
            return
        self._limiter.record_request(
            success=success,
            status_code=status_code,
            error_message=error_message,
            api_endpoint=API_URL,
        )


class PriceStore:
    """Writes bars to ``stock_prices``, idempotently per asset and timestamp."""

    def __init__(self, settings: Settings, *, connector: Connector = psycopg2.connect) -> None:
        """Remember the database.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._connector = connector

    def save(self, bars: Sequence[PriceBar]) -> int:
        """Insert the bars, return how many rows were new (ON CONFLICT (asset_id, timestamp)).

        Args:
            bars: Bars of one or more assets, in insert order.

        Returns:
            The statement's row count — bars that were already stored are not counted
            because of ``ON CONFLICT DO NOTHING``; ``0`` for an empty sequence.

        Contract:
            * An empty sequence opens no connection and executes no statement.
            * All bars travel in one ``execute_values`` statement.
            * A database failure rolls back and is re-raised.
        """
        if not bars:
            return 0
        values = [
            (bar.asset_id, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in bars
        ]
        with connection(self._settings, connector=self._connector) as db:
            with db.cursor() as cursor:
                execute_values(cursor, INSERT_SQL, values)
                saved = int(cursor.rowcount)
        return saved
