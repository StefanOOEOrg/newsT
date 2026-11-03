"""Environment-backed configuration of the newstrading package.

Settings are resolved once through :func:`from_env` and passed down explicitly.
No module reads ``os.environ`` at import time — the service that starts reads the
environment, hands the mapping in, and fails with a message naming what is missing.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from newstrading.errors import ConfigError

DEFAULT_AI_MODEL = "claude-3-5-haiku-20241022"
"""Model id of the Anthropic adapter when ``AI_MODEL`` is unset."""

DEFAULT_LLM_PROVIDER = "local"
"""Provider of the analysis calls when ``LLM_PROVIDER`` is unset."""

LLM_PROVIDERS = ("local", "anthropic")
"""Providers :func:`from_env` accepts; any other value stops the process."""

DEFAULT_LLM_BASE_URL = "http://192.168.178.87:8004/v1"
"""OpenAI-compatible base URL of the local provider — ``gb10-writing`` on the GX10."""

DEFAULT_LLM_MODEL = "gb10-writing"
"""Model id sent to the local provider."""

DEFAULT_LLM_TIMEOUT = 60.0
"""Seconds one model call may take; the measured local answer needs 9–11 s."""

DEFAULT_LLM_MAX_TOKENS = 1024
"""Answer budget that leaves room for the reasoning prefix of the local model."""

DEFAULT_LLM_MAX_CONCURRENCY = 1
"""Model calls in flight during one analyze pass; ``1`` is the serial case."""

LLM_MAX_CONCURRENCY_RANGE = (1, 16)
"""Accepted ``LLM_MAX_CONCURRENCY`` values, both ends included."""

REQUIRED_VARIABLES = ("DATABASE_URL",)
"""Variables every process needs, in the order a combined error names them.

