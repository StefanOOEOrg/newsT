"""Tests for newstrading.keywords."""

import psycopg2
import pytest

from newstrading.config import Settings
from newstrading.keywords import KeywordTracker

URL = "postgresql://app:pw@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")


class FakeCursor:
    """Records statements; raises when the connection is told to fail."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        self._connection.statements.append((query, params))
        if self._connection.fail_with is not None:
            raise self._connection.fail_with

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double with statement log and failure switch."""

    def __init__(self, fail_with=None):
        self.fail_with = fail_with
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


def connector(fake, calls=None):
    """Build a connector that returns ``fake`` and counts how often it was asked."""

    def _connector(url):
        if calls is not None:
            calls.append(url)
        return fake

    return _connector


def test_matching_is_case_insensitive_and_keeps_the_original_spelling():
    """Keywords come back as they are stored on the asset, not lower-cased."""
    matched = KeywordTracker.identify_keyword_matches(
        "Genpact announces Hiring push", ["genpact", "HIRING", "job opening"]
    )

    assert matched == ["genpact", "HIRING"]


def test_matching_is_by_substring():
    """The legacy rule: ``snow`` matches inside ``Snowflake``."""
    assert KeywordTracker.identify_keyword_matches("Snowflake beats estimates", ["snow"]) == [
        "snow"
    ]


def test_matching_returns_keywords_in_the_order_of_the_input():
    """The caller relies on a stable order for its statistics."""
    matched = KeywordTracker.identify_keyword_matches(
        "palantir and genpact", ["palantir", "genpact"]
    )

    assert matched == ["palantir", "genpact"]


@pytest.mark.parametrize(("text", "keywords"), [("", ["genpact"]), ("text", []), ("", [])])
def test_matching_without_text_or_keywords_returns_nothing(text, keywords):
    """Empty input never matches."""
    assert KeywordTracker.identify_keyword_matches(text, keywords) == []


def test_record_writes_one_lower_cased_upsert_per_keyword():
    """Every hit is counted separately, the column is the lower-cased keyword."""
    fake = FakeConnection()

    KeywordTracker(SETTINGS, connector=connector(fake)).record_keyword_hit(7, ["Genpact", "HIRING"])

    assert len(fake.statements) == 2
    assert "INSERT INTO keyword_performance" in fake.statements[0][0]
    assert fake.statements[0][1] == (7, "genpact")
    assert fake.statements[1][1] == (7, "hiring")
    assert fake.commits == 1
    assert fake.rollbacks == 0


def test_record_without_keywords_opens_no_connection():
    """Nothing to record means no database work at all."""
    calls = []

    KeywordTracker(SETTINGS, connector=connector(FakeConnection(), calls)).record_keyword_hit(7, [])

    assert calls == []


def test_record_swallows_database_errors():
    """Statistics are best effort: rollback, no exception."""
    fake = FakeConnection(fail_with=psycopg2.OperationalError("table is gone"))

    KeywordTracker(SETTINGS, connector=connector(fake)).record_keyword_hit(7, ["genpact"])

    assert fake.commits == 0
    assert fake.rollbacks == 1
