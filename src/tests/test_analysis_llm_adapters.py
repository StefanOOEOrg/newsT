"""Tests for the client seam of :mod:`newstrading.analysis.llm`.

No socket, no key, no database: the OpenAI-compatible adapter runs against a fake
``requests.Session`` and the fallback against two fake clients. The answers are the ones
measured for issue #52 — ``content: null`` with ``finish_reason: length`` at a small
budget, a fenced JSON object at 1024 tokens — so the retry classification is pinned to
what the models really send.

The last two cases drive the analyzer over the adapters: a retryable failure is retried
and the answer after it is stored, an empty answer never becomes a neutral row.
"""

from __future__ import annotations

import pytest
import requests

from newstrading.analysis.llm import (
    FallbackClient,
    LLMClient,
    ModelError,
    OpenAICompatibleClient,
    RetryableModelError,
    build_client,
)
from newstrading.analysis.parser import parse_analysis
from newstrading.analysis.service import Analyzer
from newstrading.config import Settings, from_env

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL)

LOCAL_DEFAULTS = Settings(database_url=URL)

FENCED_ANSWER = """```json
{
  "sentiment": "positive",
  "sentiment_score": 0.7,
  "category": "Growth",
  "key_topics": ["hiring", "expansion"],
  "summary": "Tesla is hiring 2,000 engineers.",
  "special_events": ["partnership"]
}
```"""

BARE_ANSWER = '{"sentiment": "positive", "sentiment_score": 0.7, "summary": "Hiring."}'


class FakeResponse:
    """A ``requests`` response double: a status, a text body and its decoded form."""

    def __init__(self, payload=None, *, status_code=200, text="", decode=True):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.decode = decode

    def json(self):
        if not self.decode:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self.payload


class FakeSession:
    """A ``requests.Session`` double: answers once and records every call."""

    def __init__(self, response=None, *, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


def chat_answer(content, finish_reason="stop"):
    """The body of an OpenAI-compatible answer with one choice."""
    return {
        "id": "chatcmpl-1",
        "model": "gb10-writing",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "reasoning": "thinking"},
                "finish_reason": finish_reason,
            }
        ],
    }


def local_client(response=None, *, error=None, **kwargs):
    """An OpenAI-compatible adapter over the recorded endpoint and a fake session."""
    session = FakeSession(response, error=error)
    kwargs.setdefault("base_url", LOCAL_DEFAULTS.llm_base_url)
    kwargs.setdefault("model", LOCAL_DEFAULTS.llm_model)
    kwargs.setdefault("max_tokens", LOCAL_DEFAULTS.llm_max_tokens)
    return OpenAICompatibleClient(session=session, **kwargs), session


# --- the OpenAI-compatible adapter ---------------------------------------------------


def test_the_openai_adapter_satisfies_the_protocol():
    """It has ``complete``, so the analyzer accepts it as a client."""
    client, _session = local_client()

    assert isinstance(client, LLMClient)


def test_the_openai_adapter_posts_the_chat_completions_payload():
    """One POST to ``/v1/chat/completions`` with the model, the prompt and the budget."""
    client, session = local_client(FakeResponse(chat_answer(BARE_ANSWER)))

    assert client.complete("a prompt") == BARE_ANSWER

    call = session.calls[0]
    assert call["url"] == "http://192.168.178.87:8004/v1/chat/completions"
    assert call["json"] == {
        "model": "gb10-writing",
        "messages": [{"role": "user", "content": "a prompt"}],
        "max_tokens": 1024,
    }
    assert call["timeout"] == 60.0
    assert "Authorization" not in call["headers"]


def test_the_openai_adapter_sends_a_configured_key_as_bearer():
    """``LLM_API_KEY`` becomes the authorization header; empty sends none."""
    response = FakeResponse(chat_answer(BARE_ANSWER))
    client, session = local_client(response, api_key="sk-local")

    client.complete("a prompt")

    assert session.calls[0]["headers"]["Authorization"] == "Bearer sk-local"


