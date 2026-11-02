"""Tests for the collector registry the CLI builds."""

import pytest

from newstrading.collectors.alphavantage import AlphaVantageCollector
from newstrading.collectors.congress import CongressionalTradesCollector
from newstrading.collectors.factories import build_registry
from newstrading.collectors.finnhub import FinnhubCollector
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.collectors.registry import CollectorError
from newstrading.collectors.rss import RSSCollector
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError

URL = "postgresql://app:secret@db.internal:5432/newstrading"

KEYED_SETTINGS = Settings(
    database_url=URL,
    anthropic_api_key="sk-test",
    newsapi_key="news-key",
    finnhub_api_key="finnhub-key",
    alphavantage_api_key="alphavantage-key",
)


def test_build_registry_registers_every_source():
    """The CLI can address every implemented collector by its source name."""
    registry = build_registry(KEYED_SETTINGS)

    assert registry.names == (
        "alphavantage",
        "congressional_trades",
        "finnhub",
        "newsapi",
        "rss",
    )


def test_build_registry_registers_without_building():
    """Registration must not need the API keys; the key is checked on construction."""
    registry = build_registry(Settings(database_url=URL, anthropic_api_key=""))

    assert registry.names == (
        "alphavantage",
        "congressional_trades",
        "finnhub",
        "newsapi",
        "rss",
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("rss", RSSCollector),
        ("newsapi", NewsAPICollector),
        ("finnhub", FinnhubCollector),
        ("alphavantage", AlphaVantageCollector),
        ("congressional_trades", CongressionalTradesCollector),
    ],
)
def test_create_returns_the_collector_of_the_name(name, expected):
    """Each source name maps to its own class."""
    assert isinstance(build_registry(KEYED_SETTINGS).create(name, KEYED_SETTINGS), expected)


def test_unknown_name_raises_with_the_known_names():
    """A typo in the configuration names the sources that do exist."""
    with pytest.raises(CollectorError) as error:
        build_registry(KEYED_SETTINGS).create("twitter", KEYED_SETTINGS)

    message = str(error.value)
    assert "twitter" in message
    assert "congressional_trades, finnhub, newsapi, rss" in message


@pytest.mark.parametrize(
    ("source", "variable"),
    [
        ("newsapi", "NEWSAPI_KEY"),
        ("finnhub", "FINNHUB_API_KEY"),
        ("alphavantage", "ALPHAVANTAGE_API_KEY"),
    ],
)
def test_a_missing_key_fails_at_construction(source, variable):
    """A keyless source is a configuration error of the registry, not a skipped source."""
    settings = Settings(database_url=URL, anthropic_api_key="sk-test")

    with pytest.raises(CollectorError) as error:
        build_registry(settings).create(source, settings)

    assert isinstance(error.value.__cause__, CollectorConfigError)
    assert variable in str(error.value)
