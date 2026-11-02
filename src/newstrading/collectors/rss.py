"""RSS collectors: one class, one module, no database access."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import feedparser

from newstrading.collectors.models import Asset, Post

logger = logging.getLogger(__name__)

MAX_ENTRIES = 50
MAX_TITLE = 500
MAX_CONTENT = 5000
MAX_AUTHOR = 255
MAX_URL = 500


@dataclass(frozen=True, slots=True)
class Feed:
    """One RSS endpoint.

    Attributes:
        name: Human readable feed name, e.g. ``Google News``; becomes part of the
            source key.
        url: URL template; contains ``{keyword}`` for keyword feeds and ``{ticker}``
            for ticker feeds.
        kind: ``"keyword"`` when the template takes the asset name, ``"ticker"`` when
            it takes the symbol.
    """

    name: str
    url: str
    kind: str


FEEDS: tuple[Feed, ...] = (
    Feed(
        name="Google News",
        url=(
            "https://news.google.com/rss/search?q={keyword}+when:7d" + "&hl=en-US&gl=US&ceid=US:en"
        ),
        kind="keyword",
    ),
    Feed(
        name="Yahoo Finance",
        url="https://finance.yahoo.com/rss/headline?s={ticker}",
        kind="ticker",
    ),
    Feed(
        name="Seeking Alpha",
        url="https://seekingalpha.com/api/sa/combined/{ticker}.xml",
        kind="ticker",
    ),
)


@runtime_checkable
class ParsedFeed(Protocol):
    """What the collector reads from the result of ``feedparser.parse``."""

    entries: Sequence[Any]
    feed: Mapping[str, Any]
    bozo: bool


Parse = Callable[[str], ParsedFeed]
Now = Callable[[], datetime]


def utcnow() -> datetime:
    """Return the current time in UTC with ``tzinfo`` set; the module's only clock."""
    return datetime.now(UTC)


class RSSCollector:
    """Collects posts from the three RSS feeds."""

    name = "rss"

    def __init__(self, parse: Parse = feedparser.parse, now: Now = utcnow) -> None:
        """Store the two seams tests replace.

        Args:
            parse: Called with one URL, returns an object with ``entries``, ``feed`` and ``bozo``
                like ``feedparser.parse`` does.
            now: Returns the current timezone aware UTC time, used when an entry has no date.
        """
        self._parse = parse
        self._now = now

    def collect_for_asset(self, asset: Asset) -> list[Post]:
        """Collect every post the three feeds carry for ``asset``.

        Args:
            asset: The asset to search for.

        Returns:
            The posts of all feeds, in ``FEEDS`` order; duplicates are left to ``PostStore``.
        """
        posts: list[Post] = []
        for feed in FEEDS:
            posts.extend(self._collect_feed(feed, asset))
        return posts

    def _collect_feed(self, feed: Feed, asset: Asset) -> list[Post]:
        """Fetch and convert one feed; a failing feed costs only its own posts."""
        try:
            parsed = self._parse(self._url_for(feed, asset))
        except Exception:
            logger.exception("RSS feed %s could not be fetched", feed.name)
            return []
        if parsed.bozo:
            logger.warning(
                "RSS feed %s reported a parse problem: %s",
                feed.name,
                getattr(parsed, "bozo_exception", None),
            )
        posts: list[Post] = []
        for entry in parsed.entries[:MAX_ENTRIES]:
            try:
                post = self._to_post(entry, parsed, feed, asset)
            except Exception:
                logger.exception("RSS entry from %s could not be converted", feed.name)
                continue
            if post is not None:
                posts.append(post)
        return posts

    @staticmethod
    def _url_for(feed: Feed, asset: Asset) -> str:
        """Render the feed template for ``asset``."""
        if feed.kind == "keyword":
            return feed.url.format(keyword=asset.name.replace(" ", "+"))
        return feed.url.format(ticker=asset.ticker)

    def _to_post(
        self, entry: Mapping[str, Any], parsed: ParsedFeed, feed: Feed, asset: Asset
    ) -> Post | None:
        """Convert one entry, or ``None`` when it has no link."""
        link = _value(entry, "link")
        if not link:
            return None
        content = _value(entry, "summary") or _value(entry, "description")
        author = _value(entry, "author") or parsed.feed.get("title") or feed.name
        return Post(
            asset_id=asset.id,
            source="rss_" + feed.name.lower().replace(" ", "_"),
            post_id="rss_" + hashlib.md5(link.encode()).hexdigest(),
            author=author[:MAX_AUTHOR],
            title=(_value(entry, "title") or "No title")[:MAX_TITLE],
            content=content[:MAX_CONTENT] if content else None,
            url=link[:MAX_URL],
            score=0,
            created_at=self._created_at(entry),
        )

    def _created_at(self, entry: Mapping[str, Any]) -> datetime:
        """Return the entry's publication time, falling back to ``now``."""
        stamp = _value(entry, "published_parsed") or _value(entry, "updated_parsed")
        if not stamp:
            return self._now()
        if isinstance(stamp, datetime):
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
        return datetime(*stamp[:6], tzinfo=UTC)


def _value(entry: Mapping[str, Any], key: str) -> Any:
    """Read ``key`` from a feedparser entry, which is a mapping with attributes."""
    value = entry.get(key) if hasattr(entry, "get") else None
    return value if value is not None else getattr(entry, key, None)
