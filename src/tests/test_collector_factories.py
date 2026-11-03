"""Tests for the collector registry the CLI builds."""

import pytest

from newstrading.collectors import factories
from newstrading.collectors.alphavantage import AlphaVantageCollector
from newstrading.collectors.congress import CongressionalTradesCollector
from newstrading.collectors.factories import build_registry
from newstrading.collectors.finnhub import FinnhubCollector
from newstrading.collectors.models import Asset
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.collectors.registry import CollectorError
from newstrading.collectors.rss import RSSCollector
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError
from newstrading.rate_limiter import RateLimitDecision, RateLimiter

URL = "postgresql://app:***@db.internal:5432/newstrading"
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("tesla",))
LIMITED_SOURCES = ("newsapi", "finnhub", "alphavantage", "congressional_trades")
EMPTY_BODIES = {
    "newsapi": {"status": "ok", "articles": []},
    "finnhub": [],
    "alphavantage": {"feed": []},
    "congressional_trades": [],
}

KEYED_SETTINGS = Settings(
    database_url=URL,
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
    registry = build_registry(Settings(database_url=URL))

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
    settings = Settings(database_url=URL)

    with pytest.raises(CollectorError) as error:
        build_registry(settings).create(source, settings)

    assert isinstance(error.value.__cause__, CollectorConfigError)
    assert variable in str(error.value)


class FakeResponse:
    """The slice of ``requests.Response`` the collectors read."""

    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


class FakeHttp:
    """HTTP seam: answers with one prepared response and counts the calls."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._response


class RecordingLimiter:
    """Stands in for ``RateLimiter``; records how a factory built it."""

    instances = []

    def __init__(self, settings, collector_name):
        self.settings = settings
        self.collector_name = collector_name
        self.allowed = True
        self.checks = 0
        self.records = []
        RecordingLimiter.instances.append(self)

    def can_make_request(self):
        self.checks += 1
        return RateLimitDecision(allowed=self.allowed, reason="quota exhausted", wait_seconds=0)

    def record_request(self, **kwargs):
        self.records.append(kwargs)


@pytest.fixture
def built_limiters(monkeypatch):
    """Replace the limiter class the factories build and return what they built."""
    RecordingLimiter.instances = []
    monkeypatch.setattr(factories, "RateLimiter", RecordingLimiter)
    return RecordingLimiter.instances


def registry_collector(source):
    """Build ``source`` through the registry and give it a recording HTTP seam.

    The registry takes no HTTP argument, so the test replaces the collector's seam
    after creation; the limiter under test still comes from the factory.
    """
    collector = build_registry(KEYED_SETTINGS).create(source, KEYED_SETTINGS)
    http = FakeHttp(FakeResponse(EMPTY_BODIES[source]))
    collector._http = http
    return collector, http


@pytest.mark.parametrize("source", LIMITED_SOURCES)
def test_each_quota_source_is_built_with_a_limiter_named_after_it(source, built_limiters):
    """A factory without its limiter would leave that quota unchecked."""
    build_registry(KEYED_SETTINGS).create(source, KEYED_SETTINGS)

    assert [limiter.collector_name for limiter in built_limiters] == [source]
    assert built_limiters[0].settings is KEYED_SETTINGS


@pytest.mark.parametrize("source", LIMITED_SOURCES)
def test_each_quota_source_is_built_with_the_real_limiter(source):
    """The registry hands the collector a ``RateLimiter`` keyed by its source name."""
    collector = build_registry(KEYED_SETTINGS).create(source, KEYED_SETTINGS)

    assert isinstance(collector._limiter, RateLimiter)
    assert collector._limiter._collector_name == source


def test_rss_is_built_without_a_limiter(built_limiters):
    """``rss`` has no API key and no hard quota, so nothing is tracked for it."""
    collector = build_registry(KEYED_SETTINGS).create("rss", KEYED_SETTINGS)

    assert isinstance(collector, RSSCollector)
    assert built_limiters == []


@pytest.mark.parametrize("source", LIMITED_SOURCES)
def test_a_denied_quota_stops_the_call_before_http(source, built_limiters):
    """The limiter the registry builds really guards the collector's HTTP call."""
    collector, http = registry_collector(source)
    built_limiters[-1].allowed = False

    assert collector.collect_for_asset(ASSET) == []
    assert http.calls == []
    assert built_limiters[-1].checks == 1
    assert built_limiters[-1].records == []


@pytest.mark.parametrize("source", LIMITED_SOURCES)
def test_an_allowed_quota_records_exactly_one_attempt(source, built_limiters):
    """One allowed collection means one HTTP call and exactly one usage row."""
    collector, http = registry_collector(source)

    collector.collect_for_asset(ASSET)

    assert len(http.calls) == 1
    assert len(built_limiters) == 1
    assert len(built_limiters[0].records) == 1
    assert built_limiters[0].records[0]["success"] is True
