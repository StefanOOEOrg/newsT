"""Tests for newstrading.config."""

import dataclasses

import pytest

from newstrading.config import DEFAULT_AI_MODEL, Settings, from_env
from newstrading.errors import ConfigError, NewsTradingError

REQUIRED = {
    "DATABASE_URL": "postgresql://user:pw@localhost:5432/newstrading",
    "ANTHROPIC_API_KEY": "sk-test",
}


def test_from_env_uses_defaults_for_absent_optionals():
    """Every optional variable falls back to the documented default."""
    settings = from_env(dict(REQUIRED))

    assert isinstance(settings, Settings)
    assert settings.database_url == REQUIRED["DATABASE_URL"]
    assert settings.anthropic_api_key == "sk-test"
    assert settings.ai_model == DEFAULT_AI_MODEL
    assert settings.max_tokens == 512
    assert settings.analysis_interval_minutes == 5
    assert settings.content_max_length == 2000
    assert settings.alert_summary_max_length == 180
    assert settings.log_level == "INFO"
    assert settings.database_log_level == "INFO"
    assert settings.newsapi_key == ""
    assert settings.finnhub_api_key == ""
    assert settings.alphavantage_api_key == ""
    assert settings.congress_trades_api_key == ""
    assert settings.congress_trades_api_url == ""


def test_from_env_reads_the_collector_api_keys():
    """The three key-based collectors get their credentials from the environment."""
    env = dict(REQUIRED)
    env.update(
        {
            "NEWSAPI_KEY": "newsapi-key",
            "FINNHUB_API_KEY": "finnhub-key",
            "ALPHAVANTAGE_API_KEY": "alpha-key",
        }
    )

    settings = from_env(env)

    assert settings.newsapi_key == "newsapi-key"
    assert settings.finnhub_api_key == "finnhub-key"
    assert settings.alphavantage_api_key == "alpha-key"


def test_from_env_reads_the_congressional_trades_settings():
    """The premium congressional trades source is configured, never required."""
    env = dict(REQUIRED)
    env.update(
        {
            "CONGRESS_TRADES_API_KEY": "premium-key",
            "CONGRESS_TRADES_API_URL": "https://premium.example.com/trades",
        }
    )

    settings = from_env(env)

    assert settings.congress_trades_api_key == "premium-key"
    assert settings.congress_trades_api_url == "https://premium.example.com/trades"


def test_from_env_reads_overrides():
    """Values from the mapping win over the defaults; levels are upper-cased."""
    env = dict(REQUIRED)
    env.update(
        {
            "AI_MODEL": "claude-sonnet-4-5",
            "MAX_TOKENS": "1024",
            "ANALYSIS_INTERVAL_MINUTES": "15",
            "CONTENT_MAX_LENGTH": "500",
            "ALERT_SUMMARY_MAX_LENGTH": "120",
            "LOG_LEVEL": "debug",
            "DATABASE_LOG_LEVEL": "warning",
        }
    )

    settings = from_env(env)

    assert settings.ai_model == "claude-sonnet-4-5"
    assert settings.max_tokens == 1024
    assert settings.analysis_interval_minutes == 15
    assert settings.content_max_length == 500
    assert settings.alert_summary_max_length == 120
    assert settings.log_level == "DEBUG"
    assert settings.database_log_level == "WARNING"


def test_from_env_names_every_missing_required_variable():
    """One error names all missing variables instead of failing on the first."""
    with pytest.raises(ConfigError) as error:
        from_env({})

    message = str(error.value)
    assert "missing required environment variables" in message
    assert "DATABASE_URL" in message
    assert "ANTHROPIC_API_KEY" in message


def test_from_env_treats_empty_required_variable_as_missing():
    """An empty string is not a configuration."""
    env = dict(REQUIRED)
    env["DATABASE_URL"] = ""

    with pytest.raises(ConfigError) as error:
        from_env(env)

    message = str(error.value)
    assert "DATABASE_URL" in message
    assert "ANTHROPIC_API_KEY" not in message


def test_from_env_rejects_a_non_integer():
    """A malformed integer names the variable and the offending value."""
    env = dict(REQUIRED)
    env["MAX_TOKENS"] = "abc"

    with pytest.raises(ConfigError) as error:
        from_env(env)

    assert str(error.value) == "MAX_TOKENS must be an integer, got 'abc'"


def test_from_env_rejects_a_non_positive_interval():
    """An interval of zero would schedule a run per instant."""
    env = dict(REQUIRED)
    env["ANALYSIS_INTERVAL_MINUTES"] = "0"

    with pytest.raises(ConfigError) as error:
        from_env(env)

    assert str(error.value) == "ANALYSIS_INTERVAL_MINUTES must be greater than 0, got 0"


def test_from_env_treats_empty_optional_variable_as_default():
    """Optional variables set to an empty string behave like unset ones."""
    env = dict(REQUIRED)
    env["MAX_TOKENS"] = ""
    env["LOG_LEVEL"] = ""
    env["NEWSAPI_KEY"] = ""

    settings = from_env(env)

    assert settings.max_tokens == 512
    assert settings.log_level == "INFO"
    assert settings.newsapi_key == ""


def test_settings_is_frozen():
    """Settings must not be mutated after they were resolved."""
    settings = from_env(dict(REQUIRED))

    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.max_tokens = 1  # type: ignore[misc]


def test_config_error_is_a_newstrading_error():
    """The package exposes one catchable base type (guideline §6)."""
    assert issubclass(ConfigError, NewsTradingError)
