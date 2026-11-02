"""Congressional trades collector: HTTP in, ``Post`` objects out, no database access.

The public source is House Stock Watcher, a free S3 feed that needs no key. A premium
endpoint is used first when ``CONGRESS_TRADES_API_KEY`` and ``CONGRESS_TRADES_API_URL``
are configured; a missing key is not an error, it only means "public source only".
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import requests

from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

PUBLIC_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/all_transactions.json"
CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades?politician={politician}"
TIMEOUT_SECONDS = 30
WINDOW_DAYS = 7
PREMIUM_LIMIT = 100
USER_AGENT = "Mozilla/5.0 (compatible; NewsTradingBot/1.0; +https://github.com/)"
MAX_POST_ID = 255
MAX_AUTHOR = 255
MAX_TITLE = 500
MAX_CONTENT = 5000
MAX_URL = 500

_TICKER_IN_PARENTHESES = re.compile(r"\(([A-Z]{1,5})\)")
_TICKER_STANDALONE = re.compile(r"\b([A-Z]{1,5})\b")

CONTENT_TEMPLATE = (
    "Congressional Trading Activity:\n\n"
    "Politician: {politician}\n"
    "Party: {party}\n"
    "State/District: {state}\n"
    "Chamber: {chamber}\n\n"
    "Ticker: ${ticker}\n"
    "Transaction Type: {transaction_type}\n"
    "Amount Range: {amount_range}\n"
    "Asset: {asset_description}\n\n"
    "Transaction Date: {transaction_date}\n"
    "Disclosure Date: {disclosure_date}\n\n"
    "Source: {source}\n"
)


class HttpResponse(Protocol):
    """What the collector reads from a ``requests.Response``."""

    status_code: int
    text: str

    def json(self) -> Any:
        """Return the decoded body."""


Http = Callable[..., HttpResponse]


def extract_ticker(text: str) -> str | None:
    """Extract the ticker symbol from an asset description.

    Args:
        text: Asset description text, e.g. ``Tesla, Inc. (TSLA)``.

    Returns:
        The symbol in parentheses when there is one, otherwise the first standalone
        upper-case word of one to five letters; ``None`` when neither matches.
    """
    if not text:
        return None
    match = _TICKER_IN_PARENTHESES.search(text)
    if match:
        return match.group(1)
    match = _TICKER_STANDALONE.search(text)
    return match.group(1) if match else None


def post_id_for(trade: dict[str, Any]) -> str:
    """Derive the stable post id from the identity of one trade.

    Args:
        trade: Normalised trade dictionary.

    Returns:
        ``congress_<md5>`` over politician, ticker, transaction date and type — the
        fields that make a trade unique, truncated to the post id column.
    """
    key = ":".join(
        (
            str(trade["politician"]),
            str(trade["ticker"]),
            str(trade["transaction_date"]),
            str(trade["transaction_type"]),
        )
    )
    return ("congress_" + hashlib.md5(key.encode()).hexdigest())[:MAX_POST_ID]


def _created_at(value: Any) -> datetime:
    """Convert a ``YYYY-MM-DD`` transaction date to UTC, falling back to now.

    Args:
        value: Raw transaction date of the source row.

    Returns:
        The day at midnight UTC, or the current UTC time when the value is missing or
        cannot be parsed.
    """
    if value:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            logger.warning("Congressional transaction date %r cannot be parsed", value)
    return datetime.now(UTC)


class CongressionalTradesCollector:
    """Collects congressional trading data from public APIs."""

    name = "congressional_trades"

    def __init__(
        self,
        settings: Settings,
        *,
        http: Http = requests.get,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Optional premium source: no key means the public source only, not an error.

        Args:
            settings: Settings holding ``congress_trades_api_key`` and
                ``congress_trades_api_url``.
            http: HTTP seam; production leaves it at :func:`requests.get`.
            limiter: Quota tracker; ``None`` disables quota tracking, not the call.
        """
        self._api_key = settings.congress_trades_api_key
        self._api_url = settings.congress_trades_api_url
        self._http = http
        self._limiter = limiter

    def collect_for_asset(self, asset: Asset) -> list[Post]:
        """Collect the congressional trades of ``asset`` as posts.

        Args:
            asset: The asset to filter the trades for, matched by its ticker.

        Returns:
            One post per matching trade; empty when the quota denies the call, the
            request fails or no trade carries the ticker.
        """
        if not asset.ticker:
            logger.warning("No ticker for %s, skipping congressional trades", asset.name)
            return []
        ticker = asset.ticker.upper()
        posts = [
            self._to_post(trade, asset) for trade in self._trades() if trade["ticker"] == ticker
        ]
        logger.info("Congressional trades collected %s posts for %s", len(posts), ticker)
        return posts

    def _trades(self) -> list[dict[str, Any]]:
        """Return the trades of the best available source, public when premium is empty."""
        if self._api_key and self._api_url:
            trades = self._premium_trades()
            if trades:
                return trades
        return self._public_trades()

    def _premium_trades(self) -> list[dict[str, Any]]:
        """Ask the configured premium endpoint and normalise its rows."""
        response = self._request(
            self._api_url,
            params={"limit": PREMIUM_LIMIT, "days_back": WINDOW_DAYS},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if response is None:
            return []
        readable, payload = self._body(response)
        if not readable:
            self._record(
                success=False,
                endpoint=self._api_url,
                status_code=response.status_code,
                error_message=payload,
            )
            return []
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            self._record(
                success=False,
                endpoint=self._api_url,
                status_code=response.status_code,
                error_message="no data list",
            )
            return []
        self._record(success=True, endpoint=self._api_url, status_code=response.status_code)
        return self._normalise(rows, premium=True)

    def _public_trades(self) -> list[dict[str, Any]]:
        """Ask House Stock Watcher and normalise its rows."""
        response = self._request(PUBLIC_URL, params=None, headers={"User-Agent": USER_AGENT})
        if response is None:
            return []
        readable, payload = self._body(response)
        if not readable:
            self._record(
                success=False,
                endpoint=PUBLIC_URL,
                status_code=response.status_code,
                error_message=payload,
            )
            return []
        if not isinstance(payload, list):
            self._record(
                success=False,
                endpoint=PUBLIC_URL,
                status_code=response.status_code,
                error_message="not a trade list",
            )
            return []
        self._record(success=True, endpoint=PUBLIC_URL, status_code=response.status_code)
        return self._normalise(payload, premium=False)

    def _normalise(self, rows: list[Any], *, premium: bool) -> list[dict[str, Any]]:
        """Normalise the rows of one source, dropping the ones that cannot be mapped."""
        trades: list[dict[str, Any]] = []
        for row in rows:
            try:
                trade = self._premium_row(row) if premium else self._public_row(row)
            except Exception:
                logger.exception("Congressional trade row could not be normalised")
                continue
            if trade is not None:
                trades.append(trade)
        return trades

    def _premium_row(self, row: Any) -> dict[str, Any] | None:
        """Map one premium row, or ``None`` when it carries no ticker."""
        if not isinstance(row, dict):
            return None
        ticker = _text(row.get("ticker") or row.get("symbol")).upper()
        if not ticker:
            return None
        return {
            "politician": _text(row.get("politician") or row.get("representative")) or "Unknown",
            "ticker": ticker,
            "transaction_type": _text(row.get("type") or row.get("transaction_type")) or "Unknown",
            "amount_range": _text(row.get("amount") or row.get("amount_range")) or "Unknown",
            "transaction_date": row.get("transaction_date") or row.get("date"),
            "disclosure_date": row.get("disclosure_date") or row.get("filed_date"),
            "asset_description": _text(row.get("asset_description") or row.get("description")),
            "party": _text(row.get("party")) or "Unknown",
            "state": _text(row.get("state") or row.get("district")) or "Unknown",
            "chamber": _text(row.get("chamber")) or "Unknown",
            "source": "premium_api",
        }

    def _public_row(self, row: Any) -> dict[str, Any] | None:
        """Map one House Stock Watcher row, or ``None`` when it carries no ticker."""
        if not isinstance(row, dict):
            return None
        ticker = extract_ticker(_text(row.get("ticker") or row.get("asset_description")))
        if not ticker:
            return None
        return {
            "politician": _text(row.get("representative")) or "Unknown",
            "ticker": ticker.upper(),
            "transaction_type": _text(row.get("type")) or "Unknown",
            "amount_range": _text(row.get("amount")) or "Unknown",
            "transaction_date": row.get("transaction_date"),
            "disclosure_date": row.get("disclosure_date"),
            "asset_description": _text(row.get("asset_description")),
            "party": _text(row.get("party")) or "Unknown",
            "state": _text(row.get("district")) or "Unknown",
            "chamber": "house",
            "source": "house_stock_watcher",
        }

    def _to_post(self, trade: dict[str, Any], asset: Asset) -> Post:
        """Turn one normalised trade into the post the legacy mapping describes."""
        policy = trade["politician"].replace(" ", "-")
        return Post(
            asset_id=asset.id,
            source=self.name,
            post_id=post_id_for(trade),
            author=f"{trade['politician']} ({trade['chamber'].title()})"[:MAX_AUTHOR],
            title=self._title(trade)[:MAX_TITLE],
            content=self._content(trade)[:MAX_CONTENT],
            url=CAPITOL_TRADES_URL.format(politician=policy)[:MAX_URL],
            score=100,
            created_at=_created_at(trade["transaction_date"]),
        )

    def _title(self, trade: dict[str, Any]) -> str:
        """Build the legacy title, marked green for a purchase and red otherwise."""
        icon = "🟢" if "purchase" in trade["transaction_type"].lower() else "🔴"
        return (
            f"{icon} {trade['politician']} ({trade['party']}-{trade['state']}) "
            f"{trade['transaction_type'].title()} ${trade['ticker']} - {trade['amount_range']}"
        )

    def _content(self, trade: dict[str, Any]) -> str:
        """Build the legacy body with every field of the trade."""
        return CONTENT_TEMPLATE.format(
            politician=trade["politician"],
            party=trade["party"],
            state=trade["state"],
            chamber=trade["chamber"].title(),
            ticker=trade["ticker"],
            transaction_type=trade["transaction_type"].title(),
            amount_range=trade["amount_range"],
            asset_description=trade["asset_description"],
            transaction_date=trade["transaction_date"],
            disclosure_date=trade["disclosure_date"],
            source=trade["source"],
        )

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> HttpResponse | None:
        """Check the quota, then call ``url``; ``None`` when denied or on a transport error."""
        if self._limiter is not None:
            decision = self._limiter.can_make_request()
            if not decision.allowed:
                logger.warning("Congressional trades quota exhausted: %s", decision.reason)
                return None
        try:
            return self._http(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            logger.warning("Congressional trades request failed: %s", error)
            self._record(success=False, endpoint=url, error_message=str(error))
            return None

    def _body(self, response: HttpResponse) -> tuple[bool, Any]:
        """Return ``(readable, payload)``; the payload is the error text when unreadable."""
        if response.status_code != 200:
            logger.warning("Congressional trades source answered HTTP %s", response.status_code)
            return False, f"HTTP {response.status_code}"
        try:
            return True, response.json()
        # boundary: a body that cannot be read is a failed call, not an exception
        except Exception as error:
            logger.warning("Congressional trades body could not be read: %s", error)
            return False, str(error)

    def _record(
        self,
        *,
        success: bool,
        endpoint: str,
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
            api_endpoint=endpoint,
        )


def _text(value: Any) -> str:
    """Return ``value`` as text, or an empty string for ``None``."""
    return "" if value is None else str(value)
