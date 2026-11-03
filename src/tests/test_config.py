"""Tests for newstrading.config."""

import dataclasses

import pytest

from newstrading.config import Settings, from_env
from newstrading.errors import ConfigError, NewsTradingError

REQUIRED = {"DATABASE_URL": "postgresql://user:***@localhost:5432/newstrading"}


def test_from_env_uses_defaults_for_absent_optionals():
    """Every optional variable falls back to the documented default."""
    settings = from_env(dict(REQUIRED))

    assert isinstance(settings, Settings)
    assert settings.database_url == REQUIRED["DATABASE_URL"]
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
    assert settings.llm_base_url == "http://192.168.178.87:8004/v1"
    assert settings.llm_model == "gb10-writing"
    assert settings.llm_api_key == ""
    assert settings.llm_timeout == 60.0
    assert settings.llm_max_tokens == 1024
    assert settings.llm_max_concurrency == 1
    assert settings.llm_fallback == ""
    assert settings.llm_fallback_model == settings.llm_model
    assert settings.llm_fallback_api_key == ""


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
            "ANALYSIS_INTERVAL_MINUTES": "15",
            "CONTENT_MAX_LENGTH": "500",
            "ALERT_SUMMARY_MAX_LENGTH": "120",
            "LOG_LEVEL": "debug",
            "DATABASE_LOG_LEVEL": "warning",
        }
    )

    settings = from_env(env)

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


def test_from_env_treats_empty_required_variable_as_missing():
    """An empty string is not a configuration."""
    env = dict(REQUIRED)
    env["DATABASE_URL"] = ""

    with pytest.raises(ConfigError) as error:
        from_env(env)

    assert "DATABASE_URL" in str(error.value)


def test_from_env_rejects_a_non_integer():
    """A malformed integer names the variable and the offending value."""
    env = dict(REQUIRED)
    env["LLM_MAX_TOKENS"] = "abc"

    with pytest.raises(ConfigError) as error:
        from_env(env)

    assert str(error.value) == "LLM_MAX_TOKENS must be an integer, got 'abc'"


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
    env["LLM_MAX_TOKENS"] = ""
    env["LOG_LEVEL"] = ""
    env["NEWSAPI_KEY"] = ""

    settings = from_env(env)

    assert settings.llm_max_tokens == 1024
    assert settings.log_level == "INFO"
    assert settings.newsapi_key == ""


def test_settings_is_frozen():
    """Settings must not be mutated after they were resolved."""
    settings = from_env(dict(REQUIRED))

    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.llm_max_tokens = 1  # type: ignore[misc]


def test_config_error_is_a_newstrading_error():
    """The package exposes one catchable base type (guideline §6)."""
    assert issubclass(ConfigError, NewsTradingError)


def test_from_env_reads_the_llm_settings():
    """The endpoint, the model and the limits come from the environment."""
    env = dict(REQUIRED)
    env.update(
        {
            "LLM_BASE_URL": "http://model.internal:9000/v1",
            "LLM_MODEL": "primary-model",
            "LLM_API_KEY": "primary-key",
            "LLM_TIMEOUT": "12.5",
            "LLM_MAX_TOKENS": "2048",
            "LLM_MAX_CONCURRENCY": "3",
        }
    )

    settings = from_env(env)

    assert settings.llm_base_url == "http://model.internal:9000/v1"
    assert settings.llm_model == "primary-model"
    assert settings.llm_api_key == "primary-key"
    assert settings.llm_timeout == 12.5
    assert settings.llm_max_tokens == 2048
    assert settings.llm_max_concurrency == 3


def test_from_env_reads_a_full_fallback_set():
    """A fallback endpoint, its model and its key are all optional and all read."""
    env = dict(REQUIRED)
    env.update(
        {
            "LLM_FALLBACK": "https://fallback.internal/v1",
            "LLM_FALLBACK_MODEL": "backup-model",
            "LLM_FALLBACK_API_KEY": "backup-key",
        }
    )

    settings = from_env(env)

    assert settings.llm_fallback == "https://fallback.internal/v1"
    assert settings.llm_fallback_model == "backup-model"
    assert settings.llm_fallback_api_key == "backup-key"


def test_the_fallback_model_defaults_to_the_primary_model():
    """Without ``LLM_FALLBACK_MODEL`` the fallback answers with ``LLM_MODEL``."""
    env = dict(REQUIRED)
    env.update({"LLM_MODEL": "primary-model", "LLM_FALLBACK": "http://fallback.internal:8000/v1"})

    settings = from_env(env)

    assert settings.llm_fallback_model == "primary-model"


def test_from_env_accepts_a_different_endpoint_with_a_trailing_slash():
    """The trailing slash is not part of the comparison."""
    env = dict(REQUIRED)
    env.update(
        {
            "LLM_BASE_URL": "http://192.168.178.87:8004/v1",
            "LLM_FALLBACK": "http://192.168.178.87:8000/v1/",
        }
    )

    settings = from_env(env)

    assert settings.llm_fallback == "http://192.168.178.87:8000/v1/"


@pytest.mark.parametrize("value", ["fallback.internal", "/v1", "ftp://fallback.internal/v1"])
def test_from_env_rejects_a_fallback_that_is_not_an_absolute_http_url(value):
    """A fallback has to be an absolute ``http``/``https`` URL."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, "LLM_FALLBACK": value})

    message = str(error.value)
    assert "LLM_FALLBACK" in message
    assert "http" in message


@pytest.mark.parametrize("name", ["LLM_FALLBACK_MODEL", "LLM_FALLBACK_API_KEY"])
def test_from_env_rejects_a_fallback_setting_without_a_fallback(name):
    """A model or key for a fallback that does not exist misconfigures the seam."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, name: "value"})

    assert str(error.value) == f"{name} requires LLM_FALLBACK"


def test_from_env_rejects_the_primary_endpoint_as_fallback():
    """Falling back to the same endpoint buys nothing, even with a trailing slash."""
    env = dict(REQUIRED)
    env.update(
        {
            "LLM_BASE_URL": "http://192.168.178.87:8004/v1/",
            "LLM_FALLBACK": "http://192.168.178.87:8004/v1",
        }
    )

    with pytest.raises(ConfigError) as error:
        from_env(env)

    message = str(error.value)
    assert "LLM_FALLBACK" in message
    assert "LLM_BASE_URL" in message
    assert "buys nothing" in message


@pytest.mark.parametrize("value", ["0", "-1", "17"])
def test_from_env_rejects_a_concurrency_outside_the_range(value):
    """A worker count below one would stall the pass; above 16 overloads the model."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, "LLM_MAX_CONCURRENCY": value})

    message = str(error.value)
    assert "LLM_MAX_CONCURRENCY" in message
    assert value in message
    assert "1" in message
    assert "16" in message


def test_from_env_rejects_a_non_integer_concurrency():
    """A malformed worker count names the variable and the offending value."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, "LLM_MAX_CONCURRENCY": "three"})

    assert str(error.value) == "LLM_MAX_CONCURRENCY must be an integer, got 'three'"


def test_from_env_rejects_a_non_numeric_timeout():
    """The timeout is a number of seconds, not a duration string."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, "LLM_TIMEOUT": "soon"})

    assert str(error.value) == "LLM_TIMEOUT must be a number, got 'soon'"
