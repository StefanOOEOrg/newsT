"""Tests for the throttled parallel execution of the analyze pass.

The pass calls the model up to ``LLM_MAX_CONCURRENCY`` times at once and still stores one
row per post in the order the database returned the rows (issue #52): ``1`` and ``3``
write the same rows in the same order, only the run time differs. Every case here drives
a fake connection, a fake completion and a fake prompt builder, so no test touches a
database, a socket or a real wait.

The completion doubles overlap on purpose: one waits until ``N`` calls are in flight, the
other answers the first post last. A serial pass fails them by timing out, which is what
makes them a test of the parallelism and of the order at once.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime

from newstrading.analysis.prompt import PromptBuilder
from newstrading.analysis.service import Analyzer
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)

CREATED_AT = datetime(2026, 1, 5, 14, 30)

WAIT = 5.0
"""Seconds a double waits for the calls it expects before it gives up."""

TEMPLATE = "Analyze {asset_name} ({ticker}): {text_to_analyze}"


def answer_for(source_post_id: str) -> str:
    """A model answer whose summary and key topics name the post it belongs to."""
    return (
        '{"sentiment": "positive", "sentiment_score": 0.5, "category": "Growth", '
        f'"key_topics": ["{source_post_id}"], "summary": "answer for {source_post_id}", '
        '"special_events": []}'
    )


def post_row(row_id: int, source_post_id: str) -> tuple:
    """One joined row, in the column order of the select."""
    return (
        row_id,
        7,
        "rss_google_news",
        source_post_id,
        "Test Feed",
        "Tesla hiring push",
        "Tesla said it will hire 2,000 engineers.",
        "https://example.com/a",
        4,
        CREATED_AT,
        "Tesla",
        "TSLA",
    )


class FakeCursor:
    """Cursor double: answers the select and records every insert."""

    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self._rows: list = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._connection.statements.append((sql, params))
        if "LEFT JOIN ai_analysis" in sql:
            self._rows = self._connection.rows
        elif "INSERT INTO ai_analysis" in sql:
            self._connection.inserted.append(params)
            self._rows = []
        else:
            self._rows = []

    def fetchall(self) -> list:
        return self._rows

    def fetchone(self) -> object:
        return self._rows[0] if self._rows else None


class FakeConnection:
    """Connection double: one row set, recorded writes."""

    def __init__(self, rows: object = ()) -> None:
        self.rows = list(rows)
        self.statements: list = []
        self.inserted: list = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeBuilder:
    """Prompt builder double: the prompt names the post, so an answer can name it too."""

    def build(self, post: object, asset: object) -> str:
        return f"PROMPT {post.post_id} for {asset.name} ({asset.ticker})"


class OverlappingModel:
    """Completion double: all calls overlap and the first post answers last.

    Every call waits at the barrier until ``parties`` calls are in flight, so a serial
    pass never gets through it. ``first`` then waits until every other call returned, so
    the answers arrive in the reverse of the order the rows have to be stored in.
    """

    def __init__(self, parties: int, first: str = "p-1", wait: float = WAIT) -> None:
        self._entered = threading.Barrier(parties, timeout=wait)
        self._others_done = threading.Event()
        self._lock = threading.Lock()
        self._parties = parties
        self._first = first
        self._wait = wait
        self._returned = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        source_post_id = prompt.split()[1]
        with self._lock:
            self.prompts.append(source_post_id)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self._entered.wait()
            if source_post_id == self._first:
                if not self._others_done.wait(self._wait):
                    raise TimeoutError("the other posts did not answer")
            else:
                with self._lock:
                    self._returned += 1
                    if self._returned == self._parties - 1:
                        self._others_done.set()
            return answer_for(source_post_id)
        finally:
            with self._lock:
                self.in_flight -= 1


class CountingModel:
    """Completion double: holds the first calls until ``parties`` calls are in flight."""

    def __init__(self, parties: int, wait: float = 2.0) -> None:
        self._condition = threading.Condition()
        self._parties = parties
        self._wait = wait
        self._overlapped = False
        self.in_flight = 0
        self.max_in_flight = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        with self._condition:
            self.prompts.append(prompt)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            if self.in_flight >= self._parties:
                self._overlapped = True
            self._condition.notify_all()
            # Only the first wave waits: once the calls overlapped, the rest run free.
            self._condition.wait_for(lambda: self._overlapped, self._wait)
        try:
            return answer_for(prompt.split()[1])
        finally:
            with self._condition:
                self.in_flight -= 1


class MappingModel:
    """Completion double: answers a fixed text per post, ignoring the order of the calls."""

    def __init__(self, answers: dict[str, str]) -> None:
        self._answers = answers

    def __call__(self, prompt: str) -> str:
        return self._answers[prompt.split()[1]]


def make_analyzer(
    connection: FakeConnection,
    model: object,
    *,
    builder: object = None,
    settings: Settings = SETTINGS,
    on_analysis: object = None,
) -> Analyzer:
    """Build an analyzer over the fakes; the builder defaults to a recording one."""
    return Analyzer(
        settings,
        connector=lambda url: connection,
        complete=model,
        builder=builder if builder is not None else FakeBuilder(),
        on_analysis=on_analysis,
    )


def three_rows() -> list[tuple]:
    return [post_row(1, "p-1"), post_row(2, "p-2"), post_row(3, "p-3")]


def stored_post_ids(connection: FakeConnection) -> list[int]:
    return [row[0] for row in connection.inserted]


def stored_topics(connection: FakeConnection) -> list[tuple[str, ...]]:
    return [row[4] for row in connection.inserted]


class RecordingCallback:
    """Callback double: records the key topics of every analysis in call order."""

    def __init__(self) -> None:
        self.topics: list[tuple[str, ...]] = []

    def __call__(self, analysis: object, asset_id: int) -> None:
        self.topics.append(analysis.key_topics)


# --- the throttle -------------------------------------------------------------------


def test_the_calls_overlap_up_to_the_configured_limit():
    connection = FakeConnection([post_row(row_id, f"p-{row_id}") for row_id in (1, 2, 3, 4)])
    model = CountingModel(parties=2)
    analyzer = make_analyzer(connection, model, settings=replace(SETTINGS, llm_max_concurrency=2))

    stored = analyzer.analyze_pending()

    assert stored == 4
    assert model.max_in_flight == 2
    assert stored_post_ids(connection) == [1, 2, 3, 4]
    assert connection.commits == 1


def test_the_default_limit_runs_the_calls_one_after_the_other():
    connection = FakeConnection(three_rows())
    model = CountingModel(parties=1)
    analyzer = make_analyzer(connection, model)

    stored = analyzer.analyze_pending()

    assert SETTINGS.llm_max_concurrency == 1
    assert stored == 3
    assert model.max_in_flight == 1
    assert stored_post_ids(connection) == [1, 2, 3]


# --- the order ----------------------------------------------------------------------


def test_the_rows_are_stored_in_database_order_when_the_answers_arrive_out_of_order():
    connection = FakeConnection(three_rows())
    model = OverlappingModel(parties=3)
    callback = RecordingCallback()
    analyzer = make_analyzer(
        connection,
        model,
        settings=replace(SETTINGS, llm_max_concurrency=3),
        on_analysis=callback,
    )

    stored = analyzer.analyze_pending()

    assert stored == 3
    assert model.max_in_flight == 3
    assert stored_post_ids(connection) == [1, 2, 3]
    assert stored_topics(connection) == [("p-1",), ("p-2",), ("p-3",)]
    assert callback.topics == [("p-1",), ("p-2",), ("p-3",)]
    assert connection.commits == 1


def test_a_failing_post_in_the_middle_does_not_shift_the_stored_rows():
    connection = FakeConnection(three_rows())
    model = MappingModel(
        {
            "p-1": answer_for("p-1"),
            "p-2": "I am not going to answer that.",
            "p-3": answer_for("p-3"),
        }
    )
    analyzer = make_analyzer(connection, model, settings=replace(SETTINGS, llm_max_concurrency=3))

    stored = analyzer.analyze_pending()

    assert stored == 2
    assert stored_post_ids(connection) == [1, 3]
    assert stored_topics(connection) == [("p-1",), ("p-3",)]
    assert connection.commits == 1


# --- the shared prompt builder ------------------------------------------------------


def test_the_builder_loads_its_template_once_when_the_calls_run_in_parallel():
    connection = FakeConnection(three_rows())
    loads: list[int] = []

    def loader() -> str:
        loads.append(1)
        # Hold the first load long enough for every worker to reach an empty cache.
        time.sleep(0.05)
        return TEMPLATE

    analyzer = Analyzer(
        replace(SETTINGS, llm_max_concurrency=3, content_max_length=100),
        connector=lambda url: connection,
        complete=lambda prompt: answer_for("p-1"),
        builder=PromptBuilder(loader, content_max_length=100),
    )

    stored = analyzer.analyze_pending()

    assert stored == 3
    assert len(loads) == 1
