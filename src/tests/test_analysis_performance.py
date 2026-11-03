"""Tests for newstrading.analysis.performance.

The tracker sits between the alert table and the price side, so every case here drives a
fake connection and a fake price provider: no database server, no network. The verdict
cases additionally run the update statement against SQLite in memory, because only an
engine shows whether the CASE writes TRUE, FALSE or NULL. The expected values
are the legacy ones — the return formula, the 0.005 direction threshold and the four
decimal places come from ``analyzer/performance_tracker.py`` and
``shared/price_fetcher.py``.
"""

import sqlite3
from datetime import date, datetime

import pytest

from newstrading.analysis.performance import UPDATE_SQL, PerformanceError, PerformanceTracker
from newstrading.config import Settings

ALERT_DAY = datetime(2026, 1, 5, 14, 30)
ALERT_DATE = ALERT_DAY.date()

SETTINGS = Settings(database_url="postgresql://localhost:5432/newstrading", anthropic_api_key="k")

# (ap.id, ap.alert_date, c.ticker, ap.price_at_alert)


class FakePrices:
    """PriceProvider that returns canned values and records what it was asked."""

    def __init__(self, base=None, series=None):
        self.base = base
        self.series_by_day = series or {}
        self.calls = []

    def price_at(self, ticker, day):
        self.calls.append(("price_at", ticker, day))
        if isinstance(self.base, dict):
            return self.base.get(ticker)
        return self.base

    def series(self, ticker, day, days):
        self.calls.append(("series", ticker, day, tuple(days)))
        return {days_after: self.series_by_day.get(days_after) for days_after in days}


class FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self._connection.statements.append((sql, params))
        if self._connection.fail_on and self._connection.fail_on in sql:
            raise RuntimeError("connection lost")
        if "INSERT INTO alert_performance" in sql:
            self._connection.inserted.append(params)
        elif "UPDATE alert_performance" in sql:
            self._connection.updated.append(params)
        self._rows = self._connection.answer(sql)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    """Connection double: answers the two selects and records writes."""

    def __init__(self, untracked=(), outdated=(), fail_on=None):
        self.untracked = list(untracked)
        self.outdated = list(outdated)
        self.fail_on = fail_on
        self.statements = []
        self.inserted = []
        self.updated = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def answer(self, sql):
        if "FROM alerts a" in sql:
            return self.untracked
        if "FROM alert_performance ap" in sql:
            return self.outdated
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def make_tracker(prices, connection, settings=SETTINGS):
    return PerformanceTracker(settings, connector=lambda url: connection, prices=prices)


def untracked_alert(alert_id=7, alert_type="partnership", ticker="AAPL", base=100.0):
    return (alert_id, 3, alert_type, ALERT_DAY, 88.5, ticker)


def outdated_record(record_id=12, ticker="AAPL", base=100.0):
    return (record_id, ALERT_DAY, ticker, base)


FULL_SERIES = {1: 101.0, 3: 102.0, 7: 105.0, 14: 98.0, 30: 110.0}


# --- determine_predicted_direction --------------------------------------------------


@pytest.mark.parametrize(
    "alert_type",
    [
        "long_signal",
        "partnership",
        "product_launch",
        "analyst_upgrade",
        "market_share",
        "guidance",
        "insider_trading",
        "executive_change",
    ],
)
def test_every_legacy_bullish_type_maps_to_bullish(alert_type):
    tracker = make_tracker(FakePrices(), FakeConnection())

    assert tracker.determine_predicted_direction(alert_type) == "bullish"


@pytest.mark.parametrize(
    "alert_type",
    [
        "short_signal",
        "regulatory_risk",
        "analyst_downgrade",
        "customer_loss",
        "problem_detected",
        "negative_sentiment",
    ],
)
def test_every_legacy_bearish_type_maps_to_bearish(alert_type):
    tracker = make_tracker(FakePrices(), FakeConnection())

    assert tracker.determine_predicted_direction(alert_type) == "bearish"


def test_the_mapping_ignores_case_and_whitespace():
    tracker = make_tracker(FakePrices(), FakeConnection())

    assert tracker.determine_predicted_direction("  Analyst_UPGRADE ") == "bullish"


