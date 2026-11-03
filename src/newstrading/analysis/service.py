"""Analyse the posts that have no analysis yet and store the result.

The module ports ``analyzer/main.py`` (``get_unanalyzed_posts``, ``analyze_post`` and
``save_analysis``) into the package. It selects the posts whose analysis is missing,
builds their prompt, calls the model, parses the answer and writes one row per post to
``ai_analysis`` — the service the CLI's ``analyze`` command runs.

The database connection, the model call and the sleep are injected, so the analyzer is
testable without a database, a socket or a real wait. A batch calls the model up to
``LLM_MAX_CONCURRENCY`` times at once (:class:`~concurrent.futures.ThreadPoolExecutor`) and
still stores its rows in the order the database returned them, so the write order does not
depend on which answer arrives first: ``1`` and ``3`` calls in flight write the same rows in
the same order. The retry policy is the legacy one: a post is not retried forever. An empty
answer is retried when the completion raises
:class:`~newstrading.analysis.llm.RetryableModelError` — which the adapters do — and stored
as the neutral analysis only when a completion hands back an empty string instead (the
content-moderation case the legacy callable encoded).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psycopg2

from newstrading.analysis.llm import RetryableModelError
from newstrading.analysis.parser import Analysis, AnalysisParseError, parse_analysis
from newstrading.analysis.prompt import PromptBuilder, database_prompt_loader
from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings
from newstrading.db import Connector, connection
from newstrading.errors import NewsTradingError

logger = logging.getLogger(__name__)

Complete = Callable[[str], str]
"""Call the model with the prompt and return the raw answer text."""

Sleep = Callable[[float], None]
"""Wait between two attempts; injected so tests do not sleep."""

RETRY_DELAYS = (2, 4, 8)
"""Seconds to wait through ``sleep`` for the three attempts of one model call."""

RETRYABLE_ERRORS = (RetryableModelError,)
"""Failures of the model call that are worth another attempt.

:class:`RetryableModelError` is what the clients of
:mod:`newstrading.analysis.llm` raise — an empty answer (a spent token budget) is one of
them. A terminal :class:`~newstrading.analysis.llm.ModelError` is not in the tuple and
skips the post at once.
"""

NEUTRAL_ANALYSIS = Analysis(
    sentiment="neutral",
    sentiment_score=0.0,
    category="Other",
    key_topics=("Content moderation filtered",),
    summary="Content could not be analyzed due to API content filters.",
    special_events=(),
)
"""What an empty model answer becomes, so the post is not retried forever."""

UNANALYZED_SQL = """
    SELECT
        sp.id,
        sp.asset_id,
        sp.source,
        sp.post_id,
        sp.author,
        sp.title,
        sp.content,
        sp.url,
        sp.score,
        sp.created_at,
        c.name,
        c.ticker
    FROM social_posts sp
    JOIN asset c ON sp.asset_id = c.id
    LEFT JOIN ai_analysis aa ON sp.id = aa.post_id
    WHERE aa.id IS NULL
    ORDER BY sp.created_at DESC
    LIMIT %s
