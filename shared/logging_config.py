"""
Logging configuration with database handler support.
"""
import os
import sys
import logging
import json
import traceback
from typing import Optional, Dict, Any
from datetime import datetime
import psycopg2
from psycopg2.extras import Json


class DatabaseLogHandler(logging.Handler):
    """
    Custom logging handler that writes logs to PostgreSQL database.

    Writes logs to the system_logs table with structured metadata.
    """

    def __init__(self, database_url: str, service_name: str, min_level: int = logging.INFO):
        """
        Initialize the database log handler.

        Args:
            database_url: PostgreSQL connection string
            service_name: Name of the service (e.g., 'collector', 'analyzer', 'dashboard')
            min_level: Minimum log level to write to database (default: INFO)
        """
        super().__init__()
        self.database_url = database_url
        self.service_name = service_name
        self.setLevel(min_level)
        self._conn = None
        self._connect()

    def _connect(self):
        """Establish database connection."""
        try:
            self._conn = psycopg2.connect(self.database_url)
            self._conn.autocommit = True  # Auto-commit for logging
        except Exception as e:
            # Fall back to console logging if DB connection fails
            print(f"WARNING: Could not connect to database for logging: {e}", file=sys.stderr)
            self._conn = None

    def _ensure_connection(self):
        """Ensure database connection is alive."""
        if self._conn is None:
            self._connect()
            return

        try:
            # Test connection
            with self._conn.cursor() as cur:
                cur.execute('SELECT 1')
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            # Reconnect if connection is dead
            logger.warning(f"Database connection lost, reconnecting: {e}")
            try:
                self._conn.close()
            except Exception:
                pass  # Ignore errors when closing dead connection
            self._connect()

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to the database.

        Args:
            record: LogRecord to write
        """
        if self._conn is None:
            return  # Skip if no DB connection

        try:
            self._ensure_connection()

            # Extract exception info
            exception_text = None
            if record.exc_info:
                exception_text = ''.join(traceback.format_exception(*record.exc_info))

            # Build metadata
            metadata: Dict[str, Any] = {
                'thread': record.thread,
                'thread_name': record.threadName,
                'process': record.process,
                'process_name': record.processName,
            }

            # Add custom fields from record
            if hasattr(record, 'metadata'):
                metadata.update(record.metadata)

            # Insert log record
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO system_logs
                    (level, logger, service, message, function, line_number, exception, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.levelname,
                        record.name,
                        self.service_name,
                        record.getMessage(),
                        record.funcName,
                        record.lineno,
                        exception_text,
                        Json(metadata)
                    )
                )

        except Exception as e:
            # Don't let logging errors break the application
            print(f"ERROR writing log to database: {e}", file=sys.stderr)
            self.handleError(record)

    def close(self):
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except:
                pass
        super().close()


def setup_logging(
    service_name: str,
    database_url: Optional[str] = None,
    console_level: str = 'INFO',
    database_level: str = 'INFO',
    log_format: Optional[str] = None
) -> logging.Logger:
    """
    Set up logging for a service with both console and database handlers.

    Args:
        service_name: Name of the service (e.g., 'collector', 'analyzer')
        database_url: PostgreSQL connection string (if None, only console logging)
        console_level: Log level for console output (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        database_level: Log level for database output (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Custom log format string (optional)

    Returns:
        Configured logger instance
    """
    # Parse log levels
    console_level_int = getattr(logging, console_level.upper(), logging.INFO)
    database_level_int = getattr(logging, database_level.upper(), logging.INFO)

    # Default format
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all levels, handlers will filter

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level_int)
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Database handler (if URL provided)
    if database_url:
        try:
            db_handler = DatabaseLogHandler(database_url, service_name, database_level_int)
            root_logger.addHandler(db_handler)
        except Exception as e:
            print(f"WARNING: Could not set up database logging: {e}", file=sys.stderr)

    # Return logger for this service
    logger = logging.getLogger(service_name)
    return logger


class LoggerAdapter(logging.LoggerAdapter):
    """
    Custom logger adapter that allows adding metadata to log records.

    Usage:
        logger = LoggerAdapter(logging.getLogger(__name__), {'collector': 'rss'})
        logger.info("Collected posts", metadata={'count': 10})
    """

    def process(self, msg, kwargs):
        """Add extra context to log records."""
        # Merge metadata
        metadata = self.extra.copy()
        if 'metadata' in kwargs:
            metadata.update(kwargs.pop('metadata'))

        # Store in kwargs for the handler
        kwargs['extra'] = {'metadata': metadata}
        return msg, kwargs


def get_logger(name: str, **metadata) -> LoggerAdapter:
    """
    Get a logger with optional metadata.

    Args:
        name: Logger name
        **metadata: Additional metadata to attach to all log records

    Returns:
        LoggerAdapter instance
    """
    logger = logging.getLogger(name)
    return LoggerAdapter(logger, metadata)
