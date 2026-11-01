"""Tests for the consolidated database schema."""

import re
from pathlib import Path

import pytest

SCHEMA = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"

REQUIRED_OBJECTS = [
    "alert_performance",
    "api_usage",
    "api_usage_stats",
    "asset_events",
    "check_rate_limit",
    "collector_statistics",
    "rate_limit_config",
    "stock_prices",
]


def schema_text() -> str:
    """Return the text of the consolidated schema file."""
    return SCHEMA.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", REQUIRED_OBJECTS)
def test_schema_defines_every_object_the_code_uses(name):
    """Each object the code queries must exist in the one schema file."""
    pattern = rf"CREATE (TABLE|OR REPLACE VIEW|OR REPLACE FUNCTION)( IF NOT EXISTS)? {name}\b"
    assert re.search(pattern, schema_text()), f"{name} is missing from sql/schema.sql"