def test_bullish_wins_when_the_type_contains_both():
    tracker = make_tracker(FakePrices(), FakeConnection())

    assert tracker.determine_predicted_direction("customer_loss_then_long_signal") == "bullish"


def test_an_unknown_type_is_neutral():
    tracker = make_tracker(FakePrices(), FakeConnection())

    assert tracker.determine_predicted_direction("dividend") == "neutral"


# --- track_new_alerts ---------------------------------------------------------------


def test_track_new_alerts_writes_one_row_per_alert_with_a_base_price():
    connection = FakeConnection(untracked=[untracked_alert(alert_id=7, ticker="AAPL")])
    tracker = make_tracker(FakePrices(base={"AAPL": 100.0}, series=FULL_SERIES), connection)

    created = tracker.track_new_alerts()

    assert created == 1
    assert [row[0] for row in connection.inserted] == [7]


def test_an_alert_without_a_base_price_writes_nothing():
    connection = FakeConnection(untracked=[untracked_alert(alert_id=7, ticker="AAPL")])
    tracker = make_tracker(FakePrices(base=None, series=FULL_SERIES), connection)

    created = tracker.track_new_alerts()
    retried = tracker.track_new_alerts()

    assert created == 0
    assert retried == 0
    assert connection.inserted == []
    assert connection.commits == 2


def test_the_created_row_carries_alert_reference_base_price_and_prediction():
    connection = FakeConnection(untracked=[untracked_alert(alert_id=7, alert_type="partnership")])
    tracker = make_tracker(FakePrices(base={"AAPL": 100.0}, series=FULL_SERIES), connection)

    tracker.track_new_alerts()

    row = connection.inserted[0]
    assert row[0] == 7  # alert_id
    assert row[1] == 3  # asset_id
    assert row[2] == "partnership"  # alert_type
    assert row[3] == ALERT_DAY  # alert_date
    assert row[4] == 88.5  # confidence_score
    assert row[5] == 100.0  # price_at_alert
    assert row[16] == "bullish"  # predicted_direction


def test_the_tracker_asks_the_provider_for_the_alert_day():
    connection = FakeConnection(untracked=[untracked_alert(ticker="AAPL")])
    prices = FakePrices(base={"AAPL": 100.0}, series=FULL_SERIES)
    tracker = make_tracker(prices, connection)

    tracker.track_new_alerts()

    assert ("price_at", "AAPL", ALERT_DATE) in prices.calls
    assert ("series", "AAPL", ALERT_DATE, (1, 3, 7, 14, 30)) in prices.calls


def test_track_new_alerts_passes_the_limit_as_a_parameter():
    connection = FakeConnection()
    tracker = make_tracker(FakePrices(), connection)

    tracker.track_new_alerts(limit=3)

    select = next(sql for sql, _ in connection.statements if "FROM alerts a" in sql)
    params = next(params for sql, params in connection.statements if sql == select)
    assert params == (3,)


# --- update_existing_records --------------------------------------------------------


def test_update_existing_records_writes_all_five_prices_and_returns():
    connection = FakeConnection(outdated=[outdated_record()])
    tracker = make_tracker(FakePrices(series=FULL_SERIES), connection)

    updated = tracker.update_existing_records()

    assert updated == 1
    row = connection.updated[0]
    assert tuple(row[0:5]) == (101.0, 102.0, 105.0, 98.0, 110.0)
    assert tuple(row[5:10]) == (0.01, 0.02, 0.05, -0.02, 0.1)


def test_the_three_legacy_directions_are_written():
    connection = FakeConnection(outdated=[outdated_record()])
    tracker = make_tracker(FakePrices(series=FULL_SERIES), connection)

    tracker.update_existing_records()

    row = connection.updated[0]
    assert tuple(row[10:13]) == ("bullish", "bullish", "bullish")
    assert row[16] == 12  # the record id travels as the WHERE parameter, after the verdicts


def test_a_missing_horizon_stays_none():
    connection = FakeConnection(outdated=[outdated_record()])
    prices = FakePrices(series={1: 101.0, 3: None, 7: None, 14: None, 30: None})
    tracker = make_tracker(prices, connection)

    tracker.update_existing_records()

    row = connection.updated[0]
    assert tuple(row[0:5]) == (101.0, None, None, None, None)
    assert tuple(row[5:10]) == (0.01, None, None, None, None)
    assert tuple(row[10:13]) == ("bullish", None, None)


