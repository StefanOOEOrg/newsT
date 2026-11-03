"""Tests for the LLM settings ``analyze`` accepts on its own command line.

Each flag is the command-line counterpart of one ``LLM_*`` variable: a flag wins over
the environment, an absent flag leaves the environment value, and an invalid value is
still exit code 2 with a message that names the variable. A run of ``analyze`` needs
``DATABASE_URL`` only.
"""

import pytest

from newstrading.cli import main

URL = "postgresql://app:***@db.internal:5432/newstrading"

CONFIGURED = (
    "DATABASE_URL",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT",
    "LLM_MAX_TOKENS",
    "LLM_MAX_CONCURRENCY",
    "LLM_FALLBACK",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_API_KEY",
)

FLAGS = (
    "--llm-base-url",
    "--llm-model",
    "--llm-api-key",
    "--llm-timeout",
    "--llm-max-tokens",
    "--llm-max-concurrency",
    "--llm-fallback",
    "--llm-fallback-model",
    "--llm-fallback-api-key",
)


@pytest.fixture
def environment(monkeypatch):
    """Clear every variable the CLI reads, and keep logging away from the database."""
    for name in CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("newstrading.cli.configure_logging", lambda settings: None)
    return monkeypatch


@pytest.fixture
def analyzed(environment):
    """Give the pass a database URL and collect the settings it was handed."""
    environment.setenv("DATABASE_URL", URL)
    seen = []
    environment.setattr(
        "newstrading.cli.analyze_pending", lambda settings: seen.append(settings) or 0
    )
    return seen


def test_every_llm_flag_reaches_the_settings(environment, analyzed):
    """The nine flags replace the nine ``LLM_*`` variables of one run."""
    code = main(
        [
            "analyze",
            "--llm-base-url",
            "http://primary.internal:9000/v1",
            "--llm-model",
            "primary-model",
            "--llm-api-key",
            "primary-key",
            "--llm-timeout",
            "12.5",
            "--llm-max-tokens",
            "2048",
            "--llm-max-concurrency",
            "3",
            "--llm-fallback",
            "http://fallback.internal:8000/v1",
            "--llm-fallback-model",
            "backup-model",
            "--llm-fallback-api-key",
            "backup-key",
        ]
    )

    assert code == 0
    settings = analyzed[0]
    assert settings.llm_base_url == "http://primary.internal:9000/v1"
    assert settings.llm_model == "primary-model"
    assert settings.llm_api_key == "primary-key"
    assert settings.llm_timeout == 12.5
    assert settings.llm_max_tokens == 2048
    assert settings.llm_max_concurrency == 3
    assert settings.llm_fallback == "http://fallback.internal:8000/v1"
    assert settings.llm_fallback_model == "backup-model"
    assert settings.llm_fallback_api_key == "backup-key"


def test_without_flags_the_environment_decides(environment, analyzed):
    """No flag: the pass reads the variables, including the optional fallback."""
    environment.setenv("LLM_BASE_URL", "http://env.internal:8000/v1")
    environment.setenv("LLM_MODEL", "env-model")
    environment.setenv("LLM_TIMEOUT", "30")
    environment.setenv("LLM_MAX_TOKENS", "512")
    environment.setenv("LLM_MAX_CONCURRENCY", "4")

    assert main(["analyze"]) == 0

    settings = analyzed[0]
    assert settings.llm_base_url == "http://env.internal:8000/v1"
    assert settings.llm_model == "env-model"
    assert settings.llm_timeout == 30.0
    assert (settings.llm_max_tokens, settings.llm_max_concurrency) == (512, 4)
    assert settings.llm_fallback == ""


def test_a_flag_wins_over_an_invalid_environment_value(environment, analyzed):
    """The flag replaces the value before it is validated, so a bad variable cannot block it."""
    environment.setenv("LLM_MAX_CONCURRENCY", "0")

    assert main(["analyze", "--llm-max-concurrency", "16"]) == 0

    assert analyzed[0].llm_max_concurrency == 16


def test_an_absent_flag_keeps_the_environment_value(environment, analyzed):
    """Only the value that was given changes; the other settings stay as they were."""
    environment.setenv("LLM_MAX_TOKENS", "512")
    environment.setenv("LLM_TIMEOUT", "12.5")

    assert main(["analyze", "--llm-max-tokens", "2048"]) == 0

    settings = analyzed[0]
    assert settings.llm_max_tokens == 2048
    assert settings.llm_timeout == 12.5


def test_analyze_needs_only_the_database_url(environment, analyzed):
    """An empty ``LLM_API_KEY`` is a valid configuration; no model key is required."""
    assert main(["analyze"]) == 0

    settings = analyzed[0]
    assert settings.llm_api_key == ""
    assert settings.llm_model == "gb10-writing"
    assert settings.llm_fallback == ""


def test_a_non_integer_token_flag_exits_2_and_names_the_setting(environment, analyzed, capsys):
    """``--llm-max-tokens abc`` is rejected with the same message as the variable."""
    assert main(["analyze", "--llm-max-tokens", "abc"]) == 2

    assert "LLM_MAX_TOKENS must be an integer, got 'abc'" in capsys.readouterr().err
    assert analyzed == []


def test_a_concurrency_flag_outside_the_range_exits_2_and_names_the_range(
    environment, analyzed, capsys
):
    """``--llm-max-concurrency 0`` is rejected with the same message as the variable."""
    assert main(["analyze", "--llm-max-concurrency", "0"]) == 2

    assert "LLM_MAX_CONCURRENCY must be between 1 and 16, got 0" in capsys.readouterr().err
    assert analyzed == []


def test_a_non_numeric_timeout_flag_exits_2_and_names_the_setting(environment, analyzed, capsys):
    """``--llm-timeout soon`` is rejected with the same message as the variable."""
    assert main(["analyze", "--llm-timeout", "soon"]) == 2

    assert "LLM_TIMEOUT must be a number, got 'soon'" in capsys.readouterr().err
    assert analyzed == []


def test_a_fallback_flag_that_is_not_a_url_exits_2_and_names_the_setting(
    environment, analyzed, capsys
):
    """``--llm-fallback fallback.internal`` fails like the variable would."""
    assert main(["analyze", "--llm-fallback", "fallback.internal"]) == 2

    error = capsys.readouterr().err
    assert "LLM_FALLBACK" in error
    assert "http" in error
    assert analyzed == []


def test_a_fallback_model_flag_without_the_fallback_exits_2(environment, analyzed, capsys):
    """``--llm-fallback-model`` alone is the same misconfiguration as the variable."""
    assert main(["analyze", "--llm-fallback-model", "backup-model"]) == 2

    assert "LLM_FALLBACK_MODEL requires LLM_FALLBACK" in capsys.readouterr().err
    assert analyzed == []


def test_the_flags_belong_to_the_analyze_command(environment):
    """Only ``analyze`` calls the model, so only it accepts the flags."""
    assert main(["collect", "--llm-max-tokens", "2048"]) == 2


def test_the_analyze_help_lists_every_llm_flag(environment, capsys):
    """``--help`` documents the flags without touching the environment."""
    assert main(["analyze", "--help"]) == 0

    help_text = capsys.readouterr().out
    for flag in FLAGS:
        assert flag in help_text
