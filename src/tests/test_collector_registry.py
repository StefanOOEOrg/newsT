"""Tests for the collector registry."""

import pytest

from newstrading.collectors.registry import CollectorError, CollectorRegistry
from newstrading.errors import NewsTradingError

SETTINGS = object()


class FakeCollector:
    """Minimal collector; the registry never looks inside it."""

    def __init__(self, name="fake"):
        self.name = name

    def collect_for_asset(self, asset):
        return []


def factory_returning(collector, seen_settings=None):
    """Build a factory that hands back ``collector`` and records its argument."""

    def _factory(settings):
        if seen_settings is not None:
            seen_settings.append(settings)
        return collector

    return _factory


def test_create_returns_what_the_factory_built():
    """The registry is a lookup, not a cache of instances."""
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("fake", factory_returning(collector))

    assert registry.create("fake", SETTINGS) is collector


def test_create_passes_the_settings_through():
    """Whatever the caller passes as settings reaches the factory unchanged."""
    registry = CollectorRegistry()
    seen = []
    registry.register("fake", factory_returning(FakeCollector(), seen))

    registry.create("fake", SETTINGS)

    assert seen == [SETTINGS]


def test_register_rejects_a_duplicate_name():
    """Two collectors under one key would silently shadow each other."""
    registry = CollectorRegistry()
    registry.register("fake", factory_returning(FakeCollector()))

    with pytest.raises(CollectorError) as error:
        registry.register("fake", factory_returning(FakeCollector()))

    assert "already registered" in str(error.value)
    assert "fake" in str(error.value)


def test_register_rejects_an_empty_name():
    """An empty key cannot be referenced from configuration."""
    registry = CollectorRegistry()

    with pytest.raises(CollectorError) as error:
        registry.register("", factory_returning(FakeCollector()))

    assert "empty" in str(error.value).lower()


def test_create_rejects_an_unknown_name_and_lists_the_known_ones():
    """A typo in the configuration has to be visible, not silently skipped."""
    registry = CollectorRegistry()
    registry.register("rss", factory_returning(FakeCollector()))
    registry.register("finnhub", factory_returning(FakeCollector()))

    with pytest.raises(CollectorError) as error:
        registry.create("newapi", SETTINGS)

    message = str(error.value)
    assert "newapi" in message
    assert "finnhub, rss" in message


def test_create_wraps_a_failing_factory():
    """A broken constructor names the collector and keeps the cause."""
    registry = CollectorRegistry()

    def exploding(settings):
        raise RuntimeError("no api key")

    registry.register("newsapi", exploding)

    with pytest.raises(CollectorError) as error:
        registry.create("newsapi", SETTINGS)

    assert "newsapi" in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)


def test_create_all_keeps_the_requested_order():
    """The scheduler runs the sources in configuration order."""
    registry = CollectorRegistry()
    registry.register("rss", factory_returning(FakeCollector("rss")))
    registry.register("stock_price", factory_returning(FakeCollector("stock_price")))

    built = registry.create_all(["stock_price", "rss"], SETTINGS)

    assert list(built) == ["stock_price", "rss"]
    assert built["rss"].name == "rss"


def test_create_all_raises_on_an_unknown_name():
    """Unlike the legacy factory, a missing source is not skipped."""
    registry = CollectorRegistry()
    registry.register("rss", factory_returning(FakeCollector()))

    with pytest.raises(CollectorError):
        registry.create_all(["rss", "twitter"], SETTINGS)


def test_names_are_sorted_and_is_available_reports_registration():
    """Both helpers answer from the same map."""
    registry = CollectorRegistry()
    registry.register("rss", factory_returning(FakeCollector()))
    registry.register("alphavantage", factory_returning(FakeCollector()))

    assert registry.names == ("alphavantage", "rss")
    assert registry.is_available("rss") is True
    assert registry.is_available("twitter") is False


def test_collector_error_is_a_newstrading_error():
    """The package exposes one catchable base type (guideline §6)."""
    assert issubclass(CollectorError, NewsTradingError)
