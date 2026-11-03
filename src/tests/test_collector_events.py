"""Tests for newstrading.collectors.events."""

import inspect
import json
from datetime import UTC, date, datetime

import pytest
import requests

from newstrading.collectors import Collector, Event, EventCollector, EventStore
from newstrading.collectors import events as events_module
from newstrading.collectors.models import Asset
from newstrading.config import Settings
from newstrading.rate_limiter import RateLimitDecision

CALENDAR_URL = "https://www.alphavantage.co/query"
ASSET = Asset(id=7, name="Tesla", ticker="TSLA", keywords=("tesla",))
TODAY = date(2026, 11, 2)
SETTINGS = Settings(
    database_url="postgresql://user:***@localhost:5432/newstrading",
    alphavantage_api_key="alpha-key",
)

CALENDAR_HEADER = "symbol,name,reportDate,fiscalDateEnding,estimate,currency"


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """Pin the legacy past-event filter so the rows below stay in the future."""
    monkeypatch.setattr(events_module, "today", lambda: TODAY)


class FakeResponse:
    """The slice of ``requests.Response`` the collector reads."""

    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    @property
    def text(self):
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)


class FakeHttp:
    """HTTP seam: one prepared response per call, in order; records the calls."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(
            {"url": url, "params": kwargs.get("params"), "timeout": kwargs.get("timeout")}
        )
        result = self._responses[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


class FakeLimiter:
    """Quota seam: answers a fixed decision and records what was booked."""

    def __init__(self, allowed=True, reason="daily quota exhausted"):
        self.decision = RateLimitDecision(allowed=allowed, reason=reason, wait_seconds=0)
        self.checks = 0
        self.records = []

    def can_make_request(self):
        self.checks += 1
        return self.decision

    def record_request(self, **kwargs):
        self.records.append(kwargs)


def calendar_csv(*rows):
    """Build the CSV body Alpha Vantage's earnings calendar returns."""
    return "\n".join([CALENDAR_HEADER, *rows])


def calendar_row(report_date, *, fiscal="2026-12-31", estimate="1.25"):
    """One earnings calendar row."""
    return f"TSLA,Tesla Inc,{report_date},{fiscal},{estimate},USD"


def collect(*responses, settings=SETTINGS, limiter=None):
    """Collect the events of the fixture asset and return (events, http)."""
    http = FakeHttp(*responses)
    collector = EventCollector(settings, http=http, limiter=limiter)
    return collector.collect_for_asset(ASSET), http


def test_the_calendar_source_is_asked_and_duplicate_rows_collapse():
    """Calendar rows become events; a repeated report date keeps only the first row."""
    calendar = calendar_csv(
        calendar_row("2027-01-27"),
        calendar_row("2027-01-27"),
        calendar_row("2027-04-28", fiscal="2027-03-31", estimate="1.10"),
    )

    events, http = collect(FakeResponse(calendar))

    assert len(http.calls) == 1
    assert [call["params"]["function"] for call in http.calls] == ["EARNINGS_CALENDAR"]
    assert [event.event_date for event in events] == [
        datetime(2027, 1, 27, tzinfo=UTC),
        datetime(2027, 4, 28, tzinfo=UTC),
    ]
    assert {event.event_type for event in events} == {"earnings"}
    assert {event.title for event in events} == {"Earnings report for Tesla"}
    assert {event.source for event in events} == {"alphavantage"}
    assert {event.asset_id for event in events} == {7}


def test_the_documented_query_parameters_reach_http():
    """The calendar feed is asked for the ticker with the key, on the documented URL."""
    events, http = collect(FakeResponse(calendar_csv()))

    assert events == []
    assert len(http.calls) == 1
    for call in http.calls:
        assert call["url"] == CALENDAR_URL
        assert call["timeout"] == 10
        assert call["params"]["symbol"] == "TSLA"
        assert call["params"]["apikey"] == "alpha-key"
        assert call["params"]["function"] == "EARNINGS_CALENDAR"


def test_the_event_date_is_timezone_aware_utc():
    """A date-only source row becomes a UTC timestamp."""
    events, _ = collect(FakeResponse(calendar_csv(calendar_row("2027-01-27"))))

    assert len(events) == 1
    assert events[0].event_date == datetime(2027, 1, 27, tzinfo=UTC)
    assert events[0].event_date.utcoffset().total_seconds() == 0


def test_a_row_without_a_date_is_skipped_and_the_others_survive():
    """The ``event_date`` column is ``NOT NULL``, so a dated row without a day is dropped."""
    calendar = calendar_csv(
        calendar_row(""),
        calendar_row("2027-01-27", fiscal="2026-12-31", estimate="1.25"),
    )

    events, _ = collect(FakeResponse(calendar))

    assert [event.event_date for event in events] == [datetime(2027, 1, 27, tzinfo=UTC)]


def test_the_calendar_metadata_travels_in_details():
    """The free-form payload carries what the source row said."""
    events, _ = collect(
        FakeResponse(calendar_csv(calendar_row("2027-01-27", fiscal="2026-12-31", estimate="1.25")))
    )

    assert events[0].details == {
        "fiscal_date_ending": "2026-12-31",
        "eps_estimate": "1.25",
        "symbol": "TSLA",
    }


