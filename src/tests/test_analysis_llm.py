"""Tests for the model seam: the ``LLMClient`` protocol and its error types.

The adapters that implement the protocol are tested in their own module; here only
the contract the analyzer codes against is pinned — one method, two failure kinds.
"""

from __future__ import annotations

from newstrading.analysis.llm import LLMClient, ModelError, RetryableModelError


class RecordingClient:
    """A stand-in adapter: it records the prompt and answers with a fixed text."""

    def __init__(self, answer: str = "{}") -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


def test_a_client_with_complete_satisfies_the_protocol() -> None:
    """Nothing to inherit: an object with ``complete`` is a client."""
    client: LLMClient = RecordingClient('{"sentiment": "neutral"}')

    assert isinstance(client, LLMClient)
    assert client.complete("a prompt") == '{"sentiment": "neutral"}'
    assert client.prompts == ["a prompt"]


def test_an_object_without_complete_is_not_a_client() -> None:
    """The protocol is structural; the missing method is what disqualifies."""
    assert not isinstance(object(), LLMClient)


def test_the_retryable_and_the_terminal_error_are_separate_types() -> None:
    """A caller retries one and gives up on the other, so neither may extend the other."""
    assert not issubclass(RetryableModelError, ModelError)
    assert not issubclass(ModelError, RetryableModelError)


def test_the_error_types_keep_their_message() -> None:
    """Both carry the detail the log line needs."""
    assert str(ModelError("a 400 said no")) == "a 400 said no"
    assert str(RetryableModelError("rate limited")) == "rate limited"
