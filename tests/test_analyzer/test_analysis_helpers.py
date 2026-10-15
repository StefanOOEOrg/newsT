"""
Unit tests for analysis helper classes.
Tests PromptBuilder, ResponseParser, and AlertGenerator with mocks.
"""
import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add analyzer directory to path
analyzer_path = Path(__file__).parent.parent.parent / 'analyzer'
sys.path.insert(0, str(analyzer_path))

from analysis_helpers import PromptBuilder, ResponseParser, AlertGenerator


class TestPromptBuilder:
    """Test the PromptBuilder class."""

    @pytest.fixture
    def mock_db_connection(self):
        """Create a mock database connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ('Test prompt template: {asset_name} ({ticker})\n\n{text_to_analyze}\n\nAnalyze in JSON format with sentiment, category, key_topics, summary.',)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        return mock_conn, mock_cursor

    @pytest.fixture
    def prompt_builder(self, mock_db_connection):
        """Create a PromptBuilder with mocked database."""
        mock_conn, _ = mock_db_connection
        builder = PromptBuilder("postgresql://test")
        # Mock get_db_connection to return our mock
        builder.get_db_connection = Mock(return_value=mock_conn)
        return builder

    def test_build_analysis_prompt_basic(self, prompt_builder):
        """Test building a basic analysis prompt."""
        post = {
            'title': 'Genpact hiring 100 new engineers',
            'content': 'Genpact announced plans to hire 100 engineers...',
            'asset_name': 'Genpact',
            'ticker': 'G'
        }

        prompt = prompt_builder.build_analysis_prompt(post)

        # Verify prompt contains expected elements
        assert 'Genpact' in prompt
        assert 'G' in prompt
        assert 'Genpact hiring 100 new engineers' in prompt
        assert 'JSON' in prompt

    def test_build_analysis_prompt_truncates_long_content(self, prompt_builder):
        """Test that long content is truncated."""
        long_content = 'A' * 5000  # Much longer than CONTENT_MAX_LENGTH
        post = {
            'title': 'Test post',
            'content': long_content,
            'asset_name': 'TestCo',
            'ticker': 'TEST'
        }

        prompt = prompt_builder.build_analysis_prompt(post)

        # Verify content was truncated (CONTENT_MAX_LENGTH = 2000)
        assert len(post['content']) == 5000
        # Prompt should not contain all 5000 chars
        assert long_content not in prompt

    def test_build_analysis_prompt_no_content(self, prompt_builder):
        """Test building prompt when post has no content."""
        post = {
            'title': 'Test post',
            'content': None,
            'asset_name': 'TestCo',
            'ticker': 'TEST'
        }

        prompt = prompt_builder.build_analysis_prompt(post)

        # Should still work without content
        assert 'Test post' in prompt
        assert 'TestCo' in prompt


class TestResponseParser:
    """Test the ResponseParser class."""

    def test_parse_valid_json_response(self):
        """Test parsing a valid JSON response."""
        response_text = json.dumps({
            'sentiment': 'positive',
            'sentiment_score': 0.8,
            'category': 'Hiring',
            'key_topics': ['hiring', 'expansion'],
            'summary': 'Company is hiring 100 engineers.'
        })

        post = {'id': 123, 'asset_id': 1}
        result = ResponseParser.parse_analysis_response(response_text, post)

        assert result is not None
        assert result['sentiment'] == 'positive'
        assert result['sentiment_score'] == 0.8
        assert result['category'] == 'Hiring'
        assert result['post_id'] == 123
        assert result['asset_id'] == 1

    def test_parse_json_with_markdown_code_block(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        response_text = """```json
{
    "sentiment": "negative",
    "sentiment_score": -0.6,
    "category": "Problems",
    "key_topics": ["layoffs", "restructuring"],
    "summary": "Company announces layoffs."
}
```"""

        post = {'id': 456, 'asset_id': 2}
        result = ResponseParser.parse_analysis_response(response_text, post)

        assert result is not None
        assert result['sentiment'] == 'negative'
        assert result['sentiment_score'] == -0.6
        assert result['category'] == 'Problems'

    def test_parse_missing_required_fields(self):
        """Test parsing response with missing required fields."""
        response_text = json.dumps({
            'sentiment': 'positive',
            'sentiment_score': 0.5
            # Missing: category, key_topics, summary
        })

        post = {'id': 789, 'asset_id': 3}
        result = ResponseParser.parse_analysis_response(response_text, post)

        # Should return None when required fields are missing
        assert result is None

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON."""
        response_text = "This is not valid JSON {{"

        post = {'id': 999, 'asset_id': 4}
        result = ResponseParser.parse_analysis_response(response_text, post)

        # Should return None for invalid JSON
        assert result is None


