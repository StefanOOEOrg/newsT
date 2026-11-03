"""The read-only dashboard API and the command that serves it.

Seven GET routes answer the dashboard screens: the overview counters, the posts with
their analysis, the alerts with their performance, the keyword performance, the source
health and the system logs, plus the alert performance aggregated per horizon and type.
Every answer is read-only by construction — no route accepts a write method — and a
database that cannot be reached is one documented 503 body.

``build_app`` takes the connector so the tests run without a database; production uses
:func:`psycopg2.connect` like every other store of the package.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import psycopg2
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from newstrading.config import Settings
from newstrading.db import Connector, connect

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8088
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
"""The Angular build served at ``/``; absent on a fresh clone until ``ng build`` runs."""

_UNAVAILABLE = {"error": "database unavailable"}
_NOT_BUILT = "web/dist not found: run ng build first (the API keeps working)"

_OVERVIEW_COLUMNS = (
    "assets",
    "posts",
    "analyses",
    "alerts",
    "open_alerts",
    "last_collector_run",
    "database_size_bytes",
)
_OVERVIEW_DEFAULTS = (0, 0, 0, 0, 0, None, None)

_OVERVIEW = """
    SELECT
        (SELECT COUNT(*) FROM asset),
        (SELECT COUNT(*) FROM social_posts),
        (SELECT COUNT(*) FROM ai_analysis),
        (SELECT COUNT(*) FROM alerts),
        (SELECT COUNT(*) FROM alerts WHERE notified IS NOT TRUE),
        (SELECT MAX(last_run_completed_at) FROM collector_statistics),
        pg_database_size(current_database())
"""

_POSTS_COLUMNS = (
    "id",
    "asset_id",
    "asset",
    "source",
    "title",
    "url",
    "score",
    "created_at",
    "sentiment",
    "sentiment_score",
    "category",
    "summary",
)
_POSTS_FILTER = (
    "WHERE (%s::integer IS NULL OR p.asset_id = %s) AND (%s::text IS NULL OR p.source = %s)"
)
_POSTS_COUNT = f"SELECT COUNT(*) FROM social_posts p {_POSTS_FILTER}"
_POSTS_PAGE = f"""
    SELECT p.id, p.asset_id, a.ticker, p.source, p.title, p.url, p.score, p.created_at,
           an.sentiment, an.sentiment_score, an.category, an.summary
    FROM social_posts p
    LEFT JOIN asset a ON a.id = p.asset_id
    LEFT JOIN ai_analysis an ON an.post_id = p.id
    {_POSTS_FILTER}
    ORDER BY p.created_at DESC, p.id DESC
    LIMIT %s OFFSET %s
"""

_ALERTS_COLUMNS = (
    "id",
    "asset_id",
    "asset",
    "alert_type",
    "severity",
    "description",
    "confidence_score",
    "timestamp",
    "notified",
    "return_7d",
    "correct_7d",
)
_ALERTS_FILTER = "WHERE (%s::text IS NULL OR al.severity = %s)"
_ALERTS_COUNT = f"SELECT COUNT(*) FROM alerts al {_ALERTS_FILTER}"
_ALERTS_PAGE = f"""
    SELECT al.id, al.asset_id, a.ticker, al.alert_type, al.severity, al.description,
           al.confidence_score, al.timestamp, al.notified, ap.return_7d, ap.correct_7d
    FROM alerts al
    LEFT JOIN asset a ON a.id = al.asset_id
    LEFT JOIN LATERAL (
        SELECT return_7d, correct_7d
        FROM alert_performance
        WHERE alert_id = al.id
        ORDER BY id DESC
        LIMIT 1
    ) ap ON TRUE
    {_ALERTS_FILTER}
    ORDER BY al.timestamp DESC, al.id DESC
    LIMIT %s OFFSET %s
