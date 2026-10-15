"""
Unit tests for BaseCollector.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add collector directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'collector'))

from collectors.base import BaseCollector


class TestableCollector(BaseCollector):
    """Concrete implementation of BaseCollector for testing."""

    def __init__(self, database_url: str, db_adapter=None):
        self.db_adapter = db_adapter
        self.collected_posts = []
        # Call super().__init__ last so we can override methods before they're called
        super().__init__(database_url)

    def _load_statistics_from_db(self):
        """Override to prevent database access during testing."""
        if not hasattr(self, 'db_adapter') or self.db_adapter is None:
            # Initialize with empty stats
            pass
        else:
            super()._load_statistics_from_db()

    def _save_statistics_to_db(self):
        """Override to prevent database access during testing."""
        if self.db_adapter is not None:
            super()._save_statistics_to_db()

    def get_db_connection(self):
        """Override to use mock adapter if provided."""
        if self.db_adapter:
            return self.db_adapter.get_connection()
        return super().get_db_connection()

    def get_assets(self):
        """Override to use mock adapter if provided."""
        if self.db_adapter:
            return self.db_adapter.get_assets()
        return super().get_assets()

    def post_exists(self, post_id: str) -> bool:
        """Override to use mock adapter if provided."""
        if self.db_adapter:
            return self.db_adapter.post_exists(post_id)
        return super().post_exists(post_id)

    def save_posts(self, posts):
        """Override to use mock adapter if provided."""
        if self.db_adapter:
            return self.db_adapter.save_posts(posts)
        return super().save_posts(posts)

    def collect_for_asset(self, asset_id, asset_name, ticker, keywords):
        """Test implementation that returns mock posts."""
        return self.collected_posts


class TestBaseCollector:
    """Test suite for BaseCollector."""

    def test_initialization(self):
        """Test that collector initializes correctly."""
        collector = TestableCollector("postgresql://test")
        assert collector.database_url == "postgresql://test"
        assert collector.name == "TestableCollector"

    def test_get_assets_with_mock(self, mock_db, sample_assets):
        """Test getting assets from database using mock."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)
        assets = collector.get_assets()

        assert len(assets) == 3
        assert assets[0] == (1, 'Genpact', 'G', ['genpact', 'G'])
        assert assets[1] == (2, 'Palantir', 'PLTR', ['palantir', 'pltr'])
        assert assets[2] == (3, 'Snowflake', 'SNOW', ['snowflake', 'snow'])

    def test_post_exists_new_post(self, mock_db):
        """Test checking if a post exists when it doesn't."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        exists = collector.post_exists("non_existent_post")
        assert exists is False

    def test_post_exists_existing_post(self, mock_db, sample_posts):
        """Test checking if a post exists when it does."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        # Add a post first
        mock_db.save_posts([sample_posts[0]])

        # Check if it exists
        exists = collector.post_exists("test_post_1")
        assert exists is True

    def test_save_posts_success(self, mock_db, sample_posts):
        """Test saving posts successfully."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        saved_count = collector.save_posts(sample_posts)

        assert saved_count == 2
        assert len(mock_db.posts) == 2
        assert mock_db.posts[0]['post_id'] == 'test_post_1'
        assert mock_db.posts[1]['post_id'] == 'test_post_2'

    def test_save_posts_duplicate_prevention(self, mock_db, sample_posts):
        """Test that duplicate posts are not saved."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        # Save posts first time
        saved_count_1 = collector.save_posts(sample_posts)
        assert saved_count_1 == 2

        # Try to save same posts again
        saved_count_2 = collector.save_posts(sample_posts)
        assert saved_count_2 == 0

        # Should still have only 2 posts
        assert len(mock_db.posts) == 2

    def test_save_posts_empty_list(self, mock_db):
        """Test saving an empty list of posts."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        saved_count = collector.save_posts([])
        assert saved_count == 0

    def test_collect_all_success(self, mock_db, sample_posts):
        """Test collect_all method with successful collection."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        # Need to generate unique posts for each asset to avoid duplicates
        call_count = [0]
        original_method = collector.collect_for_asset

        def side_effect(asset_id, asset_name, ticker, keywords):
            call_count[0] += 1
            # Return a unique post for each asset
            post = sample_posts[0].copy()
            post['post_id'] = f"test_post_{call_count[0]}"
            post['asset_id'] = asset_id
            return [post]

        collector.collect_for_asset = side_effect

        result = collector.collect_all()

        assert result['total_posts'] == 3  # Called for 3 assets
        assert result['total_saved'] == 3
        assert len(mock_db.posts) == 3

    def test_collect_all_no_posts(self, mock_db):
        """Test collect_all when no posts are found."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        # No posts to collect
        collector.collected_posts = []

        result = collector.collect_all()

        assert result['total_posts'] == 0
        assert result['total_saved'] == 0
        assert len(mock_db.posts) == 0

    def test_collect_all_partial_failure(self, mock_db, sample_posts):
        """Test collect_all when some assets fail."""
        collector = TestableCollector("postgresql://test", db_adapter=mock_db)

        # First asset succeeds, others fail
        call_count = 0
        original_method = collector.collect_for_asset

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [sample_posts[0]]
            raise Exception("Test error")

        collector.collect_for_asset = side_effect

        result = collector.collect_all()

        # Should continue despite errors
        assert result['total_posts'] == 1
        assert result['total_saved'] == 1
        assert len(mock_db.posts) == 1

    def test_get_collector_name(self):
        """Test getting the collector's human-readable name."""
        name = TestableCollector.get_collector_name()
        assert name == "Testable"

    def test_collector_logging(self, mock_db, sample_posts, caplog):
        """Test that collector logs appropriately."""
        import logging
        caplog.set_level(logging.INFO)

        collector = TestableCollector("postgresql://test", db_adapter=mock_db)
        collector.collected_posts = [sample_posts[0]]

        result = collector.collect_all()

        # Check that log messages were generated
        assert "Starting collection" in caplog.text
        assert "Collection complete" in caplog.text