"""
"""Posts without an analysis, newest first; ``limit`` binds as the only parameter."""

INSERT_SQL = """
    INSERT INTO ai_analysis (
        post_id, sentiment, sentiment_score, category, key_topics, summary, special_events
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
"""
"""The legacy insert, column for column."""


class AnalysisError(NewsTradingError):
    """Raised when the analyzer cannot read posts or store an analysis."""


def _post_and_asset(row: Any) -> tuple[Post, Asset]:
    """Split one joined row into the post and the asset its prompt needs.

    Args:
        row: ``(post id, asset_id, source, post_id, author, title, content, url, score,
            created_at, name, ticker)`` as selected by :data:`UNANALYZED_SQL`.

    Returns:
        The :class:`Post` to analyse and the :class:`Asset` it belongs to. Nullable text
        columns become empty strings and a null score ``0``; the keywords are not part
        of the select because the prompt does not use them.
    """
    (
        _row_id,
        asset_id,
        source,
        post_id,
        author,
        title,
        content,
        url,
        score,
        created_at,
        name,
        ticker,
    ) = row
    post = Post(
        asset_id=asset_id,
        source=source,
        post_id=post_id,
        author=author or "",
        title=title or "",
        content=content,
        url=url or "",
        score=score or 0,
        created_at=created_at,
    )
    asset = Asset(id=asset_id, name=name, ticker=ticker, keywords=())
    return post, asset


class Analyzer:
    """Turns unanalyzed posts into rows of ``ai_analysis``."""

    def __init__(
        self,
        settings: Settings,
        *,
        connector: Connector = psycopg2.connect,
        complete: Complete,
        sleep: Sleep = time.sleep,
        builder: PromptBuilder | None = None,
        on_analysis: Callable[[Analysis, int], None] | None = None,
    ) -> None:
        """Store the seams; ``complete(prompt) -> str`` returns the raw model text.

        Args:
            settings: Settings holding ``database_url`` and ``content_max_length``.
            connector: Connection factory; tests inject a fake.
            complete: The model call. Production is ``build_client(settings).complete``;
                it returns the raw text the model answered.
            sleep: Called with each retry delay; injected so tests do not wait.
            builder: Prompt builder. Defaults to one that reads the template from the
                database once per run and cuts the content to
                ``settings.content_max_length``.
            on_analysis: Called with every analysis the run stored and the ``asset_id``
                it was stored for. The CLI wires the alert generator in here; ``None``
                keeps the batch a pure store.
        """
        self._settings = settings
        self._connector = connector
        self._complete = complete
        self._sleep = sleep
        self._on_analysis = on_analysis
        self._builder = builder or PromptBuilder(
            database_prompt_loader(settings, connector=connector),
            content_max_length=settings.content_max_length,
        )

    def analyze_pending(self, limit: int = 20) -> int:
        """Analyse up to ``limit`` posts without an analysis; return how many were stored.

        Args:
            limit: Maximum number of posts to look at; binds into the select.

        Returns:
            Number of analyses written.

        Contract:
            * One connection for the run, one commit at the end; a database failure
              rolls back and raises :class:`AnalysisError`.
            * A post the model cannot answer or whose answer cannot be parsed is logged
              and skipped, so the rest of the batch runs and the next run retries it.
            * The model calls of the batch run up to ``settings.llm_max_concurrency``
              at a time, while the rows are still stored in the order the database
              returned them — see :meth:`_store_batch`.
        """
        stored = 0
        try:
            with connection(self._settings, connector=self._connector) as db:
                stored = self._store_batch(db, self._pending_rows(db, limit))
        # boundary: driver and programming failures become the analyzer's error type
        except Exception as error:
            raise AnalysisError("analysis run failed") from error
        return stored

    def _store_batch(self, db: Any, rows: list[Any]) -> int:
        """Analyse a batch of posts in parallel and store the answers in row order.

        Args:
            db: The connection of this run; every insert goes through it.
            rows: The rows of :data:`UNANALYZED_SQL`, in the order the database
                returned them, newest post first.

        Returns:
            Number of analyses written.

        Contract:
            * The prompt is built, the model called and the answer parsed in a worker
              thread; at most ``settings.llm_max_concurrency`` model calls are in
              flight at once, and ``1`` (the default) runs them one after the other.
            * :func:`~concurrent.futures.Executor.map` yields the results in
              submission order, so a post is stored in the order of ``rows`` whichever
              call finished first — ``1`` and ``3`` write the same rows in the same
              order.
            * The insert, the commit and the ``on_analysis`` callback stay on the
              caller's thread and on the connection of the run; a post whose analysis
              is ``None`` is skipped like a failing one.
        """
        stored = 0
        workers = self._settings.llm_max_concurrency
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analyze") as executor:
            for row, analysis in zip(rows, executor.map(self._analyze, rows), strict=True):
                if analysis is None:
                    continue
                self._store(db, row[0], analysis)
                stored += 1
                if self._on_analysis is not None:
                    self._on_analysis(analysis, row[1])
        return stored

    def _pending_rows(self, db: Any, limit: int) -> list[Any]:
        """Return the joined rows of the posts that have no analysis yet.

        Args:
            db: The connection of this run.
            limit: Maximum number of rows; binds into :data:`UNANALYZED_SQL`.

        Returns:
            The rows, as the database ordered them: newest post first.
        """
        with db.cursor() as cursor:
            cursor.execute(UNANALYZED_SQL, (limit,))
            return cursor.fetchall()

    def _analyze(self, row: Any) -> Analysis | None:
        """Build the prompt of one post, call the model and parse its answer.

        Args:
            row: One row of :data:`UNANALYZED_SQL`.

        Returns:
            The analysis to store, the neutral one for an empty answer, or ``None`` when
            the post has to wait for the next run.
        """
        post, asset = _post_and_asset(row)
        prompt = self._builder.build(post, asset)
        text = self._request(prompt, post.post_id)
        if text is None:
            return None
        if not text.strip():
            logger.warning("empty answer for post %s; storing the neutral analysis", post.post_id)
            return NEUTRAL_ANALYSIS
        try:
            return parse_analysis(text)
        except AnalysisParseError as error:
            logger.error("cannot parse the answer for post %s: %s", post.post_id, error)
            return None

    def _request(self, prompt: str, post_id: str) -> str | None:
        """Call the model, retrying only the failures the legacy service retried.

        Args:
            prompt: The prompt built for one post.
            post_id: Source id of the post, used in the log lines.

        Returns:
            The raw answer text, or ``None`` after three failed attempts.
        """
        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            try:
                return self._complete(prompt)
            except RETRYABLE_ERRORS as error:
                if attempt < len(RETRY_DELAYS):
                    logger.warning(
                        "retryable model error for post %s (attempt %d/%d): %s: %s; waiting %ss",
                        post_id,
                        attempt,
                        len(RETRY_DELAYS),
                        type(error).__name__,
                        error,
                        delay,
                    )
                    self._sleep(delay)
                else:
                    logger.error(
                        "model call for post %s failed after %d attempts: %s: %s",
                        post_id,
                        len(RETRY_DELAYS),
                        type(error).__name__,
                        error,
                    )
            # boundary: any other model failure skips only this post, the batch survives
            except Exception as error:
                logger.error(
                    "model call for post %s failed: %s: %s",
                    post_id,
                    type(error).__name__,
                    error,
                )
                return None
        return None

    def _store(self, db: Any, post_id: int, analysis: Analysis) -> None:
        """Insert one analysis into ``ai_analysis``.

        Args:
            db: The connection of this run; the caller commits when the batch is done.
            post_id: Primary key of the ``social_posts`` row.
            analysis: The parsed values, mapped onto the legacy columns.
        """
        with db.cursor() as cursor:
            cursor.execute(
                INSERT_SQL,
                (
                    post_id,
                    analysis.sentiment,
                    analysis.sentiment_score,
                    analysis.category,
                    analysis.key_topics,
                    analysis.summary,
                    analysis.special_events,
                ),
            )
