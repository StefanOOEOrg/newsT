"""
Keyword Suggester Module
Automatically suggests new keywords for assets based on collected posts using Claude AI.
"""
import os
import logging
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from anthropic import Anthropic

logger = logging.getLogger(__name__)


class KeywordSuggester:
    """Suggests keywords for assets based on post content analysis."""

    def __init__(self, database_url: str, anthropic_api_key: Optional[str] = None):
        """
        Initialize keyword suggester.

        Args:
            database_url: PostgreSQL connection string
            anthropic_api_key: Optional Anthropic API key (defaults to env var)
        """
        self.database_url = database_url
        self.client = Anthropic(api_key=anthropic_api_key or os.getenv('ANTHROPIC_API_KEY'))

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def get_top_posts_for_asset(self, asset_id: int, limit: int = 50) -> List[Dict]:
        """
        Fetch top posts for an asset to analyze for keyword suggestions.

        Args:
            asset_id: Asset ID to fetch posts for
            limit: Maximum number of posts to fetch

        Returns:
            List of post dictionaries with title and content
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT sp.id, sp.title, sp.content, sp.score
                    FROM social_posts sp
                    WHERE sp.asset_id = %s
                    ORDER BY sp.score DESC NULLS LAST, sp.created_at DESC
                    LIMIT %s
                """, (asset_id, limit))
                return cur.fetchall()
        finally:
            conn.close()

    def get_asset_info(self, asset_id: int) -> Optional[Dict]:
        """
        Get asset information including current keywords.

        Args:
            asset_id: Asset ID

        Returns:
            Dict with asset name, ticker, and current keywords
        """
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, name, ticker, search_keywords
                    FROM asset
                    WHERE id = %s
                """, (asset_id,))
                return cur.fetchone()
        finally:
            conn.close()

    def suggest_keywords(self, asset_id: int, max_keywords: int = 10) -> List[str]:
        """
        Suggest new keywords for an asset based on collected posts.

        Args:
            asset_id: Asset ID to suggest keywords for
            max_keywords: Maximum number of keywords to suggest

        Returns:
            List of suggested keyword strings
        """
        # Get asset info
        asset = self.get_asset_info(asset_id)
        if not asset:
            logger.error(f"Asset {asset_id} not found")
            return []

        # Get top posts
        posts = self.get_top_posts_for_asset(asset_id, limit=50)
        if not posts:
            logger.warning(f"No posts found for asset {asset_id}")
            return []

        # Combine post text (limit total length)
        text_samples = []
        total_chars = 0
        max_chars = 8000  # Leave room for prompt

        for post in posts:
            sample = f"Title: {post['title']}\n"
            if post['content']:
                sample += f"Content: {post['content'][:500]}\n"  # Limit each post content
            sample += "\n"

            if total_chars + len(sample) > max_chars:
                break

            text_samples.append(sample)
            total_chars += len(sample)

        combined_text = "".join(text_samples)

        # Build prompt for Claude
        current_keywords = ", ".join(asset['search_keywords'])

        prompt = f"""Analyze these social media posts about {asset['name']} ({asset['ticker']}) and suggest {max_keywords} additional search keywords we should track.

Current keywords: {current_keywords}

Focus on suggesting:
- Product names and features
- Executive names (CEO, CFO, etc.)
- Competitor names
- Common abbreviations and acronyms
- Industry-specific terminology
- Alternative company names
- Related technologies or services
- Geographic locations (if relevant)

Posts to analyze:
{combined_text}

Return ONLY a comma-separated list of {max_keywords} keywords. Do not include keywords already in the current list. Keep keywords lowercase. No explanations or additional text.

Example format: keyword1, keyword2, keyword3"""

        try:
            # Call Claude API
            message = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            response_text = message.content[0].text.strip()

            # Split by comma and clean
            suggested_keywords = [
                kw.strip().lower()
                for kw in response_text.split(',')
                if kw.strip()
            ]

            # Filter out duplicates and existing keywords
            existing_keywords_lower = [kw.lower() for kw in asset['search_keywords']]
            new_keywords = [
                kw for kw in suggested_keywords
                if kw not in existing_keywords_lower
            ]

            logger.info(f"Suggested {len(new_keywords)} new keywords for {asset['name']}: {new_keywords}")
            return new_keywords[:max_keywords]

        except Exception as e:
            logger.error(f"Error suggesting keywords for asset {asset_id}: {e}")
            return []

    def get_keyword_suggestions_for_all_assets(self, max_keywords: int = 10) -> Dict[int, List[str]]:
        """
        Generate keyword suggestions for all assets.

        Args:
            max_keywords: Maximum keywords per asset

        Returns:
            Dict mapping asset_id to list of suggested keywords
        """
        conn = self.get_db_connection()
        suggestions = {}

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM asset ORDER BY name")
                asset_ids = [row['id'] for row in cur.fetchall()]

            for asset_id in asset_ids:
                keywords = self.suggest_keywords(asset_id, max_keywords)
                if keywords:
                    suggestions[asset_id] = keywords

        finally:
            conn.close()

        return suggestions
