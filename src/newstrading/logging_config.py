"""Logging configuration: one console handler and one optional database handler.

The database handler writes to ``system_logs`` through its own connection. Logging is a
side channel: a database that is not reachable costs log rows, never the process. The
reconnect path logs through this module's logger, which is the fix for finding 9 of
issue #3 (the legacy code logged through an undefined ``logger`` and raised
``NameError``).
"""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Callable
from typing import Any

import psycopg2
from psycopg2.extras import Json

from newstrading.config import Settings

logger = logging.getLogger(__name__)

SERVICE_NAME = "newstrading"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
HANDLER_MARKER = "_newstrading_handler"

INSERT_SQL = """
    INSERT INTO system_logs
    (level, logger, service, message, function, line_number, exception, metadata)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

Connector = Callable[[str], Any]


def _level(name: str) -> int:
    """Return the logging level for a configured name; an unknown name means ``INFO``."""
    value = getattr(logging, name.upper(), None)
    return value if isinstance(value, int) else logging.INFO


def _mark(handler: logging.Handler) -> None:
    """Mark ``handler`` as added by this module, so a second call does not add it again."""
    setattr(handler, HANDLER_MARKER, True)


class DatabaseLogHandler(logging.Handler):
    """Writes log records to the ``system_logs`` table."""

    def __init__(
        self,
        database_url: str,
        service_name: str = SERVICE_NAME,
        min_level: int = logging.INFO,
        *,
        connector: Connector = psycopg2.connect,
    ) -> None:
        """Open the connection this handler writes through.

        Args:
            database_url: PostgreSQL connection string.
            service_name: Value written to the ``service`` column.
            min_level: Minimum level written to the database.
            connector: Connection factory; tests inject a fake.

        Contract:
            A database that cannot be reached costs the database records, not the process:
            the handler logs one warning and writes nothing.
        """
        super().__init__(min_level)
        self.database_url = database_url
        self.service_name = service_name
        self._connector = connector
        self._connection: Any = None
        self._connect()

    def _connect(self) -> None:
        """Open the connection, or keep working without one."""
        try:
            connection = self._connector(self.database_url)
        # boundary: logging must never take the process down
        except Exception as error:
            logger.warning("database log handler has no connection: %s", error)
            self._connection = None
            return
        connection.autocommit = True
        self._connection = connection

    def _ensure_connection(self) -> None:
        """Reconnect when the connection died, through the module logger (finding 9)."""
        if self._connection is None:
            self._connect()
            return
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as error:
            logger.warning("database log connection lost, reconnecting: %s", error)
            self._close_connection()
            self._connect()

    def emit(self, record: logging.LogRecord) -> None:
        """Write ``record`` to ``system_logs``; a failure is reported, never raised."""
        if self._connection is None:
            return
        try:
            self._ensure_connection()
            if self._connection is None:
                return
            with self._connection.cursor() as cursor:
                cursor.execute(INSERT_SQL, self._row(record))
        # boundary: logging must never take the process down
        except Exception:
            self.handleError(record)

    def _row(self, record: logging.LogRecord) -> tuple:
        """Return the parameter tuple of one log record."""
        exception_text = (
            "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None
        )
        metadata = {
            "thread": record.thread,
            "thread_name": record.threadName,
            "process": record.process,
            "process_name": record.processName,
        }
        return (
            record.levelname,
            record.name,
            self.service_name,
            record.getMessage(),
            record.funcName,
            record.lineno,
            exception_text,
            Json(metadata),
        )

    def _close_connection(self) -> None:
        """Close the connection, ignoring a driver that already gave up on it."""
        if self._connection is None:
            return
        try:
            self._connection.close()
        # boundary: a dead connection is already closed
        except Exception:
            pass
        self._connection = None

    def close(self) -> None:
        """Close the connection and the handler."""
        self._close_connection()
        super().close()


def configure_logging(settings: Settings, *, handler: logging.Handler | None = None) -> None:
    """Configure the root logger once.

    Console handler at ``settings.log_level``, optional database handler at
    ``settings.database_log_level`` (``handler`` is the seam tests replace). Calling it twice must
    not add a second pair of handlers (idempotent on the root logger).
    """
    root = logging.getLogger()
    if any(getattr(existing, HANDLER_MARKER, False) for existing in root.handlers):
        return
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(_level(settings.log_level))
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    _mark(console)
    root.addHandler(console)

    database = (
        handler if handler is not None else DatabaseLogHandler(settings.database_url, SERVICE_NAME)
    )
    database.setLevel(_level(settings.database_log_level))
    _mark(database)
    root.addHandler(database)
