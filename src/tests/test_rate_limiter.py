"""Tests for newstrading.rate_limiter."""

import dataclasses

import psycopg2
import pytest

from newstrading.config import Settings
from newstrading.rate_limiter import MAX_ERROR_MESSAGE_LENGTH, RateLimitDecision, RateLimiter

URL = "postgresql://app:pw@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)


class FakeCursor:
    """Context-manager cursor that records the statement it was given."""

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
    """Connection double: one canned row, optional failure on execute."""

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


def connector_returning(fake):
    """Build a connector that hands back ``fake``."""

    def _connector(url):
        return fake

    return _connector


def test_decision_comes_from_the_quota_function():
    """The row of check_rate_limit decides, and the collector name is the argument."""
    fake = FakeConnection(row=(False, "daily limit reached", 3600))

    decision = RateLimiter(
        SETTINGS, "newsapi", connector=connector_returning(fake)
    ).can_make_request()

    assert decision == RateLimitDecision(
        allowed=False, reason="daily limit reached", wait_seconds=3600
    )
    assert "check_rate_limit" in fake.statements[0][0]
    assert fake.statements[0][1] == ("newsapi",)


def test_missing_row_means_no_quota_is_configured():
    """Sources without a configured quota are allowed through."""
    fake = FakeConnection(row=None)

    decision = RateLimiter(SETTINGS, "rss", connector=connector_returning(fake)).can_make_request()

    assert decision == RateLimitDecision(
        allowed=True, reason="No rate limit configured", wait_seconds=0
    )


def test_a_failing_check_fails_open():
    """A broken quota table must not stop the collection."""
    fake = FakeConnection(fail_with=psycopg2.OperationalError("connection lost"))

    decision = RateLimiter(SETTINGS, "rss", connector=connector_returning(fake)).can_make_request()

    assert decision.allowed is True
    assert decision.wait_seconds == 0
    assert decision.reason.startswith("Rate limit check failed:")
    assert "connection lost" in decision.reason


def test_record_request_writes_the_call_and_commits():
    """One row into api_usage, fields in statement order."""
    fake = FakeConnection()

    RateLimiter(SETTINGS, "finnhub", connector=connector_returning(fake)).record_request(
        success=True, status_code=200, api_endpoint="https://finnhub.io/api/v1/news"
    )

    query, params = fake.statements[0]
    assert "INSERT INTO api_usage" in query
    assert params == ("finnhub", "https://finnhub.io/api/v1/news", 200, True, None)
    assert fake.commits == 1
    assert fake.rollbacks == 0


def test_record_request_truncates_the_error_message():
    """The column is bounded; a long provider message is cut, not stored whole."""
    fake = FakeConnection()

    RateLimiter(SETTINGS, "finnhub", connector=connector_returning(fake)).record_request(
        success=False, error_message="x" * 900
    )

    stored = fake.statements[0][1][-1]
    assert len(stored) == MAX_ERROR_MESSAGE_LENGTH


def test_record_request_swallows_database_errors():
    """Recording is best effort: rollback, no exception."""
    fake = FakeConnection(fail_with=psycopg2.OperationalError("disk full"))

    RateLimiter(SETTINGS, "finnhub", connector=connector_returning(fake)).record_request(
        success=True
    )

    assert fake.commits == 0
    assert fake.rollbacks == 1


def test_decision_is_frozen():
    """The decision is a value object."""
    decision = RateLimitDecision(allowed=True, reason="ok", wait_seconds=0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.allowed = False
