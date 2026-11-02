"""Event collector and store: dated events in, rows of ``asset_events`` out.

An event is not a post, so it gets its own model and its own store. Both legacy event
feeds are merged into one call and de-duplicated by the unique key of ``asset_events``
(asset, event type, event date, title).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

import psycopg2
import requests
from psycopg2.extras import Json

from newstrading.collectors.models import Asset
from newstrading.config import Settings
from newstrading.db import Connector, connect
from newstrading.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

API_URL = "https://www.alphavantage.co/query"
CALENDAR_FUNCTION = "EARNINGS_CALENDAR"
NATIVE_FUNCTION = "EARNINGS"
EVENT_TYPE = "earnings"
SOURCE = "alphavantage"
TIMEOUT_SECONDS = 10

INSERT_PREFIX = (
    "INSERT INTO asset_events "
    "(asset_id, event_type, event_date, description, source, metadata) VALUES "
)
ON_CONFLICT = " ON CONFLICT DO NOTHING"
VALUES_ROW = "(%s, %s, %s, %s, %s, %s)"


def today() -> date:
    """Return the current UTC day; the module's only clock."""
    return datetime.now(UTC).date()


class HttpResponse(Protocol):
    """What the collector reads from a ``requests.Response``."""

    status_code: int
    text: str

    def json(self) -> Any:
        """Return the decoded body."""


Http = Callable[..., HttpResponse]


@dataclass(frozen=True, slots=True)
class Event:
    """One dated event for an asset.

    Attributes:
        asset_id: Asset the event belongs to.
        event_type: Source-specific kind, e.g. ``earnings``; lower case.
        title: Short description.
        event_date: Day the event happens, timezone aware.
        source: Source key, e.g. ``alphavantage``.
        details: Free-form payload as JSON-serialisable ``dict``; empty when the source has none.
    """

    asset_id: int
    event_type: str
    title: str
    event_date: datetime
    source: str
    details: dict[str, Any] = field(default_factory=dict)