def test_a_missing_api_key_yields_no_events_without_a_request():
    """The key is optional at construction; without it there is nothing to ask."""
    settings = Settings(
        database_url=SETTINGS.database_url,
    )

    events, http = collect(settings=settings)

    assert events == []
    assert http.calls == []


@pytest.mark.parametrize("status_code", [500, 429])
def test_an_error_status_yields_no_events_and_records_a_failure(status_code):
    """The call fails: no events, one failed usage row."""
    limiter = FakeLimiter()

    events, _ = collect(FakeResponse("", status_code=status_code), limiter=limiter)

    assert events == []
    assert len(limiter.records) == 1
    assert limiter.records[0]["success"] is False
    assert limiter.records[0]["status_code"] == status_code


def test_a_network_error_yields_no_events_and_does_not_raise():
    """A transport failure is logged and booked, never raised."""
    limiter = FakeLimiter()

    events, _ = collect(requests.ConnectionError("connection refused"), limiter=limiter)

    assert events == []
    assert [record["success"] for record in limiter.records] == [False]


def test_a_denied_quota_yields_no_events_and_records_nothing():
    """The quota check runs first: no HTTP call, no usage row for the denial."""
    limiter = FakeLimiter(allowed=False)

    events, http = collect(
        FakeResponse(calendar_csv(calendar_row("2027-01-27"))),
        limiter=limiter,
    )

    assert events == []
    assert http.calls == []
    assert limiter.records == []


def test_a_successful_call_is_recorded_with_its_status():
    """An allowed call is booked as a success with status 200."""
    limiter = FakeLimiter()

    collect(FakeResponse(calendar_csv()), limiter=limiter)

    assert [record["success"] for record in limiter.records] == [True]
    assert [record["status_code"] for record in limiter.records] == [200]


def test_without_a_limiter_nothing_is_tracked():
    """``limiter=None`` means no quota bookkeeping, not a skipped call."""
    events, http = collect(FakeResponse(calendar_csv(calendar_row("2027-01-27"))))

    assert len(events) == 1
    assert len(http.calls) == 1


def test_the_event_collector_fits_the_collector_protocol():
    """The class offers the collector surface, structurally."""
    collector = EventCollector(SETTINGS)
    required = {name for name in dir(Collector) if not name.startswith("_")}

    assert required <= set(dir(collector))
    assert collector.name == "events"
    assert list(inspect.signature(collector.collect_for_asset).parameters) == ["asset"]


class FakeCursor:
    """Records statements and reports a canned row count."""

    def __init__(self, connection):
        self._connection = connection
        self.rowcount = connection.rowcount

    def execute(self, query, params=None):
        self._connection.statements.append((query, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double: records the transaction and the statements."""

    def __init__(self, rowcount=0):
        self.rowcount = rowcount
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def store(fake):
    """Build an ``EventStore`` over ``fake`` and record how often it connects."""
    opened = []

    def connector(url):
        opened.append(url)
        return fake

    return EventStore(SETTINGS, connector=connector), opened


def event(**overrides):
    """One event as the collector returns it."""
    values = {
        "asset_id": 7,
        "event_type": "earnings",
        "title": "Earnings report for Tesla",
        "event_date": datetime(2027, 1, 27, tzinfo=UTC),
        "source": "alphavantage",
        "details": {"fiscal_date_ending": "2026-12-31", "eps_estimate": "1.25"},
    }
    values.update(overrides)
    return Event(**values)


def test_save_issues_one_idempotent_insert_and_returns_the_row_count():
    """One ``INSERT … ON CONFLICT DO NOTHING`` for the batch, the row count comes back."""
    fake = FakeConnection(rowcount=2)
    event_store, _ = store(fake)

    saved = event_store.save([event(), event(title="Earnings report for Tesla (Q2)")])

    assert saved == 2
    assert len(fake.statements) == 1
    query, params = fake.statements[0]
    assert "INSERT INTO asset_events" in query
    assert "ON CONFLICT DO NOTHING" in query
    assert query.count("ON CONFLICT") == 1
    assert len(params) == 12
    assert params[0:3] == (7, "earnings", date(2027, 1, 27))
    assert params[3] == "Earnings report for Tesla"
    assert params[4] == "alphavantage"
    assert fake.commits == 1
    assert fake.closes == 1


def test_save_maps_the_details_to_json():
    """``details`` is stored in the ``metadata`` column; an empty dict stays ``NULL``."""
    fake = FakeConnection(rowcount=2)
    event_store, _ = store(fake)

    event_store.save([event(), event(title="Manual note", details={})])

    _, params = fake.statements[0]
    assert params[5].adapted == {
        "fiscal_date_ending": "2026-12-31",
        "eps_estimate": "1.25",
    }
    assert params[11] is None


def test_a_duplicate_returns_zero():
    """``ON CONFLICT DO NOTHING`` reports no rows for an already stored event."""
    fake = FakeConnection(rowcount=0)
    event_store, _ = store(fake)

    assert event_store.save([event()]) == 0


def test_an_empty_sequence_returns_zero_without_touching_the_database():
    """No events, no connection, no statement."""
    fake = FakeConnection(rowcount=1)
    event_store, opened = store(fake)

    assert event_store.save([]) == 0
    assert opened == []
    assert fake.statements == []