"""

_KEYWORDS_COLUMNS = (
    "id",
    "asset_id",
    "asset",
    "keyword",
    "posts_found",
    "last_found_at",
    "first_seen_at",
)
_KEYWORDS_COUNT = "SELECT COUNT(*) FROM keyword_performance"
_KEYWORDS_PAGE = """
    SELECT kp.id, kp.asset_id, a.ticker, kp.keyword, kp.posts_found,
           kp.last_found_at, kp.first_seen_at
    FROM keyword_performance kp
    LEFT JOIN asset a ON a.id = kp.asset_id
    ORDER BY kp.posts_found DESC NULLS LAST, kp.id
    LIMIT %s OFFSET %s
"""

_SOURCES_COLUMNS = (
    "collector",
    "last_run",
    "total_errors",
    "calls_today",
    "failures_today",
    "quota_limit",
    "quota_remaining",
    "enabled",
)
_SOURCES = """
    SELECT rc.collector_name,
           cs.last_run_completed_at,
           COALESCE(cs.total_errors, 0),
           COALESCE(usage.calls_today, 0),
           COALESCE(usage.failures_today, 0),
           rc.max_calls_per_day,
           CASE WHEN rc.max_calls_per_day IS NULL THEN NULL
                ELSE GREATEST(rc.max_calls_per_day - COALESCE(usage.calls_today, 0), 0)
           END,
           rc.enabled
    FROM rate_limit_config rc
    LEFT JOIN collector_statistics cs ON cs.collector_name = rc.collector_name
    LEFT JOIN (
        SELECT collector_name,
               COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '1 day') AS calls_today,
               COUNT(*) FILTER (
                   WHERE success IS FALSE AND timestamp >= NOW() - INTERVAL '1 day'
               ) AS failures_today
        FROM api_usage
        GROUP BY collector_name
    ) usage ON usage.collector_name = rc.collector_name
    ORDER BY rc.collector_name
"""

_LOGS_COLUMNS = (
    "id",
    "timestamp",
    "level",
    "logger",
    "service",
    "message",
    "function",
    "line_number",
    "exception",
    "metadata",
)
_LOGS_FILTER = "WHERE (%s::text IS NULL OR level = %s)"
_LOGS_COUNT = f"SELECT COUNT(*) FROM system_logs {_LOGS_FILTER}"
_LOGS_PAGE = f"""
    SELECT id, timestamp, level, logger, service, message, function, line_number,
           exception, metadata
    FROM system_logs
    {_LOGS_FILTER}
    ORDER BY timestamp DESC, id DESC
    LIMIT %s OFFSET %s
"""

_Statement = tuple[str, tuple[Any, ...]]

_PERFORMANCE_HORIZONS = ("1d", "3d", "7d")
"""The correctness columns ``alert_performance`` actually fills; returns go further."""

_PERFORMANCE_TOTALS = """
    SELECT COUNT(*),
           COUNT(*) FILTER (WHERE correct_1d IS TRUE),
           COUNT(*) FILTER (WHERE correct_3d IS TRUE),
           COUNT(*) FILTER (WHERE correct_7d IS TRUE)
    FROM alert_performance
"""
_PERFORMANCE_BY_TYPE = """
    SELECT alert_type,
           COUNT(*),
           COUNT(*) FILTER (WHERE correct_7d IS TRUE)
    FROM alert_performance
    GROUP BY alert_type
    ORDER BY alert_type
