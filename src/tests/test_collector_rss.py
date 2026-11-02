"""Tests for newstrading.collectors.rss."""

import hashlib
import inspect
from datetime import UTC, datetime
from time import struct_time

from newstrading.collectors import Collector, Feed, RSSCollector
from newstrading.collectors.models import Asset, Post
from newstrading.collectors.rss import FEEDS, utcnow

GOOGLE_TEMPLATE = (
    "https://news.google.com/rss/search?q={keyword}+when:7d" + "&hl=en-US&gl=US&ceid=US:en"
)
YAHOO_TEMPLATE = "https://finance.yahoo.com/rss/headline?s={ticker}"
SEEKING_TEMPLATE = "https://seekingalpha.com/api/sa/combined/{ticker}.xml"

ASSET = Asset(id=7, name="Tesla Inc", ticker="TSLA", keywords=("tesla",))
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
PUBLISHED = struct_time((2026, 10, 30, 8, 15, 0, 3, 303, 0))
UPDATED = struct_time((2026, 10, 31, 7, 45, 0, 4, 304, 0))


class Entry(dict):
    """feedparser's ``FeedParserDict``: keys are readable as attributes too."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


class FakeFeed:
    """The object ``feedparser.parse`` returns."""

    def __init__(self, entries=(), title=None, bozo=False):
        self.entries = list(entries)
        self.feed = {"title": title} if title else {}
        self.bozo = bozo


class ScriptedParse:
    """Parse seam: one prepared result per call, in order; records the URLs."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        result = self._results[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


def fixed_now():
    """Clock seam: a constant, timezone aware UTC time."""
    return NOW


def post_id_for(link):
    """The id the legacy collector derived from a link."""
    return "rss_" + hashlib.md5(link.encode()).hexdigest()


def collect_entries(entries, feed_title=None, bozo=False):
    """Collect ``entries`` from the first feed; the other two feeds stay empty."""
    parse = ScriptedParse(FakeFeed(entries, title=feed_title, bozo=bozo), FakeFeed(), FakeFeed())
    return RSSCollector(parse=parse, now=fixed_now).collect_for_asset(ASSET)


def collect_one(entry, feed_title=None, bozo=False):
    """Collect a single entry from the first feed."""
    return collect_entries([entry], feed_title=feed_title, bozo=bozo)


def collect_single(entry, feed_title=None, bozo=False):
    """Collect one entry and return the one post it must produce."""
    posts = collect_one(entry, feed_title=feed_title, bozo=bozo)
    assert len(posts) == 1
    return posts[0]


def test_feeds_are_the_three_legacy_endpoints():
    """The three legacy feeds keep their names, templates and order."""
    assert [feed.name for feed in FEEDS] == ["Google News", "Yahoo Finance", "Seeking Alpha"]
    assert [feed.kind for feed in FEEDS] == ["keyword", "ticker", "ticker"]
    assert [feed.url for feed in FEEDS] == [GOOGLE_TEMPLATE, YAHOO_TEMPLATE, SEEKING_TEMPLATE]


def test_a_feed_is_a_frozen_value():
    """Feeds are configuration, not state."""
    feed = FEEDS[0]

    assert isinstance(feed, Feed)
    try:
        feed.name = "mutated"
    except AttributeError:
        pass
    else:  # pragma: no cover - only runs if the dataclass stopped being frozen
        raise AssertionError("Feed must be frozen")


def test_every_feed_is_asked_once_in_order_with_the_name_or_ticker():
    """Keyword feeds get the asset name with ``+`` for spaces, ticker feeds the symbol."""
    parse = ScriptedParse(FakeFeed(), FakeFeed(), FakeFeed())

    RSSCollector(parse=parse, now=fixed_now).collect_for_asset(ASSET)

    assert parse.calls == [
        GOOGLE_TEMPLATE.format(keyword="Tesla+Inc"),
        YAHOO_TEMPLATE.format(ticker="TSLA"),
        SEEKING_TEMPLATE.format(ticker="TSLA"),
    ]


def test_one_entry_becomes_one_post():
    """Every field of the behaviour table ends up in the ``Post``."""
    link = "https://example.com/tesla-recall"
    entry = Entry(
        title="Tesla recalls Cybertrucks",
        link=link,
        summary="Body text",
        author="Jane Doe",
        published_parsed=PUBLISHED,
    )

    posts = collect_one(entry)

    assert posts == [
        Post(
            asset_id=7,
            source="rss_google_news",
            post_id=post_id_for(link),
            author="Jane Doe",
            title="Tesla recalls Cybertrucks",
            content="Body text",
            url=link,
            score=0,
            created_at=datetime(2026, 10, 30, 8, 15, tzinfo=UTC),
        )
    ]


def test_post_id_is_the_md5_of_the_link_and_stable_across_calls():
    """Same link, same id — that is what makes the database unique key work."""
    link = "https://example.com/stable"
    entry = Entry(title="Stable", link=link)
    parse = ScriptedParse(
        FakeFeed([entry]),
        FakeFeed(),
        FakeFeed(),
        FakeFeed([entry]),
        FakeFeed(),
        FakeFeed(),
    )
    collector = RSSCollector(parse=parse, now=fixed_now)

    first = collector.collect_for_asset(ASSET)
    second = collector.collect_for_asset(ASSET)

    assert first[0].post_id == post_id_for(link)
    assert second[0].post_id == first[0].post_id


