"""Database access for the newstrading package.

One place opens connections, one place decides how a failed statement is rolled back.
Callers pass :class:`~newstrading.config.Settings` in; nothing here reads the environment.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol
from urllib.parse import urlsplit

import psycopg2

from newstrading.config import Settings
from newstrading.errors import NewsTradingError


class DatabaseError(NewsTradingError):
    """Raised when a connection to the database cannot be opened."""


class Connection(Protocol):
    """The part of a psycopg2 connection this package relies on."""

    def commit(self) -> None:
        """Persist the current transaction."""

    def rollback(self) -> None:
        """Discard the current transaction."""

    def close(self) -> None:
        """Release the connection."""


Connector = Callable[[str], Connection]


def _describe_target(database_url: str) -> str:
    """Return ``host:port/dbname`` for a URL, without credentials.

    Args:
        database_url: PostgreSQL connection string.

    Returns:
        A description safe for log lines; ``unknown database`` if the URL has no host
        or no database name.
    """
    try:
        parts = urlsplit(database_url)
        database = parts.path.removeprefix("/")
        if parts.hostname is None or not database:
            return "unknown database"
        port = parts.port
    except ValueError:
        return "unknown database"
    if port is None:
        port = 5432
    return f"{parts.hostname}:{port}/{database}"


def connect(database_url: str, *, connector: Connector = psycopg2.connect) -> Connection:
    """Open a connection to ``database_url``.

    Args:
        database_url: PostgreSQL connection string.
        connector: Factory used to open the connection. Injected in tests; production
            callers leave it at :func:`psycopg2.connect`.

    Returns:
        The connection returned by ``connector``.

    Raises:
        DatabaseError: If the connector raises. The message names
            ``host:port/dbname`` and must never contain the user or the password.
    """
    try:
        return connector(database_url)
    except Exception as error:
        raise DatabaseError(
            f"cannot open a connection to {_describe_target(database_url)}"
        ) from error


@contextmanager
def connection(
    settings: Settings, *, connector: Connector = psycopg2.connect
) -> Iterator[Connection]:
    """Yield a connection and settle the transaction around the block.

    Args:
        settings: Settings holding ``database_url``.
        connector: Factory used to open the connection (see :func:`connect`).

    Yields:
        An open connection from :func:`connect`.

    Raises:
        DatabaseError: If the connection cannot be opened.
        BaseException: Whatever the body raises — it is re-raised unchanged after the
            rollback, never wrapped.

    Contract:
        * Normal exit commits, then closes.
        * An exception rolls back, closes, and re-raises the original exception.
        * ``close`` runs in both cases, also when commit or rollback raise.
    """
    open_connection = connect(settings.database_url, connector=connector)
    try:
        yield open_connection
    except BaseException:
        try:
            open_connection.rollback()
        finally:
            open_connection.close()
        raise
    else:
        try:
            open_connection.commit()
        finally:
            open_connection.close()
