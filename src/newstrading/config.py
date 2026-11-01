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

REQUIRED_VARIABLES = ("DATABASE_URL", "ANTHROPIC_API_KEY")


@dataclass(frozen=True)
class Settings:
    """Resolved application settings.

    Attributes:
        database_url: PostgreSQL connection string (``DATABASE_URL``).
        anthropic_api_key: Anthropic API key (``ANTHROPIC_API_KEY``).
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
    """

    database_url: str
    anthropic_api_key: str
    ai_model: str = DEFAULT_AI_MODEL
    max_tokens: int = 512
    analysis_interval_minutes: int = 5
    content_max_length: int = 2000
    alert_summary_max_length: int = 180
    log_level: str = "INFO"
    database_log_level: str = "INFO"


def from_env(environ: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from a mapping of environment variables.

    Args:
        environ: Mapping to read from. ``None`` (the default) means ``os.environ``.

    Returns:
        A frozen :class:`Settings` with every field resolved.

    Raises:
        ConfigError: If a required variable is missing or empty, if an integer
            variable does not hold an integer, or if ``ANALYSIS_INTERVAL_MINUTES``
            is not greater than zero.

    Contract:
        * Required: ``DATABASE_URL``, ``ANTHROPIC_API_KEY``. If several are missing,
          one ``ConfigError`` names all of them in the order of
          ``REQUIRED_VARIABLES``, message shape:
          ``missing required environment variables: DATABASE_URL, ANTHROPIC_API_KEY``.
        * Optional variables use the defaults of :class:`Settings` when they are
          absent **or empty**.
        * ``MAX_TOKENS``, ``ANALYSIS_INTERVAL_MINUTES``, ``CONTENT_MAX_LENGTH`` and
          ``ALERT_SUMMARY_MAX_LENGTH`` are parsed as integers; a non-integer raises
          ``ConfigError`` with the shape
          ``MAX_TOKENS must be an integer, got 'abc'``.
        * ``ANALYSIS_INTERVAL_MINUTES`` must be greater than zero, otherwise
          ``ConfigError`` with the shape
          ``ANALYSIS_INTERVAL_MINUTES must be greater than 0, got 0``.
        * ``LOG_LEVEL`` and ``DATABASE_LOG_LEVEL`` are returned upper-cased.
    """
    source = os.environ if environ is None else environ

    missing = [name for name in REQUIRED_VARIABLES if not source.get(name)]
    if missing:
        raise ConfigError(f"missing required environment variables: {', '.join(missing)}")

    base = Settings(
        database_url=source["DATABASE_URL"], anthropic_api_key=source["ANTHROPIC_API_KEY"]
    )

    def text(name: str, default: str) -> str:
        return source.get(name) or default

    def integer(name: str, default: int) -> int:
        raw = text(name, str(default))
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"{name} must be an integer, got {raw!r}") from None

    interval = integer("ANALYSIS_INTERVAL_MINUTES", base.analysis_interval_minutes)
    if interval <= 0:
        raise ConfigError(f"ANALYSIS_INTERVAL_MINUTES must be greater than 0, got {interval}")

    return Settings(
        database_url=base.database_url,
        anthropic_api_key=base.anthropic_api_key,
        ai_model=text("AI_MODEL", DEFAULT_AI_MODEL),
        max_tokens=integer("MAX_TOKENS", base.max_tokens),
        analysis_interval_minutes=interval,
        content_max_length=integer("CONTENT_MAX_LENGTH", base.content_max_length),
        alert_summary_max_length=integer("ALERT_SUMMARY_MAX_LENGTH", base.alert_summary_max_length),
        log_level=text("LOG_LEVEL", base.log_level).upper(),
        database_log_level=text("DATABASE_LOG_LEVEL", base.database_log_level).upper(),
    )
