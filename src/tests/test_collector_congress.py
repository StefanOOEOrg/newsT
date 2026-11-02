"""Tests for newstrading.collectors.congress."""

import hashlib
import inspect
from datetime import UTC, datetime

import pytest
import requests

from newstrading.collectors import Collector, CongressionalTradesCollector
from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.rate_limiter import RateLimitDecision

PUBLIC_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/all_transactions.json"
PREMIUM_URL = "https://premium.example.com/congress/trades"
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("tesla",))
TRADE_DATE = "2026-10-28"
POLITICIAN = "Jane Doe"
AMOUNT = "$1,001 - $15,000"


def make_settings(*, api_key: str = "", api_url: str = "") -> Settings:
    """Build settings with the congressional trades source configured as asked."""
    return Settings(
        database_url="postgresql://user:***@localhost:5432/newstrading",
        anthropic_api_key="sk-test",
        congress_trades_api_key=api_key,
        congress_trades_api_url=api_url,
    )


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
            {
                "url": url,
                "params": kwargs.get("params"),
                "headers": kwargs.get("headers"),
                "timeout": kwargs.get("timeout"),
            }
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


def trade(**overrides):
    """One trade in the shape House Stock Watcher returns it."""
    values = {
        "representative": POLITICIAN,
        "ticker": "TSLA",
        "type": "purchase",
        "amount": AMOUNT,
        "transaction_date": TRADE_DATE,
        "disclosure_date": "2026-10-30",
        "asset_description": "Tesla, Inc. (TSLA)",
        "party": "D",
        "district": "CA12",
    }
    values.update(overrides)
    return values


def post_id_for(politician, ticker, transaction_date, transaction_type):
    """The id the documented scheme derives from the trade's identity."""
    key = f"{politician}:{ticker}:{transaction_date}:{transaction_type}"
    return "congress_" + hashlib.md5(key.encode()).hexdigest()


def collect_one(item, *, limiter=None, settings=None, http=None):
    """Collect a single public trade and return the one post it must produce."""
    http = http or FakeHttp(FakeResponse([item]))
    collector = CongressionalTradesCollector(
        settings or make_settings(), http=http, limiter=limiter
    )
    posts = collector.collect_for_asset(ASSET)
    assert len(posts) == 1
    return posts[0]


def test_the_public_source_is_asked_when_no_premium_key_is_configured():
    """Without a premium key the public feed is the only source — not an error."""
    http = FakeHttp(FakeResponse([trade()]))

    posts = CongressionalTradesCollector(make_settings(), http=http).collect_for_asset(ASSET)

    assert len(posts) == 1
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == PUBLIC_URL
    assert call["params"] is None
    assert call["timeout"] == 30
    assert "NewsTradingBot" in call["headers"]["User-Agent"]


def test_one_trade_becomes_the_expected_post():
    """Every field of the legacy mapping ends up in the ``Post``."""
    post = collect_one(trade())

    assert isinstance(post, Post)
    assert post.asset_id == 7
    assert post.source == "congressional_trades"
    assert post.author == "Jane Doe (House)"
    assert post.title == f"🟢 {POLITICIAN} (D-CA12) Purchase $TSLA - {AMOUNT}"
    assert "Politician: Jane Doe" in post.content
    assert "Party: D" in post.content
    assert "Chamber: House" in post.content
    assert "Ticker: $TSLA" in post.content
    assert "Transaction Type: Purchase" in post.content
    assert f"Amount Range: {AMOUNT}" in post.content
    assert "Asset: Tesla, Inc. (TSLA)" in post.content
    assert "Source: house_stock_watcher" in post.content
    assert post.url == "https://www.capitoltrades.com/trades?politician=Jane-Doe"
    assert post.score == 100
    assert post.created_at == datetime(2026, 10, 28, tzinfo=UTC)


def test_a_sale_gets_the_sale_icon():
    """The legacy title marks a sale with the red icon."""
    post = collect_one(trade(type="sale (partial)"))

    assert post.title.startswith("🔴")
    assert "Sale (Partial)" in post.title


def test_the_post_id_follows_the_documented_scheme_and_is_stable():
    """Same trade, same id; a different transaction type gets a different id."""
    http = FakeHttp(FakeResponse([trade()]), FakeResponse([trade()]))
    collector = CongressionalTradesCollector(make_settings(), http=http)

    first = collector.collect_for_asset(ASSET)
    second = collector.collect_for_asset(ASSET)
    other = collect_one(trade(type="sale (partial)"))

    assert first[0].post_id == post_id_for(POLITICIAN, "TSLA", TRADE_DATE, "purchase")
    assert first[0].post_id.startswith("congress_")
    assert second[0].post_id == first[0].post_id
    assert other.post_id != first[0].post_id


