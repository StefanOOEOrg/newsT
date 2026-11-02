"""Tests for newstrading.collectors.newsapi."""

import hashlib
import inspect
from datetime import UTC, datetime, timedelta

import pytest
import requests

from newstrading.collectors import Collector, NewsAPICollector
from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError, NewsTradingError
from newstrading.rate_limiter import RateLimitDecision

API_URL = "https://newsapi.org/v2/everything"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("electric", "ev", "musk", "ignored"))
LINK = "https://example.com/tesla-recall"


def make_settings(*, newsapi_key: str = "newsapi-key") -> Settings:
    """Build settings with a NewsAPI key unless a test overrides it."""
    return Settings(
        database_url="postgresql://user:pw@localhost:5432/newstrading",
        anthropic_api_key="sk-test",
        newsapi_key=newsapi_key,
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

    def __init__(self, allowed=True, reason="daily quota exhausted"):
        self.decision = RateLimitDecision(allowed=allowed, reason=reason, wait_seconds=0)
        self.checks = 0
        self.records = []

    def can_make_request(self):
        self.checks += 1
        return self.decision

    def record_request(self, **kwargs):
        self.records.append(kwargs)


def article(**overrides):
    """One article in the shape NewsAPI returns it."""
    values = {
        "author": "Jane Doe",
        "title": "Tesla recalls Cybertrucks",
        "description": "Body text",
        "url": LINK,
        "publishedAt": "2026-10-30T08:15:00Z",
        "source": {"id": "reuters", "name": "Reuters"},
    }
    values.update(overrides)
    return values


def payload(*articles, status="ok"):
    """A NewsAPI response body."""
    return {"status": status, "totalResults": len(articles), "articles": list(articles)}


def collect_one(item, *, limiter=None, now=fixed_now):
    """Collect a single article and return the one post it must produce."""
    http = FakeHttp(FakeResponse(payload(item)))
    collector = NewsAPICollector(make_settings(), http=http, limiter=limiter, now=now)
    posts = collector.collect_for_asset(ASSET)
    assert len(posts) == 1
    return posts[0]


def post_id_for(url):
    """The id the documented scheme derives from a URL."""
    return "newsapi_" + hashlib.md5(url.encode()).hexdigest()


def test_a_missing_key_fails_in_the_constructor():
    """Without a key the collector cannot work, so it refuses to exist."""
    with pytest.raises(CollectorConfigError) as error:
        NewsAPICollector(make_settings(newsapi_key=""))

    assert "NEWSAPI_KEY" in str(error.value)
    assert isinstance(error.value, NewsTradingError)


def test_a_present_key_builds_the_collector():
    """The key is all the constructor needs."""
    collector = NewsAPICollector(make_settings())

    assert collector.name == "newsapi"


def test_one_article_becomes_the_expected_post():
    """Every field of the legacy mapping ends up in the ``Post``."""
    post = collect_one(article())

    assert post == Post(
        asset_id=7,
        source="newsapi",
        post_id=post_id_for(LINK),
        author="Jane Doe",
        title="Tesla recalls Cybertrucks",
        content="Body text",
        url=LINK,
        score=0,
        created_at=datetime(2026, 10, 30, 8, 15, tzinfo=UTC),
    )
    assert post.created_at.tzinfo is not None


def test_the_documented_query_parameters_reach_http():
    """Query, key, language, order, the seven day window and the page size."""
    http = FakeHttp(FakeResponse(payload()))

    NewsAPICollector(make_settings(), http=http, now=fixed_now).collect_for_asset(ASSET)

    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == API_URL
    assert call["timeout"] == 10
    assert call["params"] == {
        "q": '"Tesla" OR "TSLA" OR "electric" OR "ev" OR "musk"',
        "apiKey": "newsapi-key",
        "language": "en",
        "sortBy": "publishedAt",
        "from": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"),
        "pageSize": 100,
    }


def test_the_date_window_is_the_last_seven_days():
    """The window follows the injected clock instead of the wall clock."""
    http = FakeHttp(FakeResponse(payload()))
    collector = NewsAPICollector(make_settings(), http=http, now=fixed_now)

    collector.collect_for_asset(ASSET)

    assert http.calls[0]["params"]["from"] == "2026-10-26"


def test_the_post_id_is_the_md5_of_the_url_and_stable():
    """Same input, same id; a different article gets a different id."""
    http = FakeHttp(
        FakeResponse(payload(article())),
        FakeResponse(payload(article())),
        FakeResponse(payload(article(url="https://example.com/other"))),
    )
    collector = NewsAPICollector(make_settings(), http=http, now=fixed_now)

    first = collector.collect_for_asset(ASSET)
    second = collector.collect_for_asset(ASSET)
    other = collector.collect_for_asset(ASSET)

    assert first[0].post_id == post_id_for(LINK)
    assert first[0].post_id.startswith("newsapi_")
    assert second[0].post_id == first[0].post_id
    assert other[0].post_id == post_id_for("https://example.com/other")
    assert other[0].post_id != first[0].post_id


def test_a_denied_call_yields_no_posts_and_is_not_recorded():
    """The quota check runs first: no HTTP call, no usage row for the denial."""
    limiter = FakeLimiter(allowed=False)
    http = FakeHttp(FakeResponse(payload(article())))
    collector = NewsAPICollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

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
    collector = NewsAPICollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == status_code


def test_a_network_error_yields_no_posts_and_does_not_raise():
    """A transport failure is logged and booked, never raised."""
    limiter = FakeLimiter()
    http = FakeHttp(requests.ConnectionError("connection refused"))
    collector = NewsAPICollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] is None


