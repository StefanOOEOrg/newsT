"""The model seam: the one protocol the analyzer calls and the errors it maps.

Every provider adapter — the OpenAI-compatible client of the local GX10, the
Anthropic client — implements :class:`LLMClient`. The analysis service therefore
depends on this module only: it sends a prompt, gets raw answer text back, and
retries :class:`RetryableModelError` while giving up on :class:`ModelError`.

The adapters live in this module as well so the provider SDKs stay importable in a
single place; both translate their library's failures into the two types below, so
no caller has to know which provider answered.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

import requests
from anthropic import (
    Anthropic,
    AnthropicError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

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

    A rejected request (4xx other than 429), a malformed response body and an SDK
    error say that the call itself is wrong, not the moment it was made. A second
    attempt with the same input would only repeat the failure.
    """


@runtime_checkable
class LLMClient(Protocol):
    """What the analyzer needs from a model provider.

    Implementations send the prompt to their provider and return the raw answer text
    — fences and all; stripping them is the parser's job. They translate their
    library's failures into :class:`RetryableModelError` or :class:`ModelError` so
    that the analysis service never imports a provider SDK.
    """

    def complete(self, prompt: str) -> str:
        """Send ``prompt`` to the provider and return the raw answer text."""
        ...


CHAT_COMPLETIONS_PATH = "/chat/completions"
"""Suffix of an OpenAI-compatible base URL that answers a chat prompt."""

PREFILL = "sentiment:"
"""Assistant turn that opens the Anthropic answer, as in the legacy call."""

TRUNCATED_FINISH_REASON = "length"
"""``finish_reason`` of an answer whose token budget ran out before the verdict."""

_PREFILL_PREFIXES = ("{", "```")
"""How an answer starts when the model ignored the prefill and answered the object."""

_EXCERPT_LENGTH = 80

_RETRYABLE_ANTHROPIC_ERRORS = (
    RateLimitError,
    InternalServerError,
    APITimeoutError,
    APIConnectionError,
)
"""Anthropic failures another attempt can fix — the four the legacy service retried."""


class OpenAICompatibleClient:
    """The ``/v1/chat/completions`` adapter of the local GB10 servers.

    One class covers every OpenAI-compatible endpoint of the GX10 — port 8004
    (``gb10-writing``, the default), 8000 (``gb10-reasoning``) and 8001
    (``gb10-embedding``). The port is part of ``base_url``; nothing else differs, so the
    provider is chosen in the configuration, not in the code.

    Attributes:
        base_url: OpenAI-compatible base URL, e.g. ``http://192.168.178.87:8004/v1``.
        model: Model id sent in the payload, e.g. ``gb10-writing``.
        api_key: Bearer token; empty sends no ``Authorization`` header, which the GX10
            servers do not need.
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


class AnthropicClient:
    """The Anthropic adapter, carrying the legacy call and its prefill.

    The prefill is the ``assistant`` turn the legacy call sent to keep the answer to the
    object itself; an answer that ignored it and starts with ``{`` or a fence is passed
    on unchanged, so the parser reads what the model actually said.

    Attributes:
        model: Anthropic model id, e.g. ``claude-3-5-haiku-20241022``.
        max_tokens: Token budget of one answer (``MAX_TOKENS``, the legacy setting).
        prefill: Assistant turn that opens the answer.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        prefill: str = PREFILL,
        client: Any = None,
    ) -> None:
        """Store the model and the SDK client; ``client`` is the seam for the tests.

        Args:
            model: Anthropic model id.
            api_key: Anthropic API key; empty is accepted here because the configuration
                already refuses ``LLM_PROVIDER=anthropic`` without one.
            max_tokens: Token budget of one answer.
            prefill: Assistant turn that opens the answer.
            client: ``anthropic.Anthropic``-like object. Defaults to a real client.
        """
        self.model = model
        self._max_tokens = max_tokens
        self._prefill = prefill
        self._client = client if client is not None else Anthropic(api_key=api_key)

    def complete(self, prompt: str) -> str:
        """Send ``prompt`` with the prefill and return the raw answer text.

        Args:
            prompt: The analysis prompt of one post.

        Returns:
            The answer text, prefixed with :data:`PREFILL` when the model continued the
            assistant turn instead of writing the object.

        Raises:
            RetryableModelError: Rate limit, overload, timeout or connection failure —
                the legacy retryable four — and an empty or ``max_tokens``-cut answer.
            ModelError: A rejected request or any other SDK error.
        """
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": self._prefill},
                ],
            )
        # boundary: retryable first — RateLimitError and InternalServerError are status errors
        except _RETRYABLE_ANTHROPIC_ERRORS as error:
            raise RetryableModelError(f"{self.model}: {type(error).__name__}: {error}") from error
        except (APIStatusError, AnthropicError) as error:
            raise ModelError(f"{self.model}: {type(error).__name__}: {error}") from error
        return self._answer(message)

    def _answer(self, message: Any) -> str:
        """Return the text of ``message``, with the prefill restored when it is bare.

        Raises:
            RetryableModelError: The answer has no text, or ``stop_reason`` says the
                budget ran out (``max_tokens``).
        """
        stop_reason = getattr(message, "stop_reason", None)
        content = getattr(message, "content", None) or []
        text = ""
        for block in content:
            if getattr(block, "type", "text") == "text":
                text = getattr(block, "text", "")
                break
        if stop_reason == "max_tokens":
            raise RetryableModelError(
                f"{self.model}: the answer was cut off (stop_reason='max_tokens');"
                " the budget was not enough"
            )
        if not text.strip():
            raise RetryableModelError(
                f"{self.model}: the answer is empty (stop_reason={stop_reason!r});"
                " the budget may have been spent before the verdict"
            )
        if text.lstrip().startswith(_PREFILL_PREFIXES):
            return text
        return self._prefill + text


def build_client(settings: Settings) -> LLMClient:
    """Return the adapter ``settings.llm_provider`` selects.

    Args:
        settings: The resolved settings; the adapter reads its endpoint, model, key,
            timeout and budget from it.

    Returns:
        :class:`AnthropicClient` when the provider is ``anthropic`` — today's behaviour
        with the legacy ``max_tokens`` and ``ai_model`` — and
        :class:`OpenAICompatibleClient` on ``llm_base_url``/``llm_model`` for every other
        value, which ``config.from_env`` has already restricted to ``local``.
    """
    if settings.llm_provider == "anthropic":
        return AnthropicClient(
            settings.ai_model,
            settings.anthropic_api_key,
            max_tokens=settings.max_tokens,
        )
    return OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
    )


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