def test_returns_are_rounded_to_four_decimals():
    connection = FakeConnection(outdated=[outdated_record(base=3.0)])
    prices = FakePrices(series={1: 4.0, 3: 2.0, 7: 3.0, 14: None, 30: None})
    tracker = make_tracker(prices, connection)

    tracker.update_existing_records()

    row = connection.updated[0]
    assert tuple(row[5:10]) == (0.3333, -0.3333, 0.0, None, None)


def test_directions_follow_the_legacy_threshold():
    connection = FakeConnection(outdated=[outdated_record()])
    prices = FakePrices(series={1: 100.6, 3: 100.5, 7: 99.4, 14: None, 30: None})
    tracker = make_tracker(prices, connection)

    tracker.update_existing_records()

    row = connection.updated[0]
    assert tuple(row[10:13]) == ("bullish", "neutral", "bearish")


def test_update_existing_records_passes_the_limit_as_a_parameter():
    connection = FakeConnection()
    tracker = make_tracker(FakePrices(), connection)

    tracker.update_existing_records(limit=4)

    params = next(
        params for sql, params in connection.statements if "FROM alert_performance ap" in sql
    )
    assert params == (4,)


# --- correctness, judged when the horizon closes ------------------------------------

UPDATE_IN_SQLITE = UPDATE_SQL.replace("NOW()", "CURRENT_TIMESTAMP").replace("%s", "?")

VERDICT_SCHEMA = """
    CREATE TABLE alert_performance (
        id INTEGER PRIMARY KEY,
        price_1d_later REAL,
        price_3d_later REAL,
        price_7d_later REAL,
        price_14d_later REAL,
        price_30d_later REAL,
        return_1d REAL,
        return_3d REAL,
        return_7d REAL,
        return_14d REAL,
        return_30d REAL,
        predicted_direction TEXT,
        actual_direction_1d TEXT,
        actual_direction_3d TEXT,
        actual_direction_7d TEXT,
        correct_1d INTEGER,
        correct_3d INTEGER,
        correct_7d INTEGER,
        last_updated TIMESTAMP
    )
"""


def verdicts_after(row, predicted_direction):
    """Run the real update statement against an in-memory SQLite table.

    The fake cursor proves which columns the statement names and in which order the
    parameters travel; only an engine can show that the CASE over ``predicted_direction``
    yields TRUE, FALSE or NULL. SQLite evaluates the same CASE, so the statement runs
    with its placeholders and ``NOW()`` translated, against one row carrying the
    prediction. The verdicts come back as ``None``/``bool``, the types the column holds.
    """
    db = sqlite3.connect(":memory:")
    try:
        db.execute(VERDICT_SCHEMA)
        db.execute(
            "INSERT INTO alert_performance (id, predicted_direction) VALUES (?, ?)",
            (row[-1], predicted_direction),
        )
        db.execute(UPDATE_IN_SQLITE, row)
        verdicts = db.execute(
            "SELECT correct_1d, correct_3d, correct_7d FROM alert_performance WHERE id = ?",
            (row[-1],),
        ).fetchone()
    finally:
        db.close()
    return tuple(None if value is None else bool(value) for value in verdicts)


def verdicts_of_one_update(series, predicted_direction, base=100.0):
    """Update one record with ``series`` and return the verdicts the statement wrote."""
    connection = FakeConnection(outdated=[outdated_record(base=base)])
    tracker = make_tracker(FakePrices(series=series), connection)

    tracker.update_existing_records()

    assert len(connection.updated) == 1
    return verdicts_after(connection.updated[0], predicted_direction)


ONE_DAY = {1: 101.0, 3: None, 7: None, 14: None, 30: None}
THREE_DAYS = {1: 101.0, 3: 102.0, 7: None, 14: None, 30: None}
FALLING = {1: 99.0, 3: 98.0, 7: 97.0, 14: None, 30: None}


def test_the_first_closed_horizon_gets_a_verdict_and_the_open_ones_stay_null():
    assert verdicts_of_one_update(ONE_DAY, "bullish") == (True, None, None)


