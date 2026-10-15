"""
Finnhub Collector - fetches company news from Finnhub.io

Free tier: 60 API calls/minute, company news included
Get API key: https://finnhub.io/register
"""
import os
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict
import requests
from .base import BaseCollector

logger = logging.getLogger(__name__)


class FinnhubCollector(BaseCollector):
    """
    Collects financial news from Finnhub.io

    Free tier: 60 calls/minute, company news, market data
    Premium: From $99/month for real-time data
    """

    API_URL = "https://finnhub.io/api/v1/company-news"

    def __init__(self, database_url: str):
        """Initialize Finnhub collector."""
        super().__init__(database_url)

        self.api_key = os.getenv('FINNHUB_API_KEY')
        if not self.api_key:
            raise ValueError(
                "FINNHUB_API_KEY not found in environment. "
                "Get one at https://finnhub.io/register"
            )

    def generate_post_id(self, article_id: int, url: str) -> str:
        """Generate unique post ID."""
        # Use article ID if available, otherwise hash URL
        if article_id:
            return f"finnhub_{article_id}"
        return f"finnhub_{hashlib.md5(url.encode()).hexdigest()}"

    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect news articles for a specific asset from Finnhub.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Ticker symbol (stock, crypto, etc.)
            keywords: List of keywords to search for

        Returns:
            List of post dictionaries
        """
        posts = []

        try:
            # Date range (last 7 days)
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

            # Make API request
            params = {
                'symbol': ticker,
                'from': from_date,
                'to': to_date,
                'token': self.api_key
            }

            logger.info(f"Fetching Finnhub news for {ticker}")
            response = requests.get(self.API_URL, params=params, timeout=10)

            if response.status_code == 401:
                logger.error("Finnhub: Invalid API key")
                return []
            elif response.status_code == 429:
                logger.warning("Finnhub: Rate limit exceeded")
                return []
            elif response.status_code != 200:
                logger.error(f"Finnhub: HTTP {response.status_code}")
                return []

            articles = response.json()

            if not isinstance(articles, list):
                logger.error(f"Finnhub: Unexpected response format")
                return []

            # Process articles
            for article in articles:
                try:
                    url = article.get('url')
                    if not url:
                        continue

                    # Generate post ID
                    article_id = article.get('id')
                    post_id = self.generate_post_id(article_id, url)

                    # Skip if exists
                    if self.post_exists(post_id):
                        continue

                    # Parse timestamp (Unix timestamp)
                    timestamp = article.get('datetime')
                    if timestamp:
                        created_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    else:
                        created_at = datetime.now(timezone.utc)

                    post = {
                        'asset_id': asset_id,
                        'source': 'finnhub',
                        'post_id': post_id,
                        'author': article.get('source', 'Finnhub')[:255],
                        'title': article.get('headline', 'No title')[:500],
                        'content': article.get('summary', '')[:5000],
                        'url': url[:500],
                        'score': 0,  # Finnhub doesn't provide engagement metrics
                        'created_at': created_at
                    }
                    posts.append(post)
                    logger.debug(f"Found article: {post['title'][:50]}...")

                except Exception as e:
                    logger.error(f"Error processing Finnhub article: {e}")
                    continue

            logger.info(f"Finnhub: Collected {len(posts)} articles for {ticker}")

        except requests.RequestException as e:
            logger.error(f"Finnhub request error for {ticker}: {e}")
        except Exception as e:
            logger.error(f"Finnhub error for {ticker}: {e}")

        return posts
