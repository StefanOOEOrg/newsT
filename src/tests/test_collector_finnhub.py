"""Tests for newstrading.collectors.finnhub."""

import hashlib
import inspect
from datetime import UTC, datetime, timedelta

import pytest
import requests

from newstrading.collectors import Collector, FinnhubCollector
from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError, NewsTradingError
from newstrading.rate_limiter import RateLimitDecision

API_URL = "https://finnhub.io/api/v1/company-news"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
PUBLISHED = 1793348100  # 2026-10-30T08:15:00Z
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("tesla",))
LINK = "https://example.com/finnhub-story"
ARTICLE_ID = 1234567


def make_settings(*, finnhub_api_key: str = "finnhub-key") -> Settings:
    """Build settings with a Finnhub key unless a test overrides it."""
    return Settings(
        database_url="postgresql://user:pw@localhost:5432/newstrading",
        anthropic_api_key="sk-test",
        finnhub_api_key=finnhub_api_key,
    )


def fixed_now():
    """Clock seam: a constant, timezone aware UTC time."""
    return NOW


class FakeResponse:
    """The slice of ``requests.Response`` the collector reads."""

    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    @property
    def text(self):
        return str(self._payload)


class FakeHttp:
    """HTTP seam: one prepared response per call, in order; records the calls."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(
            {"url": url, "params": kwargs.get("params"), "timeout": kwargs.get("timeout")}
        )
        result = self._responses[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


class FakeLimiter:
    """Quota seam: answers a fixed decision and records what was booked."""

    def __init__(self, allowed=True, reason="minute quota exhausted"):
        self.decision = RateLimitDecision(allowed=allowed, reason=reason, wait_seconds=0)
        self.checks = 0
        self.records = []

    def can_make_request(self):
        self.checks += 1
        return self.decision

    def record_request(self, **kwargs):
        self.records.append(kwargs)


def article(**overrides):
    """One article in the shape Finnhub returns it."""
    values = {
        "id": ARTICLE_ID,
        "url": LINK,
        "headline": "Tesla beats estimates",
        "summary": "Quarterly results beat the consensus.",
        "source": "Reuters",
        "datetime": PUBLISHED,
    }
    values.update(overrides)
    return values


def collect_one(item, *, limiter=None, now=fixed_now):
    """Collect a single article and return the one post it must produce."""
    http = FakeHttp(FakeResponse([item]))
    collector = FinnhubCollector(make_settings(), http=http, limiter=limiter, now=now)
    posts = collector.collect_for_asset(ASSET)
    assert len(posts) == 1
    return posts[0]


def post_id_for(article_id, url):
    """The id the documented scheme derives from the article id and the URL."""
    return "finnhub_" + hashlib.md5(f"{article_id}:{url}".encode()).hexdigest()


def test_a_missing_key_fails_in_the_constructor():
    """Without a key the collector cannot work, so it refuses to exist."""
    with pytest.raises(CollectorConfigError) as error:
        FinnhubCollector(make_settings(finnhub_api_key=""))

    assert "FINNHUB_API_KEY" in str(error.value)
    assert isinstance(error.value, NewsTradingError)


def test_a_present_key_builds_the_collector():
    """The key is all the constructor needs."""
    collector = FinnhubCollector(make_settings())

    assert collector.name == "finnhub"


def test_one_article_becomes_the_expected_post():
    """Every field of the legacy mapping ends up in the ``Post``."""
    post = collect_one(article())

    assert post == Post(
        asset_id=7,
        source="finnhub",
        post_id=post_id_for(ARTICLE_ID, LINK),
        author="Reuters",
        title="Tesla beats estimates",
        content="Quarterly results beat the consensus.",
        url=LINK,
        score=0,
        created_at=datetime(2026, 10, 30, 8, 15, tzinfo=UTC),
    )
    assert post.created_at.tzinfo is not None


def test_the_documented_query_parameters_reach_http():
    """Symbol, both ends of the seven day window and the token."""
    http = FakeHttp(FakeResponse([]))

    FinnhubCollector(make_settings(), http=http, now=fixed_now).collect_for_asset(ASSET)

    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == API_URL
    assert call["timeout"] == 10
    assert call["params"] == {
        "symbol": "TSLA",
        "from": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"),
        "to": NOW.strftime("%Y-%m-%d"),
        "token": "finnhub-key",
    }


def test_the_post_id_is_the_md5_of_id_and_url_and_stable():
    """Same input, same id; a different article gets a different id."""
    http = FakeHttp(
        FakeResponse([article()]),
        FakeResponse([article()]),
        FakeResponse([article(id=7654321)]),
    )
    collector = FinnhubCollector(make_settings(), http=http, now=fixed_now)

    first = collector.collect_for_asset(ASSET)
    second = collector.collect_for_asset(ASSET)
    other = collector.collect_for_asset(ASSET)

    assert first[0].post_id == post_id_for(ARTICLE_ID, LINK)
    assert first[0].post_id.startswith("finnhub_")
    assert second[0].post_id == first[0].post_id
    assert other[0].post_id == post_id_for(7654321, LINK)
    assert other[0].post_id != first[0].post_id


def test_a_denied_call_yields_no_posts_and_is_not_recorded():
    """The quota check runs first: no HTTP call, no usage row for the denial."""
    limiter = FakeLimiter(allowed=False)
    http = FakeHttp(FakeResponse([article()]))
    collector = FinnhubCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert http.calls == []
    assert limiter.checks == 1
    assert limiter.records == []


def test_an_allowed_call_is_recorded_with_its_status():
    """A successful call is booked as a success with status 200."""
    limiter = FakeLimiter()

    collect_one(article(), limiter=limiter)

    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is True
    assert limiter.records[0]["status_code"] == 200


@pytest.mark.parametrize("status_code", [500, 429])
def test_an_error_status_records_a_failure_without_posts(status_code):
    """A non-200 answer produces no posts and one failed usage row."""
    limiter = FakeLimiter()
    http = FakeHttp(FakeResponse([], status_code=status_code))
    collector = FinnhubCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == status_code


def test_a_network_error_yields_no_posts_and_does_not_raise():
    """A transport failure is logged and booked, never raised."""
    limiter = FakeLimiter()
    http = FakeHttp(requests.ConnectionError("connection refused"))
    collector = FinnhubCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] is None


def test_a_body_that_is_not_a_list_yields_no_posts_and_a_failure():
    """Finnhub answers a dict for errors; that is not an article list."""
    limiter = FakeLimiter()
    http = FakeHttp(FakeResponse({"error": "You don't have access"}))
    collector = FinnhubCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == 200


def test_an_unreadable_body_yields_no_posts_and_records_a_failure():
    """A body that cannot be decoded is a failed call."""
    limiter = FakeLimiter()
    http = FakeHttp(FakeResponse(ValueError("not json")))
    collector = FinnhubCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False


def test_a_missing_timestamp_falls_back_to_the_injected_clock():
    """No ``datetime`` means now, as the clock seam defines it."""
    post = collect_one(article(datetime=None))

    assert post.created_at == NOW
    assert post.created_at.tzinfo == UTC


def test_an_unparseable_timestamp_falls_back_to_the_injected_clock():
    """A timestamp the collector cannot read must not cost the article."""
    post = collect_one(article(datetime="not a timestamp"))

    assert post.created_at == NOW


def test_the_source_falls_back_to_the_literal_finnhub():
    """Without a source name the post still names where it came from."""
    post = collect_one(article(source=None))

    assert post.author == "Finnhub"


def test_content_is_none_when_only_a_headline_is_delivered():
    """There is no summary to store, so ``content`` stays ``None``."""
    post = collect_one(article(summary=None))

    assert post.content is None


def test_long_values_are_truncated_to_the_limits():
    """Author 255, title 500, content 5000, url 500 — the id keeps the full URL."""
    link = "https://example.com/" + "a" * 600
    item = article(url=link, headline="T" * 600, summary="S" * 6000, source="A" * 300)

    post = collect_one(item)

    assert len(post.title) == 500
    assert len(post.content) == 5000
    assert len(post.author) == 255
    assert len(post.url) == 500
    assert post.post_id == post_id_for(ARTICLE_ID, link)


def test_an_article_without_a_url_is_skipped():
    """A post without a link cannot be stored."""
    http = FakeHttp(FakeResponse([article(url=None), article(url="https://example.com/kept")]))
    collector = FinnhubCollector(make_settings(), http=http, now=fixed_now)

    posts = collector.collect_for_asset(ASSET)

    assert [post.url for post in posts] == ["https://example.com/kept"]


def test_without_a_limiter_nothing_is_tracked():
    """``limiter=None`` means no quota bookkeeping, not a skipped call."""
    http = FakeHttp(FakeResponse([article()]))
    collector = FinnhubCollector(make_settings(), http=http, now=fixed_now)

    assert len(collector.collect_for_asset(ASSET)) == 1


def test_the_collector_fits_the_collector_protocol():
    """The class offers what ``Collector`` declares, structurally."""
    collector = FinnhubCollector(make_settings())
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "finnhub"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]
