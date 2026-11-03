"""Tests for newstrading.analysis.prices: the ``PriceProvider`` over ``stock_prices``."""

import inspect
from datetime import date, datetime

import pytest

from newstrading.analysis.performance import PriceProvider
from newstrading.analysis.prices import DatabasePriceProvider
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)
DAY = date(2026, 10, 1)
ROWS = (
    (datetime(2026, 9, 30, 15, 0), 99.0),
    (datetime(2026, 10, 1, 9, 30), 100.0),
    (datetime(2026, 10, 1, 15, 30), 102.5),
    (datetime(2026, 10, 2, 15, 30), 103.0),
    (datetime(2026, 10, 5, 15, 30), 101.0),
    (datetime(2026, 10, 6, 9, 30), 104.0),
    (datetime(2026, 10, 6, 15, 30), 105.5),
)


class FakeCursor:
    """Cursor double that filters and orders the prepared rows like Postgres would."""

    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement, parameters=None):
        self.connection.statements.append((statement, parameters))
        self.rows = self.connection.answer(statement, parameters)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    """Connection double holding one ticker's bars."""

    def __init__(self, rows=ROWS, fail_with=None):
        self.bars = list(rows)
        self.fail_with = fail_with
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def answer(self, statement, parameters):
        if self.fail_with is not None:
            raise self.fail_with
        day = parameters[1]
        if "<= %s" in statement:
            within = [row for row in self.bars if row[0].date() <= day]
            within.sort(key=lambda row: row[0], reverse="DESC" in statement)
            return [(close,) for _timestamp, close in within]
        after = [row for row in self.bars if row[0].date() > day]
        return sorted(after, key=lambda row: row[0])

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def provider(connection=None):
    """Build a provider over the fake connection, recording the URLs it opens."""
    connection = connection or FakeConnection()
    return DatabasePriceProvider(SETTINGS, connector=lambda url: connection), connection


def test_price_at_takes_the_last_close_of_the_day():
    """Two bars on the day: the later one is the day's close."""
    prices, _ = provider()

    assert prices.price_at("TSLA", DAY) == 102.5


def test_price_at_falls_back_to_the_nearest_earlier_trading_day():
    """A Saturday has no bars, so the Friday close is the answer."""
    prices, _ = provider()

    assert prices.price_at("TSLA", date(2026, 10, 3)) == 103.0
    assert prices.price_at("TSLA", date(2026, 10, 8)) == 105.5


def test_price_at_is_none_without_any_earlier_row():
    """Before the first stored bar there is no price to report."""
    prices, _ = provider()

    assert prices.price_at("TSLA", date(2026, 9, 1)) is None


def test_price_at_reads_the_latest_close_with_its_own_statement():
    """The query asks Postgres for the newest row of the ticker up to the day."""
    prices, connection = provider()

    prices.price_at("TSLA", DAY)

    statement, parameters = connection.statements[0]
    assert parameters == ("TSLA", DAY)
    assert "stock_prices" in statement
    assert "asset" in statement
    assert "ORDER BY s.timestamp DESC" in statement
    assert "LIMIT 1" in statement
    assert isinstance(prices.price_at("TSLA", DAY), float)


def test_series_returns_the_five_horizons_of_the_prepared_set():
    """Horizon ``n`` is the close of the n-th trading day after ``day``, else ``None``."""
    prices, _ = provider()

    assert prices.series("TSLA", DAY, [1, 3, 7, 14, 30]) == {
        1: 103.0,
        3: 105.5,
        7: None,
        14: None,
        30: None,
    }


def test_series_takes_the_last_close_of_each_later_day():
    """The third trading day after ``DAY`` has two bars; its close is the later one."""
    prices, _ = provider()

    assert prices.series("TSLA", DAY, [3]) == {3: 105.5}


def test_series_reads_the_bars_after_the_day_from_one_statement():
    """One query per call, keyed by ticker and day, ascending."""
    prices, connection = provider()

    prices.series("TSLA", DAY, [1, 3])

    assert len(connection.statements) == 1
    statement, parameters = connection.statements[0]
    assert parameters == ("TSLA", DAY)
    assert "stock_prices" in statement
    assert "ORDER BY s.timestamp" in statement
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 0, 1)


def test_series_without_horizons_reads_nothing():
    """No horizon requested, no query, an empty answer."""
    prices, connection = provider()

    assert prices.series("TSLA", DAY, []) == {}
    assert connection.statements == []


def test_the_provider_fits_the_price_provider_protocol():
    """The tracker's protocol is what this class implements, structurally."""
    prices, _ = provider()
    required = {name for name in dir(PriceProvider) if not name.startswith("_")}

    assert required <= set(dir(prices))
    assert list(inspect.signature(prices.price_at).parameters) == ["ticker", "day"]
    assert list(inspect.signature(prices.series).parameters) == ["ticker", "day", "days"]


def test_a_failing_database_is_not_swallowed():
    """The tracker decides what a broken read means; the provider does not hide it."""
    prices, _ = provider(FakeConnection(fail_with=RuntimeError("connection lost")))

    with pytest.raises(RuntimeError, match="connection lost"):
        prices.price_at("TSLA", DAY)
