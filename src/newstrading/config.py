"""Environment-backed configuration of the newstrading package.

Settings are resolved once through :func:`from_env` and passed down explicitly.
No module reads ``os.environ`` at import time — the service that starts reads the
environment, hands the mapping in, and fails with a message naming what is missing.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from newstrading.errors import ConfigError

DEFAULT_LLM_BASE_URL = "http://192.168.178.87:8004/v1"
"""OpenAI-compatible base URL of the analysis endpoint — ``gb10-writing`` on the GX10."""

DEFAULT_LLM_MODEL = "gb10-writing"
"""Model id sent to the analysis endpoint."""

DEFAULT_LLM_TIMEOUT = 60.0
"""Seconds one model call may take; the measured answer needs 9–11 s."""

DEFAULT_LLM_MAX_TOKENS = 1024
"""Answer budget that leaves room for the reasoning prefix of the model."""

DEFAULT_LLM_MAX_CONCURRENCY = 1
"""Model calls in flight during one analyze pass; ``1`` is the serial case."""

LLM_MAX_CONCURRENCY_RANGE = (1, 16)
"""Accepted ``LLM_MAX_CONCURRENCY`` values, both ends included."""

REQUIRED_VARIABLES = ("DATABASE_URL",)
"""Variables every process needs, in the order a combined error names them."""


@dataclass(frozen=True)
class Settings:
    """Resolved application settings.

    Attributes:
        database_url: PostgreSQL connection string (``DATABASE_URL``).
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
        llm_base_url: Base URL of the analysis endpoint (``LLM_BASE_URL``).
        llm_model: Model id sent to the endpoint (``LLM_MODEL``).
        llm_api_key: Bearer token of the endpoint (``LLM_API_KEY``); empty sends no
            authorization header.
        llm_timeout: Seconds one model call may take (``LLM_TIMEOUT``).
        llm_max_tokens: Maximum tokens of one answer (``LLM_MAX_TOKENS``).
        llm_max_concurrency: Model calls in flight in one analyze pass
            (``LLM_MAX_CONCURRENCY``), between 1 and 16.
        llm_fallback: Optional second endpoint (``LLM_FALLBACK``); empty disables it.
        llm_fallback_model: Model id sent to the fallback endpoint
            (``LLM_FALLBACK_MODEL``); :func:`from_env` resolves it to ``llm_model``
            when it is unset.
        llm_fallback_api_key: Bearer token of the fallback endpoint
            (``LLM_FALLBACK_API_KEY``); empty sends no authorization header.
    """

    database_url: str
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
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_api_key: str = ""
    llm_timeout: float = DEFAULT_LLM_TIMEOUT
    llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    llm_max_concurrency: int = DEFAULT_LLM_MAX_CONCURRENCY
    llm_fallback: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_key: str = ""


def _is_http_url(value: str) -> bool:
    """Return whether ``value`` is an absolute ``http``/``https`` URL with a host."""
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _check_fallback(fallback: str, model: str, api_key: str, base_url: str) -> None:
    """Reject a fallback configuration that cannot work.

    Args:
        fallback: ``LLM_FALLBACK`` as read, empty when the fallback is disabled.
        model: ``LLM_FALLBACK_MODEL`` as read, empty when it is unset.
        api_key: ``LLM_FALLBACK_API_KEY`` as read, empty when it is unset.
        base_url: ``LLM_BASE_URL``, the endpoint the fallback must differ from.

    Raises:
        ConfigError: The URL is not absolute ``http(s)``, the model or key is set
            without a fallback, or the fallback equals the primary endpoint.
    """
    if fallback and not _is_http_url(fallback):
        raise ConfigError(f"LLM_FALLBACK must be an absolute http(s) URL, got {fallback!r}")
    if not fallback:
        for name, value in (("LLM_FALLBACK_MODEL", model), ("LLM_FALLBACK_API_KEY", api_key)):
            if value:
                raise ConfigError(f"{name} requires LLM_FALLBACK")
        return
    if fallback.rstrip("/") == base_url.rstrip("/"):
        raise ConfigError(
            "LLM_FALLBACK must differ from LLM_BASE_URL; a fallback to the same endpoint"
            " buys nothing"
        )


def from_env(environ: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from a mapping of environment variables.

    Args:
        environ: Mapping to read from. ``None`` (the default) means ``os.environ``.

    Returns:
        A frozen :class:`Settings` with every field resolved.

    Raises:
        ConfigError: If a required variable is missing or empty, if an integer or a
            numeric variable does not hold such a value, if
            ``ANALYSIS_INTERVAL_MINUTES`` is not greater than zero, if
            ``LLM_MAX_CONCURRENCY`` is outside ``1..16``, or if the fallback settings
            describe an endpoint that cannot work.

    Contract:
        * Required: ``DATABASE_URL`` only. If several are missing, one ``ConfigError``
          names all of them in the order of ``REQUIRED_VARIABLES``, message shape:
          ``missing required environment variables: DATABASE_URL``.
        * Optional variables use the defaults of :class:`Settings` when they are
          absent **or empty**.
        * ``ANALYSIS_INTERVAL_MINUTES``, ``CONTENT_MAX_LENGTH``,
          ``ALERT_SUMMARY_MAX_LENGTH``, ``LLM_MAX_TOKENS`` and ``LLM_MAX_CONCURRENCY``
          are parsed as integers; a non-integer raises ``ConfigError`` with the shape
          ``LLM_MAX_TOKENS must be an integer, got 'abc'``.
        * ``LLM_TIMEOUT`` is parsed as a number, otherwise ``ConfigError`` with the
          shape ``LLM_TIMEOUT must be a number, got 'soon'``.
        * ``ANALYSIS_INTERVAL_MINUTES`` must be greater than zero, otherwise
          ``ConfigError`` with the shape
          ``ANALYSIS_INTERVAL_MINUTES must be greater than 0, got 0``.
        * ``LLM_MAX_CONCURRENCY`` must be between 1 and 16, otherwise ``ConfigError``
          with the shape
          ``LLM_MAX_CONCURRENCY must be between 1 and 16, got 0``.
        * ``LLM_FALLBACK`` is empty (no fallback) or an absolute ``http(s)`` URL;
          anything else raises ``ConfigError`` with the shape
          ``LLM_FALLBACK must be an absolute http(s) URL, got 'fallback.internal'``.
        * ``LLM_FALLBACK_MODEL`` and ``LLM_FALLBACK_API_KEY`` are rejected while
          ``LLM_FALLBACK`` is empty, with the shape
          ``LLM_FALLBACK_MODEL requires LLM_FALLBACK``.
        * ``LLM_FALLBACK`` equal to ``LLM_BASE_URL`` ignoring a trailing slash is
          rejected: a fallback to the same endpoint buys nothing.
        * ``llm_fallback_model`` resolves to ``llm_model`` when it is unset, so the
          client factory never has to.
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

    interval = integer("ANALYSIS_INTERVAL_MINUTES", 5)
    if interval <= 0:
        raise ConfigError(f"ANALYSIS_INTERVAL_MINUTES must be greater than 0, got {interval}")

    concurrency = integer("LLM_MAX_CONCURRENCY", DEFAULT_LLM_MAX_CONCURRENCY)
    lowest, highest = LLM_MAX_CONCURRENCY_RANGE
    if not lowest <= concurrency <= highest:
        raise ConfigError(
            f"LLM_MAX_CONCURRENCY must be between {lowest} and {highest}, got {concurrency}"
        )

    base_url = text("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
    model = text("LLM_MODEL", DEFAULT_LLM_MODEL)
    fallback = text("LLM_FALLBACK", "")
    fallback_model = text("LLM_FALLBACK_MODEL", "")
    fallback_api_key = text("LLM_FALLBACK_API_KEY", "")
    _check_fallback(fallback, fallback_model, fallback_api_key, base_url)

    return Settings(
        database_url=source["DATABASE_URL"],
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
        llm_base_url=base_url,
        llm_model=model,
        llm_api_key=text("LLM_API_KEY", ""),
        llm_timeout=number("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT),
        llm_max_tokens=integer("LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS),
        llm_max_concurrency=concurrency,
        llm_fallback=fallback,
        llm_fallback_model=fallback_model or model,
        llm_fallback_api_key=fallback_api_key,
    )
