"""
Unit tests for logging_config module.
"""
import pytest
import logging
import sys
from io import StringIO
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'shared'))

from logging_config import DatabaseLogHandler, setup_logging, LoggerAdapter, get_logger


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self, should_fail=False):
        self.autocommit = False
        self.closed = False
        self.should_fail = should_fail
        self.queries = []
        self.commit_count = 0

    def cursor(self):
        """Return mock cursor."""
        return MockCursor(self)

    def commit(self):
        """Mock commit."""
        self.commit_count += 1

    def close(self):
        """Mock close."""
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockCursor:
    """Mock database cursor."""

    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def execute(self, query, params=None):
        """Mock execute."""
        if self.connection.should_fail:
            raise Exception("Database error")
        self.queries.append((query, params))
        self.connection.queries.append((query, params))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class TestDatabaseLogHandler:
    """Test suite for DatabaseLogHandler."""

    @patch('logging_config.psycopg2.connect')
    def test_initialization_success(self, mock_connect):
        """Test successful handler initialization."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        assert handler.database_url == "postgresql://test"
        assert handler.service_name == "test_service"
        assert handler.level == logging.INFO
        assert mock_conn.autocommit is True

    @patch('logging_config.psycopg2.connect')
    def test_initialization_with_custom_level(self, mock_connect):
        """Test initialization with custom log level."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service",
            min_level=logging.WARNING
        )

        assert handler.level == logging.WARNING

    @patch('logging_config.psycopg2.connect')
    def test_initialization_connection_failure(self, mock_connect, capsys):
        """Test handler initialization when connection fails."""
        mock_connect.side_effect = Exception("Connection failed")

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Should create handler but with no connection
        assert handler._conn is None

        # Should print warning
        captured = capsys.readouterr()
        assert "WARNING: Could not connect to database for logging" in captured.err

    @patch('logging_config.psycopg2.connect')
    def test_emit_log_record(self, mock_connect):
        """Test emitting a log record to database."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Create log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Emit record
        handler.emit(record)

        # Verify INSERT query was executed
        assert len(mock_conn.queries) > 0
        query, params = mock_conn.queries[-1]
        assert "INSERT INTO system_logs" in query
        assert params[0] == "INFO"  # level
        assert params[1] == "test"  # logger name
        assert params[2] == "test_service"  # service name
        assert params[3] == "Test message"  # message

    @patch('logging_config.psycopg2.connect')
    def test_emit_with_exception_info(self, mock_connect):
        """Test emitting log with exception information."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Create log record with exception
        logger = logging.getLogger("test")
        try:
            raise ValueError("Test error")
        except ValueError:
            record = logger.makeRecord(
                name="test",
                level=logging.ERROR,
                fn="test.py",
                lno=42,
                msg="Error occurred",
                args=(),
                exc_info=sys.exc_info()
            )

        # Emit record
        handler.emit(record)

        # Verify exception was captured
        query, params = mock_conn.queries[-1]
        exception_text = params[6]  # exception parameter
        assert exception_text is not None
        assert "ValueError: Test error" in exception_text
        assert "Traceback" in exception_text

    @patch('logging_config.psycopg2.connect')
    def test_emit_with_custom_metadata(self, mock_connect):
        """Test emitting log with custom metadata."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Create log record with metadata
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.metadata = {"custom_field": "custom_value", "count": 123}

        # Emit record
        handler.emit(record)

        # Verify metadata was included
        query, params = mock_conn.queries[-1]
        metadata = params[7]  # metadata parameter (Json object)
        # Check that custom metadata is included
        assert hasattr(metadata, 'adapted')  # It's a Json object

    @patch('logging_config.psycopg2.connect')
    def test_emit_when_no_connection(self, mock_connect):
        """Test emitting when no database connection."""
        mock_connect.side_effect = Exception("Connection failed")

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Create log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Should not raise exception
        handler.emit(record)

    @patch('logging_config.psycopg2.connect')
    def test_emit_handles_database_errors(self, mock_connect, capsys):
        """Test that emit handles database errors gracefully."""
        mock_conn = MockConnection(should_fail=True)
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Create log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=42,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Should handle error gracefully
        handler.emit(record)

        # Should print error message
        captured = capsys.readouterr()
        assert "ERROR writing log to database" in captured.err

    @patch('logging_config.psycopg2.connect')
    def test_ensure_connection_reconnects(self, mock_connect):
        """Test that _ensure_connection reconnects when needed."""
        # First connection succeeds
        mock_conn1 = MockConnection()
        # Second connection for reconnect
        mock_conn2 = MockConnection()

        mock_connect.side_effect = [mock_conn1, mock_conn2]

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Simulate dead connection
        handler._conn = None

        # Call _ensure_connection
        handler._ensure_connection()

        # Should have reconnected
        assert handler._conn is not None

    @patch('logging_config.psycopg2.connect')
    def test_close_handler(self, mock_connect):
        """Test closing the handler."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn

        handler = DatabaseLogHandler(
            database_url="postgresql://test",
            service_name="test_service"
        )

        # Close handler
        handler.close()

        # Connection should be closed
        assert mock_conn.closed is True


