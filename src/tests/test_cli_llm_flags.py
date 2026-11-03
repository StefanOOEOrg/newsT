"""Tests for the LLM settings ``analyze`` accepts on its own command line.

The three flags are the command-line counterpart of ``LLM_PROVIDER``,
``LLM_MAX_TOKENS`` and ``LLM_MAX_CONCURRENCY``: a flag wins over the environment,
the environment keeps its defaults, and an invalid value is still exit code 2 with
a message that names the variable.
"""

import pytest

from newstrading.cli import main

URL = "postgresql://app:***@db.internal:5432/newstrading"

CONFIGURED = (
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT",
    "LLM_MAX_TOKENS",
    "LLM_MAX_CONCURRENCY",
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


def test_the_flags_override_the_environment(environment, analyzed):
    """Each flag replaces its variable; the other settings keep the environment value."""
    environment.setenv("LLM_MAX_TOKENS", "512")
    environment.setenv("LLM_MAX_CONCURRENCY", "2")

    code = main(
        [
            "analyze",
            "--llm-provider",
            "local",
            "--llm-max-tokens",
            "2048",
            "--llm-max-concurrency",
            "3",
        ]
    )

    assert code == 0
    assert (analyzed[0].llm_max_tokens, analyzed[0].llm_max_concurrency) == (2048, 3)
    assert analyzed[0].llm_provider == "local"


def test_without_flags_the_environment_decides(environment, analyzed):
    """No flag: the pass reads the variables, as before the flags existed."""
    environment.setenv("LLM_MAX_TOKENS", "512")
    environment.setenv("LLM_MAX_CONCURRENCY", "4")

    assert main(["analyze"]) == 0

    assert (analyzed[0].llm_max_tokens, analyzed[0].llm_max_concurrency) == (512, 4)


def test_a_flag_wins_over_an_invalid_environment_value(environment, analyzed):
    """The flag replaces the value before it is validated, so a bad variable cannot block it."""
    environment.setenv("LLM_MAX_CONCURRENCY", "0")

    assert main(["analyze", "--llm-max-concurrency", "16"]) == 0

    assert analyzed[0].llm_max_concurrency == 16


def test_the_provider_flag_switches_to_anthropic(environment, analyzed):
    """``--llm-provider anthropic`` reaches the settings once the key is there."""
    environment.setenv("ANTHROPIC_API_KEY", "sk-test")

    assert main(["analyze", "--llm-provider", "anthropic"]) == 0

    assert analyzed[0].llm_provider == "anthropic"


def test_the_provider_flag_reaches_the_conditional_key_check(environment, analyzed, capsys):
    """The provider given as a flag, not only as a variable, makes the key required."""
    assert main(["analyze", "--llm-provider", "anthropic"]) == 2

    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert analyzed == []


def test_an_unknown_provider_flag_exits_2_naming_the_allowed_values(environment, analyzed, capsys):
    """An unknown provider is a configuration error, not an argparse usage error."""
    assert main(["analyze", "--llm-provider", "openai"]) == 2

    error = capsys.readouterr().err
    assert "LLM_PROVIDER" in error
    assert "local, anthropic" in error
    assert analyzed == []


def test_a_concurrency_flag_outside_the_range_exits_2_and_names_the_range(
    environment, analyzed, capsys
):
    """``--llm-max-concurrency 0`` is rejected with the same message as the variable."""
    assert main(["analyze", "--llm-max-concurrency", "0"]) == 2

    assert "LLM_MAX_CONCURRENCY must be between 1 and 16, got 0" in capsys.readouterr().err
    assert analyzed == []


def test_a_non_integer_token_flag_exits_2_and_names_the_setting(environment, analyzed, capsys):
    """``--llm-max-tokens abc`` is rejected with the same message as the variable."""
    assert main(["analyze", "--llm-max-tokens", "abc"]) == 2

    assert "LLM_MAX_TOKENS must be an integer, got 'abc'" in capsys.readouterr().err
    assert analyzed == []


def test_the_flags_belong_to_the_analyze_command(environment):
    """Only ``analyze`` calls the model, so only it accepts the flags."""
    assert main(["collect", "--llm-max-tokens", "2048"]) == 2


def test_the_analyze_help_lists_the_three_flags(environment, capsys):
    """``--help`` documents the flags without touching the environment."""
    assert main(["analyze", "--help"]) == 0

    help_text = capsys.readouterr().out
    for flag in ("--llm-provider", "--llm-max-tokens", "--llm-max-concurrency"):
        assert flag in help_text
