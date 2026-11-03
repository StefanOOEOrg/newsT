"""Tests for newstrading.collectors.alphavantage."""

import hashlib
import inspect
from datetime import UTC, datetime

import pytest
import requests

from newstrading.collectors import AlphaVantageCollector, Collector
from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError, NewsTradingError
from newstrading.rate_limiter import RateLimitDecision

API_URL = "https://www.alphavantage.co/query"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("tesla",))
LINK = "https://example.com/tesla-prices"


def make_settings(*, alphavantage_api_key: str = "alpha-key") -> Settings:
    """Build settings with an Alpha Vantage key unless a test overrides it."""
    return Settings(
        database_url="postgresql://user:pw@localhost:5432/newstrading",
        alphavantage_api_key=alphavantage_api_key,
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

    def __init__(self, allowed=True, reason="25 daily calls used"):
        self.decision = RateLimitDecision(allowed=allowed, reason=reason, wait_seconds=0)
        self.checks = 0
        self.records = []

    def can_make_request(self):
        self.checks += 1
        return self.decision

    def record_request(self, **kwargs):
        self.records.append(kwargs)


def article(**overrides):
    """One feed item in the shape Alpha Vantage returns it."""
    values = {
        "title": "Tesla raises prices",
        "url": LINK,
        "summary": "Body text",
        "authors": ["Jane Doe", "John Roe"],
        "time_published": "20261030T081500",
        "ticker_sentiment": [
            {"ticker": "AAPL", "ticker_sentiment_score": "-0.6"},
            {"ticker": "TSLA", "ticker_sentiment_score": "0.35"},
        ],
    }
    values.update(overrides)
    return values


def payload(*articles):
    """A NEWS_SENTIMENT response body."""
    return {"items": str(len(articles)), "feed": list(articles)}


def collect_one(item, *, limiter=None, now=fixed_now):
    """Collect a single article and return the one post it must produce."""
    http = FakeHttp(FakeResponse(payload(item)))
    collector = AlphaVantageCollector(make_settings(), http=http, limiter=limiter, now=now)
    posts = collector.collect_for_asset(ASSET)
    assert len(posts) == 1
    return posts[0]


def post_id_for(url, title):
    """The id the documented scheme derives from the URL and the title."""
    return "alphavantage_" + hashlib.md5(f"{url}:{title}".encode()).hexdigest()


def test_a_missing_key_fails_in_the_constructor():
    """Without a key the collector cannot work, so it refuses to exist."""
    with pytest.raises(CollectorConfigError) as error:
        AlphaVantageCollector(make_settings(alphavantage_api_key=""))

    assert "ALPHAVANTAGE_API_KEY" in str(error.value)
    assert isinstance(error.value, NewsTradingError)


def test_a_present_key_builds_the_collector():
    """The key is all the constructor needs."""
    collector = AlphaVantageCollector(make_settings())

    assert collector.name == "alphavantage"


def test_one_article_becomes_the_expected_post():
    """Every field of the legacy mapping ends up in the ``Post``."""
    post = collect_one(article())

    assert post == Post(
        asset_id=7,
        source="alphavantage",
        post_id=post_id_for(LINK, "Tesla raises prices"),
        author="Jane Doe, John Roe",
        title="Tesla raises prices",
        content="Body text",
        url=LINK,
        score=67,
        created_at=datetime(2026, 10, 30, 8, 15, tzinfo=UTC),
    )
    assert post.created_at.tzinfo is not None


def test_the_documented_query_parameters_reach_http():
    """Function, tickers, key and the item limit of the legacy call."""
    http = FakeHttp(FakeResponse(payload()))

    AlphaVantageCollector(make_settings(), http=http, now=fixed_now).collect_for_asset(ASSET)

    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == API_URL
    assert call["timeout"] == 15
    assert call["params"] == {
        "function": "NEWS_SENTIMENT",
        "tickers": "TSLA",
        "apikey": "alpha-key",
        "limit": 50,
    }


def test_the_post_id_is_the_md5_of_url_and_title_and_stable():
    """Same input, same id; a different article gets a different id."""
    http = FakeHttp(
        FakeResponse(payload(article())),
        FakeResponse(payload(article())),
        FakeResponse(payload(article(title="Other headline"))),
    )
    collector = AlphaVantageCollector(make_settings(), http=http, now=fixed_now)

    first = collector.collect_for_asset(ASSET)
    second = collector.collect_for_asset(ASSET)
    other = collector.collect_for_asset(ASSET)

    assert first[0].post_id == post_id_for(LINK, "Tesla raises prices")
    assert first[0].post_id.startswith("alphavantage_")
    assert second[0].post_id == first[0].post_id
    assert other[0].post_id == post_id_for(LINK, "Other headline")
    assert other[0].post_id != first[0].post_id


def test_a_denied_call_yields_no_posts_and_is_not_recorded():
    """The quota check runs first: no HTTP call, no usage row for the denial."""
    limiter = FakeLimiter(allowed=False)
    http = FakeHttp(FakeResponse(payload(article())))
    collector = AlphaVantageCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

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
    http = FakeHttp(FakeResponse({}, status_code=status_code))
    collector = AlphaVantageCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == status_code


def test_a_network_error_yields_no_posts_and_does_not_raise():
    """A transport failure is logged and booked, never raised."""
    limiter = FakeLimiter()
    http = FakeHttp(requests.ConnectionError("connection refused"))
    collector = AlphaVantageCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"Error Message": "Invalid API call."},
        {"Note": "Thank you for using Alpha Vantage! 25 requests per day."},
        ValueError("not json"),
    ],
)
def test_an_unreadable_body_yields_no_posts_and_records_a_failure(body):
    """An error note or a body that cannot be decoded is a failed call."""
    limiter = FakeLimiter()
    http = FakeHttp(FakeResponse(body))
    collector = AlphaVantageCollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False


