"""Build the prompt that is sent to the model for one post.

The template can come from the database (``notification_settings.analysis_prompt``), so
its content is not ours to control. That is why placeholders are filled by literal
substitution and not with :meth:`str.format`: a template that shows a JSON example
carries braces of its own, and ``format`` would read them as missing keys and raise
``KeyError``.
"""

from collections.abc import Callable

import psycopg2

from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.db import Connector

ASSET_NAME_PLACEHOLDER = "{asset_name}"
TICKER_PLACEHOLDER = "{ticker}"
POST_PLACEHOLDER = "{text_to_analyze}"

DEFAULT_PROMPT_TEMPLATE = """Analyze this post about {asset_name} ({ticker}) as a trader.

Post data (JSON):
{text_to_analyze}

Answer with a single JSON object and nothing else:
{
  "sentiment": "positive" | "negative" | "neutral",
  "sentiment_score": a number between -1.0 (very bearish) and 1.0 (very bullish),
  "category": "Hiring" | "Growth" | "Problems" | "Product" | "Earnings" | "Other",
  "key_topics": ["2 to 5 short topics"],
  "summary": "one or two sentences, at most 100 words",
  "special_events": ["event types, or an empty list"]
}

Bullish (long): hiring, partnerships, product launches, earnings beats, growth, positive guidance.
Bearish (short): problems, layoffs, negative coverage, downgrades, missed earnings, legal issues."""
"""Fallback template used when the database holds none."""


class PromptBuilder:
    """Build the analysis prompt for a post.

    Attributes:
        template_loader: Called once to obtain the template; a callable returning the
            template string. Defaults to :data:`DEFAULT_PROMPT_TEMPLATE`.
    """

    def __init__(
        self,
        template_loader: Callable[[], str] | None = None,
        *,
        content_max_length: int = 2000,
    ) -> None:
        """Store the loader and start without a cached template.

        Args:
            template_loader: Returns the template text. Called on the first
                :meth:`build` and again after :meth:`reload`. Exceptions it raises are
                not caught here — a template that cannot be read is a real failure, not
                a reason to analyse with a prompt nobody chose.
            content_max_length: Characters of ``post.content`` that reach the model;
                pass :attr:`Settings.content_max_length` in production.
        """
        raise NotImplementedError

    @property
    def template(self) -> str:
        """The cached template, loading it on first use.

        Returns:
            The template text.

        Contract:
            * The loader runs at most once per cache generation, even across many
              :meth:`build` calls — one prompt per post must not mean one query per post.
            * The loaded text is cached as is, empty string included.
        """
        raise NotImplementedError

    def reload(self) -> None:
        """Drop the cached template so the next :meth:`template` loads it again.

        Contract:
            * Never calls the loader itself.
            * Safe on a builder that has not loaded yet.
        """
        raise NotImplementedError

    def build(self, post: Post, asset: Asset) -> str:
        """Fill the template for ``post`` and its ``asset``.

        Args:
            post: The post to analyse.
            asset: Asset the post was collected for; supplies name and ticker.

        Returns:
            The prompt, ready to send.

        Contract:
            * ``{asset_name}``, ``{ticker}`` and ``{text_to_analyze}`` are replaced by
              literal substitution (:meth:`str.replace`), so braces anywhere else in the
              template survive untouched.
            * ``{text_to_analyze}`` is filled with :meth:`payload`.
            * A placeholder that does not occur in the template is not an error.
        """
        raise NotImplementedError

    def payload(self, post: Post, asset: Asset) -> str:
        """Render the post as the JSON block that goes into the prompt.

        Args:
            post: The post to render.
            asset: Asset the post was collected for; supplies name and ticker.

        Returns:
            A JSON object string with ``title``, ``asset_name``, ``ticker`` and, when
            present, ``content``.

        Contract:
            * Keys are written in that order so two prompts for the same post are
              byte-identical — otherwise a cached prompt and a fresh one differ and the
              difference looks like model drift.
            * ``content`` is cut to :attr:`Settings.content_max_length` characters.
            * ``content`` that is ``None`` or empty leaves the key out entirely; a
              literal ``"None"`` must never reach the model.
            * Non-ASCII text is kept as is (``ensure_ascii=False``).
        """
        raise NotImplementedError


def database_prompt_loader(
    settings: Settings, *, connector: Connector = psycopg2.connect
) -> Callable[[], str]:
    """Return a loader that reads the template from the database.

    Args:
        settings: Settings with ``database_url``.
        connector: Connection factory, injected in tests.

    Returns:
        A zero-argument callable that returns the template on each call.

    Raises:
        DatabaseError: If the query fails, raised by :func:`newstrading.db.connection`.

    Contract:
        * Reads ``analysis_prompt`` from ``notification_settings`` where ``id = 1``.
        * A missing row, a ``NULL`` or a blank value returns
          :data:`DEFAULT_PROMPT_TEMPLATE` — the analysis must not stop because nobody
          configured a prompt, and silently sending an empty prompt would be worse.
        * The returned text is used verbatim, not stripped.
    """
    raise NotImplementedError
