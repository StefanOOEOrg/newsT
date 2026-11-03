"""Tests for the provider adapters of :mod:`newstrading.analysis.llm`.

No socket, no key, no database: the OpenAI-compatible adapter runs against a fake
``requests.Session`` and the Anthropic adapter against a fake ``messages`` client. The
answers are the ones measured for issue #52 — ``content: null`` with
``finish_reason: length`` at a small budget, a fenced JSON object at 1024 tokens — so the
retry classification is pinned to what the models really send.

The last two cases drive the analyzer over the adapters: a retryable failure is retried
and the answer after it is stored, an empty answer never becomes a neutral row.
"""

from __future__ import annotations

import httpx
import pytest
import requests
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from newstrading.analysis.llm import (
    AnthropicClient,
    LLMClient,
    ModelError,
    OpenAICompatibleClient,
    RetryableModelError,
    build_client,
)
from newstrading.analysis.parser import parse_analysis
from newstrading.analysis.service import Analyzer
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")

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

PREFILL_ANSWER = " positive, score 0.7, category Growth."


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
    """An OpenAI-compatible adapter over the recorded GX10 endpoint and a fake session."""
    session = FakeSession(response, error=error)
    kwargs.setdefault("base_url", LOCAL_DEFAULTS.llm_base_url)
    kwargs.setdefault("model", LOCAL_DEFAULTS.llm_model)
    kwargs.setdefault("max_tokens", LOCAL_DEFAULTS.llm_max_tokens)
    return OpenAICompatibleClient(session=session, **kwargs), session


class FakeMessage:
    """One content block of an Anthropic answer."""

    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeAnthropicAnswer:
    """An Anthropic message double: a text and the reason the model stopped."""

    def __init__(self, text=None, *, stop_reason="end_turn"):
        self.content = [] if text is None else [FakeMessage(text)]
        self.stop_reason = stop_reason


class FakeMessages:
    """The ``messages`` resource double: records the request, then answers or raises."""

    def __init__(self, answer=None, *, error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.answer


class FakeAnthropic:
    """An ``anthropic.Anthropic`` double: only ``messages`` is used."""

    def __init__(self, answer=None, *, error=None):
        self.messages = FakeMessages(answer, error=error)


def anthropic_client(answer=None, *, error=None):
    """An Anthropic adapter over a fake SDK client."""
    client = FakeAnthropic(answer, error=error)
    return AnthropicClient("claude-3-5-haiku-20241022", "sk-test", client=client), client


def _request():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(error_type, status):
    return error_type(
        "provider said no", response=httpx.Response(status, request=_request()), body=None
    )


# --- the OpenAI-compatible adapter of the local GB10 endpoints ------------------------


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
    """The GX10 addresses are written with and without the slash; both work."""
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
    """An unreachable GX10 may come back within the retry window."""
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


# --- the Anthropic adapter -----------------------------------------------------------


def test_the_anthropic_adapter_satisfies_the_protocol():
    """Same seam, different provider."""
    client, _client = anthropic_client()

    assert isinstance(client, LLMClient)


def test_the_anthropic_adapter_keeps_the_prefill():
    """The legacy assistant turn stays, and a bare answer gets the prefill back."""
    client, sdk = anthropic_client(FakeAnthropicAnswer(PREFILL_ANSWER))

    assert client.complete("a prompt") == "sentiment:" + PREFILL_ANSWER

    call = sdk.messages.calls[0]
    assert call["model"] == "claude-3-5-haiku-20241022"
    assert call["messages"][0] == {"role": "user", "content": "a prompt"}
    assert call["messages"][1] == {"role": "assistant", "content": "sentiment:"}


def test_the_anthropic_adapter_returns_a_json_answer_unchanged():
    """An answer that ignored the prefill is passed on as it came."""
    client, _sdk = anthropic_client(FakeAnthropicAnswer(BARE_ANSWER))

    assert client.complete("a prompt") == BARE_ANSWER


def test_the_anthropic_adapter_returns_a_fenced_answer_unchanged():
    """The fenced shape is the one issue #52 measured; the parser strips it."""
    client, _sdk = anthropic_client(FakeAnthropicAnswer(FENCED_ANSWER))

    assert client.complete("a prompt") == FENCED_ANSWER


def test_an_empty_anthropic_answer_is_retryable():
    """No content block is the same empty-answer case as ``content: null``."""
    client, _sdk = anthropic_client(FakeAnthropicAnswer(None))

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


def test_an_anthropic_answer_cut_by_max_tokens_is_retryable():
    """``stop_reason: max_tokens`` is the Anthropic form of a spent budget."""
    client, _sdk = anthropic_client(
        FakeAnthropicAnswer('{"sentiment": "posi', stop_reason="max_tokens")
    )

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


@pytest.mark.parametrize(
    "error",
    [
        _status_error(RateLimitError, 429),
        _status_error(InternalServerError, 529),
        APITimeoutError(request=_request()),
        APIConnectionError(request=_request()),
    ],
    ids=["rate-limit", "overloaded", "timeout", "connection"],
)
def test_the_transient_anthropic_failures_are_retryable(error):
    """The four legacy retryable errors still classify as retryable, now via the seam."""
    client, _sdk = anthropic_client(error=error)

    with pytest.raises(RetryableModelError):
        client.complete("a prompt")


def test_a_rejected_anthropic_request_is_terminal():
    """A 400 would fail again with the same prompt."""
    client, _sdk = anthropic_client(error=_status_error(BadRequestError, 400))

    with pytest.raises(ModelError):
        client.complete("a prompt")


def test_every_anthropic_sdk_error_maps_onto_the_two_seam_errors():
    """Whatever the SDK raises, the caller only ever sees the seam's types."""
    client, _sdk = anthropic_client(error=_status_error(APIStatusError, 418))

    with pytest.raises(ModelError):
        client.complete("a prompt")


# --- the factory ---------------------------------------------------------------------


def test_the_default_settings_build_the_local_adapter():
    """``LLM_PROVIDER`` defaults to ``local``, so the GX10 writing model answers."""
    client = build_client(LOCAL_DEFAULTS)

    assert isinstance(client, OpenAICompatibleClient)


def test_the_anthropic_provider_builds_the_anthropic_adapter():
    """The provider switch decides which adapter the analyzer gets."""
    client = build_client(
        Settings(database_url=URL, anthropic_api_key="sk-test", llm_provider="anthropic")
    )

    assert isinstance(client, AnthropicClient)


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
