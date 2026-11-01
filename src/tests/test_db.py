"""Tests for newstrading.db."""

import psycopg2
import pytest

from newstrading.config import Settings
from newstrading.db import DatabaseError, connect, connection
from newstrading.errors import NewsTradingError

URL = "postgresql://app:secret-pw@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")


class FakeConnection:
    """Records what the package does with a connection."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def connector_returning(fake, seen_urls=None):
    """Build a connector that hands back ``fake`` and records the URL."""

    def _connector(url):
        if seen_urls is not None:
            seen_urls.append(url)
        return fake

    return _connector


def connector_raising(error):
    """Build a connector that raises ``error``."""

    def _connector(url):
        raise error

    return _connector


def test_connect_returns_the_connection():
    """connect hands back whatever the connector opened."""
    fake = FakeConnection()

    assert connect(URL, connector=connector_returning(fake)) is fake


def test_connect_passes_the_url_unchanged():
    """The connection string reaches the driver untouched."""
    seen = []

    connect(URL, connector=connector_returning(FakeConnection(), seen))

    assert seen == [URL]


def test_connect_wraps_driver_errors_without_credentials():
    """The error names host, port and database — never the user or the password."""
    failure = psycopg2.OperationalError('could not translate host name "db.internal"')

    with pytest.raises(DatabaseError) as error:
        connect(URL, connector=connector_raising(failure))

    message = str(error.value)
    assert "db.internal:5432/newstrading" in message
    assert "secret-pw" not in message
    assert "app:" not in message
    assert error.value.__cause__ is failure


def test_connect_reports_an_unparseable_url_as_unknown():
    """A URL without host or database still produces a readable error."""
    failure = psycopg2.ProgrammingError("invalid dsn")

    with pytest.raises(DatabaseError) as error:
        connect("not-a-url", connector=connector_raising(failure))

    assert "unknown database" in str(error.value)


def test_connection_commits_and_closes_on_success():
    """A block that finishes settles the transaction and releases the connection."""
    fake = FakeConnection()

    with connection(SETTINGS, connector=connector_returning(fake)) as opened:
        assert opened is fake

    assert (fake.commits, fake.rollbacks, fake.closes) == (1, 0, 1)


def test_connection_rolls_back_and_reraises_unchanged():
    """A failing block rolls back and re-raises the original exception."""
    fake = FakeConnection()

    with pytest.raises(ValueError, match="boom"):
        with connection(SETTINGS, connector=connector_returning(fake)):
            raise ValueError("boom")

    assert (fake.commits, fake.rollbacks, fake.closes) == (0, 1, 1)


def test_database_error_is_a_newstrading_error():
    """The package exposes one catchable base type (guideline §6)."""
    assert issubclass(DatabaseError, NewsTradingError)
