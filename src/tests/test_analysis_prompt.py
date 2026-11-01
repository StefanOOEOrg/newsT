"""Tests for newstrading.analysis.prompt.

The template may come from the database, so it is not ours to control: a template that
shows a JSON example carries braces of its own. The first test that matters is therefore
the one with braces in the template — a ``str.format`` implementation passes every other
case here and still breaks on the real default prompt.
"""

import json

import pytest

from newstrading.analysis.prompt import (
    DEFAULT_PROMPT_TEMPLATE,
    PromptBuilder,
    database_prompt_loader,
)
from newstrading.collectors.models import Asset, Post
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")

POST = Post(
    asset_id=7,
    source="rss_google_news",
    post_id="p-1",
    author="Test Feed",
    title="Genpact announces hiring push",
    content="Genpact said it will hire 2,000 engineers.",
    url="https://example.com/a",
    score=0,
    created_at=None,
)
"""Post double; ``created_at`` is unused by the prompt."""

ASSET = Asset(id=7, name="Genpact", ticker="G", keywords=("genpact",))


class FakeCursor:
    """Cursor double: answers the settings query with one row."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, params=None):
        self._connection.statements.append((query, params))

    def fetchone(self):
        return self._connection.row

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double holding the row the query should return."""

    def __init__(self, row=None):
        self.row = row
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def test_the_three_placeholders_are_filled():
    builder = PromptBuilder(lambda: "A {asset_name} {ticker} B {text_to_analyze}")

    prompt = builder.build(POST, ASSET)

    assert prompt.startswith("A Genpact G B ")
    assert "Genpact announces hiring push" in prompt


def test_braces_outside_the_placeholders_survive():
    template = 'Answer as {"sentiment": "{asset_name}"} for {ticker}:\n{text_to_analyze}'

    prompt = PromptBuilder(lambda: template).build(POST, ASSET)

    assert prompt.startswith('Answer as {"sentiment": "Genpact"} for G:')


def test_a_placeholder_missing_from_the_template_is_not_an_error():
    prompt = PromptBuilder(lambda: "only {ticker}").build(POST, ASSET)

    assert prompt == "only G"


def test_content_is_cut_to_the_configured_length():
    builder = PromptBuilder(lambda: "{text_to_analyze}", content_max_length=20)

    payload = json.loads(builder.build(POST, ASSET))

    assert payload["content"] == POST.content[:20]


def test_a_post_without_content_carries_no_content_key():
    post = Post(**{**POST.__dict__, "content": None})

    payload = PromptBuilder(lambda: "{text_to_analyze}").payload(post, ASSET)

    assert "content" not in json.loads(payload)
    assert "None" not in payload


def test_the_payload_key_order_is_stable():
    payload = PromptBuilder(lambda: "{text_to_analyze}").payload(POST, ASSET)

    assert payload.startswith('{"title": ')


def test_the_template_is_loaded_once_for_many_prompts():
    calls = []
    builder = PromptBuilder(lambda: calls.append(1) or "x {text_to_analyze}")

    builder.build(POST, ASSET)
    builder.build(POST, ASSET)

    assert len(calls) == 1


def test_reload_forces_one_more_load():
    calls = []
    builder = PromptBuilder(lambda: calls.append(1) or "x {text_to_analyze}")

    builder.build(POST, ASSET)
    builder.reload()
    builder.build(POST, ASSET)

    assert len(calls) == 2


def test_a_failing_loader_is_not_swallowed():
    def loader():
        raise RuntimeError("settings table is gone")

    with pytest.raises(RuntimeError, match="settings table is gone"):
        PromptBuilder(loader).build(POST, ASSET)


def test_the_database_loader_returns_the_stored_template():
    connection = FakeConnection(row=("analyse {asset_name} now",))
    loader = database_prompt_loader(SETTINGS, connector=lambda *a, **kw: connection)

    assert loader() == "analyse {asset_name} now"
    assert connection.closes == 1


@pytest.mark.parametrize("row", [None, (None,), ("",), ("   ",)])
def test_the_database_loader_falls_back_to_the_default_template(row):
    connection = FakeConnection(row=row)
    loader = database_prompt_loader(SETTINGS, connector=lambda *a, **kw: connection)

    assert loader() == DEFAULT_PROMPT_TEMPLATE


def test_the_default_template_carries_all_three_placeholders():
    assert "{asset_name}" in DEFAULT_PROMPT_TEMPLATE
    assert "{ticker}" in DEFAULT_PROMPT_TEMPLATE
    assert "{text_to_analyze}" in DEFAULT_PROMPT_TEMPLATE