"""


class DatabaseUnavailable(Exception):
    """Raised when a dashboard query cannot reach the database."""


def build_app(settings: Settings, *, connector: Connector = psycopg2.connect) -> FastAPI:
    """All routes under /api; no write route exists.

    Args:
        settings: Settings holding ``database_url``; every request opens its own
            connection.
        connector: Connection factory. Production leaves it at
            :func:`psycopg2.connect`; tests inject a fake.

    Returns:
        The FastAPI application with the seven GET routes and one exception handler that
        turns :class:`DatabaseUnavailable` into a 503 with
        ``{"error": "database unavailable"}``.

    Contract:
        * Every list answer is ``{"items": [...], "total": n, "page": p, "per_page": pp}``;
          ``per_page`` defaults to 50 and is capped at 200.
        * ``None`` columns are ``null`` in the JSON, never omitted.
        * ``page`` and ``per_page`` below 1 are a 422 that names the parameter.
        * No route accepts POST, PUT, PATCH or DELETE.
    """
    app = FastAPI(title="newstrading dashboard")

    @app.exception_handler(DatabaseUnavailable)
    async def unavailable(_request: Request, _error: DatabaseUnavailable) -> JSONResponse:
        """Answer a database that cannot be reached with the documented 503 body."""
        return JSONResponse(_UNAVAILABLE, status_code=503)

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        """Counters: assets, posts, analyses, alerts, open alerts, last run, DB size."""
        rows = _fetch(settings, connector, [(_OVERVIEW, ())])[0]
        row = rows[0] if rows else _OVERVIEW_DEFAULTS
        return dict(zip(_OVERVIEW_COLUMNS, row, strict=False))

    @app.get("/api/posts")
    def posts(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PER_PAGE, ge=1),
        asset_id: int | None = Query(default=None),
        source: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Posts joined with their analysis, newest first, filtered by asset and source."""
        limit, offset = _window(page, per_page)
        filters: tuple[Any, ...] = (asset_id, asset_id, source, source)
        count, items = _fetch(
            settings,
            connector,
            [
                (_POSTS_COUNT, filters),
                (_POSTS_PAGE, (*filters, limit, offset)),
            ],
        )
        return _page(_POSTS_COLUMNS, items, _total(count), page, limit)

    @app.get("/api/alerts")
    def alerts(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PER_PAGE, ge=1),
        severity: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Alerts with their 7-day return and correctness, newest first."""
        limit, offset = _window(page, per_page)
        filters: tuple[Any, ...] = (severity, severity)
        count, items = _fetch(
            settings,
            connector,
            [
                (_ALERTS_COUNT, filters),
                (_ALERTS_PAGE, (*filters, limit, offset)),
            ],
        )
        return _page(_ALERTS_COLUMNS, items, _total(count), page, limit)

    @app.get("/api/keywords")
    def keywords(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PER_PAGE, ge=1),
    ) -> dict[str, Any]:
        """Rows of ``keyword_performance``, the ones that find the most posts first."""
        limit, offset = _window(page, per_page)
        count, items = _fetch(
            settings,
            connector,
            [
                (_KEYWORDS_COUNT, ()),
                (_KEYWORDS_PAGE, (limit, offset)),
            ],
        )
        return _page(_KEYWORDS_COLUMNS, items, _total(count), page, limit)

    @app.get("/api/sources")
    def sources() -> dict[str, Any]:
        """Per collector: calls today, failures, last run, quota limit and budget left.

        The list is not paged; the envelope reports page 1 with the default page size.
        """
        items = _fetch(settings, connector, [(_SOURCES, ())])[0]
        return {
            "items": _items(_SOURCES_COLUMNS, items),
            "total": len(items),
            "page": 1,
            "per_page": DEFAULT_PER_PAGE,
        }

    @app.get("/api/logs")
    def logs(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PER_PAGE, ge=1),
        level: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """``system_logs``, newest first, optionally only one level."""
        limit, offset = _window(page, per_page)
        filters: tuple[Any, ...] = (level, level)
        count, items = _fetch(
            settings,
            connector,
            [
                (_LOGS_COUNT, filters),
                (_LOGS_PAGE, (*filters, limit, offset)),
            ],
        )
        return _page(_LOGS_COLUMNS, items, _total(count), page, limit)

    @app.get("/api/performance")
    def performance() -> dict[str, Any]:
        """Hit rate per horizon and per alert type, aggregated by the database.

        One aggregate row answers the three correctness horizons ``alert_performance``
        fills (1d, 3d, 7d) and one aggregate row per alert type answers the 7d rate.
        ``hit_rate`` is ``null`` when a horizon has no alert — the screens render the
        em dash, never ``0 %`` — and is rounded to three decimals otherwise.
        """
        totals_rows, by_type = _fetch(
            settings,
            connector,
            [
                (_PERFORMANCE_TOTALS, ()),
                (_PERFORMANCE_BY_TYPE, ()),
            ],
        )
        alerts, *correct = totals_rows[0] if totals_rows else (0, 0, 0, 0)
        return {
            "horizons": [
                _horizon_row(horizon, int(alerts), int(hit))
                for horizon, hit in zip(_PERFORMANCE_HORIZONS, correct, strict=True)
            ],
            "by_type": [_type_row(*row) for row in by_type],
        }

    return app


def serve(settings: Settings, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Serve the built web/dist under / and the API under /api.

    Args:
        settings: Settings holding ``database_url``.
        host: Interface to bind; the default ``127.0.0.1`` keeps the dashboard local,
            there is no authentication.
        port: TCP port, default 8088.

    Contract:
        * ``web/dist`` is mounted as static files when the directory exists.
        * Without a build, ``GET /`` is a plain 404 whose sentence says to run
          ``ng build first``; the API keeps working.
    """
    app = build_app(settings)
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:

        @app.get("/")
        def not_built() -> PlainTextResponse:
            """Explain the missing build instead of returning a bare 404 page."""
            return PlainTextResponse(_NOT_BUILT, status_code=404)

    logger.info("dashboard on http://%s:%s (web/dist: %s)", host, port, WEB_DIST)
    uvicorn.run(app, host=host, port=port)


