"""The model seam: the one protocol the analyzer calls, the errors it maps and the factory.

An endpoint is a URL and a model an id, so nothing in this module names a vendor. The
transport is the chat-completions protocol; the analysis service depends on
:class:`LLMClient` only: it sends a prompt, gets raw answer text back, and retries
:class:`RetryableModelError` while giving up on :class:`ModelError`.

The adapters live in this module so the transport import stays in a single place. They
translate their library's failures into the two types below, so no caller has to know
which endpoint answered.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import requests

from newstrading.config import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TIMEOUT,
    Settings,
)


class RetryableModelError(Exception):
    """A model call that failed in a way another attempt can fix.

    Rate limits, timeouts, connection failures and 5xx answers are transient. An
    empty answer belongs here as well: a reasoning model can spend its whole token
    budget before it writes a verdict, so the same prompt with a larger budget — or
    simply at a calmer moment — may well succeed. The service retries this error and
    leaves the post unanalysed when the last attempt fails.
    """


class ModelError(Exception):
    """A model call that failed terminally and is not repeated as it was.

    A rejected request (4xx other than 429), a malformed response body and any other
    transport error say that the call itself is wrong, not the moment it was made. A
    second attempt with the same input would only repeat the failure.
    """


@runtime_checkable
class LLMClient(Protocol):
    """What the analyzer needs from a model client.

    Implementations send the prompt to their endpoint and return the raw answer text
    — fences and all; stripping them is the parser's job. They translate their
    transport's failures into :class:`RetryableModelError` or :class:`ModelError` so
    that the analysis service never imports a transport library.
    """

    def complete(self, prompt: str) -> str:
        """Send ``prompt`` to the endpoint and return the raw answer text."""
        ...


CHAT_COMPLETIONS_PATH = "/chat/completions"
"""Suffix of an OpenAI-compatible base URL that answers a chat prompt."""

TRUNCATED_FINISH_REASON = "length"
"""``finish_reason`` of an answer whose token budget ran out before the verdict."""

_EXCERPT_LENGTH = 80


class OpenAICompatibleClient:
    """The ``/v1/chat/completions`` adapter of an OpenAI-compatible endpoint.

    The same class covers every such endpoint: the port belongs to ``base_url`` and the
    model is an id, so an endpoint is chosen in the configuration, not in the code.

    Attributes:
        base_url: OpenAI-compatible base URL, e.g. ``http://192.168.178.87:8004/v1``.
        model: Model id sent in the payload, e.g. ``gb10-writing``.
        api_key: Bearer token; empty sends no ``Authorization`` header.
        timeout: Seconds one call may take; the measured answer needs 9–11 s.
        max_tokens: Token budget of one answer. It must cover the reasoning prefix the
            model writes before the verdict — 1024 is the measured default.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        timeout: float = DEFAULT_LLM_TIMEOUT,
        max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        session: Any = None,
    ) -> None:
        """Store the endpoint; ``session`` is the transport seam for the tests.

        Args:
            base_url: Base URL of the server; a trailing slash is ignored.
            model: Model id the server should answer with.
            api_key: Bearer token; empty sends no authorization header.
            timeout: Seconds one call may take.
            max_tokens: Token budget of one answer.
            session: ``requests.Session``-like object with ``post``. Defaults to a new
                :class:`requests.Session`, so the calls of one run share a connection.
        """
        self.base_url = base_url
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._session = session if session is not None else requests.Session()

    @property
    def url(self) -> str:
        """The endpoint one prompt is posted to, without a doubled separator."""
        return self.base_url.rstrip("/") + CHAT_COMPLETIONS_PATH

    def complete(self, prompt: str) -> str:
        """Send ``prompt`` to the endpoint and return the raw answer text.

        Args:
            prompt: The analysis prompt of one post.

        Returns:
            ``choices[0].message.content`` exactly as the model wrote it — a fenced
            answer keeps its fences, the parser strips them.

        Raises:
            RetryableModelError: The transport failed (timeout, connection), the server
                answered 429 or 5xx, or the answer is empty or was cut off
                (``finish_reason: length``). The measured case — ``content: null`` at a
                budget of 300 — is exactly this: the model spent the budget on its
                reasoning and never wrote the verdict.
            ModelError: The server rejected the request (4xx other than 429), the body
                is not JSON or holds no choice.
        """
        try:
            response = self._session.post(
                self.url,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self._max_tokens,
                },
                headers=self._headers(),
                timeout=self._timeout,
            )
        # boundary: the transport's failures become the seam's two error kinds
        except requests.Timeout as error:
            raise RetryableModelError(
                f"{self.model}: no answer within {self._timeout}s: {error}"
            ) from error
        except requests.ConnectionError as error:
            raise RetryableModelError(f"{self.model}: cannot reach {self.url}: {error}") from error
        except requests.RequestException as error:
            raise ModelError(f"{self.model}: the request failed: {error}") from error
        return _openai_answer(_json_body(response, self.model), self.model)

    def _headers(self) -> dict[str, str]:
        """Return the headers of one call; the authorization only when a key is set."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


class FallbackClient:
    """A client that asks a second endpoint when the first one fails retryably.

    A retryable failure of the primary is the one case another endpoint can fix, so the
    secondary is asked exactly once for that prompt. A terminal failure of the primary
    says the request itself is wrong and propagates at once.

    Attributes:
        primary: The client asked first.
        secondary: The client asked once when ``primary`` raised
            :class:`RetryableModelError`.
    """

    def __init__(self, primary: LLMClient, secondary: LLMClient) -> None:
        """Store both clients; no call is made here.

        Args:
            primary: The client asked first.
            secondary: The client asked when the primary fails retryably.
        """
        self.primary = primary
        self.secondary = secondary

    def complete(self, prompt: str) -> str:
        """Send ``prompt`` to the primary and, on a retryable failure, to the secondary.

        Args:
            prompt: The analysis prompt of one post.

        Returns:
            The answer of the primary, or the answer of the secondary when the primary
            failed retryably. Both are returned raw, exactly alike.

        Raises:
            ModelError: The primary (or the secondary) rejected the request; the
                secondary is not asked when the primary already answered terminally.
            RetryableModelError: Both calls failed retryably. The message holds both
                texts, primary first: ``"{primary}; fallback: {secondary}"``.
        """
        try:
            return self.primary.complete(prompt)
        except RetryableModelError as primary_error:
            try:
                return self.secondary.complete(prompt)
            except RetryableModelError as secondary_error:
                raise RetryableModelError(
                    f"{primary_error}; fallback: {secondary_error}"
                ) from secondary_error


def build_client(settings: Settings) -> LLMClient:
    """Return the client the settings describe, with the optional fallback.

    Args:
        settings: The resolved settings; the client reads its endpoint, model, key,
            timeout and budget from it.

    Returns:
        :class:`OpenAICompatibleClient` on ``llm_base_url``/``llm_model`` when
        ``llm_fallback`` is empty — the adapter itself, not a wrapper. With a fallback,
        a :class:`FallbackClient` of that primary and a second
        :class:`OpenAICompatibleClient` on ``llm_fallback``/``llm_fallback_model``;
        both share the timeout and the token budget.
    """
    primary = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
    )
    if not settings.llm_fallback:
        return primary
    secondary = OpenAICompatibleClient(
        settings.llm_fallback,
        settings.llm_fallback_model,
        api_key=settings.llm_fallback_api_key,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
    )
    return FallbackClient(primary, secondary)


def _json_body(response: Any, model: str) -> dict:
    """Return the decoded body of ``response`` or classify its status.

    Args:
        response: ``requests`` response-like object with ``status_code``, ``text`` and
            ``json``.
        model: Model id, used in the error message.

    Returns:
        The decoded body.

    Raises:
        RetryableModelError: HTTP 429 or 5xx.
        ModelError: Any other HTTP error, a body that is not JSON, or a body that is not
            an object.
    """
    status = getattr(response, "status_code", 0)
    text = getattr(response, "text", "")
    if status == 429 or status >= 500:
        raise RetryableModelError(f"{model}: HTTP {status}: {_excerpt(text)}")
    if status >= 400:
        raise ModelError(f"{model}: HTTP {status}: {_excerpt(text)}")
    try:
        body = response.json()
    except ValueError as error:
        raise ModelError(f"{model}: the answer is not JSON: {_excerpt(text)}") from error
    if not isinstance(body, dict):
        raise ModelError(f"{model}: the answer is not a JSON object: {_excerpt(text)}")
    return body


def _openai_answer(body: dict, model: str) -> str:
    """Return ``choices[0].message.content`` of an OpenAI-compatible answer.

    Args:
        body: The decoded answer body.
        model: Model id, used in the error message.

    Returns:
        The answer text, raw.

    Raises:
        RetryableModelError: ``finish_reason`` is ``length`` (the budget was spent before
            the verdict) or the content is empty.
        ModelError: The body holds no choice at all.
    """
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ModelError(f"{model}: the answer holds no choice: {_excerpt(json.dumps(body))}")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if finish_reason == TRUNCATED_FINISH_REASON:
        raise RetryableModelError(
            f"{model}: the answer was cut off (finish_reason='length'); the budget was not enough"
        )
    if not isinstance(content, str) or not content.strip():
        raise RetryableModelError(
            f"{model}: the answer is empty (finish_reason={finish_reason!r}); the budget may"
            " have been spent before the verdict"
        )
    return content


def _excerpt(text: str) -> str:
    """Return at most the first :data:`_EXCERPT_LENGTH` characters of ``text``."""
    return str(text)[:_EXCERPT_LENGTH]
