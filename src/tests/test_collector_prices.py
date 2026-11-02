"""Tests for newstrading.collectors.prices: Yahoo Finance bars and their store."""

import inspect
import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest
import requests

from newstrading.collectors import Collector
from newstrading.collectors.models import Asset
from newstrading.collectors.prices import (
    INTERVAL,
    PERIOD,
    PriceBar,
    PriceStore,
    StockPriceCollector,
)
from newstrading.config import Settings
from newstrading.rate_limiter import RateLimitDecision

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("tesla",))
FIRST = datetime(2026, 11, 2, 14, 30)
SECOND = datetime(2026, 11, 2, 14, 35, tzinfo=UTC)
LOGGER = "newstrading.collectors.prices"


class FakeFrame:
    """The slice of a yfinance frame the collector reads: ``iterrows`` only."""

    def __init__(self, rows):
        self._rows = list(rows)

    def iterrows(self):
        return iter(self._rows)


class FakeHistory:
    """History seam: one prepared answer per call, in order; records the calls."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    def __call__(self, ticker, period, interval):
        self.calls.append((ticker, period, interval))
        answer = self._answers[len(self.calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeLimiter:
    """Quota seam: answers a fixed decision and records what was booked."""

    def __init__(self, allowed=True, reason="hour quota exhausted"):
        self.decision = RateLimitDecision(allowed=allowed, reason=reason, wait_seconds=0)
        self.checks = 0
        self.records = []

    def can_make_request(self):
        self.checks += 1
        return self.decision

    def record_request(self, **kwargs):
        self.records.append(kwargs)


def frame_row(timestamp=FIRST, close=100.5, volume=1000):
    """One bar in the yfinance columns, with open/high/low around ``close``."""
    return timestamp, {
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": volume,
    }


def collect_one(*rows, limiter=None):
    """Collect one frame of ``rows`` and return the bars it yields."""
    history = FakeHistory(FakeFrame(rows))
    collector = StockPriceCollector(SETTINGS, history=history, limiter=limiter)
    return collector.collect_for_asset(ASSET)


def test_the_period_and_interval_are_the_legacy_ones():
    """``1d`` of ``5m`` bars is what the legacy collector fetched."""
    assert (PERIOD, INTERVAL) == ("1d", "5m")


def test_a_frame_becomes_the_expected_bars():
    """Every OHLCV field of a row ends up in a ``PriceBar`` of that asset."""
    bars = collect_one(frame_row(FIRST, 100.5, 1000), frame_row(SECOND, 101.5, 2000))

    assert bars == [
        PriceBar(
            asset_id=7,
            timestamp=datetime(2026, 11, 2, 14, 30, tzinfo=UTC),
            open=100.0,
            high=101.5,
            low=99.5,
            close=100.5,
            volume=1000,
        ),
        PriceBar(
            asset_id=7,
            timestamp=datetime(2026, 11, 2, 14, 35, tzinfo=UTC),
            open=101.0,
            high=102.5,
            low=100.5,
            close=101.5,
            volume=2000,
        ),
    ]
    assert all(bar.timestamp.tzinfo is UTC for bar in bars)


def test_the_history_call_carries_the_documented_arguments():
    """The ticker of the asset plus the module's period and interval."""
    history = FakeHistory(FakeFrame([]))

    StockPriceCollector(SETTINGS, history=history).collect_for_asset(ASSET)

    assert history.calls == [("TSLA", PERIOD, INTERVAL)]


