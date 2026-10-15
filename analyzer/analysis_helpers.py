"""
Helper classes for AI analysis - separated concerns for better testability.
"""
import json
import logging
from typing import Dict, Optional, List
import psycopg2
from toon import decode as toon_decode, encode as toon_encode

from config import (
    CONTENT_MAX_LENGTH, ALERT_SUMMARY_MAX_LENGTH,
    REQUIRED_ANALYSIS_FIELDS,
    BULLISH_CATEGORIES,
    SHORT_SIGNAL_THRESHOLD, SHORT_SIGNAL_LOW_THRESHOLD,
    SHORT_SIGNAL_MEDIUM_THRESHOLD, SHORT_SIGNAL_HIGH_THRESHOLD,
    SHORT_SIGNAL_PROBLEM_MEDIUM, SHORT_SIGNAL_PROBLEM_HIGH,
    LONG_SIGNAL_THRESHOLD, LONG_SIGNAL_LOW_THRESHOLD,
    LONG_SIGNAL_MEDIUM_THRESHOLD, LONG_SIGNAL_HIGH_THRESHOLD,
    EVENT_ALERT_CONFIG
)

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Builds prompts for Claude AI analysis."""

    def __init__(self, database_url: str):
        """
        Initialize prompt builder.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self._prompt_template = None

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def get_prompt_template(self) -> str:
        """
        Fetch the analysis prompt template from database.

        Returns:
            Prompt template string with {asset_name}, {ticker}, {text_to_analyze} placeholders
        """
        if self._prompt_template is not None:
            return self._prompt_template

        conn = None
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT analysis_prompt FROM notification_settings WHERE id = 1")
                row = cur.fetchone()
                if row and row[0]:
                    self._prompt_template = row[0]
                else:
                    # Fallback to default prompt if not found
                    self._prompt_template = """Analyze this social media post about {asset_name} ({ticker}) from a trading perspective.

Post data (in TOON format):
{text_to_analyze}

Provide your analysis in TOON format (Token-Oriented Object Notation) with these fields:
- sentiment: one of "positive", "negative", or "neutral"
- sentiment_score: a number between -1.0 (very bearish/short signal) and 1.0 (very bullish/long signal)
- category: one of "Hiring", "Growth", "Problems", "Product", "Earnings", "Other"
- key_topics: array of 2-5 key topics or themes (as strings)
- summary: brief summary in 1-2 sentences (max 100 words)
- special_events: array of special event types (optional, use [] if none)

Focus on identifying trading signals:
- BULLISH (long signals): hiring, partnerships, product launches, earnings beats, growth indicators, positive guidance
- BEARISH (short signals): problems, layoffs, negative sentiment, downgrades, missed earnings, legal issues

Return ONLY valid TOON format, no other text. Use YAML-style indentation and CSV-style arrays.

Example TOON format:
sentiment: positive
sentiment_score: 0.7
category: Hiring
key_topics[3]: hiring surge, AI expansion, growth signals
summary: Company announces significant hiring push in AI division.
special_events[1]: partnership_announced"""
            return self._prompt_template
        except Exception as e:
            logger.error(f"Error fetching prompt template: {e}")
            # Return default prompt on error
            return """Analyze this social media post about {asset_name} ({ticker}) from a trading perspective.

Post data (in TOON format):
{text_to_analyze}

Provide your analysis in TOON format (Token-Oriented Object Notation) with these fields:
- sentiment: one of "positive", "negative", or "neutral"
- sentiment_score: a number between -1.0 (very bearish/short signal) and 1.0 (very bullish/long signal)
- category: one of "Hiring", "Growth", "Problems", "Product", "Earnings", "Other"
- key_topics: array of 2-5 key topics or themes (as strings)
- summary: brief summary in 1-2 sentences (max 100 words)
- special_events: array of special event types (optional, use [] if none)

Focus on identifying trading signals:
- BULLISH (long signals): hiring, partnerships, product launches, earnings beats, growth indicators, positive guidance
- BEARISH (short signals): problems, layoffs, negative sentiment, downgrades, missed earnings, legal issues

Return ONLY valid TOON format, no other text. Use YAML-style indentation and CSV-style arrays.

Example TOON format:
sentiment: positive
sentiment_score: 0.7
category: Hiring
key_topics[3]: hiring surge, AI expansion, growth signals
summary: Company announces significant hiring push in AI division.
special_events[1]: partnership_announced"""
        finally:
            if conn:
                conn.close()

    def build_analysis_prompt(self, post: Dict) -> str:
        """
        Build analysis prompt for a social media post.

        Args:
            post: Post dictionary with title, content, asset_name, ticker

        Returns:
            Formatted prompt string
        """
        # Prepare post data in TOON format for better token efficiency and accuracy
        post_data = {
            'title': post['title'],
            'ticker': post['ticker'],
            'asset_name': post['asset_name']
        }

        # Add content if present (truncate to limit)
        if post.get('content'):
            post_data['content'] = post['content'][:CONTENT_MAX_LENGTH]

        # Convert post data to TOON format
        text_to_analyze = toon_encode(post_data)

        # Get template from database and format it
        template = self.get_prompt_template()
        prompt = template.format(
            asset_name=post['asset_name'],
            ticker=post['ticker'],
            text_to_analyze=text_to_analyze
        )

        return prompt