def test_a_trailing_slash_on_the_base_url_does_not_double_the_separator():
    """The endpoints are written with and without the slash; both work."""
    client, session = local_client(
        FakeResponse(chat_answer(BARE_ANSWER)), base_url="http://192.168.178.87:8004/v1/"
    )

    client.complete("a prompt")

    assert session.calls[0]["url"] == "http://192.168.178.87:8004/v1/chat/completions"


@pytest.mark.parametrize("port", ["8004", "8000", "8001"])
def test_the_measured_endpoints_are_reached_through_the_same_adapter(port):
    """One adapter covers all three servers; the port comes from the base URL."""
    client, session = local_client(
        FakeResponse(chat_answer(BARE_ANSWER)), base_url=f"http://192.168.178.87:{port}/v1"
    )

    client.complete("a prompt")

    assert session.calls[0]["url"] == f"http://192.168.178.87:{port}/v1/chat/completions"


def test_the_openai_adapter_returns_the_fenced_answer_unchanged():
    """Fences are the parser's job: the adapter hands the raw text on."""
    client, _session = local_client(FakeResponse(chat_answer(FENCED_ANSWER)))

    assert client.complete("a prompt") == FENCED_ANSWER


def test_the_measured_empty_answer_is_retryable():
    """``content: null`` with ``finish_reason: length`` must never become a neutral row."""
    client, _session = local_client(FakeResponse(chat_answer(None, finish_reason="length")))

    with pytest.raises(RetryableModelError) as raised:
        client.complete("a prompt")

    assert "finish_reason='length'" in str(raised.value)
    assert "budget" in str(raised.value)


def test_a_truncated_answer_is_retryable_even_when_it_has_content():
    """A budget that ran out mid-answer cannot hold the verdict either."""
    client, _session = local_client(
        FakeResponse(chat_answer('{"sentiment": "posi', finish_reason="length"))
    )

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


@pytest.mark.parametrize("content", [None, "", "   \n"])
def test_an_empty_answer_is_retryable_whatever_the_finish_reason(content):
    """Empty stays retryable when the server claims a normal stop."""
    client, _session = local_client(FakeResponse(chat_answer(content)))

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


def test_a_rate_limited_call_is_retryable():
    """HTTP 429 is the classic case for another attempt."""
    client, _session = local_client(FakeResponse(None, status_code=429, text="slow down"))

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


def test_a_server_error_is_retryable():
    """HTTP 503 says the moment was wrong, not the request."""
    client, _session = local_client(FakeResponse(None, status_code=503, text="overloaded"))

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


@pytest.mark.parametrize("status", [400, 401, 404])
def test_a_rejected_request_is_terminal(status):
    """A 4xx other than 429 would fail again with the same prompt."""
    client, _session = local_client(FakeResponse(None, status_code=status, text="nope"))

    with pytest.raises(ModelError):
        client.complete("a prompt")


def test_a_timeout_is_retryable():
    """The measured call needs 9–11 s; a timeout is transient."""
    client, _session = local_client(error=requests.ReadTimeout("read timed out"))

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


def test_a_connection_error_is_retryable():
    """An unreachable endpoint may come back within the retry window."""
    client, _session = local_client(error=requests.ConnectionError("connection refused"))

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


def test_a_request_the_transport_refuses_is_terminal():
    """A malformed base URL would fail again, however often it is sent."""
    client, _session = local_client(error=requests.exceptions.InvalidURL("no host"))

    with pytest.raises(ModelError):
        client.complete("a prompt")


def test_a_body_that_is_not_an_object_is_terminal():
    """A JSON array is not an answer either; the endpoint is wrong."""
    client, _session = local_client(FakeResponse(["not", "a", "choice"]))

    with pytest.raises(ModelError):
        client.complete("a prompt")


def test_a_body_that_is_not_json_is_terminal():
    """A gateway page instead of an answer is a wrong endpoint, not a busy one."""
    client, _session = local_client(
        FakeResponse(None, text="<html>bad gateway</html>", decode=False)
    )

    with pytest.raises(ModelError):
        client.complete("a prompt")


