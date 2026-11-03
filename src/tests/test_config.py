"""Tests for newstrading.config."""

import dataclasses

import pytest

from newstrading.config import DEFAULT_AI_MODEL, Settings, from_env
from newstrading.errors import ConfigError, NewsTradingError

REQUIRED = {"DATABASE_URL": "postgresql://user:pw@localhost:5432/newstrading"}


def test_from_env_uses_defaults_for_absent_optionals():
    """Every optional variable falls back to the documented default."""
    settings = from_env(dict(REQUIRED))

    assert isinstance(settings, Settings)
    assert settings.database_url == REQUIRED["DATABASE_URL"]
    assert settings.anthropic_api_key == ""
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
    assert settings.llm_provider == "local"
    assert settings.llm_base_url == "http://192.168.178.87:8004/v1"
    assert settings.llm_model == "gb10-writing"
    assert settings.llm_api_key == ""
    assert settings.llm_timeout == 60.0
    assert settings.llm_max_tokens == 1024
    assert settings.llm_max_concurrency == 1


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
    # The model key is only required by the anthropic provider (see below).
    assert "ANTHROPIC_API_KEY" not in message


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


def test_from_env_reads_the_llm_settings():
    """The provider switch and the model limits come from the environment."""
    env = dict(REQUIRED)
    env.update(
        {
            "LLM_PROVIDER": "anthropic",
            "LLM_BASE_URL": "http://model.internal:9000/v1",
            "LLM_MODEL": "local-model",
            "LLM_API_KEY": "local-key",
            "LLM_TIMEOUT": "12.5",
            "LLM_MAX_TOKENS": "2048",
            "LLM_MAX_CONCURRENCY": "3",
            "ANTHROPIC_API_KEY": "sk-test",
        }
    )

    settings = from_env(env)

    assert settings.llm_provider == "anthropic"
    assert settings.llm_base_url == "http://model.internal:9000/v1"
    assert settings.llm_model == "local-model"
    assert settings.llm_api_key == "local-key"
    assert settings.llm_timeout == 12.5
    assert settings.llm_max_tokens == 2048
    assert settings.llm_max_concurrency == 3
    assert settings.anthropic_api_key == "sk-test"


def test_from_env_starts_with_the_local_provider_without_the_anthropic_key():
    """The default provider is local and it reads no Anthropic key at all."""
    settings = from_env(dict(REQUIRED))
    assert settings.llm_provider == "local"
    assert settings.anthropic_api_key == ""

    explicit = from_env({**REQUIRED, "LLM_PROVIDER": "local", "ANTHROPIC_API_KEY": ""})
    assert explicit.llm_provider == "local"
    assert explicit.anthropic_api_key == ""


def test_from_env_treats_an_empty_provider_as_the_default():
    """An empty optional variable behaves like an unset one."""
    settings = from_env({**REQUIRED, "LLM_PROVIDER": "", "LLM_MAX_CONCURRENCY": ""})

    assert settings.llm_provider == "local"
    assert settings.llm_max_concurrency == 1


def test_from_env_requires_the_anthropic_key_only_for_the_anthropic_provider():
    """``LLM_PROVIDER=anthropic`` is the one case that needs the key."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, "LLM_PROVIDER": "anthropic"})

    assert str(error.value) == "missing required environment variables: ANTHROPIC_API_KEY"


def test_from_env_rejects_an_unknown_provider():
    """A typo must fail at startup, naming the variable and both allowed values."""
    with pytest.raises(ConfigError) as error:
        from_env({**REQUIRED, "LLM_PROVIDER": "openai"})

    message = str(error.value)
    assert "LLM_PROVIDER" in message
    assert "local" in message
    assert "anthropic" in message
    assert "openai" in message


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