def _fetch(
    settings: Settings, connector: Connector, statements: list[_Statement]
) -> list[list[tuple[Any, ...]]]:
    """Run ``statements`` on one connection and return their rows in the same order.

    Args:
        settings: Settings holding ``database_url``.
        connector: Connection factory of the app.
        statements: ``(sql, parameters)`` pairs, executed one after the other.

    Returns:
        One row list per statement; an empty result is an empty list.

    Raises:
        DatabaseUnavailable: If the connection cannot be opened or a statement fails.
            The message of the driver error is never part of the HTTP body.
    """
    connection: Any = None
    try:
        connection = connect(settings.database_url, connector=connector)
        results: list[list[tuple[Any, ...]]] = []
        with connection.cursor() as cursor:
            for statement, parameters in statements:
                cursor.execute(statement, parameters)
                results.append(list(cursor.fetchall()))
        return results
    # boundary: every driver failure is the one documented 503 answer
    except Exception as error:
        raise DatabaseUnavailable from error
    finally:
        if connection is not None:
            connection.close()


def _window(page: int, per_page: int) -> tuple[int, int]:
    """Return the effective ``(limit, offset)`` of a page after the per-page cap.

    Args:
        page: 1-based page number, already validated (``>= 1``).
        per_page: Requested page size; anything above :data:`MAX_PER_PAGE` is capped.

    Returns:
        The page size actually answered and the offset of its first row.
    """
    limit = min(per_page, MAX_PER_PAGE)
    return limit, (page - 1) * limit


def _page(
    columns: tuple[str, ...],
    rows: list[tuple[Any, ...]],
    total: int,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Wrap one page of rows in the documented list envelope."""
    return {
        "items": _items(columns, rows),
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def _items(columns: tuple[str, ...], rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """Name the columns of every row; a ``None`` value stays ``None``."""
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _total(count: list[tuple[Any, ...]]) -> int:
    """Return the number of the count query; a missing row is zero."""
    return int(count[0][0]) if count else 0


def _hit_rate(alerts: int, correct: int) -> float | None:
    """Return ``correct / alerts`` rounded to three decimals, or ``None`` without alerts."""
    if alerts == 0:
        return None
    return round(correct / alerts, 3)


def _horizon_row(horizon: str, alerts: int, correct: int) -> dict[str, Any]:
    """One horizon of the performance answer; a horizon without alerts has a null rate."""
    return {
        "horizon": horizon,
        "alerts": alerts,
        "correct": correct,
        "hit_rate": _hit_rate(alerts, correct),
    }


def _type_row(alert_type: str, alerts: int, correct: int) -> dict[str, Any]:
    """One per-type row, reported for the 7d horizon the correctness columns end at."""
    return {
        "alert_type": alert_type,
        "horizon": _PERFORMANCE_HORIZONS[-1],
        "alerts": int(alerts),
        "correct": int(correct),
        "hit_rate": _hit_rate(int(alerts), int(correct)),
    }
