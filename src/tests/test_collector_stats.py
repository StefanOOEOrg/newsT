"""Tests for newstrading.collectors.stats."""

from datetime import UTC, datetime

import psycopg2

from newstrading.collectors.stats import (
    MAX_ERROR_MESSAGE_LENGTH,
    CollectorStats,
    CollectorStatsStore,
)
from newstrading.config import Settings

URL = "postgresql://app:pw@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")
STARTED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


class FakeCursor:
    """Records statements and returns the canned row."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        self._connection.statements.append((query, params))
        if self._connection.fail_with is not None:
            raise self._connection.fail_with

    def fetchone(self):
        return self._connection.row

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double with one canned row and a failure switch."""

    def __init__(self, row=None, fail_with=None):
        self.row = row
        self.fail_with = fail_with
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


def connector(fake):
    """Build a connector returning ``fake``."""

    def _connector(url):
        return fake

    return _connector


def test_load_maps_a_stored_row():
    """Column order of the select becomes the fields of the dataclass."""
    row = (
        STARTED,
        STARTED,
        12.5,
        100,
        80,
        10,
        8,
        3,
        "boom",
        STARTED,
    )
    fake = FakeConnection(row=row)

    stats = CollectorStatsStore(SETTINGS, connector=connector(fake)).load("rss")

    assert stats == CollectorStats(
        collector_name="rss",
        last_run_started_at=STARTED,
        last_run_completed_at=STARTED,
        last_run_duration_seconds=12.5,
        total_posts_collected=100,
        total_posts_saved=80,
        last_run_posts_collected=10,
        last_run_posts_saved=8,
        total_errors=3,
        last_error_message="boom",
        last_error_at=STARTED,
    )
    assert fake.statements[0][1] == ("rss",)


def test_load_without_a_row_returns_defaults():
    """A collector that never ran has zeroed counters."""
    fake = FakeConnection(row=None)

    stats = CollectorStatsStore(SETTINGS, connector=connector(fake)).load("finnhub")

    assert stats == CollectorStats(collector_name="finnhub")
    assert stats.total_posts_collected == 0
    assert stats.last_run_started_at is None


def test_load_swallows_database_errors():
    """A broken read must not abort the run; defaults come back."""
    fake = FakeConnection(fail_with=psycopg2.OperationalError("table is gone"))

    stats = CollectorStatsStore(SETTINGS, connector=connector(fake)).load("rss")

    assert stats == CollectorStats(collector_name="rss")


def test_save_upserts_and_commits():
    """One upsert on the collector name, then a commit."""
    fake = FakeConnection()
    stats = CollectorStats(
        collector_name="rss", total_posts_collected=7, last_run_duration_seconds=1.5
    )

    CollectorStatsStore(SETTINGS, connector=connector(fake)).save(stats)

    query, params = fake.statements[0]
    assert "INSERT INTO collector_statistics" in query
    assert "ON CONFLICT (collector_name)" in query
    assert params == ("rss", None, None, 1.5, 7, 0, 0, 0, 0, None, None)
    assert fake.commits == 1
    assert fake.rollbacks == 0


def test_save_truncates_the_error_message():
    """The column is bounded by the caller, not by the database."""
    fake = FakeConnection()
    stats = CollectorStats(collector_name="rss", last_error_message="x" * 900)

    CollectorStatsStore(SETTINGS, connector=connector(fake)).save(stats)

    stored = fake.statements[0][1][-2]
    assert stored is not None
    assert len(stored) == MAX_ERROR_MESSAGE_LENGTH


def test_save_swallows_database_errors():
    """Statistics are best effort: rollback, no exception."""
    fake = FakeConnection(fail_with=psycopg2.OperationalError("disk full"))

    CollectorStatsStore(SETTINGS, connector=connector(fake)).save(
        CollectorStats(collector_name="rss")
    )

    assert fake.commits == 0
    assert fake.rollbacks == 1
