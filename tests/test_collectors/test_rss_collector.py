"""
Unit tests for RSSCollector.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add collector directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'collector'))

from collectors.rss_collector import RSSCollector


class TestableRSSCollector(RSSCollector):
    """Testable version of RSSCollector with dependency injection."""

    def __init__(self, database_url: str, db_adapter=None):
        self.db_adapter = db_adapter
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


class TestRSSCollector:
    """Test suite for RSSCollector."""

    def test_initialization(self):
        """Test that RSS collector initializes correctly."""
        collector = TestableRSSCollector("postgresql://test")
        assert collector.database_url == "postgresql://test"
        assert collector.name == "TestableRSSCollector"

    def test_generate_post_id_consistency(self):
        """Test that same URL generates same post ID."""
        collector = TestableRSSCollector("postgresql://test")

        url = "https://example.com/article"
        post_id_1 = collector.generate_post_id(url)
        post_id_2 = collector.generate_post_id(url)

        assert post_id_1 == post_id_2
        assert post_id_1.startswith("rss_")

    def test_generate_post_id_uniqueness(self):
        """Test that different URLs generate different post IDs."""
        collector = TestableRSSCollector("postgresql://test")

        post_id_1 = collector.generate_post_id("https://example.com/article1")
        post_id_2 = collector.generate_post_id("https://example.com/article2")

        assert post_id_1 != post_id_2

    @patch('collectors.rss_collector.feedparser')
    def test_fetch_rss_feed_with_ticker(self, mock_feedparser, mock_db):
        """Test fetching RSS feed with ticker-based URL."""
        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Setup mock feed
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda key, default=None: {
            'title': 'Genpact announces Q4 results',
            'link': 'https://example.com/article1',
            'summary': 'Genpact reported strong Q4 results...',
            'author': 'Business Wire',
            'published_parsed': (2025, 1, 15, 10, 0, 0)
        }.get(key, default)

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [mock_entry]
        mock_feed.feed.get.return_value = 'Yahoo Finance'

        mock_feedparser.parse.return_value = mock_feed

        # Test with ticker-based feed
        feed_config = {
            'name': 'Yahoo Finance',
            'url': 'https://finance.yahoo.com/rss/headline?s={ticker}',
            'use_ticker': True
        }

        posts = collector.fetch_rss_feed(
            feed_config,
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact', 'G']
        )

        assert len(posts) == 1
        assert posts[0]['asset_id'] == 1
        assert posts[0]['title'] == 'Genpact announces Q4 results'
        assert posts[0]['source'] == 'rss_yahoo_finance'
        assert posts[0]['url'] == 'https://example.com/article1'
        assert posts[0]['score'] == 0

        # Verify URL was formatted with ticker
        call_args = mock_feedparser.parse.call_args[0][0]
        assert '?s=G' in call_args or 'ticker=G' in call_args or '/G' in call_args

    @patch('collectors.rss_collector.feedparser')
    def test_fetch_rss_feed_with_keyword(self, mock_feedparser, mock_db):
        """Test fetching RSS feed with keyword-based URL."""
        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Setup mock feed
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda key, default=None: {
            'title': 'Genpact wins major contract',
            'link': 'https://example.com/article2',
            'summary': 'Genpact has secured a large contract...',
            'author': 'News Source',
            'published_parsed': (2025, 1, 14, 12, 0, 0)
        }.get(key, default)

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [mock_entry]
        mock_feed.feed = MagicMock()
        mock_feed.feed.get.return_value = 'Google News'

        mock_feedparser.parse.return_value = mock_feed

        # Test with keyword-based feed
        feed_config = {
            'name': 'Google News',
            'url': 'https://news.google.com/rss/search?q={keyword}',
            'use_keyword': True
        }

        posts = collector.fetch_rss_feed(
            feed_config,
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact']
        )

        assert len(posts) == 1
        assert posts[0]['title'] == 'Genpact wins major contract'

        # Verify URL was formatted with keyword
        call_args = mock_feedparser.parse.call_args[0][0]
        assert 'Genpact' in call_args

    @patch('collectors.rss_collector.feedparser')
    def test_fetch_rss_feed_skip_duplicates(self, mock_feedparser, mock_db):
        """Test that duplicate posts are skipped."""
        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Add existing post
        existing_post_id = collector.generate_post_id('https://example.com/article1')
        mock_db.posts.append({'post_id': existing_post_id})

        # Setup mock feed with duplicate
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda key, default=None: {
            'title': 'Duplicate article',
            'link': 'https://example.com/article1',  # Same URL as existing
            'summary': 'This is a duplicate...',
            'published_parsed': (2025, 1, 15, 10, 0, 0)
        }.get(key, default)

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [mock_entry]
        mock_feed.feed = MagicMock()
        mock_feed.feed.get.return_value = 'Test Feed'

        mock_feedparser.parse.return_value = mock_feed

        feed_config = {
            'name': 'Test Feed',
            'url': 'https://example.com/rss',
            'use_ticker': True
        }

        posts = collector.fetch_rss_feed(
            feed_config,
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact']
        )

        # Should return empty list because post already exists
        assert len(posts) == 0

    @patch('collectors.rss_collector.feedparser')
    def test_fetch_rss_feed_handles_missing_fields(self, mock_feedparser, mock_db):
        """Test handling of RSS entries with missing fields."""
        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Setup mock entry with minimal fields
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda key, default=None: {
            'title': 'Minimal article',
            'link': 'https://example.com/minimal'
        }.get(key, default)

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [mock_entry]
        mock_feed.feed = MagicMock()
        mock_feed.feed.get.return_value = 'Test Feed'

        mock_feedparser.parse.return_value = mock_feed

        feed_config = {
            'name': 'Test Feed',
            'url': 'https://example.com/rss',
            'use_ticker': True
        }

        posts = collector.fetch_rss_feed(
            feed_config,
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact']
        )

        assert len(posts) == 1
        assert posts[0]['title'] == 'Minimal article'
        assert posts[0]['content'] is None  # No summary provided
        assert posts[0]['author'] == 'Test Feed'  # Falls back to feed title
        assert posts[0]['created_at'] is not None  # Should use current time

    @patch('collectors.rss_collector.feedparser')
    def test_fetch_rss_feed_skips_entries_without_link(self, mock_feedparser, mock_db):
        """Test that entries without links are skipped."""
        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Setup mock entry without link
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda key, default=None: {
            'title': 'Article without link'
        }.get(key, default)

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [mock_entry]
        mock_feed.feed = MagicMock()

        mock_feedparser.parse.return_value = mock_feed

        feed_config = {
            'name': 'Test Feed',
            'url': 'https://example.com/rss',
            'use_ticker': True
        }

        posts = collector.fetch_rss_feed(
            feed_config,
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact']
        )

        # Should skip entry without link
        assert len(posts) == 0

    @patch('collectors.rss_collector.feedparser')
    def test_fetch_rss_feed_handles_feed_error(self, mock_feedparser, mock_db, caplog):
        """Test handling of feed parsing errors."""
        import logging
        caplog.set_level(logging.ERROR)

        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Mock feedparser to raise exception
        mock_feedparser.parse.side_effect = Exception("Network error")

        feed_config = {
            'name': 'Test Feed',
            'url': 'https://example.com/rss',
            'use_ticker': True
        }

        posts = collector.fetch_rss_feed(
            feed_config,
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact']
        )

        # Should return empty list on error
        assert len(posts) == 0
        assert "Error fetching RSS feed" in caplog.text

    @patch('collectors.rss_collector.feedparser')
    def test_collect_for_asset_multiple_feeds(self, mock_feedparser, mock_db):
        """Test collecting from multiple RSS feeds for a company."""
        collector = TestableRSSCollector("postgresql://test", db_adapter=mock_db)

        # Mock different entries for each feed
        call_count = 0

        def mock_parse(url):
            nonlocal call_count
            call_count += 1

            mock_entry = MagicMock()
            mock_entry.get.side_effect = lambda key, default=None: {
                'title': f'Article {call_count}',
                'link': f'https://example.com/article{call_count}',
                'summary': f'Summary {call_count}',
                'published_parsed': (2025, 1, 15, 10, 0, 0)
            }.get(key, default)

            mock_feed = MagicMock()
            mock_feed.bozo = False
            mock_feed.entries = [mock_entry]
            mock_feed.feed = MagicMock()
            mock_feed.feed.get.return_value = 'Feed'

            return mock_feed

        mock_feedparser.parse.side_effect = mock_parse

        # Collect for company (should fetch from all configured feeds)
        posts = collector.collect_for_asset(
            asset_id=1,
            asset_name='Genpact',
            ticker='G',
            keywords=['genpact']
        )

        # Should have posts from multiple feeds
        assert len(posts) >= 1
        assert call_count == len(collector.RSS_FEEDS)

    def test_collector_name(self):
        """Test getting the collector name."""
        assert RSSCollector.get_collector_name() == "RSS"
