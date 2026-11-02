"""Tests for newstrading.analysis.service.

The analyzer sits between ``social_posts`` and the model, so every case here drives a
fake connection, a fake completion and a fake prompt builder: no database, no socket,
no model. The expected values are the legacy ones — the select, the retry delays
``2, 4`` between the three attempts and the neutral fallback for an empty answer come
from ``analyzer/main.py``; the parsing comes from :mod:`newstrading.analysis.parser`.
"""

from datetime import datetime

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from newstrading.analysis.parser import Analysis
from newstrading.analysis.service import AnalysisError, Analyzer
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")

CREATED_AT = datetime(2026, 1, 5, 14, 30)

TEMPLATE = "Analyze {asset_name} ({ticker}): {text_to_analyze}"

ANSWER = """{
  "sentiment": "positive",
  "sentiment_score": 0.7,
  "category": "Growth",
  "key_topics": ["hiring", "expansion"],
  "summary": "Tesla is hiring 2,000 engineers.",
  "special_events": ["partnership"]
}"""

NEUTRAL_SUMMARY = "Content could not be analyzed due to API content filters."


def post_row(
    row_id=1,
    source_post_id="p-1",
    title="Tesla hiring push",
    content="Tesla said it will hire 2,000 engineers.",
    score=4,
    created_at=CREATED_AT,
    name="Tesla",
    ticker="TSLA",
):
    """One joined row, in the column order of the select."""
    return (
        row_id,
        7,
        "rss_google_news",
        source_post_id,
        "Test Feed",
        title,
        content,
        "https://example.com/a",
        score,
        created_at,
        name,
        ticker,
    )


class FakeCursor:
    """Cursor double: answers the two selects and records every statement."""

    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self._connection.statements.append((sql, params))
        if self._connection.fail_on and self._connection.fail_on in sql:
            raise RuntimeError("connection lost")
        if "notification_settings" in sql:
            self._connection.template_queries += 1
            self._rows = [(self._connection.template,)]
        elif "LEFT JOIN ai_analysis" in sql:
            self._rows = self._connection.rows
        elif "INSERT INTO ai_analysis" in sql:
            self._connection.inserted.append(params)
            self._rows = []
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    """Connection double: one row set, one template, recorded writes."""

    def __init__(self, rows=(), *, fail_on=None, template=TEMPLATE):
        self.rows = list(rows)
        self.fail_on = fail_on
        self.template = template
        self.template_queries = 0
        self.statements = []
        self.inserted = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeBuilder:
    """Prompt builder double: returns a readable prompt and records its arguments."""

    def __init__(self):
        self.calls = []

    def build(self, post, asset):
        self.calls.append((post, asset))
        return f"PROMPT {post.post_id} for {asset.name} ({asset.ticker})"