class ResponseParser:
    """Parses and validates Claude API responses."""

    @staticmethod
    def parse_analysis_response(response_text: str, post: Dict) -> Optional[Dict]:
        """
        Parse and validate Claude AI analysis response.

        Args:
            response_text: Raw response text from Claude API
            post: Original post dictionary (for adding context)

        Returns:
            Validated analysis dictionary or None if invalid
        """
        try:
            # Remove markdown code blocks if present
            cleaned_text = response_text.strip()

            # Log first 200 chars of raw response for format debugging
            logger.debug(f"Raw Claude response preview: {cleaned_text[:200]}")

            if cleaned_text.startswith('```'):
                parts = cleaned_text.split('```')
                if len(parts) >= 2:
                    cleaned_text = parts[1]
                    # Skip format identifier (toon, json, etc.)
                    if cleaned_text.startswith('toon') or cleaned_text.startswith('json'):
                        cleaned_text = cleaned_text[4:]
                    cleaned_text = cleaned_text.strip()
                else:
                    # Malformed code block, try to strip just the backticks
                    cleaned_text = cleaned_text.lstrip('`').strip()

            # Parse TOON format (or fall back to JSON/YAML if needed)
            try:
                analysis = toon_decode(cleaned_text)
                logger.debug(f"Successfully parsed response using TOON format")
            except Exception as toon_error:
                # Check if response contains YAML-style arrays (- item format)
                if '\n  -' in cleaned_text or '\n-' in cleaned_text:
                    # Claude returned YAML format - parse manually
                    logger.warning(
                        f"Claude returned YAML-style arrays instead of TOON format. "
                        f"Converting to TOON-compatible format."
                    )
                    analysis = ResponseParser._parse_yaml_style_response(cleaned_text)
                else:
                    # Fallback to JSON if TOON parsing fails
                    logger.warning(
                        f"Claude returned JSON instead of TOON format. "
                        f"TOON parsing error: {toon_error}. Falling back to JSON parser."
                    )
                    analysis = json.loads(cleaned_text)

            # Validate required fields (special_events is optional with default [])
            required_base_fields = [f for f in REQUIRED_ANALYSIS_FIELDS if f != 'special_events']
            if not all(field in analysis for field in required_base_fields):
                logger.error(f"Missing required fields in analysis: {analysis}")
                return None

            # Ensure key_topics is a proper list (TOON may return JSON string)
            if 'key_topics' in analysis and isinstance(analysis['key_topics'], str):
                try:
                    analysis['key_topics'] = json.loads(analysis['key_topics'])
                except json.JSONDecodeError:
                    # If it's a comma-separated string, split it
                    analysis['key_topics'] = [t.strip() for t in analysis['key_topics'].split(',')]

            # Ensure special_events field exists with default empty array
            if 'special_events' not in analysis:
                analysis['special_events'] = []
            elif isinstance(analysis['special_events'], str):
                try:
                    analysis['special_events'] = json.loads(analysis['special_events'])
                except json.JSONDecodeError:
                    logger.warning(f"special_events is a string, defaulting to empty array")
                    analysis['special_events'] = []
            elif not isinstance(analysis['special_events'], list):
                logger.warning(f"special_events is not a list, defaulting to empty array")
                analysis['special_events'] = []

            # Add post context
            analysis['post_id'] = post['id']
            analysis['asset_id'] = post['asset_id']

            return analysis

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse response (TOON or JSON): {e}")
            logger.error(f"Response text: {response_text[:200]}")
            return None
        except Exception as e:
            import traceback
            logger.error(f"Error parsing analysis response: {type(e).__name__}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            return None

    @staticmethod
    def _parse_yaml_style_response(text: str) -> Dict:
        """
        Parse YAML-style response where arrays use bullet points.

        Example:
            sentiment: positive
            key_topics:
              - topic1
              - topic2

        Args:
            text: Response text with YAML-style arrays

        Returns:
            Dictionary with parsed fields
        """
        result = {}
        lines = text.split('\n')
        current_key = None
        current_array = []

        for line in lines:
            line = line.rstrip()

            # Check for key-value pair (no leading spaces or only for array items)
            if ':' in line and not line.strip().startswith('-'):
                # Save previous array if exists
                if current_key and current_array:
                    result[current_key] = current_array
                    current_array = []

                # Parse new key-value
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                if value:  # Simple value
                    # Try to convert to appropriate type
                    if value.lower() in ['true', 'false']:
                        result[key] = value.lower() == 'true'
                    else:
                        try:
                            result[key] = float(value)
                        except ValueError:
                            result[key] = value
                    current_key = None
                else:  # Array follows
                    current_key = key

            elif line.strip().startswith('-') and current_key:
                # Array item
                item = line.strip()[1:].strip()  # Remove '- ' prefix
                if item:
                    current_array.append(item)

        # Save last array if exists
        if current_key and current_array:
            result[current_key] = current_array
        elif current_key:
            result[current_key] = []

        return result


class AlertGenerator:
    """Generates alerts based on analysis results."""

    def __init__(self, database_url: str):
        """
        Initialize alert generator.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def generate_alerts(self, analysis: Dict) -> None:
        """
        Generate alerts based on analysis results.

        Args:
            analysis: Analysis dictionary with sentiment_score, category, special_events, etc.
        """
        conn = None
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cur:
                sentiment = analysis['sentiment_score']
                category = analysis['category']

                # Generate short signal (bearish) alerts
                self._generate_short_signal(cur, analysis, sentiment, category)

                # Generate long signal (bullish) alerts
                self._generate_long_signal(cur, analysis, sentiment, category)

                # Generate special event alerts
                special_events = analysis.get('special_events', [])
                if special_events:
                    self._generate_special_event_alerts(cur, analysis, special_events, sentiment)

                conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error generating alerts: {e}")
        finally:
            if conn:
                conn.close()

    def _generate_short_signal(self, cur, analysis: Dict, sentiment: float, category: str) -> None:
        """Generate short signal (bearish) alerts."""
        if sentiment < SHORT_SIGNAL_THRESHOLD:
            # Determine severity level
            if sentiment < SHORT_SIGNAL_HIGH_THRESHOLD or (category == 'Problems' and sentiment < SHORT_SIGNAL_PROBLEM_HIGH):
                severity = 'high'
                description_prefix = "Strong short signal"
            elif sentiment < SHORT_SIGNAL_MEDIUM_THRESHOLD or (category == 'Problems' and sentiment < SHORT_SIGNAL_PROBLEM_MEDIUM):
                severity = 'medium'
                description_prefix = "Moderate short signal"
            else:
                severity = 'low'
                description_prefix = "Weak short signal"

            # Context-aware description
            if category == 'Problems':
                description = f"{description_prefix}: Problem reported - {analysis['summary'][:ALERT_SUMMARY_MAX_LENGTH]}"
            else:
                description = f"{description_prefix}: Negative sentiment detected - {analysis['summary'][:ALERT_SUMMARY_MAX_LENGTH]}"

            cur.execute("""
                INSERT INTO alerts
                (asset_id, alert_type, severity, description, confidence_score)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                analysis['asset_id'],
                'short_signal',
                severity,
                description,
                abs(sentiment)
            ))

    def _generate_long_signal(self, cur, analysis: Dict, sentiment: float, category: str) -> None:
        """Generate long signal (bullish) alerts."""
        if sentiment > LONG_SIGNAL_THRESHOLD and category in BULLISH_CATEGORIES:
            # Determine severity level based on strength
            if sentiment > LONG_SIGNAL_HIGH_THRESHOLD:
                severity = 'high'
                description_prefix = "Strong long signal"
            elif sentiment > LONG_SIGNAL_MEDIUM_THRESHOLD:
                severity = 'medium'
                description_prefix = "Moderate long signal"
            else:
                severity = 'low'
                description_prefix = "Weak long signal"

            cur.execute("""
                INSERT INTO alerts
                (asset_id, alert_type, severity, description, confidence_score)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                analysis['asset_id'],
                'long_signal',
                severity,
                f"{description_prefix}: {category} activity detected - {analysis['summary'][:ALERT_SUMMARY_MAX_LENGTH]}",
                sentiment
            ))

    def _generate_special_event_alerts(self, cur, analysis: Dict, special_events: List[str], sentiment: float) -> None:
        """
        Generate alerts for special events detected in the analysis.

        Args:
            cur: Database cursor
            analysis: Full analysis dictionary
            special_events: List of detected special event types
            sentiment: Sentiment score from analysis
        """
        for event in special_events:
            if event not in EVENT_ALERT_CONFIG:
                logger.warning(f"Unknown special event type: {event}")
                continue

            alert_type, default_severity, is_bullish = EVENT_ALERT_CONFIG[event]

            # Adjust severity based on sentiment strength
            severity = self._adjust_event_severity(default_severity, sentiment, is_bullish)

            # Create human-readable description
            description = self._format_event_description(event, analysis['summary'])

            # Calculate confidence score (use absolute sentiment for confidence)
            confidence = abs(sentiment) if is_bullish is not None else 0.5

            cur.execute("""
                INSERT INTO alerts
                (asset_id, alert_type, severity, description, confidence_score)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                analysis['asset_id'],
                alert_type,
                severity,
                description[:ALERT_SUMMARY_MAX_LENGTH + 50],  # Allow slightly longer for event descriptions
                confidence
            ))

            logger.info(f"Generated {alert_type} alert (severity: {severity}) for asset {analysis['asset_id']}")

    def _adjust_event_severity(self, default_severity: str, sentiment: float, is_bullish: Optional[bool]) -> str:
        """
        Adjust event severity based on sentiment score.

        Args:
            default_severity: Default severity from config
            sentiment: Sentiment score
            is_bullish: Whether event is bullish (True), bearish (False), or neutral (None)

        Returns:
            Adjusted severity level
        """
        # If neutral event or weak sentiment, use default
        if is_bullish is None or abs(sentiment) < 0.3:
            return default_severity

        # For bullish events with strong positive sentiment, increase severity
        if is_bullish and sentiment > 0.7:
            if default_severity == 'low':
                return 'medium'
            elif default_severity == 'medium':
                return 'high'

        # For bearish events with strong negative sentiment, increase severity
        if not is_bullish and sentiment < -0.7:
            if default_severity == 'low':
                return 'medium'
            elif default_severity == 'medium':
                return 'high'

        return default_severity

    def _format_event_description(self, event: str, summary: str) -> str:
        """
        Format a human-readable description for an event alert.

        Args:
            event: Event type (e.g., 'partnership_announced')
            summary: AI-generated summary

        Returns:
            Formatted description string
        """
        # Event type display names
        event_names = {
            'partnership_announced': 'Partnership Announced',
            'product_launch': 'Product Launch',
            'regulatory_risk': 'Regulatory Risk',
            'analyst_upgrade': 'Analyst Upgrade',
            'analyst_downgrade': 'Analyst Downgrade',
            'market_share_gain': 'Market Share Gain',
            'customer_loss': 'Customer Loss',
            'executive_change': 'Executive Change',
            'guidance_raise': 'Guidance Raised',
            'guidance_cut': 'Guidance Cut',
            'insider_buying': 'Insider Buying',
            'insider_selling': 'Insider Selling',
        }

        display_name = event_names.get(event, event.replace('_', ' ').title())
        return f"{display_name}: {summary}"
