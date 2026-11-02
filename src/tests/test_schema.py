"""Tests for the consolidated database schema."""

import re
from pathlib import Path

import pytest

from newstrading.collectors import (
    AlphaVantageCollector,
    CongressionalTradesCollector,
    FinnhubCollector,
    NewsAPICollector,
    RSSCollector,
)

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

COLLECTORS = (
    AlphaVantageCollector,
    CongressionalTradesCollector,
    FinnhubCollector,
    NewsAPICollector,
    RSSCollector,
)

# The class names the schema seeded before the quota rows were keyed by source name.
RENAMES = (
    ("NewsAPICollector", NewsAPICollector.name),
    ("FinnhubCollector", FinnhubCollector.name),
    ("AlphaVantageCollector", AlphaVantageCollector.name),
    ("RSSCollector", RSSCollector.name),
    ("CongressionalTradesCollector", CongressionalTradesCollector.name),
)


def schema_text() -> str:
    """Return the text of the consolidated schema file."""
    return SCHEMA.read_text(encoding="utf-8")


def seeded_rate_limit_names() -> list[str]:
    """Return the collector names of the five seeded ``rate_limit_config`` rows."""
    block = schema_text().split("INSERT INTO rate_limit_config", 1)[1].split(";", 1)[0]
    return re.findall(r"^\s*\('([a-z_]+)'", block, flags=re.MULTILINE)


@pytest.mark.parametrize("name", REQUIRED_OBJECTS)
def test_schema_defines_every_object_the_code_uses(name):
    """Each object the code queries must exist in the one schema file."""
    pattern = rf"CREATE (TABLE|OR REPLACE VIEW|OR REPLACE FUNCTION)( IF NOT EXISTS)? {name}\b"
    assert re.search(pattern, schema_text()), f"{name} is missing from sql/schema.sql"


def test_asset_events_has_the_unique_key_the_event_store_relies_on():
    """``ON CONFLICT DO NOTHING`` is only idempotent with this key on the table."""
    body = schema_text().split("CREATE TABLE IF NOT EXISTS asset_events", 1)[1].split(");", 1)[0]
    compact = " ".join(body.split())

    assert "UNIQUE(asset_id, event_type, event_date, description)" in compact


def test_the_seeded_rate_limit_names_are_exactly_the_collector_names():
    """``check_rate_limit`` allows an unknown name, so a drifted seed disables the quota."""
    names = seeded_rate_limit_names()

    assert sorted(names) == sorted(collector.name for collector in COLLECTORS)
    assert not [name for name in names if name.endswith("Collector")]


@pytest.mark.parametrize("collector", COLLECTORS, ids=lambda collector: collector.__name__)
def test_every_collector_has_a_seeded_quota_row(collector):
    """The seed uses the source key the collector reports, not its class name."""
    assert collector.name in seeded_rate_limit_names()


@pytest.mark.parametrize(("legacy", "current"), RENAMES)
def test_the_legacy_seed_name_is_repaired_idempotently(legacy, current):
    """An old database is migrated in place; the guard makes a second run a no-op."""
    statement = (
        f"UPDATE rate_limit_config SET collector_name = '{current}'\n"
        f"WHERE collector_name = '{legacy}'\n"
        f"  AND NOT EXISTS (SELECT 1 FROM rate_limit_config WHERE collector_name = '{current}');"
    )

    assert statement in schema_text()


def test_the_repairs_run_before_the_seed_statements():
    """A legacy row is renamed first, so the seed then hits ``ON CONFLICT DO NOTHING``."""
    text = schema_text()
    first_seed = text.index("INSERT INTO rate_limit_config")

    for legacy, _current in RENAMES:
        assert text.index(f"WHERE collector_name = '{legacy}'") < first_seed