``ANTHROPIC_API_KEY`` is not in this tuple: it is required only when
``LLM_PROVIDER=anthropic`` and therefore lives next to the provider switch.
"""


@dataclass(frozen=True)
class Settings:
    """Resolved application settings.

    Attributes:
        database_url: PostgreSQL connection string (``DATABASE_URL``).
        anthropic_api_key: Anthropic API key (``ANTHROPIC_API_KEY``); required only
            when the provider is ``anthropic``, empty otherwise.
        ai_model: Model id for the analysis calls (``AI_MODEL``).
        max_tokens: Maximum tokens of one analysis response (``MAX_TOKENS``).
        analysis_interval_minutes: Minutes between two analysis runs
            (``ANALYSIS_INTERVAL_MINUTES``).
        content_max_length: Characters of post content sent to the model
            (``CONTENT_MAX_LENGTH``).
        alert_summary_max_length: Characters of the alert summary
            (``ALERT_SUMMARY_MAX_LENGTH``).
        log_level: Console log level (``LOG_LEVEL``), upper-cased.
        database_log_level: Database log level (``DATABASE_LOG_LEVEL``), upper-cased.
        newsapi_key: NewsAPI.org API key (``NEWSAPI_KEY``); empty disables the source.
        finnhub_api_key: Finnhub API key (``FINNHUB_API_KEY``); empty disables the source.
        alphavantage_api_key: Alpha Vantage API key (``ALPHAVANTAGE_API_KEY``); empty
            disables the source.
        congress_trades_api_key: Premium congressional trades API key
            (``CONGRESS_TRADES_API_KEY``); empty keeps the public source only.
        congress_trades_api_url: Premium congressional trades endpoint
            (``CONGRESS_TRADES_API_URL``); empty keeps the public source only.
        llm_provider: Provider of the analysis calls (``LLM_PROVIDER``), either
            ``local`` (OpenAI-compatible) or ``anthropic``.
        llm_base_url: Base URL of the local provider (``LLM_BASE_URL``).
        llm_model: Model id sent to the local provider (``LLM_MODEL``).
        llm_api_key: Bearer token of the local provider (``LLM_API_KEY``); empty
            sends no authorization header.
        llm_timeout: Seconds one model call may take (``LLM_TIMEOUT``).
        llm_max_tokens: Maximum tokens of one local answer (``LLM_MAX_TOKENS``).
        llm_max_concurrency: Model calls in flight in one analyze pass
            (``LLM_MAX_CONCURRENCY``), between 1 and 16.
    """

    database_url: str
    anthropic_api_key: str = ""
    ai_model: str = DEFAULT_AI_MODEL
    max_tokens: int = 512
    analysis_interval_minutes: int = 5
    content_max_length: int = 2000
    alert_summary_max_length: int = 180
    log_level: str = "INFO"
    database_log_level: str = "INFO"
    newsapi_key: str = ""
    finnhub_api_key: str = ""
    alphavantage_api_key: str = ""
    congress_trades_api_key: str = ""
    congress_trades_api_url: str = ""
    llm_provider: str = DEFAULT_LLM_PROVIDER
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_api_key: str = ""
    llm_timeout: float = DEFAULT_LLM_TIMEOUT
    llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    llm_max_concurrency: int = DEFAULT_LLM_MAX_CONCURRENCY


def from_env(environ: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from a mapping of environment variables.

    Args:
        environ: Mapping to read from. ``None`` (the default) means ``os.environ``.

    Returns:
        A frozen :class:`Settings` with every field resolved.

    Raises:
        ConfigError: If a required variable is missing or empty, if an integer or a
            numeric variable does not hold such a value, if ``ANALYSIS_INTERVAL_MINUTES``
            is not greater than zero, if ``LLM_PROVIDER`` names an unknown provider, if
            ``LLM_MAX_CONCURRENCY`` is outside ``1..16``, or if the ``anthropic``
            provider has no ``ANTHROPIC_API_KEY``.

    Contract:
        * Required: ``DATABASE_URL``, plus ``ANTHROPIC_API_KEY`` when
          ``LLM_PROVIDER=anthropic``. If several are missing, one ``ConfigError``
          names all of them in the order of ``REQUIRED_VARIABLES``, message shape:
          ``missing required environment variables: DATABASE_URL``.
        * Optional variables use the defaults of :class:`Settings` when they are
          absent **or empty**.
        * ``LLM_PROVIDER`` must be one of ``local`` and ``anthropic``, otherwise
          ``ConfigError`` with the shape
          ``LLM_PROVIDER must be one of local, anthropic, got 'openai'``.
        * ``MAX_TOKENS``, ``ANALYSIS_INTERVAL_MINUTES``, ``CONTENT_MAX_LENGTH``,
          ``ALERT_SUMMARY_MAX_LENGTH``, ``LLM_MAX_TOKENS`` and ``LLM_MAX_CONCURRENCY``
          are parsed as integers; a non-integer raises ``ConfigError`` with the shape
          ``MAX_TOKENS must be an integer, got 'abc'``.
        * ``LLM_TIMEOUT`` is parsed as a number, otherwise ``ConfigError`` with the
          shape ``LLM_TIMEOUT must be a number, got 'soon'``.
        * ``ANALYSIS_INTERVAL_MINUTES`` must be greater than zero, otherwise
          ``ConfigError`` with the shape
          ``ANALYSIS_INTERVAL_MINUTES must be greater than 0, got 0``.
        * ``LLM_MAX_CONCURRENCY`` must be between 1 and 16, otherwise ``ConfigError``
          with the shape
          ``LLM_MAX_CONCURRENCY must be between 1 and 16, got 0``.
        * ``LOG_LEVEL`` and ``DATABASE_LOG_LEVEL`` are returned upper-cased.
    """
    source = os.environ if environ is None else environ

    missing = [name for name in REQUIRED_VARIABLES if not source.get(name)]
    if missing:
        raise ConfigError(f"missing required environment variables: {', '.join(missing)}")

    def text(name: str, default: str) -> str:
        return source.get(name) or default

    def integer(name: str, default: int) -> int:
        raw = text(name, str(default))
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"{name} must be an integer, got {raw!r}") from None

    def number(name: str, default: float) -> float:
        raw = text(name, str(default))
        try:
            return float(raw)
        except ValueError:
            raise ConfigError(f"{name} must be a number, got {raw!r}") from None

    provider = text("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)
    if provider not in LLM_PROVIDERS:
        raise ConfigError(
            f"LLM_PROVIDER must be one of {', '.join(LLM_PROVIDERS)}, got {provider!r}"
        )
    anthropic_api_key = text("ANTHROPIC_API_KEY", "")
    if provider == "anthropic" and not anthropic_api_key:
        raise ConfigError("missing required environment variables: ANTHROPIC_API_KEY")

    interval = integer("ANALYSIS_INTERVAL_MINUTES", 5)
    if interval <= 0:
        raise ConfigError(f"ANALYSIS_INTERVAL_MINUTES must be greater than 0, got {interval}")

    concurrency = integer("LLM_MAX_CONCURRENCY", DEFAULT_LLM_MAX_CONCURRENCY)
    lowest, highest = LLM_MAX_CONCURRENCY_RANGE
    if not lowest <= concurrency <= highest:
        raise ConfigError(
            f"LLM_MAX_CONCURRENCY must be between {lowest} and {highest}, got {concurrency}"
        )

    return Settings(
        database_url=source["DATABASE_URL"],
        anthropic_api_key=anthropic_api_key,
        ai_model=text("AI_MODEL", DEFAULT_AI_MODEL),
        max_tokens=integer("MAX_TOKENS", 512),
        analysis_interval_minutes=interval,
        content_max_length=integer("CONTENT_MAX_LENGTH", 2000),
        alert_summary_max_length=integer("ALERT_SUMMARY_MAX_LENGTH", 180),
        log_level=text("LOG_LEVEL", "INFO").upper(),
        database_log_level=text("DATABASE_LOG_LEVEL", "INFO").upper(),
        newsapi_key=text("NEWSAPI_KEY", ""),
        finnhub_api_key=text("FINNHUB_API_KEY", ""),
        alphavantage_api_key=text("ALPHAVANTAGE_API_KEY", ""),
        congress_trades_api_key=text("CONGRESS_TRADES_API_KEY", ""),
        congress_trades_api_url=text("CONGRESS_TRADES_API_URL", ""),
        llm_provider=provider,
        llm_base_url=text("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        llm_model=text("LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_api_key=text("LLM_API_KEY", ""),
        llm_timeout=number("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT),
        llm_max_tokens=integer("LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS),
        llm_max_concurrency=concurrency,
    )
