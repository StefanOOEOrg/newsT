"""Data model of a collection run: the asset asked for and the post returned."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Asset:
    """A tracked asset as the collector sees it.

    Attributes:
        id: Primary key in the ``asset`` table.
        name: Human readable name, e.g. ``Tesla``.
        ticker: Exchange symbol, e.g. ``TSLA``.
        keywords: Search terms that match this asset, already lower-cased by the
            database.
    """

    id: int
    name: str
    ticker: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Post:
    """One article or social post, normalised across all sources.

    Attributes:
        asset_id: Asset the post was collected for.
        source: Source key, e.g. ``rss_google_news`` or ``finnhub``.
        post_id: Stable identifier from the source, unique per post.
        author: Author or feed name; empty string when the source has none.
        title: Headline.
        content: Body text, ``None`` when the source delivers only a headline.
        url: Link to the original.
        score: Source engagement score, ``0`` when the source has none.
        created_at: Publication time, timezone aware.
    """

    asset_id: int
    source: str
    post_id: str
    author: str
    title: str
    content: str | None
    url: str
    score: int
    created_at: datetime
