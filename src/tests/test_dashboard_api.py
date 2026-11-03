"""Tests for newstrading.dashboard.api: the six read-only endpoints and ``serve``."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from newstrading.config import Settings
from newstrading.dashboard import api
from newstrading.dashboard.api import DEFAULT_PER_PAGE, MAX_PER_PAGE, build_app, serve

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)

LIST_ROUTES = ("/api/posts", "/api/alerts", "/api/keywords", "/api/logs")


class FakeCursor:
    """A cursor that answers the queued result sets of its connection, in order."""

    def __init__(self, connection):
        self._connection = connection
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement, parameters=None):
        self._connection.statements.append((statement, parameters))
        if self._connection.error is not None:
            raise self._connection.error
        self._result = self._connection.results.pop(0) if self._connection.results else []

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None


class FakeConnection:
    """A connection over a fixed list of result sets, with no database behind it."""

    def __init__(self, *results, error=None):
        self.statements = []
        self.results = list(results)
        self.error = error
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closes += 1


def build_client(*results, error=None):
    """Return a test client and the connection its fake connector hands out."""
    connection = FakeConnection(*results, error=error)
    return TestClient(build_app(SETTINGS, connector=lambda url: connection)), connection


def test_overview_returns_the_counters_and_the_database_size():
    """One row becomes the documented overview object, nulls included."""
    last_run = datetime(2026, 11, 3, 6, 15)
    client, _ = build_client(((3, 120, 117, 7, 2, last_run, 123456),))

    response = client.get("/api/overview")

    assert response.status_code == 200
    assert response.json() == {
        "assets": 3,
        "posts": 120,
        "analyses": 117,
        "alerts": 7,
        "open_alerts": 2,
        "last_collector_run": last_run.isoformat(),
        "database_size_bytes": 123456,
    }


def test_overview_on_an_empty_database_returns_zeros_and_a_null_last_run():
    """No rows at all is an honest empty overview, not an error."""
    client, _ = build_client(())

    response = client.get("/api/overview")

    assert response.status_code == 200
    assert response.json() == {
        "assets": 0,
        "posts": 0,
        "analyses": 0,
        "alerts": 0,
        "open_alerts": 0,
        "last_collector_run": None,
        "database_size_bytes": None,
    }


def test_posts_returns_a_page_of_posts_joined_with_their_analysis():
    """A page carries the count query first and the rows second."""
    created = datetime(2026, 11, 2, 9, 30)
    rows = [
        (
            17,
            2,
            "PLTR",
            "rss",
            "Palantir wins",
            "https://example.com/17",
            42,
            created,
            "positive",
            0.8,
            "Growth",
            "A contract win.",
        ),
    ]
    client, _ = build_client(((1,),), rows)

    response = client.get("/api/posts")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": 17,
                "asset_id": 2,
                "asset": "PLTR",
                "source": "rss",
                "title": "Palantir wins",
                "url": "https://example.com/17",
                "score": 42,
                "created_at": created.isoformat(),
                "sentiment": "positive",
                "sentiment_score": 0.8,
                "category": "Growth",
                "summary": "A contract win.",
            }
        ],
        "total": 1,
        "page": 1,
        "per_page": DEFAULT_PER_PAGE,
    }


def test_posts_preserves_a_missing_analysis_and_a_missing_asset_as_null():
    """``NULL`` stays ``null`` in JSON: the UI must be able to say "no data"."""
    created = datetime(2026, 11, 2, 9, 30)
    rows = [(18, None, None, "newsapi", None, None, None, created, None, None, None, None)]
    client, _ = build_client(((1,),), rows)

    items = client.get("/api/posts").json()["items"]

    assert items == [
        {
            "id": 18,
            "asset_id": None,
            "asset": None,
            "source": "newsapi",
            "title": None,
            "url": None,
            "score": None,
            "created_at": created.isoformat(),
            "sentiment": None,
            "sentiment_score": None,
            "category": None,
            "summary": None,
        }
    ]


def test_posts_passes_page_filters_and_the_window_to_the_query():
    """``page``/``per_page`` become LIMIT/OFFSET; the filters reach the statement."""
    client, connection = build_client(((0,),), [])

    response = client.get("/api/posts?page=2&per_page=10&asset_id=7&source=rss")

    assert response.json() == {"items": [], "total": 0, "page": 2, "per_page": 10}
    _statement, parameters = connection.statements[1]
    assert 7 in parameters
    assert "rss" in parameters
    assert parameters[-2:] == (10, 10)


def test_alerts_returns_a_page_with_the_7d_performance():
    """An alert carries its 7-day return and correctness; a missing one stays null."""
    stamped = datetime(2026, 11, 1, 14, 0)
    rows = [
        (5, 2, "PLTR", "sentiment_spike", "high", "Score jumped", 0.91, stamped, True, 0.042, True),
        (6, 2, "PLTR", "volume_spike", "low", "Quiet day", 0.55, stamped, False, None, None),
    ]
    client, _ = build_client(((2,),), rows)

    response = client.get("/api/alerts")

    assert response.json() == {
        "items": [
            {
                "id": 5,
                "asset_id": 2,
                "asset": "PLTR",
                "alert_type": "sentiment_spike",
                "severity": "high",
                "description": "Score jumped",
                "confidence_score": 0.91,
                "timestamp": stamped.isoformat(),
                "notified": True,
                "return_7d": 0.042,
                "correct_7d": True,
            },
            {
                "id": 6,
                "asset_id": 2,
                "asset": "PLTR",
                "alert_type": "volume_spike",
                "severity": "low",
                "description": "Quiet day",
                "confidence_score": 0.55,
                "timestamp": stamped.isoformat(),
                "notified": False,
                "return_7d": None,
                "correct_7d": None,
            },
        ],
        "total": 2,
        "page": 1,
        "per_page": DEFAULT_PER_PAGE,
    }


def test_alerts_passes_the_severity_filter_to_count_and_page():
    """The severity filter narrows both the total and the page."""
    client, connection = build_client(((0,),), [])

    response = client.get("/api/alerts?severity=high")

    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": DEFAULT_PER_PAGE}
    assert all("high" in parameters for _statement, parameters in connection.statements)


def test_keywords_returns_a_page_of_keyword_performance():
    """A keyword row carries its asset, the posts it found and its timestamps."""
    first_seen = datetime(2026, 10, 1, 8, 0)
    last_found = datetime(2026, 11, 2, 20, 0)
    rows = [(9, 2, "PLTR", "palantir", 31, last_found, first_seen)]
    client, _ = build_client(((1,),), rows)

    response = client.get("/api/keywords")

    assert response.json() == {
        "items": [
            {
                "id": 9,
                "asset_id": 2,
                "asset": "PLTR",
                "keyword": "palantir",
                "posts_found": 31,
                "last_found_at": last_found.isoformat(),
                "first_seen_at": first_seen.isoformat(),
            }
        ],
        "total": 1,
        "page": 1,
        "per_page": DEFAULT_PER_PAGE,
    }


def test_sources_lists_every_collector_with_its_remaining_budget():
    """Calls, failures, last run and the quota limit plus the remaining budget."""
    last_run = datetime(2026, 11, 3, 7, 0)
    rows = [
        ("newsapi", last_run, 3, 12, 1, 100, 88, True),
        ("rss", None, 0, 40, 0, None, None, True),
    ]
    client, _ = build_client(rows)

    response = client.get("/api/sources")

    assert response.json() == {
        "items": [
            {
                "collector": "newsapi",
                "last_run": last_run.isoformat(),
                "total_errors": 3,
                "calls_today": 12,
                "failures_today": 1,
                "quota_limit": 100,
                "quota_remaining": 88,
                "enabled": True,
            },
            {
                "collector": "rss",
                "last_run": None,
                "total_errors": 0,
                "calls_today": 40,
                "failures_today": 0,
                "quota_limit": None,
                "quota_remaining": None,
                "enabled": True,
            },
        ],
        "total": 2,
        "page": 1,
        "per_page": DEFAULT_PER_PAGE,
    }


def test_sources_on_a_fresh_database_returns_no_items():
    """No configured collector is an empty list, not an error."""
    client, _ = build_client([])

    response = client.get("/api/sources")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": DEFAULT_PER_PAGE}


def test_logs_returns_a_page_of_system_logs():
    """A log row carries its level, logger, service and the exception text."""
    stamped = datetime(2026, 11, 3, 6, 59)
    rows = [
        (
            77,
            stamped,
            "ERROR",
            "newstrading.collectors.rss",
            "collect",
            "feed exploded",
            "collect_for_asset",
            120,
            "Traceback: boom",
            {"source": "rss"},
        )
    ]
    client, _ = build_client(((1,),), rows)

    response = client.get("/api/logs")

    assert response.json() == {
        "items": [
            {
                "id": 77,
                "timestamp": stamped.isoformat(),
                "level": "ERROR",
                "logger": "newstrading.collectors.rss",
                "service": "collect",
                "message": "feed exploded",
                "function": "collect_for_asset",
                "line_number": 120,
                "exception": "Traceback: boom",
                "metadata": {"source": "rss"},
            }
        ],
        "total": 1,
        "page": 1,
        "per_page": DEFAULT_PER_PAGE,
    }


def test_logs_passes_the_level_filter_to_count_and_page():
    """The level filter narrows both the total and the page."""
    client, connection = build_client(((0,),), [])

    response = client.get("/api/logs?level=ERROR")

    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": DEFAULT_PER_PAGE}
    assert all("ERROR" in parameters for _statement, parameters in connection.statements)


@pytest.mark.parametrize("route", LIST_ROUTES)
def test_an_empty_table_answers_an_empty_page(route):
    """``{"items": [], "total": 0, …}`` is the answer of an empty table, not an error."""
    client, _ = build_client(((0,),), [])

    response = client.get(route)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "per_page": DEFAULT_PER_PAGE}


def test_page_zero_is_a_422_that_names_the_parameter():
    """``page=0`` is invalid and the validation error names ``page``."""
    client, connection = build_client(((0,),), [])

    response = client.get("/api/posts?page=0")

    assert response.status_code == 422
    assert "page" in response.text
    assert connection.statements == []


def test_per_page_above_the_cap_is_capped_to_200():
    """``per_page=500`` is capped, and the answer reports the effective page size."""
    client, connection = build_client(((0,),), [])

    response = client.get("/api/posts?per_page=500")

    assert response.status_code == 200
    assert response.json()["per_page"] == MAX_PER_PAGE
    _statement, parameters = connection.statements[1]
    assert parameters[-2:] == (MAX_PER_PAGE, 0)


def test_per_page_zero_is_a_422_that_names_the_parameter():
    """A page size of zero is invalid like a page number of zero."""
    client, _ = build_client(((0,),), [])

    response = client.get("/api/keywords?per_page=0")

    assert response.status_code == 422
    assert "per_page" in response.text


def test_a_connector_that_cannot_connect_answers_503_without_a_traceback():
    """A broken database is one documented 503 body, never a stack trace."""

    def broken(url):
        raise RuntimeError("could not connect to db.internal:5432/newstrading")

    client = TestClient(build_app(SETTINGS, connector=broken))

    response = client.get("/api/overview")

    assert response.status_code == 503
    assert response.json() == {"error": "database unavailable"}
    assert "Traceback" not in response.text
    assert "db.internal" not in response.text


def test_a_failing_query_answers_503_without_a_traceback():
    """A statement that fails is the same documented 503 body."""
    client, _ = build_client(error=RuntimeError('relation "social_posts" does not exist'))

    response = client.get("/api/posts")

    assert response.status_code == 503
    assert response.json() == {"error": "database unavailable"}
    assert "social_posts" not in response.text


def test_the_app_has_no_write_route():
    """Read-only by construction: no route accepts POST, PUT, PATCH or DELETE."""
    app = build_app(SETTINGS, connector=lambda url: FakeConnection())

    methods = {
        method for route in app.routes for method in (getattr(route, "methods", None) or set())
    }

    assert methods <= {"GET", "HEAD"}


def test_the_six_api_routes_are_registered_under_api():
    """Every documented endpoint is a GET route under ``/api``."""
    app = build_app(SETTINGS, connector=lambda url: FakeConnection())

    paths = {
        route.path for route in app.routes if "GET" in (getattr(route, "methods", None) or set())
    }

    assert {
        "/api/overview",
        "/api/posts",
        "/api/alerts",
        "/api/keywords",
        "/api/sources",
        "/api/logs",
    } <= paths


def test_serve_without_a_web_build_still_answers_the_api_and_explains_the_404(
    monkeypatch, tmp_path
):
    """Without ``web/dist`` the API works and ``/`` says which command is missing."""
    captured = {}
    monkeypatch.setattr(
        api.uvicorn, "run", lambda app, host, port: captured.update(app=app, host=host, port=port)
    )
    monkeypatch.setattr(api, "WEB_DIST", tmp_path / "missing")
    connection = FakeConnection(
        ((0, 0, 0, 0, 0, None, None),),
    )
    monkeypatch.setattr(api, "connect", lambda url, connector=None: connection)

    serve(SETTINGS)

    assert (captured["host"], captured["port"]) == ("127.0.0.1", 8088)
    client = TestClient(captured["app"])
    assert client.get("/api/overview").status_code == 200
    response = client.get("/")
    assert response.status_code == 404
    assert "run ng build first" in response.text


def test_serve_mounts_the_built_app_at_the_root(monkeypatch, tmp_path):
    """``web/dist`` is served under ``/`` next to the API."""
    captured = {}
    monkeypatch.setattr(api.uvicorn, "run", lambda app, host, port: captured.update(app=app))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>newstrading dashboard</h1>", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    serve(SETTINGS, port=9099)

    client = TestClient(captured["app"])
    response = client.get("/")
    assert response.status_code == 200
    assert "newstrading dashboard" in response.text


def test_the_command_default_port_matches_the_server_default():
    """The CLI and the server must not drift apart on the default port."""
    from newstrading import cli

    assert cli.DEFAULT_DASHBOARD_PORT == api.DEFAULT_PORT
