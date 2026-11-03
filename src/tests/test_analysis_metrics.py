"""Tests for newstrading.analysis.metrics.

``update_daily_metrics`` ports ``AIAnalyzer.update_daily_metrics`` of
``analyzer/main.py``: one ``SELECT id FROM asset`` followed by one insert-select per
asset. The statement is checked whole — the ``ON CONFLICT (asset_id, date) DO UPDATE``
clause is what makes a rerun idempotent, so losing it must break a test. No database
is involved: a fake connection records the statements.
"""

import pytest

from newstrading.analysis.metrics import (
    ASSET_IDS_SQL,
    DAILY_METRICS_SQL,
    MetricsError,
    update_daily_metrics,
)
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)


class FakeCursor:
    """Records every statement and serves the asset ids on ``fetchall``."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement, parameters=None):
        self._connection.statements.append((statement, parameters))
        if self._connection.fail_on and self._connection.fail_on in statement:
            raise RuntimeError("relation does not exist")

    def fetchall(self):
        return [(asset_id,) for asset_id in self._connection.assets]


class FakeConnection:
    """A connection that records commit, rollback and close."""

    def __init__(self, assets=(1,), fail_on=None):
        self.assets = list(assets)
        self.fail_on = fail_on
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


def install(assets=(1,), fail_on=None):
    """Run ``update_daily_metrics`` against a fake connection and return both."""
    connection = FakeConnection(assets=assets, fail_on=fail_on)
    opened = []

    def connector(database_url):
        opened.append(database_url)
        return connection

    touched = update_daily_metrics(SETTINGS, connector=connector)
    return touched, connection, opened


def test_one_statement_per_asset_and_the_asset_count_is_returned():
    """Three assets mean three metric statements, in the order the ids came back."""
    touched, connection, _opened = install(assets=(4, 9, 11))

    assert touched == 3
    assert connection.statements[0] == (ASSET_IDS_SQL, None)
    assert connection.statements[1:] == [
        (DAILY_METRICS_SQL, (4,)),
        (DAILY_METRICS_SQL, (9,)),
        (DAILY_METRICS_SQL, (11,)),
    ]


def test_the_statement_is_the_legacy_upsert():
    """The insert-select aggregates the analyses per day and upserts the row."""
    _touched, connection, _opened = install(assets=(4,))

    statement = connection.statements[1][0]

    assert "INSERT INTO daily_metrics" in statement
    assert "FROM social_posts sp" in statement
    assert "JOIN ai_analysis aa ON sp.id = aa.post_id" in statement
    assert "WHERE sp.asset_id = %s" in statement
    assert "GROUP BY sp.asset_id, DATE(sp.created_at)" in statement
    assert "ON CONFLICT (asset_id, date)" in statement
    assert "DO UPDATE SET" in statement
    for column in (
        "mention_count = EXCLUDED.mention_count",
        "sentiment_avg = EXCLUDED.sentiment_avg",
        "hiring_mentions = EXCLUDED.hiring_mentions",
        "problem_mentions = EXCLUDED.problem_mentions",
        "growth_mentions = EXCLUDED.growth_mentions",
    ):
        assert column in statement


def test_the_aggregations_are_the_legacy_ones():
    """The three category counts and the average are the legacy expressions."""
    _touched, connection, _opened = install(assets=(4,))

    statement = connection.statements[1][0]

    assert "AVG(aa.sentiment_score)" in statement
    assert "SUM(CASE WHEN aa.category = 'Hiring' THEN 1 ELSE 0 END)" in statement
    assert "SUM(CASE WHEN aa.category = 'Problems' THEN 1 ELSE 0 END)" in statement
    assert "SUM(CASE WHEN aa.category = 'Growth' THEN 1 ELSE 0 END)" in statement


def test_no_assets_means_no_metric_statement():
    """An empty ``asset`` table touches nothing and still settles the transaction."""
    touched, connection, _opened = install(assets=())

    assert touched == 0
    assert connection.statements == [(ASSET_IDS_SQL, None)]
    assert connection.commits == 1
    assert connection.closes == 1


def test_the_run_uses_one_connection_and_commits_once():
    """One connection for every asset, one commit at the end, closed afterwards."""
    _touched, connection, opened = install(assets=(4, 9))

    assert opened == [URL]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closes == 1


def test_a_database_error_rolls_back_and_raises_the_named_error():
    """A failing statement rolls the batch back and names the failure."""
    connection = FakeConnection(assets=(4, 9), fail_on="INSERT INTO daily_metrics")

    with pytest.raises(MetricsError):
        update_daily_metrics(SETTINGS, connector=lambda database_url: connection)

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closes == 1


def test_a_failure_while_reading_the_assets_rolls_back_too():
    """The select itself can fail; the run still settles the transaction."""
    connection = FakeConnection(assets=(4,), fail_on="SELECT id FROM asset")

    with pytest.raises(MetricsError):
        update_daily_metrics(SETTINGS, connector=lambda database_url: connection)

    assert connection.rollbacks == 1
    assert connection.commits == 0
