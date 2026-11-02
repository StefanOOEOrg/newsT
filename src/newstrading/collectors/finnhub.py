"""Finnhub collector: HTTP in, ``Post`` objects out, no database access."""

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

API_URL = "https://finnhub.io/api/v1/company-news"
TIMEOUT_SECONDS = 10
WINDOW_DAYS = 7
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


def _post_id(article_id: Any, url: str) -> str:
    """Derive the stable, documented post id from the article id and its URL."""
    return "finnhub_" + hashlib.md5(f"{article_id or ''}:{url}".encode()).hexdigest()


class FinnhubCollector:
    """Collects company news from Finnhub.io."""

    name = "finnhub"

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
            settings: Settings holding ``finnhub_api_key``.
            http: HTTP seam; production leaves it at :func:`requests.get`.
            limiter: Quota tracker; ``None`` disables quota tracking, not the call.
            now: Returns the current timezone aware UTC time, used for the request
                window and when an article has no usable timestamp.

        Raises:
            CollectorConfigError: When ``settings.finnhub_api_key`` is empty; the
                message names the environment variable ``FINNHUB_API_KEY``.
        """
        if not settings.finnhub_api_key:
            raise CollectorConfigError("FINNHUB_API_KEY is not set; Finnhub is not configured")
        self._api_key = settings.finnhub_api_key
        self._http = http
        self._limiter = limiter
        self._now = now

    def collect_for_asset(self, asset: Asset) -> list[Post]:
        """Collect every article Finnhub carries for ``asset``.

        Args:
            asset: The asset to search for, matched by its ticker.

        Returns:
            The response's articles as posts; empty when the quota denies the call or
            the request fails.
        """
        if self._limiter is not None:
            decision = self._limiter.can_make_request()
            if not decision.allowed:
                logger.warning("Finnhub quota exhausted for %s: %s", asset.ticker, decision.reason)
                return []
        try:
            response = self._http(API_URL, params=self._params(asset), timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            logger.warning("Finnhub request for %s failed: %s", asset.ticker, error)
            self._record(success=False, error_message=str(error))
            return []
        return self._posts(response, asset)

    def _params(self, asset: Asset) -> dict[str, Any]:
        """Build the legacy query: the symbol and the last seven days."""
        now = self._now()
        return {
            "symbol": asset.ticker,
            "from": (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
            "token": self._api_key,
        }

    def _posts(self, response: HttpResponse, asset: Asset) -> list[Post]:
        """Turn one response into posts; an unreadable answer yields none."""
        if response.status_code != 200:
            logger.warning("Finnhub answered HTTP %s for %s", response.status_code, asset.ticker)
            message = f"HTTP {response.status_code}"
            self._record(success=False, status_code=response.status_code, error_message=message)
            return []
        try:
            articles = response.json()
            if not isinstance(articles, list):
                raise ValueError("Finnhub body is not an article list")
        # boundary: a body that cannot be read is a failed call, not an exception
        except Exception as error:
            logger.warning("Finnhub body for %s could not be read: %s", asset.ticker, error)
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
                logger.exception("Finnhub article for %s could not be converted", asset.ticker)
                continue
            if post is not None:
                posts.append(post)
        logger.info("Finnhub collected %s articles for %s", len(posts), asset.ticker)
        return posts

    def _to_post(self, article: dict[str, Any], asset: Asset) -> Post | None:
        """Convert one article, or ``None`` when it has no URL."""
        url = article.get("url")
        if not url or not isinstance(url, str):
            return None
        content = article.get("summary") or ""
        return Post(
            asset_id=asset.id,
            source=self.name,
            post_id=_post_id(article.get("id"), url),
            author=str(article.get("source") or "Finnhub")[:MAX_AUTHOR],
            title=(article.get("headline") or "No title")[:MAX_TITLE],
            content=content[:MAX_CONTENT] if content else None,
            url=url[:MAX_URL],
            score=0,
            created_at=self._created_at(article.get("datetime")),
        )

    def _created_at(self, value: Any) -> datetime:
        """Convert the Unix timestamp to UTC, falling back to the injected clock."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(value, tz=UTC)
            except (OverflowError, OSError, ValueError):
                logger.warning("Finnhub datetime %r could not be converted", value)
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