def test_a_body_without_choices_is_terminal():
    """An answer with no choice carries no verdict for this prompt."""
    client, _session = local_client(FakeResponse({"error": "no model loaded"}))

    with pytest.raises(ModelError):
        client.complete("a prompt")


def test_a_fenced_answer_from_the_adapter_is_parsed():
    """Adapter and parser fit together: the fence never reaches the decoder."""
    client, _session = local_client(FakeResponse(chat_answer(FENCED_ANSWER)))

    analysis = parse_analysis(client.complete("a prompt"))

    assert analysis.sentiment == "positive"
    assert analysis.sentiment_score == 0.7
    assert analysis.category == "Growth"
    assert analysis.key_topics == ("hiring", "expansion")


# --- the fallback client -------------------------------------------------------------


class FakeClient:
    """An ``LLMClient`` double: answers from a list and records every prompt."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def test_the_fallback_satisfies_the_protocol():
    """It has ``complete``, so it can stand where any other client stands."""
    client = FallbackClient(FakeClient("answer"), FakeClient("answer"))

    assert isinstance(client, LLMClient)


def test_a_retryable_primary_failure_is_answered_by_the_fallback():
    """One retryable failure of the primary is the fallback's cue, not the caller's."""
    primary = FakeClient(RetryableModelError("primary is overloaded"))
    secondary = FakeClient("the fallback answer")
    client = FallbackClient(primary, secondary)

    assert client.complete("a prompt") == "the fallback answer"

    assert primary.prompts == ["a prompt"]
    assert secondary.prompts == ["a prompt"]


def test_a_terminal_primary_failure_never_reaches_the_fallback():
    """A rejected request would be rejected again; asking the fallback hides nothing."""
    error = ModelError("primary rejected the request")
    primary = FakeClient(error)
    secondary = FakeClient("the fallback answer")
    client = FallbackClient(primary, secondary)

    with pytest.raises(ModelError) as raised:
        client.complete("a prompt")

    assert raised.value is error
    assert secondary.prompts == []


def test_two_retryable_failures_name_both_errors_primary_first():
    """The raised message keeps both texts, and the cause is the fallback error."""
    primary_error = RetryableModelError("primary timed out")
    secondary_error = RetryableModelError("fallback is unreachable")
    client = FallbackClient(FakeClient(primary_error), FakeClient(secondary_error))

    with pytest.raises(RetryableModelError) as raised:
        client.complete("a prompt")

    assert str(raised.value) == "primary timed out; fallback: fallback is unreachable"
    assert raised.value.__cause__ is secondary_error


def test_the_fallback_is_asked_once_per_prompt():
    """One prompt, one primary call, one fallback call — no retry loop of its own."""
    primary = FakeClient(RetryableModelError("down"), RetryableModelError("down again"))
    secondary = FakeClient("first answer", "second answer")
    client = FallbackClient(primary, secondary)

    assert client.complete("first prompt") == "first answer"
    assert client.complete("second prompt") == "second answer"

    assert primary.prompts == ["first prompt", "second prompt"]
    assert secondary.prompts == ["first prompt", "second prompt"]


def test_a_fallback_answer_is_returned_exactly_like_a_primary_one():
    """The caller cannot see which endpoint answered."""
    client = FallbackClient(FakeClient(RetryableModelError("down")), FakeClient(FENCED_ANSWER))

    assert client.complete("a prompt") == FENCED_ANSWER


# --- the factory ---------------------------------------------------------------------


def test_the_default_settings_build_the_openai_adapter():
    """Without a fallback the factory returns exactly the primary adapter."""
    client = build_client(LOCAL_DEFAULTS)

    assert isinstance(client, OpenAICompatibleClient)
    assert not isinstance(client, FallbackClient)


def test_a_configured_fallback_wraps_both_adapters():
    """``LLM_FALLBACK`` switches the factory from one adapter to the pair."""
    settings = from_env(
        {
            "DATABASE_URL": URL,
            "LLM_FALLBACK": "http://fallback.internal:8000/v1",
        }
    )

    client = build_client(settings)

    assert isinstance(client, FallbackClient)
    assert isinstance(client.primary, OpenAICompatibleClient)
    assert isinstance(client.secondary, OpenAICompatibleClient)
    assert client.primary.base_url == settings.llm_base_url
    assert client.secondary.base_url == "http://fallback.internal:8000/v1"


def test_the_fallback_model_defaults_to_the_primary_model():
    """The factory reads the resolved model; ``from_env`` already defaulted it."""
    settings = from_env(
        {
            "DATABASE_URL": URL,
            "LLM_MODEL": "primary-model",
            "LLM_FALLBACK": "http://fallback.internal:8000/v1",
        }
    )

    client = build_client(settings)

    assert client.secondary.model == "primary-model"


def test_the_fallback_key_reaches_the_second_adapter():
    """``LLM_FALLBACK_API_KEY`` is the second adapter's bearer token, no one else's."""
    settings = from_env(
        {
            "DATABASE_URL": URL,
            "LLM_API_KEY": "primary-key",
            "LLM_FALLBACK": "http://fallback.internal:8000/v1",
            "LLM_FALLBACK_API_KEY": "fallback-key",
        }
    )

    client = build_client(settings)

    assert client.primary._headers()["Authorization"] == "Bearer primary-key"
    assert client.secondary._headers()["Authorization"] == "Bearer fallback-key"


def test_both_adapters_share_the_timeout_and_the_budget():
    """One call budget for the pair: the fallback is not a second configuration."""
    settings = from_env(
        {
            "DATABASE_URL": URL,
            "LLM_TIMEOUT": "12.5",
            "LLM_MAX_TOKENS": "2048",
            "LLM_FALLBACK": "http://fallback.internal:8000/v1",
        }
    )

    client = build_client(settings)

    assert (client.primary._timeout, client.primary._max_tokens) == (12.5, 2048)
    assert (client.secondary._timeout, client.secondary._max_tokens) == (12.5, 2048)


# --- the analyzer over the adapters --------------------------------------------------


class FakeCursor:
    """Cursor double: answers the pending select and the prompt select, records writes."""

    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        if "notification_settings" in sql:
            self._rows = [("PROMPT {asset_name} {ticker} {text_to_analyze}",)]
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
    """Connection double: one post row and the analyses written for it."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.inserted = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def post_row(row_id=1):
    """One joined row, in the column order of the analyzer's select."""
    return (
        row_id,
        7,
        "rss",
        "p-1",
        "author",
        "title",
        "content",
        "https://example.com",
        4,
        None,
        "Tesla",
        "TSLA",
    )