def test_a_missing_date_falls_back_to_the_injected_clock():
    """No ``time_published`` means now, as the clock seam defines it."""
    post = collect_one(article(time_published=None))

    assert post.created_at == NOW
    assert post.created_at.tzinfo == UTC


def test_an_unparseable_date_falls_back_to_the_injected_clock():
    """A timestamp the collector cannot read must not cost the article."""
    post = collect_one(article(time_published="30.10.2026"))

    assert post.created_at == NOW


def test_the_score_is_the_sentiment_of_the_asset_ticker():
    """A sentiment of ``s`` becomes ``int((s + 1) * 50)``, as in the legacy code."""
    positive = collect_one(article())
    negative = collect_one(
        article(ticker_sentiment=[{"ticker": "TSLA", "ticker_sentiment_score": "-0.6"}])
    )
    neutral = collect_one(article(ticker_sentiment=[]))

    assert positive.score == 67
    assert negative.score == 20
    assert neutral.score == 50


def test_the_author_is_the_joined_author_list_with_a_fallback():
    """Authors are joined with ``, ``; without any, the source name is used."""
    without_authors = collect_one(article(authors=None))
    single = collect_one(article(authors=["Jane Doe"]))
    many = collect_one(article(authors=["A" * 200, "B" * 200]))

    assert without_authors.author == "Alpha Vantage"
    assert single.author == "Jane Doe"
    assert len(many.author) == 255


def test_content_is_none_when_only_a_headline_is_delivered():
    """There is no summary to store, so ``content`` stays ``None``."""
    post = collect_one(article(summary=None))

    assert post.content is None


def test_a_missing_url_falls_back_to_the_documented_source_link():
    """The legacy fallback link keeps the post reachable."""
    post = collect_one(article(url=None))

    assert post.url == "https://alphavantage.co/news/" + post_id_for("", "Tesla raises prices")


def test_long_values_are_truncated_to_the_limits():
    """Author 255, title 500, content 5000, url 500 — the id keeps the full URL."""
    link = "https://example.com/" + "a" * 600
    item = article(url=link, title="T" * 600, summary="S" * 6000)

    post = collect_one(item)

    assert len(post.title) == 500
    assert len(post.content) == 5000
    assert len(post.url) == 500
    assert post.post_id == post_id_for(link, "T" * 600)


def test_an_article_without_a_title_is_skipped():
    """A post without a headline cannot be stored."""
    http = FakeHttp(
        FakeResponse(payload(article(title=None), article(url="https://example.com/kept")))
    )
    collector = AlphaVantageCollector(make_settings(), http=http, now=fixed_now)

    posts = collector.collect_for_asset(ASSET)

    assert [post.url for post in posts] == ["https://example.com/kept"]


def test_without_a_limiter_nothing_is_tracked():
    """``limiter=None`` means no quota bookkeeping, not a skipped call."""
    http = FakeHttp(FakeResponse(payload(article())))
    collector = AlphaVantageCollector(make_settings(), http=http, now=fixed_now)

    assert len(collector.collect_for_asset(ASSET)) == 1


def test_the_collector_fits_the_collector_protocol():
    """The class offers what ``Collector`` declares, structurally."""
    collector = AlphaVantageCollector(make_settings())
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "alphavantage"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]
