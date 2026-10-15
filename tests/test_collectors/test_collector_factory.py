"""
Unit tests for CollectorFactory.
"""
import pytest
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add collector directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'collector'))

from collector_factory import CollectorFactory
from collectors.base import BaseCollector


class DummyCollector(BaseCollector):
    """Dummy collector for testing factory."""

    def __init__(self, database_url: str):
        super().__init__(database_url)

    def _load_statistics_from_db(self):
        """Override to prevent database access during testing."""
        pass

    def _save_statistics_to_db(self):
        """Override to prevent database access during testing."""
        pass

    def collect_for_asset(self, asset_id, asset_name, ticker, keywords):
        return []


class AnotherDummyCollector(BaseCollector):
    """Another dummy collector for testing."""

    def __init__(self, database_url: str):
        super().__init__(database_url)

    def _load_statistics_from_db(self):
        """Override to prevent database access during testing."""
        pass

    def _save_statistics_to_db(self):
        """Override to prevent database access during testing."""
        pass

    def collect_for_asset(self, asset_id, asset_name, ticker, keywords):
        return []


class TestCollectorFactory:
    """Test suite for CollectorFactory."""

    def test_initialization(self):
        """Test that factory initializes with empty registry."""
        factory = CollectorFactory()
        assert factory.list_available() == []

    def test_register_collector(self):
        """Test registering a collector class."""
        factory = CollectorFactory()
        factory.register('dummy', DummyCollector)

        assert 'dummy' in factory.list_available()
        assert factory.is_available('dummy')

    def test_register_multiple_collectors(self):
        """Test registering multiple collector classes."""
        factory = CollectorFactory()
        factory.register('dummy1', DummyCollector)
        factory.register('dummy2', AnotherDummyCollector)

        available = factory.list_available()
        assert len(available) == 2
        assert 'dummy1' in available
        assert 'dummy2' in available

    def test_register_non_collector_class_raises_error(self):
        """Test that registering non-BaseCollector class raises error."""
        factory = CollectorFactory()

        class NotACollector:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseCollector"):
            factory.register('invalid', NotACollector)

    def test_create_collector(self):
        """Test creating a collector instance."""
        factory = CollectorFactory()
        factory.register('dummy', DummyCollector)

        collector = factory.create('dummy', 'postgresql://test')

        assert collector is not None
        assert isinstance(collector, DummyCollector)
        assert collector.database_url == 'postgresql://test'

    def test_create_unregistered_collector_returns_none(self, caplog):
        """Test that creating unregistered collector returns None."""
        import logging
        caplog.set_level(logging.ERROR)

        factory = CollectorFactory()

        collector = factory.create('nonexistent', 'postgresql://test')

        assert collector is None
        assert "not registered" in caplog.text

    def test_create_collector_with_init_error_returns_none(self, caplog):
        """Test handling of collector initialization errors."""
        import logging
        caplog.set_level(logging.ERROR)

        class BrokenCollector(BaseCollector):
            def __init__(self, database_url: str):
                raise Exception("Initialization failed")

            def collect_for_asset(self, *args):
                pass

        factory = CollectorFactory()
        factory.register('broken', BrokenCollector)

        collector = factory.create('broken', 'postgresql://test')

        assert collector is None
        assert "Failed to create" in caplog.text

    def test_create_all_collectors(self):
        """Test creating multiple collectors at once."""
        factory = CollectorFactory()
        factory.register('dummy1', DummyCollector)
        factory.register('dummy2', AnotherDummyCollector)

        collectors = factory.create_all('postgresql://test', ['dummy1', 'dummy2'])

        assert len(collectors) == 2
        assert isinstance(collectors[0], BaseCollector)
        assert isinstance(collectors[1], BaseCollector)

    def test_create_all_with_some_invalid(self, caplog):
        """Test creating multiple collectors when some names are invalid."""
        import logging
        caplog.set_level(logging.INFO)

        factory = CollectorFactory()
        factory.register('dummy', DummyCollector)

        collectors = factory.create_all('postgresql://test', ['dummy', 'invalid'])

        # Should only create valid collector
        assert len(collectors) == 1
        assert isinstance(collectors[0], DummyCollector)
        assert "Created 1/2 collectors" in caplog.text

    def test_create_all_empty_list(self):
        """Test creating collectors with empty list."""
        factory = CollectorFactory()

        collectors = factory.create_all('postgresql://test', [])

        assert len(collectors) == 0

    def test_is_available(self):
        """Test checking if collector is available."""
        factory = CollectorFactory()
        factory.register('dummy', DummyCollector)

        assert factory.is_available('dummy') is True
        assert factory.is_available('nonexistent') is False

    def test_list_available(self):
        """Test listing all available collectors."""
        factory = CollectorFactory()
        factory.register('collector1', DummyCollector)
        factory.register('collector2', AnotherDummyCollector)

        available = factory.list_available()

        assert isinstance(available, list)
        assert len(available) == 2
        assert 'collector1' in available
        assert 'collector2' in available

    @patch('collector_factory.logger')
    def test_auto_discover_rss_collector(self, mock_logger):
        """Test auto-discovering RSS collector."""
        factory = CollectorFactory()
        factory.auto_discover()

        # RSS collector should always be available
        assert 'rss' in factory.list_available()

    @patch('collector_factory.logger')
    def test_auto_discover_handles_import_errors(self, mock_logger):
        """Test that auto_discover handles import errors gracefully."""
        factory = CollectorFactory()

        # This should not raise an exception even if some collectors fail to import
        factory.auto_discover()

        # Should have at least RSS collector
        assert len(factory.list_available()) >= 1

    def test_factory_is_singleton(self):
        """Test that get_factory returns the same instance."""
        from collector_factory import get_factory

        factory1 = get_factory()
        factory2 = get_factory()

        assert factory1 is factory2

    def test_register_same_name_overwrites(self):
        """Test that registering same name overwrites previous registration."""
        factory = CollectorFactory()
        factory.register('test', DummyCollector)
        factory.register('test', AnotherDummyCollector)

        collector = factory.create('test', 'postgresql://test')

        # Should create the second registered class
        assert isinstance(collector, AnotherDummyCollector)

    def test_create_with_different_database_urls(self):
        """Test creating collectors with different database URLs."""
        factory = CollectorFactory()
        factory.register('dummy', DummyCollector)

        collector1 = factory.create('dummy', 'postgresql://db1')
        collector2 = factory.create('dummy', 'postgresql://db2')

        assert collector1.database_url == 'postgresql://db1'
        assert collector2.database_url == 'postgresql://db2'
        assert collector1 is not collector2