def test_a_row_without_a_close_is_skipped():
    """The close is mandatory; a row without one must not cost the other rows."""
    no_close = (FIRST, {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": None, "Volume": 5})

    bars = collect_one(no_close, frame_row(SECOND, 101.0))

    assert [bar.close for bar in bars] == [101.0]
    assert [bar.timestamp for bar in bars] == [SECOND]


def test_a_missing_volume_becomes_none():
    """``volume`` is optional; a row without the column keeps a ``None`` volume."""
    only_prices = (FIRST, {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5})

    bars = collect_one(only_prices)

    assert bars[0].volume is None
    assert bars[0].close == 1.5


def test_a_naive_index_is_read_as_utc():
    """yfinance hands back a naive index on some paths; it is UTC for this package."""
    bars = collect_one(frame_row(datetime(2026, 11, 2, 14, 30)))

    assert bars[0].timestamp == datetime(2026, 11, 2, 14, 30, tzinfo=UTC)


def test_an_aware_index_is_converted_to_utc():
    """An exchange-local index is shifted onto UTC, not relabelled."""
    vienna = timezone(timedelta(hours=1))

    bars = collect_one(frame_row(datetime(2026, 11, 2, 15, 30, tzinfo=vienna)))

    assert bars[0].timestamp == datetime(2026, 11, 2, 14, 30, tzinfo=UTC)


def test_a_denied_call_makes_no_history_call_and_is_not_recorded():
    """The quota check runs first: no request, no usage row for the denial."""
    limiter = FakeLimiter(allowed=False)
    history = FakeHistory(FakeFrame([frame_row()]))
    collector = StockPriceCollector(SETTINGS, history=history, limiter=limiter)

    assert collector.collect_for_asset(ASSET) == []
    assert history.calls == []
    assert limiter.checks == 1
    assert limiter.records == []


def test_an_allowed_call_is_recorded_once_as_a_success():
    """A readable frame is booked once, with status 200."""
    limiter = FakeLimiter()

    collect_one(frame_row(), limiter=limiter)

    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is True
    assert limiter.records[0]["status_code"] == 200


def test_a_network_error_yields_no_bars_and_does_not_raise(caplog):
    """A transport failure is logged with the ticker and booked, never raised."""
    limiter = FakeLimiter()
    history = FakeHistory(requests.ConnectionError("connection refused"))
    collector = StockPriceCollector(SETTINGS, history=history, limiter=limiter)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collector.collect_for_asset(ASSET) == []

    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["error_message"] == "connection refused"
    assert "TSLA" in caplog.text
    assert "connection refused" in caplog.text


def test_an_empty_frame_yields_no_bars_and_records_a_failure(caplog):
    """An empty frame is a failed call with status 200, as the legacy collector booked it."""
    limiter = FakeLimiter()

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collect_one(limiter=limiter) == []

    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == 200
    assert "TSLA" in caplog.text


@pytest.mark.parametrize("frame", ["not a frame", object(), FakeFrame(["junk"])])
def test_a_malformed_frame_yields_no_bars_and_records_a_failure(frame, caplog):
    """A frame the collector cannot read is logged and booked, not raised."""
    limiter = FakeLimiter()
    history = FakeHistory(frame)
    collector = StockPriceCollector(SETTINGS, history=history, limiter=limiter)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert collector.collect_for_asset(ASSET) == []

    assert limiter.records[0]["success"] is False
    assert "TSLA" in caplog.text


def test_without_a_limiter_nothing_is_tracked():
    """``limiter=None`` means no quota bookkeeping, not a skipped call."""
    assert len(collect_one(frame_row())) == 1


def test_the_collector_fits_the_collector_protocol():
    """The class offers what ``Collector`` declares, structurally."""
    collector = StockPriceCollector(SETTINGS)
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "stock_prices"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]


class FakeCursor:
    """Cursor double: records what ``execute_values`` mogrifies and executes."""

    def __init__(self, connection):
        self.connection = connection
        self.rowcount = connection.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def mogrify(self, template, args):
        self.connection.rows.append(tuple(args))
        return b"(" + b",".join(str(value).encode() for value in args) + b")"

    def execute(self, statement, parameters=None):
        self.connection.statements.append((statement, parameters))


class FakeConnection:
    """Connection double: a known row count and no database."""

    def __init__(self, rowcount=2):
        self.encoding = "UTF8"
        self.rowcount = rowcount
        self.rows = []
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def bar(timestamp=FIRST, close=100.5, volume=1000):
    """One bar of asset 7, with open/high/low around ``close``."""
    return PriceBar(
        asset_id=7,
        timestamp=timestamp,
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=volume,
    )


def test_save_issues_one_insert_with_the_conflict_clause():
    """One statement for all bars, in the column order of the table, idempotent."""
    connection = FakeConnection()

    PriceStore(SETTINGS, connector=lambda url: connection).save([bar(), bar(SECOND, 101.5)])

    assert len(connection.statements) == 1
    statement = connection.statements[0][0].decode()
    assert "INSERT INTO stock_prices" in statement
    assert "ON CONFLICT (asset_id, timestamp) DO NOTHING" in statement
    assert connection.rows == [
        (7, FIRST, 100.0, 101.5, 99.5, 100.5, 1000),
        (7, SECOND, 101.0, 102.5, 100.5, 101.5, 1000),
    ]


def test_save_returns_the_row_count_and_settles_the_connection():
    """The statement's row count is the number of new bars; one commit, one close."""
    connection = FakeConnection(rowcount=1)

    saved = PriceStore(SETTINGS, connector=lambda url: connection).save([bar(), bar(SECOND, 101.5)])

    assert saved == 1
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 0, 1)


def test_save_of_nothing_touches_no_connection():
    """Empty input opens no connection and executes no statement."""
    opened = []

    saved = PriceStore(SETTINGS, connector=lambda url: opened.append(url)).save([])

    assert saved == 0
    assert opened == []