def test_the_next_update_judges_the_three_day_horizon():
    assert verdicts_of_one_update(THREE_DAYS, "bullish") == (True, True, None)


def test_the_third_update_judges_the_seven_day_horizon():
    assert verdicts_of_one_update(FULL_SERIES, "bullish") == (True, True, True)


def test_a_wrong_direction_is_false():
    assert verdicts_of_one_update(FALLING, "bullish") == (False, False, False)


def test_a_right_bearish_call_is_true():
    assert verdicts_of_one_update(FALLING, "bearish") == (True, True, True)


def test_a_neutral_prediction_stays_unjudged_in_every_horizon():
    assert verdicts_of_one_update(ONE_DAY, "neutral") == (None, None, None)
    assert verdicts_of_one_update(FULL_SERIES, "neutral") == (None, None, None)


def test_the_update_sets_all_three_verdict_columns_from_the_prediction():
    connection = FakeConnection(outdated=[outdated_record()])
    tracker = make_tracker(FakePrices(series=FULL_SERIES), connection)

    tracker.update_existing_records()

    statement = next(sql for sql, _ in connection.statements if "UPDATE alert_performance" in sql)
    assignments = statement.split("WHERE id")[0]
    for horizon in ("1d", "3d", "7d"):
        assert f"correct_{horizon} =" in assignments
    assert "predicted_direction = 'neutral'" in assignments
    assert "= predicted_direction" in assignments


def test_the_update_binds_prices_returns_directions_verdicts_then_the_id():
    connection = FakeConnection(outdated=[outdated_record()])
    tracker = make_tracker(
        FakePrices(series={1: 101.0, 3: 99.0, 7: 100.5, 14: None, 30: None}), connection
    )

    tracker.update_existing_records()

    row = connection.updated[0]
    assert len(row) == 17
    assert tuple(row[0:5]) == (101.0, 99.0, 100.5, None, None)
    assert tuple(row[5:10]) == (0.01, -0.01, 0.005, None, None)
    assert tuple(row[10:13]) == ("bullish", "bearish", "neutral")
    assert tuple(row[13:16]) == ("bullish", "bearish", "neutral")  # the comparison input
    assert row[16] == 12  # the record id travels as the WHERE parameter


# --- run_full_update ----------------------------------------------------------------


def test_run_full_update_returns_created_and_updated_in_order():
    calls = []
    connection = FakeConnection()
    tracker = make_tracker(FakePrices(), connection)

    def track(*args, **kwargs):
        calls.append("track")
        return 2

    def update(*args, **kwargs):
        calls.append("update")
        return 3

    tracker.track_new_alerts = track
    tracker.update_existing_records = update

    assert tracker.run_full_update() == (2, 3)
    assert calls == ["track", "update"]


# --- failure handling ---------------------------------------------------------------


def test_a_database_error_rolls_back_and_raises_a_named_error():
    connection = FakeConnection(
        untracked=[untracked_alert()], fail_on="INSERT INTO alert_performance"
    )
    tracker = make_tracker(FakePrices(base={"AAPL": 100.0}, series=FULL_SERIES), connection)

    with pytest.raises(PerformanceError):
        tracker.track_new_alerts()

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closed is True
    assert connection.inserted == []


def test_the_legacy_horizons_are_used_for_a_new_record():
    connection = FakeConnection(untracked=[untracked_alert()])
    tracker = make_tracker(FakePrices(base={"AAPL": 100.0}, series=FULL_SERIES), connection)

    tracker.track_new_alerts()

    row = connection.inserted[0]
    assert tuple(row[6:11]) == (101.0, 102.0, 105.0, 98.0, 110.0)
    assert tuple(row[11:16]) == (0.01, 0.02, 0.05, -0.02, 0.1)


def test_the_alert_day_is_the_day_of_the_timestamp():
    prices = FakePrices(base={"AAPL": 100.0}, series=FULL_SERIES)
    tracker = make_tracker(prices, FakeConnection(untracked=[untracked_alert()]))

    tracker.track_new_alerts()

    day = next(call[2] for call in prices.calls if call[0] == "price_at")
    assert day == date(2026, 1, 5)