class TestSetupLogging:
    """Test suite for setup_logging function."""

    @patch('logging_config.DatabaseLogHandler')
    def test_setup_logging_console_only(self, mock_handler_class):
        """Test setup with console logging only."""
        logger = setup_logging(
            service_name="test_service",
            console_level="INFO"
        )

        assert logger is not None
        assert logger.name == "test_service"

        # Should not create database handler
        mock_handler_class.assert_not_called()

    @patch('logging_config.DatabaseLogHandler')
    @patch('logging_config.psycopg2.connect')
    def test_setup_logging_with_database(self, mock_connect, mock_handler_class):
        """Test setup with both console and database logging."""
        mock_conn = MockConnection()
        mock_connect.return_value = mock_conn
        mock_handler = Mock()
        mock_handler_class.return_value = mock_handler

        logger = setup_logging(
            service_name="test_service",
            database_url="postgresql://test",
            console_level="INFO",
            database_level="WARNING"
        )

        assert logger is not None

        # Should create database handler
        mock_handler_class.assert_called_once()
        call_args = mock_handler_class.call_args
        assert call_args[0][0] == "postgresql://test"
        assert call_args[0][1] == "test_service"

    def test_setup_logging_custom_format(self):
        """Test setup with custom log format."""
        custom_format = "%(levelname)s - %(message)s"

        logger = setup_logging(
            service_name="test_service",
            console_level="DEBUG",
            log_format=custom_format
        )

        # Check that console handler has custom format
        root_logger = logging.getLogger()
        console_handler = root_logger.handlers[0]
        assert console_handler.formatter._fmt == custom_format

    def test_setup_logging_clears_existing_handlers(self):
        """Test that setup clears existing handlers."""
        root_logger = logging.getLogger()

        # Add a dummy handler
        dummy_handler = logging.StreamHandler()
        root_logger.addHandler(dummy_handler)

        initial_count = len(root_logger.handlers)

        # Setup logging
        setup_logging(service_name="test_service")

        # Old handlers should be cleared
        assert dummy_handler not in root_logger.handlers


class TestLoggerAdapter:
    """Test suite for LoggerAdapter."""

    def test_logger_adapter_creation(self):
        """Test creating a logger adapter."""
        base_logger = logging.getLogger("test")
        adapter = LoggerAdapter(base_logger, {"service": "test_service"})

        assert adapter.logger == base_logger
        assert adapter.extra == {"service": "test_service"}

    def test_logger_adapter_process(self):
        """Test processing messages with adapter."""
        base_logger = logging.getLogger("test")
        adapter = LoggerAdapter(base_logger, {"service": "test_service"})

        msg, kwargs = adapter.process("Test message", {"metadata": {"count": 10}})

        assert msg == "Test message"
        assert "extra" in kwargs
        assert "metadata" in kwargs["extra"]
        assert kwargs["extra"]["metadata"]["service"] == "test_service"
        assert kwargs["extra"]["metadata"]["count"] == 10

    def test_logger_adapter_merges_metadata(self):
        """Test that adapter merges metadata correctly."""
        base_logger = logging.getLogger("test")
        adapter = LoggerAdapter(base_logger, {"base_key": "base_value"})

        msg, kwargs = adapter.process(
            "Test message",
            {"metadata": {"extra_key": "extra_value"}}
        )

        metadata = kwargs["extra"]["metadata"]
        assert metadata["base_key"] == "base_value"
        assert metadata["extra_key"] == "extra_value"


class TestGetLogger:
    """Test suite for get_logger function."""

    def test_get_logger_without_metadata(self):
        """Test getting logger without metadata."""
        logger = get_logger("test_logger")

        assert isinstance(logger, LoggerAdapter)
        assert logger.logger.name == "test_logger"
        assert logger.extra == {}

    def test_get_logger_with_metadata(self):
        """Test getting logger with metadata."""
        logger = get_logger("test_logger", service="collector", collector_type="rss")

        assert isinstance(logger, LoggerAdapter)
        assert logger.extra["service"] == "collector"
        assert logger.extra["collector_type"] == "rss"

    def test_get_logger_reuses_base_logger(self):
        """Test that get_logger reuses the same base logger."""
        logger1 = get_logger("test_logger")
        logger2 = get_logger("test_logger")

        # Should have same base logger
        assert logger1.logger is logger2.logger