class EventCollector:
    """Collects the dated events of one asset from the Alpha Vantage feeds."""

    name = "events"

    def __init__(
        self,
        settings: Settings,
        *,
        http: Http = requests.get,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Remember the key, the HTTP seam and the quota tracker.

        Args:
            settings: Settings holding ``alphavantage_api_key``; an empty key collects
                nothing, it is not an error.
            http: HTTP seam; production leaves it at :func:`requests.get`.
            limiter: Quota tracker; ``None`` disables quota tracking, not the call.
        """
        self._api_key = settings.alphavantage_api_key
        self._http = http
        self._limiter = limiter

    def collect_for_asset(self, asset: Asset) -> list[Event]:
        """Collect every event Alpha Vantage carries for ``asset``.

        Args:
            asset: The asset to search for, matched by its ticker.

        Returns:
            The merged, de-duplicated events of both feeds; empty when the key is
            missing, the quota denies a call or the request fails.
        """
        if not self._api_key:
            logger.info("ALPHAVANTAGE_API_KEY is not set; no events for %s", asset.ticker)
            return []
        events = self._calendar_events(asset) + self._native_events(asset)
        unique = _unique(events)
        logger.info("Event collector found %s events for %s", len(unique), asset.ticker)
        return unique

    def _calendar_events(self, asset: Asset) -> list[Event]:
        """Ask the earnings calendar feed and parse its CSV rows."""
        response = self._request(asset, CALENDAR_FUNCTION)
        if response is None:
            return []
        if response.status_code != 200:
            self._record(success=False, status_code=response.status_code)
            return []
        self._record(success=True, status_code=response.status_code)
        return self._parse_calendar(response.text, asset)

    def _native_events(self, asset: Asset) -> list[Event]:
        """Ask the per-symbol earnings feed and parse its JSON rows."""
        response = self._request(asset, NATIVE_FUNCTION)
        if response is None:
            return []
        if response.status_code != 200:
            self._record(success=False, status_code=response.status_code)
            return []
        try:
            payload = response.json()
        # boundary: a body that cannot be read is a failed call, not an exception
        except Exception as error:
            logger.warning("Alpha Vantage earnings body could not be read: %s", error)
            self._record(success=False, status_code=response.status_code, error_message=str(error))
            return []
        rows = payload.get("quarterlyEarnings") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            logger.warning("Alpha Vantage earnings body for %s has no quarterly rows", asset.ticker)
            self._record(
                success=False,
                status_code=response.status_code,
                error_message="no quarterlyEarnings list",
            )
            return []
        self._record(success=True, status_code=response.status_code)
        symbol = _text(payload.get("symbol")) or asset.ticker
        return [event for row in rows if (event := self._native_event(row, asset, symbol))]

    def _parse_calendar(self, text: str, asset: Asset) -> list[Event]:
        """Turn the earnings calendar CSV into events, skipping the rows without a day."""
        lines = text.strip().split("\n")
        if len(lines) < 2:
            logger.info("No earnings calendar rows for %s", asset.ticker)
            return []
        events: list[Event] = []
        for line in lines[1:]:
            event = self._calendar_event(line.split(","), asset)
            if event is not None:
                events.append(event)
        return events

    def _calendar_event(self, values: list[str], asset: Asset) -> Event | None:
        """Map one CSV row, or ``None`` when it has no usable date."""
        if len(values) < 3:
            logger.warning("Earnings calendar row for %s has too few columns", asset.ticker)
            return None
        event_date = _event_date(values[2], asset.ticker)
        if event_date is None:
            return None
        details = _details(
            fiscal_date_ending=values[3] if len(values) > 3 else None,
            eps_estimate=values[4] if len(values) > 4 else None,
            symbol=values[0] or asset.ticker,
        )
        return _event(asset, event_date, details)

    def _native_event(self, row: Any, asset: Asset, symbol: str) -> Event | None:
        """Map one JSON row, or ``None`` when it has no usable date."""
        if not isinstance(row, dict):
            logger.warning("Alpha Vantage earnings row for %s is not an object", asset.ticker)
            return None
        event_date = _event_date(row.get("reportedDate"), asset.ticker)
        if event_date is None:
            return None
        details = _details(
            fiscal_date_ending=row.get("fiscalDateEnding"),
            reported_eps=row.get("reportedEPS"),
            estimated_eps=row.get("estimatedEPS"),
            symbol=symbol,
        )
        return _event(asset, event_date, details)

    def _request(self, asset: Asset, function: str) -> HttpResponse | None:
        """Check the quota, then ask ``function`` for the ticker of ``asset``."""
        if self._limiter is not None:
            decision = self._limiter.can_make_request()
            if not decision.allowed:
                logger.warning(
                    "Alpha Vantage quota exhausted for %s: %s", asset.ticker, decision.reason
                )
                return None
        params = {"function": function, "symbol": asset.ticker, "apikey": self._api_key}
        try:
            return self._http(API_URL, params=params, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            logger.warning("Alpha Vantage request for %s failed: %s", asset.ticker, error)
            self._record(success=False, error_message=str(error))
            return None

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


class EventStore:
    """Writes events to ``asset_events``."""

    def __init__(
        self,
        settings: Settings,
        *,
        connector: Connector = psycopg2.connect,
    ) -> None:
        """Remember the database.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
        """
        self._settings = settings
        self._connector = connector

    def save(self, events: Sequence[Event]) -> int:
        """Insert the events, return how many rows were new.

        Contract: idempotent — the statement uses ``ON CONFLICT DO NOTHING`` on the unique key of
        ``asset_events`` (asset, event_type, event_date, title); a duplicate is not counted.
        """
        if not events:
            return 0
        rows = [
            (
                event.asset_id,
                event.event_type,
                event.event_date.date(),
                event.title,
                event.source,
                Json(event.details) if event.details else None,
            )
            for event in events
        ]
        query = INSERT_PREFIX + ", ".join([VALUES_ROW] * len(rows)) + ON_CONFLICT
        params = tuple(value for row in rows for value in row)

        connection: Any = None
        try:
            connection = connect(self._settings.database_url, connector=self._connector)
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                saved = int(cursor.rowcount)
            connection.commit()
        # boundary: rollback and re-raise — a lost event is a real loss
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()
        logger.info("Event store saved %s new events", saved)
        return saved


def _event(asset: Asset, event_date: datetime, details: dict[str, Any]) -> Event:
    """Build the one event the sources share for an earnings report."""
    return Event(
        asset_id=asset.id,
        event_type=EVENT_TYPE,
        title=f"Earnings report for {asset.name}",
        event_date=event_date,
        source=SOURCE,
        details=details,
    )


def _details(**values: Any) -> dict[str, Any]:
    """Return the source fields that carry a value, as the event's free-form payload."""
    return {name: value for name, value in values.items() if value not in (None, "")}


def _event_date(value: Any, ticker: str) -> datetime | None:
    """Parse a source date to midnight UTC; ``None`` when missing, past or unreadable.

    Args:
        value: Raw date of the source row, usually ``YYYY-MM-DD``.
        ticker: Ticker the row belongs to, for the log line.

    Returns:
        The day as a timezone aware UTC timestamp, or ``None`` when the row has to be
        skipped — ``asset_events.event_date`` is ``NOT NULL`` and the legacy collector
        keeps only upcoming events.
    """
    if value in (None, ""):
        logger.warning("Event row for %s has no date; skipped", ticker)
        return None
    try:
        day = datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        logger.warning("Event date %r for %s cannot be parsed; skipped", value, ticker)
        return None
    if day < today():
        logger.info("Event for %s on %s is in the past; skipped", ticker, day)
        return None
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _unique(events: list[Event]) -> list[Event]:
    """Drop duplicates by the unique key of ``asset_events``, keeping the first one."""
    seen: set[tuple[int, str, datetime, str]] = set()
    unique: list[Event] = []
    for event in events:
        key = (event.asset_id, event.event_type, event.event_date, event.title)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def _text(value: Any) -> str:
    """Return ``value`` as text, or an empty string for ``None``."""
    return "" if value is None else str(value)