class FakeModel:
    """Completion double: answers in order, raising an exception entry as is."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeSleep:
    """Sleep double: records the delays instead of waiting."""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def make_analyzer(
    connection, model, *, builder=None, sleep=None, settings=SETTINGS, on_analysis=None
):
    """Build an analyzer over the fakes; the builder defaults to a recording one."""
    return Analyzer(
        settings,
        connector=lambda url: connection,
        complete=model,
        sleep=sleep if sleep is not None else FakeSleep(),
        builder=builder if builder is not None else FakeBuilder(),
        on_analysis=on_analysis,
    )


def _message_request():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def rate_limit_error():
    return RateLimitError(
        "slow down", response=httpx.Response(429, request=_message_request()), body=None
    )


def internal_server_error():
    return InternalServerError(
        "overloaded", response=httpx.Response(529, request=_message_request()), body=None
    )


def timeout_error():
    return APITimeoutError(request=_message_request())


def connection_error():
    return APIConnectionError(request=_message_request())


# --- the select ---------------------------------------------------------------------


def test_the_select_asks_for_posts_without_an_analysis_newest_first():
    connection = FakeConnection()
    analyzer = make_analyzer(connection, FakeModel())

    analyzer.analyze_pending(limit=7)

    sql, params = connection.statements[0]
    assert "LEFT JOIN ai_analysis aa ON sp.id = aa.post_id" in sql
    assert "WHERE aa.id IS NULL" in sql
    assert "ORDER BY sp.created_at DESC" in sql
    assert sql.rstrip().endswith("LIMIT %s")
    assert params == (7,)


# --- one post, one answer -----------------------------------------------------------


def test_one_post_and_one_answer_store_one_analysis():
    connection = FakeConnection([post_row()])
    analyzer = make_analyzer(connection, FakeModel(ANSWER))

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert connection.inserted == [
        (
            1,
            "positive",
            0.7,
            "Growth",
            ("hiring", "expansion"),
            "Tesla is hiring 2,000 engineers.",
            ("partnership",),
        )
    ]
    assert connection.commits == 1


def test_the_prompt_sent_to_the_model_is_the_builders_output():
    connection = FakeConnection([post_row()])
    builder = FakeBuilder()
    model = FakeModel(ANSWER)
    analyzer = make_analyzer(connection, model, builder=builder)

    analyzer.analyze_pending()

    assert model.prompts == ["PROMPT p-1 for Tesla (TSLA)"]


def test_the_builder_receives_the_post_and_asset_from_the_row():
    connection = FakeConnection([post_row()])
    builder = FakeBuilder()
    analyzer = make_analyzer(connection, FakeModel(ANSWER), builder=builder)

    analyzer.analyze_pending()

    post, asset = builder.calls[0]
    assert post.asset_id == 7
    assert post.source == "rss_google_news"
    assert post.post_id == "p-1"
    assert post.author == "Test Feed"
    assert post.title == "Tesla hiring push"
    assert post.content == "Tesla said it will hire 2,000 engineers."
    assert post.url == "https://example.com/a"
    assert post.score == 4
    assert post.created_at == CREATED_AT
    assert (asset.id, asset.name, asset.ticker) == (7, "Tesla", "TSLA")


def test_the_default_builder_loads_the_template_once_per_run_and_cuts_the_content():
    settings = Settings(database_url=URL, anthropic_api_key="sk-test", content_max_length=10)
    connection = FakeConnection(
        [
            post_row(row_id=1, source_post_id="p-1", content="x" * 30),
            post_row(row_id=2, source_post_id="p-2", content="x" * 30),
        ]
    )
    model = FakeModel(ANSWER, ANSWER)
    analyzer = Analyzer(
        settings, connector=lambda url: connection, complete=model, sleep=FakeSleep()
    )

    stored = analyzer.analyze_pending()

    assert stored == 2
    assert connection.template_queries == 1
    assert '"content": "xxxxxxxxxx"' in model.prompts[0]
    assert "xxxxxxxxxxx" not in model.prompts[0]


# --- the empty answer ---------------------------------------------------------------


@pytest.mark.parametrize("answer", ["", "   \n"])
def test_an_empty_answer_stores_the_neutral_analysis(answer):
    connection = FakeConnection([post_row()])
    analyzer = make_analyzer(connection, FakeModel(answer))

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert connection.inserted == [
        (
            1,
            "neutral",
            0.0,
            "Other",
            ("Content moderation filtered",),
            NEUTRAL_SUMMARY,
            (),
        )
    ]


# --- retries ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_error",
    [rate_limit_error, internal_server_error, timeout_error, connection_error],
)
def test_a_retryable_error_is_retried_three_times_with_the_legacy_delays(make_error):
    connection = FakeConnection([post_row()])
    model = FakeModel(make_error(), make_error(), make_error())
    sleep = FakeSleep()
    analyzer = make_analyzer(connection, model, sleep=sleep)

    stored = analyzer.analyze_pending()

    assert stored == 0
    assert len(model.prompts) == 3
    assert sleep.calls == [2, 4]
    assert connection.inserted == []


def test_a_retryable_error_then_a_good_answer_stores_the_analysis():
    connection = FakeConnection([post_row()])
    sleep = FakeSleep()
    analyzer = make_analyzer(connection, FakeModel(rate_limit_error(), ANSWER), sleep=sleep)

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert sleep.calls == [2]
    assert connection.inserted[0][1] == "positive"


def test_a_parse_error_is_not_retried_and_stores_nothing():
    connection = FakeConnection([post_row()])
    model = FakeModel("I am not going to answer that.")
    sleep = FakeSleep()
    analyzer = make_analyzer(connection, model, sleep=sleep)

    stored = analyzer.analyze_pending()

    assert stored == 0
    assert len(model.prompts) == 1
    assert sleep.calls == []
    assert connection.inserted == []


# --- the batch ----------------------------------------------------------------------


def test_one_failing_post_does_not_stop_the_batch_and_is_not_counted():
    connection = FakeConnection(
        [
            post_row(row_id=1, source_post_id="p-1"),
            post_row(row_id=2, source_post_id="p-2"),
        ]
    )
    analyzer = make_analyzer(connection, FakeModel("not JSON", ANSWER))

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert [row[0] for row in connection.inserted] == [2]
    assert connection.commits == 1


def test_a_non_retryable_model_error_skips_only_its_post():
    connection = FakeConnection(
        [
            post_row(row_id=1, source_post_id="p-1"),
            post_row(row_id=2, source_post_id="p-2"),
        ]
    )
    analyzer = make_analyzer(connection, FakeModel(ValueError("bad request"), ANSWER))

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert [row[0] for row in connection.inserted] == [2]
    assert connection.commits == 1
    assert connection.rollbacks == 0


# --- failure handling ---------------------------------------------------------------


def test_a_database_error_rolls_back_and_raises_a_named_error():
    connection = FakeConnection([post_row()], fail_on="INSERT INTO ai_analysis")
    analyzer = make_analyzer(connection, FakeModel(ANSWER))

    with pytest.raises(AnalysisError):
        analyzer.analyze_pending()

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closed is True
    assert connection.inserted == []


# --- the on_analysis seam ------------------------------------------------------------


class FakeCallback:
    """Callback double: records every analysis and asset id it is handed."""

    def __init__(self):
        self.calls = []

    def __call__(self, analysis, asset_id):
        self.calls.append((analysis, asset_id))


def test_a_stored_analysis_calls_on_analysis_once_with_the_analysis_and_the_asset_id():
    row = list(post_row(row_id=11))
    row[1] = 42
    connection = FakeConnection([row])
    callback = FakeCallback()
    analyzer = make_analyzer(connection, FakeModel(ANSWER), on_analysis=callback)

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert len(callback.calls) == 1
    analysis, asset_id = callback.calls[0]
    assert isinstance(analysis, Analysis)
    assert (analysis.sentiment, analysis.sentiment_score) == ("positive", 0.7)
    assert (analysis.category, analysis.key_topics) == ("Growth", ("hiring", "expansion"))
    assert asset_id == 42


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("I am not going to answer that.", id="parse-error"),
        pytest.param(ValueError("bad request"), id="model-error"),
    ],
)
def test_a_failing_post_does_not_call_on_analysis(answer):
    connection = FakeConnection([post_row()])
    callback = FakeCallback()
    analyzer = make_analyzer(connection, FakeModel(answer), on_analysis=callback)

    stored = analyzer.analyze_pending()

    assert stored == 0
    assert connection.inserted == []
    assert callback.calls == []


def test_on_analysis_none_stores_the_analysis_and_calls_nothing():
    connection = FakeConnection([post_row()])
    analyzer = make_analyzer(connection, FakeModel(ANSWER))

    stored = analyzer.analyze_pending()

    assert stored == 1
    assert [row[0] for row in connection.inserted] == [1]
    assert connection.commits == 1
