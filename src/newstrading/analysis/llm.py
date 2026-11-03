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

from typing import Protocol, runtime_checkable


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
