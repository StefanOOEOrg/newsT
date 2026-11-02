"""Alpha Vantage collector: HTTP in, ``Post`` objects out, no database access."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import requests

from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError
from newstrading.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

API_URL = "https://www.alphavantage.co/query"
TIMEOUT_SECONDS = 15
ITEM_LIMIT = 50
STAMP_FORMAT = "%Y%m%dT%H%M%S"
FALLBACK_URL = "https://alphavantage.co/news/"
MAX_AUTHOR = 255
MAX_TITLE = 500
MAX_CONTENT = 5000
MAX_URL = 500


class HttpResponse(Protocol):
    """What the collector reads from a ``requests.Response``."""

    status_code: int
    text: str

    def json(self) -> Any:
        """Return the decoded body."""


Http = Callable[..., HttpResponse]
Now = Callable[[], datetime]


def utcnow() -> datetime:
    """Return the current time in UTC with ``tzinfo`` set; the module's only clock."""
    return datetime.now(UTC)


def _post_id(url: str, title: str) -> str:
    """Derive the stable, documented post id from the URL and the title."""
    return "alphavantage_" + hashlib.md5(f"{url}:{title}".encode()).hexdigest()


def _score(article: dict[str, Any], ticker: str) -> int:
    """Map the sentiment of ``ticker`` from ``-1..1`` onto the legacy ``0..100`` scale."""
    sentiment = 0.0
    for entry in article.get("ticker_sentiment") or []:
        if isinstance(entry, dict) and entry.get("ticker") == ticker:
            sentiment = float(entry.get("ticker_sentiment_score") or 0)
            break
    return int((sentiment + 1) * 50)


class AlphaVantageCollector:
    """Collects news and sentiment from Alpha Vantage."""

    name = "alphavantage"

    def __init__(
        self,
        settings: Settings,
        *,
        http: Http = requests.get,
        limiter: RateLimiter | None = None,
        now: Now = utcnow,
    ) -> None:
        """Fail fast when the key is missing.

        Args:
            settings: Settings holding ``alphavantage_api_key``.
            http: HTTP seam; production leaves it at :func:`requests.get`.
            limiter: Quota tracker; ``None`` disables quota tracking, not the call.
            now: Returns the current timezone aware UTC time, used when an article has
                no usable publication time.

        Raises:
            CollectorConfigError: When ``settings.alphavantage_api_key`` is empty; the
                message names the environment variable ``ALPHAVANTAGE_API_KEY``.
        """
        if not settings.alphavantage_api_key:
            raise CollectorConfigError(
                "ALPHAVANTAGE_API_KEY is not set; Alpha Vantage is not configured"
            )
        self._api_key = settings.alphavantage_api_key
        self._http = http
        self._limiter = limiter
        self._now = now

    def collect_for_asset(self, asset: Asset) -> list[Post]:
        """Collect the news feed Alpha Vantage carries for ``asset``.

        Args:
            asset: The asset to search for, matched by its ticker.

        Returns:
            The feed's articles as posts; empty when the quota denies the call or the
            request fails.
        """
        if self._limiter is not None:
            decision = self._limiter.can_make_request()
            if not decision.allowed:
                logger.warning(
                    "Alpha Vantage quota exhausted for %s: %s", asset.ticker, decision.reason
                )
                return []
        try:
            response = self._http(API_URL, params=self._params(asset), timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            logger.warning("Alpha Vantage request for %s failed: %s", asset.ticker, error)
            self._record(success=False, error_message=str(error))
            return []
        return self._posts(response, asset)

    def _params(self, asset: Asset) -> dict[str, Any]:
        """Build the legacy query: the news sentiment function for one ticker."""
        return {
            "function": "NEWS_SENTIMENT",
            "tickers": asset.ticker,
            "apikey": self._api_key,
            "limit": ITEM_LIMIT,
        }

    def _posts(self, response: HttpResponse, asset: Asset) -> list[Post]:
        """Turn one response into posts; an unreadable answer yields none."""
        if response.status_code != 200:
            logger.warning(
                "Alpha Vantage answered HTTP %s for %s", response.status_code, asset.ticker
            )
            message = f"HTTP {response.status_code}"
            self._record(success=False, status_code=response.status_code, error_message=message)
            return []
        try:
            feed = _feed(response)
        # boundary: a body that cannot be read is a failed call, not an exception
        except Exception as error:
            logger.warning("Alpha Vantage body for %s could not be read: %s", asset.ticker, error)
            self._record(success=False, status_code=200, error_message=str(error))
            return []
        self._record(success=True, status_code=200)
        return self._convert(feed, asset)

    def _convert(self, feed: list[Any], asset: Asset) -> list[Post]:
        """Convert every article, dropping the ones that cannot be mapped."""
        posts: list[Post] = []
        for article in feed:
            try:
                post = self._to_post(article, asset)
            except Exception:
                logger.exception(
                    "Alpha Vantage article for %s could not be converted", asset.ticker
                )
                continue
            if post is not None:
                posts.append(post)
        logger.info("Alpha Vantage collected %s articles for %s", len(posts), asset.ticker)
        return posts

    def _to_post(self, article: dict[str, Any], asset: Asset) -> Post | None:
        """Convert one article, or ``None`` when it has no title."""
        title = article.get("title")
        if not title or not isinstance(title, str):
            return None
        url = article.get("url") or ""
        content = article.get("summary") or ""
        post_id = _post_id(url, title)
        return Post(
            asset_id=asset.id,
            source=self.name,
            post_id=post_id,
            author=self._author(article)[:MAX_AUTHOR],
            title=title[:MAX_TITLE],
            content=content[:MAX_CONTENT] if content else None,
            url=url[:MAX_URL] if url else FALLBACK_URL + post_id,
            score=_score(article, asset.ticker),
            created_at=self._created_at(article.get("time_published")),
        )

    @staticmethod
    def _author(article: dict[str, Any]) -> str:
        """Join the author list, falling back to the source name."""
        authors = article.get("authors") or ["Alpha Vantage"]
        return ", ".join(str(author) for author in authors)

    def _created_at(self, value: Any) -> datetime:
        """Parse ``time_published`` as UTC time, falling back to the injected clock."""
        if isinstance(value, str) and value:
            try:
                return datetime.strptime(value, STAMP_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                logger.warning("Alpha Vantage time_published %r could not be parsed", value)
        return self._now()

    def _record(
        self,
        *,
        success: bool,
        status_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Book the call in the limiter, when one is configured."""
        if self._limiter is None:
            return
        self._limiter.record_request(
            success=success,
            status_code=status_code,
            error_message=error_message,
            api_endpoint=API_URL,
        )


def _feed(response: HttpResponse) -> list[dict[str, Any]]:
    """Read the news feed of an Alpha Vantage body, or raise ``ValueError``."""
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Alpha Vantage body is not an object")
    refusal = data.get("Error Message") or data.get("Note")
    if refusal:
        raise ValueError(str(refusal))
    feed = data.get("feed") or []
    if not isinstance(feed, list):
        raise ValueError("Alpha Vantage feed is not a list")
    return feed