class TestAlertGenerator:
    """Test the AlertGenerator class."""

    @pytest.fixture
    def mock_db_connection(self):
        """Create a mock database connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        return mock_conn, mock_cursor

    @pytest.fixture
    def alert_generator(self, mock_db_connection):
        """Create an AlertGenerator with mocked database."""
        mock_conn, _ = mock_db_connection
        generator = AlertGenerator("postgresql://test")

        # Mock get_db_connection to return our mock
        generator.get_db_connection = Mock(return_value=mock_conn)

        return generator

    def test_generate_short_signal_high_severity(self, alert_generator, mock_db_connection):
        """Test generating high severity short signal."""
        _, mock_cursor = mock_db_connection

        analysis = {
            'asset_id': 1,
            'sentiment_score': -0.8,  # Very negative
            'category': 'Problems',
            'summary': 'Major security breach reported'
        }

        alert_generator.generate_alerts(analysis)

        # Verify short signal alert was created
        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args_list

        # Find the INSERT for short_signal
        short_signal_call = None
        for call in call_args:
            if 'short_signal' in str(call):
                short_signal_call = call
                break

        assert short_signal_call is not None
        # Verify it's a high severity alert
        assert 'high' in str(short_signal_call)

    def test_generate_long_signal_medium_severity(self, alert_generator, mock_db_connection):
        """Test generating medium severity long signal."""
        _, mock_cursor = mock_db_connection

        analysis = {
            'asset_id': 2,
            'sentiment_score': 0.6,  # Moderately positive
            'category': 'Hiring',
            'summary': 'Company hiring 50 engineers'
        }

        alert_generator.generate_alerts(analysis)

        # Verify long signal alert was created
        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args_list

        # Find the INSERT for long_signal
        long_signal_call = None
        for call in call_args:
            if 'long_signal' in str(call):
                long_signal_call = call
                break

        assert long_signal_call is not None
        # Verify it's a medium severity alert
        assert 'medium' in str(long_signal_call)

    def test_no_alerts_for_neutral_sentiment(self, alert_generator, mock_db_connection):
        """Test that no alerts are generated for neutral sentiment."""
        _, mock_cursor = mock_db_connection

        analysis = {
            'asset_id': 3,
            'sentiment_score': 0.0,  # Neutral
            'category': 'Other',
            'summary': 'Routine quarterly update'
        }

        alert_generator.generate_alerts(analysis)

        # Verify no INSERT statements were made
        assert not mock_cursor.execute.called

    def test_long_signal_requires_bullish_category(self, alert_generator, mock_db_connection):
        """Test that long signals require bullish category."""
        _, mock_cursor = mock_db_connection

        analysis = {
            'asset_id': 4,
            'sentiment_score': 0.8,  # Very positive
            'category': 'Other',  # But not a bullish category
            'summary': 'Some positive news'
        }

        alert_generator.generate_alerts(analysis)

        # Verify no long_signal alert was created (only bullish categories)
        call_args = str(mock_cursor.execute.call_args_list)
        assert 'long_signal' not in call_args

    def test_problem_category_has_lower_threshold(self, alert_generator, mock_db_connection):
        """Test that Problems category triggers at lower threshold."""
        _, mock_cursor = mock_db_connection

        analysis = {
            'asset_id': 5,
            'sentiment_score': -0.45,  # Moderate negative
            'category': 'Problems',
            'summary': 'Customer complaints increasing'
        }

        alert_generator.generate_alerts(analysis)

        # Verify short signal was created (Problems has lower threshold)
        call_args = str(mock_cursor.execute.call_args_list)
        assert 'short_signal' in call_args
        assert 'medium' in call_args  # Should be medium severity

    def test_database_error_handling(self, alert_generator):
        """Test that database errors are handled gracefully."""
        # Mock get_db_connection to raise an error
        alert_generator.get_db_connection = Mock(side_effect=Exception("DB connection failed"))

        analysis = {
            'asset_id': 6,
            'sentiment_score': -0.8,
            'category': 'Problems',
            'summary': 'Test'
        }

        # Should not raise exception
        try:
            alert_generator.generate_alerts(analysis)
        except Exception:
            pytest.fail("generate_alerts() raised an exception when it shouldn't")
