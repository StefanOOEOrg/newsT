"""Tests for newstrading.logging_config: the handlers, their levels and the idempotency."""

import logging

import psycopg2
import pytest

from newstrading.config import Settings
from newstrading.logging_config import DatabaseLogHandler, configure_logging

URL = "postgresql://app:secret@db.internal:5432/newstrading"
SETTINGS = Settings(
    database_url=URL,
    anthropic_api_key="sk-test",
    log_level="WARNING",
    database_log_level="ERROR",
)


class FakeCursor:
    """Records the statements of a fake connection, optionally failing."""

    def __init__(self, connection, failure=None):
        self._connection = connection
        self._failure = failure

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement, parameters=None):
        if self._failure is not None:
            raise self._failure
        self._connection.statements.append((statement, parameters))


class FakeConnection:
    """A connection that can fail on the health check or on the insert."""

    def __init__(self, *, fails_select=False, fails_insert=False):
        self.statements = []
        self.autocommit = False
        self.closed = 0
        self._fails_select = fails_select
        self._fails_insert = fails_insert

    def cursor(self):
        if self._fails_select:
            raise psycopg2.InterfaceError("connection already closed")
        failure = RuntimeError("insert failed") if self._fails_insert else None
        return FakeCursor(self, failure)

    def close(self):
        self.closed += 1


@pytest.fixture
def root_handlers():
    """Run with a clean root logger and restore its handlers afterwards."""
    root = logging.getLogger()
    before = list(root.handlers)
    root.handlers.clear()
    yield root
    root.handlers.clear()
    root.handlers.extend(before)


def record(message="starting"):
    """Build the log record a real logger would hand to a handler."""
    return logging.LogRecord("newstrading.cli", logging.INFO, __file__, 7, message, None, None)


def test_configure_logging_adds_one_console_and_one_database_handler(root_handlers):
    """A configured run writes to the console and to the database."""
    database_handler = logging.NullHandler()
    before = set(root_handlers.handlers)

    configure_logging(SETTINGS, handler=database_handler)

    added = [handler for handler in root_handlers.handlers if handler not in before]
    assert len(added) == 2
    assert database_handler in added
    assert root_handlers.level == logging.DEBUG


def test_configure_logging_uses_the_configured_levels(root_handlers):
    """Console and database read their own level from the settings."""
    database_handler = logging.NullHandler()
    before = set(root_handlers.handlers)

    configure_logging(SETTINGS, handler=database_handler)

    added = [handler for handler in root_handlers.handlers if handler not in before]
    console = next(handler for handler in added if handler is not database_handler)
    assert isinstance(console, logging.StreamHandler)
    assert console.level == logging.WARNING
    assert database_handler.level == logging.ERROR


def test_configure_logging_is_idempotent(root_handlers):
    """A second call must not add a second pair of handlers."""
    database_handler = logging.NullHandler()
    configure_logging(SETTINGS, handler=database_handler)
    configured = list(root_handlers.handlers)

    configure_logging(SETTINGS, handler=database_handler)

    assert len(configured) == len(root_handlers.handlers)
    assert root_handlers.handlers == configured


def test_configure_logging_keeps_the_first_configuration(root_handlers):
    """The second call is a no-op even when it carries another handler."""
    configure_logging(SETTINGS, handler=logging.NullHandler())
    configured = list(root_handlers.handlers)
    other = logging.NullHandler()

    configure_logging(SETTINGS, handler=other)

    assert other not in root_handlers.handlers
    assert root_handlers.handlers == configured


def test_configure_logging_builds_the_database_handler_when_none_is_given(
    root_handlers, monkeypatch
):
    """Production passes no handler: the database URL of the settings is used."""
    built = []
    before = set(root_handlers.handlers)

    class FakeDatabaseHandler(logging.Handler):
        def __init__(self, database_url, service_name):
            super().__init__()
            self.database_url = database_url
            self.service_name = service_name
            built.append(self)

    monkeypatch.setattr("newstrading.logging_config.DatabaseLogHandler", FakeDatabaseHandler)

    configure_logging(SETTINGS)

    assert built[0].database_url == URL
    assert built[0].level == logging.ERROR
    assert built[0] in root_handlers.handlers
    assert len([handler for handler in root_handlers.handlers if handler not in before]) == 2


def test_database_handler_writes_a_record(caplog):
    """A healthy connection receives the documented insert."""
    connection = FakeConnection()
    handler = DatabaseLogHandler(URL, connector=lambda url: connection)

    with caplog.at_level(logging.ERROR, logger="newstrading.test"):
        handler.emit(record())

    statement, parameters = connection.statements[-1]
    assert "INSERT INTO system_logs" in statement
    assert parameters[2] == "newstrading"
    assert parameters[3] == "starting"
    assert caplog.records == []


def test_database_handler_logs_a_lost_connection_through_the_module_logger(caplog):
    """The reconnect path of finding 9 logs instead of raising ``NameError``."""
    lost = FakeConnection(fails_select=True)
    recovered = FakeConnection()
    connections = iter([lost, recovered])
    handler = DatabaseLogHandler(URL, connector=lambda url: next(connections))

    with caplog.at_level(logging.WARNING, logger="newstrading.logging_config"):
        handler.emit(record())

    assert lost.closed == 1
    assert [entry.name for entry in caplog.records] == ["newstrading.logging_config"]
    assert "reconnect" in caplog.records[0].getMessage()
    assert "INSERT INTO system_logs" in recovered.statements[-1][0]


def test_database_handler_without_a_connection_writes_nothing(caplog):
    """An unreachable database costs the records, not the process."""

    def refusing(url):
        raise psycopg2.OperationalError("no route to host")

    handler = DatabaseLogHandler(URL, connector=refusing)

    with caplog.at_level(logging.WARNING, logger="newstrading.logging_config"):
        handler.emit(record())

    assert "no connection" in caplog.records[0].getMessage()
    assert handler.database_url == URL


def test_database_handler_contains_an_insert_failure(monkeypatch):
    """A failing insert is reported to ``handleError`` and never raised."""
    connection = FakeConnection(fails_insert=True)
    handler = DatabaseLogHandler(URL, connector=lambda url: connection)
    handled = []
    monkeypatch.setattr(handler, "handleError", handled.append)

    handler.emit(record())

    assert handled != []


def test_database_handler_closes_its_connection():
    """Closing the handler releases the connection."""
    connection = FakeConnection()
    handler = DatabaseLogHandler(URL, connector=lambda url: connection)

    handler.close()

    assert connection.closed == 1
