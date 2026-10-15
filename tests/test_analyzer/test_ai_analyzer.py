"""
Unit tests for AIAnalyzer class.
Tests the main analyzer with mocked dependencies.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
from pathlib import Path

# Add analyzer and shared directories to path
analyzer_path = Path(__file__).parent.parent.parent / 'analyzer'
shared_path = Path(__file__).parent.parent.parent / 'shared'
sys.path.insert(0, str(analyzer_path))
sys.path.insert(0, str(shared_path))

from main import AIAnalyzer


class TestAIAnalyzer:
    """Test the AIAnalyzer class."""

    @pytest.fixture
    def mock_anthropic_client(self):
        """Create a mock Anthropic client."""
        mock_client = Mock()
        mock_message = Mock()
        mock_message.content = [Mock(text='{"sentiment": "positive", "sentiment_score": 0.7, "category": "Hiring", "key_topics": ["hiring"], "summary": "Test"}')]
        mock_client.messages.create.return_value = mock_message
        return mock_client

    @pytest.fixture
    def mock_db_connection(self):
        """Create a mock database connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        return mock_conn, mock_cursor

    @pytest.fixture
    def analyzer(self, mock_anthropic_client):
        """Create an AIAnalyzer with mocked Anthropic client."""
        return AIAnalyzer(
            database_url="postgresql://test",
            anthropic_client=mock_anthropic_client
        )

    def test_initialization(self, analyzer, mock_anthropic_client):
        """Test analyzer initialization."""
        assert analyzer.database_url == "postgresql://test"
        assert analyzer.client == mock_anthropic_client
        assert analyzer.alert_generator is not None

    def test_analyze_post_success(self, analyzer, mock_anthropic_client):
        """Test successful post analysis."""
        post = {
            'id': 123,
            'asset_id': 1,
            'title': 'Test post',
            'content': 'Test content',
            'asset_name': 'TestCo',
            'ticker': 'TEST'
        }

        result = analyzer.analyze_post(post)

        # Verify API was called
        mock_anthropic_client.messages.create.assert_called_once()

        # Verify result
        assert result is not None
        assert result['sentiment'] == 'positive'
        assert result['post_id'] == 123
        assert result['asset_id'] == 1

    def test_analyze_post_api_error(self, analyzer, mock_anthropic_client):
        """Test handling of API errors."""
        mock_anthropic_client.messages.create.side_effect = Exception("API Error")

        post = {
            'id': 456,
            'asset_id': 2,
            'title': 'Test',
            'content': 'Test',
            'asset_name': 'TestCo',
            'ticker': 'TEST'
        }

        result = analyzer.analyze_post(post)

        # Should return None on error
        assert result is None

    def test_analyze_post_invalid_response(self, mock_anthropic_client):
        """Test handling of invalid API response."""
        # Mock invalid JSON response
        mock_message = Mock()
        mock_message.content = [Mock(text='Invalid JSON {{')]
        mock_anthropic_client.messages.create.return_value = mock_message

        analyzer = AIAnalyzer(
            database_url="postgresql://test",
            anthropic_client=mock_anthropic_client
        )

        post = {
            'id': 789,
            'asset_id': 3,
            'title': 'Test',
            'content': 'Test',
            'asset_name': 'TestCo',
            'ticker': 'TEST'
        }

        result = analyzer.analyze_post(post)

        # Should return None for invalid response
        assert result is None

    @patch('main.psycopg2.connect')
    def test_get_unanalyzed_posts(self, mock_connect, analyzer):
        """Test fetching unanalyzed posts."""
        # Mock database cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'id': 1,
                'asset_id': 1,
                'title': 'Post 1',
                'content': 'Content 1',
                'source': 'reddit',
                'url': 'https://reddit.com/1',
                'asset_name': 'TestCo',
                'ticker': 'TEST'
            }
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        posts = analyzer.get_unanalyzed_posts(limit=10)

        # Verify query was executed
        mock_cursor.execute.assert_called_once()
        assert len(posts) == 1
        assert posts[0]['id'] == 1

    @patch('main.psycopg2.connect')
    def test_save_analysis(self, mock_connect, analyzer):
        """Test saving analysis results."""
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        analysis = {
            'post_id': 123,
            'sentiment': 'positive',
            'sentiment_score': 0.7,
            'category': 'Hiring',
            'key_topics': ['hiring', 'growth'],
            'summary': 'Company is hiring'
        }

        analyzer.save_analysis(analysis)

        # Verify INSERT was called
        mock_cursor.execute.assert_called_once()
        call_args = str(mock_cursor.execute.call_args)
        assert 'INSERT INTO ai_analysis' in call_args
        assert mock_conn.commit.called

    def test_generate_alerts_delegates_to_alert_generator(self, analyzer):
        """Test that generate_alerts delegates to AlertGenerator."""
        # Mock the alert_generator
        analyzer.alert_generator = Mock()

        analysis = {
            'asset_id': 1,
            'sentiment_score': 0.8,
            'category': 'Hiring',
            'summary': 'Test'
        }

        analyzer.generate_alerts(analysis)

        # Verify delegation
        analyzer.alert_generator.generate_alerts.assert_called_once_with(analysis)

    def test_dependency_injection_allows_custom_client(self, mock_anthropic_client):
        """Test that custom Anthropic client can be injected."""
        custom_client = Mock()
        analyzer = AIAnalyzer(
            database_url="postgresql://test",
            anthropic_client=custom_client
        )

        assert analyzer.client == custom_client
        assert analyzer.client != mock_anthropic_client

    def test_dependency_injection_creates_default_client(self):
        """Test that default client is created when none provided."""
        with patch('main.Anthropic') as mock_anthropic_class:
            mock_client = Mock()
            mock_anthropic_class.return_value = mock_client

            analyzer = AIAnalyzer(database_url="postgresql://test")

            # Verify Anthropic was instantiated
            mock_anthropic_class.assert_called_once()
            assert analyzer.client == mock_client
