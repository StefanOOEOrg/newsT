"""NewsAPI collector: HTTP in, ``Post`` objects out, no database access."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import requests

from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.errors import CollectorConfigError
from newstrading.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

API_URL = "https://newsapi.org/v2/everything"
TIMEOUT_SECONDS = 10
WINDOW_DAYS = 7
MAX_KEYWORDS = 3
PAGE_SIZE = 100
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


def _post_id(url: str) -> str:
    """Derive the stable, documented post id from the article URL."""
    return "newsapi_" + hashlib.md5(url.encode()).hexdigest()


def _articles(response: HttpResponse) -> list[dict[str, Any]]:
    """Read the article list of a NewsAPI body, or raise ``ValueError``."""
    data = response.json()
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise ValueError("NewsAPI body does not carry status ok")
    articles = data.get("articles") or []
    if not isinstance(articles, list):
        raise ValueError("NewsAPI articles are not a list")
    return articles


class NewsAPICollector:
    """Collects financial news from NewsAPI.org."""

    name = "newsapi"

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
            settings: Settings holding ``newsapi_key``.
            http: HTTP seam; production leaves it at :func:`requests.get`.
            limiter: Quota tracker; ``None`` disables quota tracking, not the call.
            now: Returns the current timezone aware UTC time, used for the request
                window and when an article has no usable date.

        Raises:
            CollectorConfigError: When ``settings.newsapi_key`` is empty; the message
                names the environment variable ``NEWSAPI_KEY``.
        """
        if not settings.newsapi_key:
            raise CollectorConfigError("NEWSAPI_KEY is not set; NewsAPI is not configured")
        self._api_key = settings.newsapi_key
        self._http = http
        self._limiter = limiter
        self._now = now

    def collect_for_asset(self, asset: Asset) -> list[Post]:
        """Collect every article NewsAPI carries for ``asset``.

        Args:
            asset: The asset to search for.

        Returns:
            The response's articles as posts; empty when the quota denies the call or
            the request fails.
        """
        if self._limiter is not None:
            decision = self._limiter.can_make_request()
            if not decision.allowed:
                logger.warning("NewsAPI quota exhausted for %s: %s", asset.name, decision.reason)
                return []
        try:
            response = self._http(API_URL, params=self._params(asset), timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            logger.warning("NewsAPI request for %s failed: %s", asset.name, error)
            self._record(success=False, error_message=str(error))
            return []
        return self._posts(response, asset)

    def _params(self, asset: Asset) -> dict[str, Any]:
        """Build the legacy query: name, ticker and the first three keywords."""
        parts = [asset.name, asset.ticker, *asset.keywords[:MAX_KEYWORDS]]
        query = " OR ".join(f'"{part}"' for part in parts if part)
        since = self._now() - timedelta(days=WINDOW_DAYS)
        return {
            "q": query,
            "apiKey": self._api_key,
            "language": "en",
            "sortBy": "publishedAt",
            "from": since.strftime("%Y-%m-%d"),
            "pageSize": PAGE_SIZE,
        }

    def _posts(self, response: HttpResponse, asset: Asset) -> list[Post]:
        """Turn one response into posts; an unreadable answer yields none."""
        if response.status_code != 200:
            logger.warning("NewsAPI answered HTTP %s for %s", response.status_code, asset.name)
            message = f"HTTP {response.status_code}"
            self._record(success=False, status_code=response.status_code, error_message=message)
            return []
        try:
            articles = _articles(response)
        # boundary: a body that cannot be read is a failed call, not an exception
        except Exception as error:
            logger.warning("NewsAPI body for %s could not be read: %s", asset.name, error)
            self._record(success=False, status_code=200, error_message=str(error))
            return []
        self._record(success=True, status_code=200)
        return self._convert(articles, asset)

    def _convert(self, articles: list[Any], asset: Asset) -> list[Post]:
        """Convert every article, dropping the ones that cannot be mapped."""
        posts: list[Post] = []
        for article in articles:
            try:
                post = self._to_post(article, asset)
            except Exception:
                logger.exception("NewsAPI article for %s could not be converted", asset.name)
                continue
            if post is not None:
                posts.append(post)
        logger.info("NewsAPI collected %s articles for %s", len(posts), asset.name)
        return posts

    def _to_post(self, article: dict[str, Any], asset: Asset) -> Post | None:
        """Convert one article, or ``None`` when it has no URL."""
        url = article.get("url")
        if not url or not isinstance(url, str):
            return None
        content = article.get("description") or article.get("content") or ""
        return Post(
            asset_id=asset.id,
            source=self.name,
            post_id=_post_id(url),
            author=self._author(article)[:MAX_AUTHOR],
            title=(article.get("title") or "No title")[:MAX_TITLE],
            content=content[:MAX_CONTENT] if content else None,
            url=url[:MAX_URL],
            score=0,
            created_at=self._created_at(article.get("publishedAt")),
        )

    @staticmethod
    def _author(article: dict[str, Any]) -> str:
        """Author, then the source name, then ``Unknown`` — as in the legacy code."""
        author = article.get("author")
        if author:
            return str(author)
        source = article.get("source")
        if isinstance(source, dict) and source.get("name"):
            return str(source["name"])
        return "Unknown"

    def _created_at(self, value: Any) -> datetime:
        """Parse ``publishedAt`` as UTC time, falling back to the injected clock."""
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("NewsAPI publishedAt %r could not be parsed", value)
            else:
                return (
                    parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
                )
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