def test_the_premium_query_parameters_and_date_window_reach_http():
    """The configured premium endpoint gets the legacy parameters and the bearer key."""
    http = FakeHttp(FakeResponse({"data": [trade()]}))
    settings = make_settings(api_key="premium-key", api_url=PREMIUM_URL)

    posts = CongressionalTradesCollector(settings, http=http).collect_for_asset(ASSET)

    assert len(posts) == 1
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == PREMIUM_URL
    assert call["params"] == {"limit": 100, "days_back": 7}
    assert call["headers"] == {"Authorization": "Bearer premium-key"}
    assert call["timeout"] == 30


def test_a_premium_call_without_rows_falls_back_to_the_public_source():
    """The public feed is the fallback, as in the legacy collector."""
    http = FakeHttp(FakeResponse({"data": []}), FakeResponse([trade()]))
    settings = make_settings(api_key="premium-key", api_url=PREMIUM_URL)

    posts = CongressionalTradesCollector(settings, http=http).collect_for_asset(ASSET)

    assert len(posts) == 1
    assert [call["url"] for call in http.calls] == [PREMIUM_URL, PUBLIC_URL]


def test_a_failed_premium_call_falls_back_to_the_public_source():
    """A broken premium source must not cost the public data."""
    http = FakeHttp(FakeResponse([], status_code=500), FakeResponse([trade()]))
    settings = make_settings(api_key="premium-key", api_url=PREMIUM_URL)

    posts = CongressionalTradesCollector(settings, http=http).collect_for_asset(ASSET)

    assert len(posts) == 1
    assert http.calls[1]["url"] == PUBLIC_URL


def test_only_trades_of_the_requested_ticker_become_posts():
    """Rows for other symbols are dropped before the mapping."""
    http = FakeHttp(FakeResponse([trade(), trade(ticker="AAPL", asset_description="Apple (AAPL)")]))

    posts = CongressionalTradesCollector(make_settings(), http=http).collect_for_asset(ASSET)

    assert [post.title for post in posts] == [f"🟢 {POLITICIAN} (D-CA12) Purchase $TSLA - {AMOUNT}"]


def test_a_row_without_a_readable_ticker_is_skipped():
    """A trade without a symbol cannot be mapped to an asset."""
    http = FakeHttp(FakeResponse([trade(ticker="", asset_description="")]))

    assert CongressionalTradesCollector(make_settings(), http=http).collect_for_asset(ASSET) == []


def test_a_missing_transaction_date_falls_back_to_now_in_utc():
    """A post without a readable date is still a post, stamped with the current time."""
    post = collect_one(trade(transaction_date=None))

    assert post.created_at.tzinfo is not None
    assert post.created_at.utcoffset().total_seconds() == 0
    assert abs((datetime.now(UTC) - post.created_at).total_seconds()) < 60


@pytest.mark.parametrize("status_code", [500, 429])
def test_an_error_status_yields_no_posts_and_records_a_failure(status_code):
    """A non-200 answer produces no posts and one failed usage row."""
    limiter = FakeLimiter()
    http = FakeHttp(FakeResponse([], status_code=status_code))
    collector = CongressionalTradesCollector(make_settings(), http=http, limiter=limiter)

    assert collector.collect_for_asset(ASSET) == []
    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == status_code


def test_a_network_error_yields_no_posts_and_does_not_raise():
    """A transport failure is logged and booked, never raised."""
    limiter = FakeLimiter()
    http = FakeHttp(requests.ConnectionError("connection refused"))
    collector = CongressionalTradesCollector(make_settings(), http=http, limiter=limiter)

    assert collector.collect_for_asset(ASSET) == []
    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] is None


def test_a_denied_call_yields_no_posts_and_is_not_recorded():
    """The quota check runs first: no HTTP call, no usage row for the denial."""
    limiter = FakeLimiter(allowed=False)
    http = FakeHttp(FakeResponse([trade()]))
    collector = CongressionalTradesCollector(make_settings(), http=http, limiter=limiter)

    assert collector.collect_for_asset(ASSET) == []
    assert http.calls == []
    assert limiter.checks == 1
    assert limiter.records == []


def test_an_allowed_call_is_recorded_with_its_status():
    """A successful call is booked as a success with status 200."""
    limiter = FakeLimiter()

    collect_one(trade(), limiter=limiter)

    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is True
    assert limiter.records[0]["status_code"] == 200


def test_without_a_limiter_nothing_is_tracked():
    """``limiter=None`` means no quota bookkeeping, not a skipped call."""
    http = FakeHttp(FakeResponse([trade()]))
    collector = CongressionalTradesCollector(make_settings(), http=http)

    assert len(collector.collect_for_asset(ASSET)) == 1


def test_the_collector_fits_the_collector_protocol():
    """The class offers what ``Collector`` declares, structurally."""
    collector = CongressionalTradesCollector(make_settings())
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "congressional_trades"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]