def test_an_entry_without_a_link_is_skipped_and_the_rest_survives():
    """An entry without a link cannot be stored, so it is dropped."""
    kept = Entry(title="Kept", link="https://example.com/kept")

    posts = collect_entries([Entry(title="No link"), kept])

    assert [post.title for post in posts] == ["Kept"]


def test_empty_feeds_return_no_posts():
    """Nothing parsed, nothing returned, no exception."""
    assert collect_entries([]) == []


def test_missing_title_summary_and_date_fall_back():
    """Title, content and date have defined fallbacks."""
    link = "https://example.com/bare"

    posts = collect_one(Entry(link=link))

    assert len(posts) == 1
    assert posts[0].title == "No title"
    assert posts[0].content is None
    assert posts[0].created_at == NOW
    assert posts[0].created_at.tzinfo is not None
    assert posts[0].author == "Google News"


def test_the_feed_title_is_the_author_fallback():
    """The feed's own title wins over its configured name."""
    post = collect_single(Entry(link="https://example.com/a"), feed_title="Google News - Search")

    assert post.author == "Google News - Search"


def test_description_is_used_when_the_summary_is_missing_or_empty():
    """``summary`` first, then ``description``; empty means missing."""
    missing = collect_single(Entry(link="https://example.com/a", description="From description"))
    empty = collect_single(Entry(link="https://example.com/b", summary="", description="Fallback"))

    assert missing.content == "From description"
    assert empty.content == "Fallback"


def test_published_parsed_wins_over_updated_parsed():
    """A publication date beats a modification date."""
    entry = Entry(
        link="https://example.com/a",
        published_parsed=PUBLISHED,
        updated_parsed=UPDATED,
    )

    post = collect_single(entry)

    assert post.created_at == datetime(2026, 10, 30, 8, 15, tzinfo=UTC)


def test_updated_parsed_is_used_when_published_is_missing():
    """Without a publication date the update date is used."""
    entry = Entry(link="https://example.com/a", updated_parsed=UPDATED)

    post = collect_single(entry)

    assert post.created_at == datetime(2026, 10, 31, 7, 45, tzinfo=UTC)


def test_long_values_are_truncated_to_the_limits():
    """Title 500, content 5000, author 255, url 500 — the id keeps the full link."""
    link = "https://example.com/" + "a" * 600
    entry = Entry(title="T" * 600, link=link, summary="S" * 6000, author="A" * 300)

    post = collect_single(entry)

    assert len(post.title) == 500
    assert len(post.content) == 5000
    assert len(post.author) == 255
    assert len(post.url) == 500
    assert post.url == link[:500]
    assert post.post_id == post_id_for(link)


def test_a_bozo_feed_still_yields_its_entries():
    """A parser warning is not fatal."""
    posts = collect_one(Entry(title="X", link="https://example.com/x"), bozo=True)

    assert [post.title for post in posts] == ["X"]


def test_a_failing_feed_is_skipped_and_other_feeds_still_report():
    """One broken feed must not lose the entries of the other two."""
    first = Entry(title="First", link="https://example.com/first")
    third = Entry(title="Third", link="https://example.com/third")
    parse = ScriptedParse(FakeFeed([first]), RuntimeError("feed is down"), FakeFeed([third]))

    posts = RSSCollector(parse=parse, now=fixed_now).collect_for_asset(ASSET)

    assert [post.title for post in posts] == ["First", "Third"]
    assert [post.source for post in posts] == ["rss_google_news", "rss_seeking_alpha"]


def test_a_broken_entry_is_skipped_and_the_rest_of_the_feed_survives():
    """A date that cannot be converted only costs that one entry."""
    broken = Entry(link="https://example.com/bad", published_parsed=(2026, 10))
    good = Entry(title="Good", link="https://example.com/good")

    posts = collect_entries([broken, good])

    assert [post.title for post in posts] == ["Good"]


def test_only_the_first_fifty_entries_are_read():
    """A feed with 60 entries contributes its first 50."""
    entries = [Entry(link=f"https://example.com/{index}", title=f"T{index}") for index in range(60)]

    posts = collect_entries(entries)

    assert len(posts) == 50
    assert [post.title for post in posts] == [f"T{index}" for index in range(50)]


def test_utcnow_returns_an_aware_utc_time():
    """``utcnow`` is the module's clock and is timezone aware."""
    before = datetime.now(UTC)
    value = utcnow()
    after = datetime.now(UTC)

    assert value.tzinfo is not None
    assert before <= value <= after


def test_the_collector_fits_the_collector_protocol():
    """The class offers what ``Collector`` declares.

    ``Collector`` is a plain :class:`typing.Protocol` without ``@runtime_checkable``,
    so ``isinstance(collector, Collector)`` raises ``TypeError``; the declared members
    are checked structurally instead.
    """
    parse = ScriptedParse(FakeFeed(), FakeFeed(), FakeFeed())
    collector = RSSCollector(parse=parse, now=fixed_now)
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "rss"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]