def test_an_unreadable_body_yields_no_posts_and_records_a_failure():
    """A body that is not the documented payload is a failed call."""
    limiter = FakeLimiter()
    http = FakeHttp(FakeResponse(ValueError("not json")))
    collector = NewsAPICollector(make_settings(), http=http, limiter=limiter, now=fixed_now)

    assert collector.collect_for_asset(ASSET) == []
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == 200


def test_an_error_status_inside_the_body_yields_no_posts():
    """``status: error`` is an API refusal, not a news day without articles."""
    posts = None
    http = FakeHttp(FakeResponse({"status": "error", "message": "apiKeyInvalid"}))
    collector = NewsAPICollector(make_settings(), http=http, now=fixed_now)

    posts = collector.collect_for_asset(ASSET)

    assert posts == []


def test_a_missing_date_falls_back_to_the_injected_clock():
    """No ``publishedAt`` means now, as the clock seam defines it."""
    post = collect_one(article(publishedAt=None))

    assert post.created_at == NOW
    assert post.created_at.tzinfo == UTC


def test_an_unparseable_date_falls_back_to_the_injected_clock():
    """A timestamp the collector cannot read must not cost the article."""
    post = collect_one(article(publishedAt="yesterday"))

    assert post.created_at == NOW


def test_the_author_falls_back_to_the_source_name_then_to_unknown():
    """``author`` beats ``source.name``, which beats the literal ``Unknown``."""
    named = collect_one(article(author=None, source={"name": "Reuters"}))
    unknown = collect_one(article(author=None, source=None))

    assert named.author == "Reuters"
    assert unknown.author == "Unknown"


def test_content_is_none_when_only_a_headline_is_delivered():
    """There is no body to store, so ``content`` stays ``None``."""
    post = collect_one(article(description=None, content=None))

    assert post.content is None


def test_the_content_falls_back_from_description_to_content():
    """``description`` first, then ``content``, as in the legacy collector."""
    post = collect_one(article(description=None, content="Full text"))

    assert post.content == "Full text"


def test_long_values_are_truncated_to_the_limits():
    """Author 255, title 500, content 5000, url 500 — the id keeps the full URL."""
    link = "https://example.com/" + "a" * 600
    item = article(title="T" * 600, description="S" * 6000, author="A" * 300, url=link)

    post = collect_one(item)

    assert len(post.title) == 500
    assert len(post.content) == 5000
    assert len(post.author) == 255
    assert len(post.url) == 500
    assert post.post_id == post_id_for(link)


def test_an_article_without_a_url_is_skipped():
    """A post without a link cannot be stored."""
    http = FakeHttp(
        FakeResponse(payload(article(url=None), article(url="https://example.com/kept")))
    )
    collector = NewsAPICollector(make_settings(), http=http, now=fixed_now)

    posts = collector.collect_for_asset(ASSET)

    assert [post.url for post in posts] == ["https://example.com/kept"]


def test_a_broken_article_is_skipped_and_the_rest_of_the_body_survives():
    """A malformed entry is logged, the rest of the response still becomes posts."""
    broken = article(title=12345)
    good = article(title="Good", url="https://example.com/good")
    http = FakeHttp(FakeResponse(payload(broken, good)))
    collector = NewsAPICollector(make_settings(), http=http, now=fixed_now)

    posts = collector.collect_for_asset(ASSET)

    assert [post.title for post in posts] == ["Good"]


def test_without_a_limiter_nothing_is_tracked():
    """``limiter=None`` means no quota bookkeeping, not a skipped call."""
    http = FakeHttp(FakeResponse(payload(article())))
    collector = NewsAPICollector(make_settings(), http=http, now=fixed_now)

    assert len(collector.collect_for_asset(ASSET)) == 1


def test_the_collector_fits_the_collector_protocol():
    """The class offers what ``Collector`` declares, structurally."""
    collector = NewsAPICollector(make_settings())
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "newsapi"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]
