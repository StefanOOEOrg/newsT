"""
NewsAPI Collector - fetches news from NewsAPI.org

Free tier: 100 requests/day
Get API key: https://newsapi.org/register
"""
import os
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict
import requests
from .base import BaseCollector

logger = logging.getLogger(__name__)


class NewsAPICollector(BaseCollector):
    """
    Collects financial news from NewsAPI.org

    Free tier: 100 requests/day, 30 days historical data
    Paid tier: From $449/month for more requests
    """

    API_URL = "https://newsapi.org/v2/everything"

    def __init__(self, database_url: str):
        """Initialize NewsAPI collector."""
        super().__init__(database_url)

        self.api_key = os.getenv('NEWSAPI_KEY')
        if not self.api_key:
            raise ValueError(
                "NEWSAPI_KEY not found in environment. "
                "Get one at https://newsapi.org/register"
            )

    def generate_post_id(self, url: str) -> str:
        """Generate unique post ID from URL."""
        return f"newsapi_{hashlib.md5(url.encode()).hexdigest()}"

    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect news articles for a specific asset from NewsAPI.

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
            # Check rate limit before making request
            can_proceed, reason, wait_seconds = self.rate_limiter.can_make_request()

            if not can_proceed:
                logger.warning(
                    f"NewsAPI: Rate limit hit for {asset_name} - {reason}. "
                    f"Skipping this collection cycle"
                )
                return []

            # Build search query
            query_parts = [asset_name, ticker] + keywords[:3]  # Limit keywords
            query = ' OR '.join(f'"{part}"' for part in query_parts if part)

            # Date range (last 7 days for free tier)
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

            # Make API request
            params = {
                'q': query,
                'apiKey': self.api_key,
                'language': 'en',
                'sortBy': 'publishedAt',
                'from': from_date,
                'pageSize': 100  # Max for free tier
            }

            logger.info(f"Fetching NewsAPI for {asset_name}")
            response = requests.get(self.API_URL, params=params, timeout=10)

            # Record API usage
            if response.status_code == 401:
                logger.error("NewsAPI: Invalid API key")
                self.rate_limiter.record_request(success=False, status_code=401, error_message="Invalid API key")
                return []
            elif response.status_code == 429:
                logger.warning("NewsAPI: Rate limit exceeded")
                self.rate_limiter.record_request(success=False, status_code=429, error_message="Rate limit exceeded")
                return []
            elif response.status_code != 200:
                logger.error(f"NewsAPI: HTTP {response.status_code}")
                self.rate_limiter.record_request(success=False, status_code=response.status_code)
                return []

            # Record successful request
            self.rate_limiter.record_request(success=True, status_code=200, api_endpoint=self.API_URL)

            data = response.json()

            if data.get('status') != 'ok':
                logger.error(f"NewsAPI error: {data.get('message', 'Unknown error')}")
                return []

            # Process articles
            for article in data.get('articles', []):
                try:
                    url = article.get('url')
                    if not url:
                        continue

                    # Generate post ID
                    post_id = self.generate_post_id(url)

                    # Skip if exists
                    if self.post_exists(post_id):
                        continue

                    # Parse published date
                    published_at = article.get('publishedAt')
                    if published_at:
                        created_at = datetime.fromisoformat(
                            published_at.replace('Z', '+00:00')
                        )
                    else:
                        created_at = datetime.now(timezone.utc)

                    # Safely extract author, handling None values
                    author = article.get('author')
                    if not author:
                        source_obj = article.get('source')
                        if source_obj and isinstance(source_obj, dict):
                            author = source_obj.get('name', 'Unknown')
                        else:
                            author = 'Unknown'

                    post = {
                        'asset_id': asset_id,
                        'source': 'newsapi',
                        'post_id': post_id,
                        'author': author[:255],
                        'title': article.get('title', 'No title')[:500],
                        'content': (article.get('description') or article.get('content') or '')[:5000],
                        'url': url[:500],
                        'score': 0,  # NewsAPI doesn't provide engagement metrics
                        'created_at': created_at
                    }
                    posts.append(post)
                    logger.debug(f"Found article: {post['title'][:50]}...")

                except Exception as e:
                    logger.error(f"Error processing NewsAPI article: {e}")
                    continue

            logger.info(f"NewsAPI: Collected {len(posts)} articles for {asset_name}")

        except requests.RequestException as e:
            logger.error(f"NewsAPI request error for {asset_name}: {e}")
        except Exception as e:
            logger.error(f"NewsAPI error for {asset_name}: {e}")

        return posts

    def collect_for_asset_historical(self, asset_id: int, asset_name: str,
                                     ticker: str, keywords: List[str],
                                     days_back: int = 30) -> List[Dict]:
        """
        Collect historical news for an asset using NewsAPI.

        NewsAPI free tier supports 30 days of historical data.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Ticker symbol (stock, crypto, etc.)
            keywords: List of keywords to search for
            days_back: Number of days to go back (max 30 for free tier)

        Returns:
            List of post dictionaries
        """
        posts = []

        # Free tier limit
        if days_back > 30:
            logger.warning(f"NewsAPI free tier limited to 30 days, using 30 instead of {days_back}")
            days_back = 30

        try:
            # Build search query
            query_parts = [asset_name, ticker] + keywords[:3]
            query = ' OR '.join(f'"{part}"' for part in query_parts if part)

            # Date range
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days_back)

            # Make API request
            params = {
                'q': query,
                'apiKey': self.api_key,
                'language': 'en',
                'sortBy': 'publishedAt',
                'from': from_date.strftime('%Y-%m-%d'),
                'to': to_date.strftime('%Y-%m-%d'),
                'pageSize': 100
            }

            logger.info(f"Fetching {days_back} days of historical data from NewsAPI for {asset_name}")
            response = requests.get(self.API_URL, params=params, timeout=10)

            if response.status_code != 200:
                logger.error(f"NewsAPI: HTTP {response.status_code}")
                return []

            data = response.json()

            if data.get('status') != 'ok':
                logger.error(f"NewsAPI error: {data.get('message', 'Unknown error')}")
                return []

            # Process articles
            for article in data.get('articles', []):
                try:
                    url = article.get('url')
                    if not url:
                        continue

                    # Generate unique post ID
                    post_id = self.generate_post_id(url)

                    # Skip if already exists
                    if self.post_exists(post_id):
                        continue

                    # Parse published date
                    published_at_str = article.get('publishedAt')
                    if published_at_str:
                        created_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                    else:
                        created_at = datetime.now(timezone.utc)

                    # Safely extract author, handling None values
                    author = article.get('author')
                    if not author:
                        source_obj = article.get('source')
                        if source_obj and isinstance(source_obj, dict):
                            author = source_obj.get('name', 'Unknown')
                        else:
                            author = 'Unknown'

                    # Safely extract content
                    content = article.get('description') or article.get('content') or ''
                    content = content[:5000] if content else ''

                    post = {
                        'asset_id': asset_id,
                        'source': 'newsapi',
                        'post_id': post_id,
                        'author': author[:255],
                        'title': article.get('title', 'No title')[:500],
                        'content': content,
                        'url': url[:500],
                        'score': 0,
                        'created_at': created_at
                    }
                    posts.append(post)

                except Exception as e:
                    logger.error(f"Error processing historical NewsAPI article: {e}")
                    continue

            logger.info(f"NewsAPI: Collected {len(posts)} historical articles for {asset_name}")

        except Exception as e:
            logger.error(f"NewsAPI historical collection error for {asset_name}: {e}")

        return posts
