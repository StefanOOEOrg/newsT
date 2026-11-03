"""Tests for newstrading.collectors.posts."""

from datetime import UTC, datetime

import psycopg2
import pytest

from newstrading.collectors.models import Post
from newstrading.collectors.posts import PostStore
from newstrading.config import Settings

URL = "postgresql://app:pw@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)
CREATED = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)


def make_post(post_id="abc", asset_id=1, title="Genpact announces hiring", content="body"):
    return Post(
        asset_id=asset_id,
        source="rss_google_news",
        post_id=post_id,
        author="Test Feed",
        title=title,
        content=content,
        url="https://example.com/a",
        score=0,
        created_at=CREATED,
    )


class FakeCursor:
    """Cursor double: records statements, replays asset keywords."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        self._connection.statements.append((query, params))
        if self._connection.fail_with is not None:
            raise self._connection.fail_with
        if "FROM asset" in query:
            self._connection.row = (self._connection.keywords[params[0]],)

    def fetchone(self):
        return self._connection.row

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double with per-asset keywords and a failure switch."""

    def __init__(self, keywords=None, fail_with=None):
        self.keywords = keywords or {}
        self.fail_with = fail_with
        self.row = None
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


class FakeTracker:
    """Tracks the matching calls and the recorded hits."""

    def __init__(self, matches=("genpact",)):
        self.matches = list(matches)
        self.matched_for = []
        self.hits = []

    def identify_keyword_matches(self, text, keywords):
        self.matched_for.append((text, tuple(keywords)))
        return list(self.matches)

    def record_keyword_hit(self, asset_id, keywords):
        self.hits.append((asset_id, tuple(keywords)))


def connector(fake, calls=None):
    """Build a connector returning ``fake`` and counting its calls."""

    def _connector(url):
        if calls is not None:
            calls.append(url)
        return fake

    return _connector


def insert_returning(count, seen=None):
    """Build an insert strategy that reports ``count`` new rows."""

    def _insert(cursor, values):
        if seen is not None:
            seen.append(list(values))
        return count

    return _insert


def test_no_posts_opens_no_connection():
    """Nothing to store means no work at all."""
    calls = []
    tracker = FakeTracker()

    saved = PostStore(
        SETTINGS,
        keyword_tracker=tracker,
        insert=insert_returning(0),
        connector=connector(FakeConnection(), calls),
    ).save([])

    assert saved == 0
    assert calls == []
    assert tracker.hits == []


def test_keywords_are_read_once_per_distinct_asset():
    """Two posts of the same asset cost one query, not two."""
    fake = FakeConnection(keywords={1: ["genpact"], 2: ["palantir"]})

    PostStore(
        SETTINGS,
        keyword_tracker=FakeTracker(),
        insert=insert_returning(3),
        connector=connector(fake),
    ).save([make_post("a", 1), make_post("b", 1), make_post("c", 2)])

    asset_queries = [params for query, params in fake.statements if "FROM asset" in query]
    assert asset_queries == [(1,), (2,)]


def test_rows_are_inserted_in_column_order_with_matched_keywords():
    """The last column carries the keywords the tracker matched."""
    fake = FakeConnection(keywords={1: ["genpact", "hiring"]})
    seen = []

    PostStore(
        SETTINGS,
        keyword_tracker=FakeTracker(["genpact", "hiring"]),
        insert=insert_returning(1, seen),
        connector=connector(fake),
    ).save([make_post("abc", 1)])

    row = seen[0][0]
    assert row == (
        1,
        "rss_google_news",
        "abc",
        "Test Feed",
        "Genpact announces hiring",
        "body",
        "https://example.com/a",
        0,
        CREATED,
        ["genpact", "hiring"],
    )


def test_matching_uses_title_and_content_with_the_asset_keywords():
    """The text handed to the tracker is the joined title and body."""
    fake = FakeConnection(keywords={1: ["genpact"]})
    tracker = FakeTracker()

    PostStore(
        SETTINGS, keyword_tracker=tracker, insert=insert_returning(1), connector=connector(fake)
    ).save([make_post()])

    text, keywords = tracker.matched_for[0]
    assert text == "Genpact announces hiring body"
    assert keywords == ("genpact",)


def test_saved_count_comes_from_the_insert():
    """The number of new rows is what the insert reports."""
    fake = FakeConnection(keywords={1: ["genpact"]})

    saved = PostStore(
        SETTINGS,
        keyword_tracker=FakeTracker(),
        insert=insert_returning(2),
        connector=connector(fake),
    ).save([make_post("a"), make_post("b")])

    assert saved == 2
    assert fake.commits == 1


def test_keyword_hits_are_recorded_only_for_saved_posts():
    """A post that was already stored must not inflate the keyword counters."""
    fake = FakeConnection(keywords={1: ["genpact"]})
    tracker = FakeTracker(["genpact"])

    PostStore(
        SETTINGS, keyword_tracker=tracker, insert=insert_returning(0), connector=connector(fake)
    ).save([make_post()])

    assert tracker.hits == []

    PostStore(
        SETTINGS, keyword_tracker=tracker, insert=insert_returning(1), connector=connector(fake)
    ).save([make_post()])

    assert tracker.hits == [(1, ("genpact",))]


def test_a_failing_insert_rolls_back_and_raises():
    """A lost post is a real loss — unlike a statistics row, this is not swallowed."""
    fake = FakeConnection(
        keywords={1: ["genpact"]}, fail_with=psycopg2.OperationalError("disk full")
    )

    with pytest.raises(psycopg2.OperationalError):
        PostStore(SETTINGS, keyword_tracker=FakeTracker(), connector=connector(fake)).save(
            [make_post()]
        )

    assert fake.rollbacks == 1
    assert fake.commits == 0