def make_analyzer(*answers, sleep_calls):
    """An analyzer over a fake connection and a completion that answers in order."""
    queue = list(answers)

    def complete(prompt):
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def sleep(seconds):
        sleep_calls.append(seconds)

    connection = FakeConnection([post_row()])
    return (
        Analyzer(
            SETTINGS,
            connector=lambda url: connection,
            complete=complete,
            sleep=sleep,
        ),
        connection,
    )


def test_the_analyzer_retries_a_retryable_model_error_and_stores_the_second_answer():
    """A finished model that answered empty is asked again instead of being stored neutral."""
    sleeps = []
    analyzer, connection = make_analyzer(
        RetryableModelError("empty answer (finish_reason='length')"),
        FENCED_ANSWER,
        sleep_calls=sleeps,
    )

    assert analyzer.analyze_pending() == 1
    assert sleeps == [2]
    assert connection.inserted[0][1] == "positive"


def test_an_empty_answer_that_stays_empty_is_never_stored():
    """Three empty answers leave the post unanalysed for the next pass."""
    sleeps = []
    analyzer, connection = make_analyzer(
        RetryableModelError("empty answer"),
        RetryableModelError("empty answer"),
        RetryableModelError("empty answer"),
        sleep_calls=sleeps,
    )

    assert analyzer.analyze_pending() == 0
    assert sleeps == [2, 4]
    assert connection.inserted == []
