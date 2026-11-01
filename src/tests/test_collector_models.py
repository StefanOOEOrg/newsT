"""Tests for the collector data model."""

import dataclasses
from datetime import UTC, datetime

import pytest

from newstrading.collectors.models import Asset, Post


def test_asset_is_immutable():
    """The model is a value object; nothing may rewrite it in place."""
    asset = Asset(id=1, name="Tesla", ticker="TSLA", keywords=("tesla", "tsla"))

    assert asset.keywords == ("tesla", "tsla")
    with pytest.raises(dataclasses.FrozenInstanceError):
        asset.ticker = "OTHER"


def test_post_carries_every_field_and_allows_a_missing_body():
    """A headline-only source leaves ``content`` at ``None``."""
    created = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    post = Post(
        asset_id=1,
        source="rss_google_news",
        post_id="abc",
        author="Test Feed",
        title="Tesla announces something",
        content=None,
        url="https://example.com/a",
        score=0,
        created_at=created,
    )

    assert post.asset_id == 1
    assert post.content is None
    assert post.created_at is created
    with pytest.raises(dataclasses.FrozenInstanceError):
        post.title = "changed"
