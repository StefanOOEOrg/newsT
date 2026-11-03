"""Tests for newstrading.collectors.assets."""

import psycopg2
import pytest

from newstrading.collectors.assets import AssetStore
from newstrading.collectors.models import Asset
from newstrading.config import Settings
from newstrading.db import DatabaseError

URL = "postgresql://app:pw@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)


class FakeCursor:
    """Records every statement and replays canned rows."""

    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def execute(self, query, params=None):
        self._connection.statements.append((query, params))
        if self._connection.fail_with is not None:
            raise self._connection.fail_with
        self._rows = list(self._connection.rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double with canned rows and a failure switch."""

    def __init__(self, rows=(), fail_with=None):
        self.rows = rows
        self.fail_with = fail_with
        self.statements = []
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closes += 1


def connector(fake):
    """Build a connector returning ``fake``."""

    def _connector(url):
        return fake

    return _connector


def test_default_call_uses_the_dss_order_and_maps_rows():
    """The regular set is ordered by signal strength and becomes Asset objects."""
    fake = FakeConnection(rows=[(1, "Genpact", "G", ["genpact", "hiring"])])

    assets = AssetStore(SETTINGS, connector=connector(fake)).list_for_collection()

    assert assets == [Asset(id=1, name="Genpact", ticker="G", keywords=("genpact", "hiring"))]
    query = fake.statements[0][0]
    assert "abs_dss" in query
    assert "ORDER BY abs_dss DESC, a.name" in query


def test_dss_query_states_the_filter_and_the_today_window():
    """The signal count is limited to today's alerts and to the regular statuses."""
    fake = FakeConnection(rows=[])

    AssetStore(SETTINGS, connector=connector(fake)).list_for_collection()

    query = " ".join(fake.statements[0][0].split())
    assert "CURRENT_DATE" in query
    assert "alert_type = 'long_signal'" in query
    assert "alert_type = 'short_signal'" in query
    assert "initialization_status IN ('completed', 'in_progress')" in query


def test_without_dss_the_assets_are_ordered_by_name():
    """Turning the priority off falls back to a plain name order."""
    fake = FakeConnection(rows=[(2, "Palantir", "PLTR", ["palantir"])])

    AssetStore(SETTINGS, connector=connector(fake)).list_for_collection(prioritize_by_dss=False)

    query = " ".join(fake.statements[0][0].split())
    assert "abs_dss" not in query
    assert "ORDER BY name" in query


def test_pending_initialisation_selects_only_pending_assets():
    """The backfill path asks for the pending rows and nothing else."""
    fake = FakeConnection(rows=[(3, "Snowflake", "SNOW", ["snowflake"])])

    assets = AssetStore(SETTINGS, connector=connector(fake)).list_for_collection(
        include_pending_init=True
    )

    assert assets[0].ticker == "SNOW"
    query = " ".join(fake.statements[0][0].split())
    assert "initialization_status = 'pending'" in query
    assert "ORDER BY" not in query


def test_keywords_become_a_tuple():
    """The model is immutable; a list from the driver would break that promise."""
    fake = FakeConnection(rows=[(1, "Genpact", "G", ["genpact", "hiring", "job opening"])])

    assets = AssetStore(SETTINGS, connector=connector(fake)).list_for_collection()

    assert isinstance(assets[0].keywords, tuple)
    assert assets[0].keywords == ("genpact", "hiring", "job opening")


def test_exists_reports_a_stored_post():
    """A row for the post id means it was already collected."""
    fake = FakeConnection(rows=[(1,)])

    assert AssetStore(SETTINGS, connector=connector(fake)).exists("abc") is True
    query, params = fake.statements[0]
    assert "FROM social_posts" in query
    assert params == ("abc",)


def test_exists_reports_a_new_post():
    """No row means the post is new."""
    fake = FakeConnection(rows=[])

    assert AssetStore(SETTINGS, connector=connector(fake)).exists("abc") is False


def test_a_broken_connection_reaches_the_caller():
    """Without assets there is nothing to collect, so a failed connect is not swallowed."""

    def failing_connector(url):
        raise psycopg2.OperationalError("connection refused")

    with pytest.raises(DatabaseError):
        AssetStore(SETTINGS, connector=failing_connector).list_for_collection()


def test_a_broken_statement_reaches_the_caller():
    """A failing query surfaces as the driver error instead of an empty asset list."""
    fake = FakeConnection(fail_with=psycopg2.OperationalError("relation does not exist"))

    with pytest.raises(psycopg2.OperationalError):
        AssetStore(SETTINGS, connector=connector(fake)).list_for_collection()
