"""
Alpha Vantage Collector - fetches news and sentiment from Alpha Vantage

Free tier: 25 API calls/day
Get API key: https://www.alphavantage.co/support/#api-key
"""
import os
import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict
import requests
from .base import BaseCollector

logger = logging.getLogger(__name__)


class AlphaVantageCollector(BaseCollector):
    """
    Collects financial news and sentiment from Alpha Vantage

    Free tier: 25 calls/day (limited but includes sentiment!)
    Premium: From $49.99/month for more calls
    """

    API_URL = "https://www.alphavantage.co/query"

    def __init__(self, database_url: str):
        """Initialize Alpha Vantage collector."""
        super().__init__(database_url)

        self.api_key = os.getenv('ALPHAVANTAGE_API_KEY')
        if not self.api_key:
            raise ValueError(
                "ALPHAVANTAGE_API_KEY not found in environment. "
                "Get one at https://www.alphavantage.co/support/#api-key"
            )

        self.calls_made = 0  # Track API calls

    def generate_post_id(self, url: str, title: str) -> str:
        """Generate unique post ID."""
        # Use URL if available, otherwise hash title
        if url:
            return f"alphavantage_{hashlib.md5(url.encode()).hexdigest()}"
        return f"alphavantage_{hashlib.md5(title.encode()).hexdigest()}"

    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect news and sentiment for a specific asset from Alpha Vantage.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Ticker symbol (stock, crypto, etc.)
            keywords: List of keywords to search for

        Returns:
            List of post dictionaries
        """
        posts = []

        # Limit API calls (25/day for free tier)
        if self.calls_made >= 25:
            logger.warning("AlphaVantage: Daily API limit reached (25 calls)")
            return []

        try:
            # Make API request for news & sentiment
            params = {
                'function': 'NEWS_SENTIMENT',
                'tickers': ticker,
                'apikey': self.api_key,
                'limit': 50  # Number of news items
            }

            logger.info(f"Fetching Alpha Vantage news for {ticker}")
            response = requests.get(self.API_URL, params=params, timeout=15)
            self.calls_made += 1

            if response.status_code == 401:
                logger.error("AlphaVantage: Invalid API key")
                return []
            elif response.status_code == 429:
                logger.warning("AlphaVantage: Rate limit exceeded")
                return []
            elif response.status_code != 200:
                logger.error(f"AlphaVantage: HTTP {response.status_code}")
                return []

            data = response.json()

            # Check for API errors
            if 'Error Message' in data:
                logger.error(f"AlphaVantage error: {data['Error Message']}")
                return []
            if 'Note' in data:
                logger.warning(f"AlphaVantage note: {data['Note']}")
                return []

            # Process news feed
            feed = data.get('feed', [])

            for article in feed:
                try:
                    title = article.get('title')
                    url = article.get('url', '')

                    if not title:
                        continue

                    # Generate post ID
                    post_id = self.generate_post_id(url, title)

                    # Skip if exists
                    if self.post_exists(post_id):
                        continue

                    # Parse timestamp
                    time_published = article.get('time_published')
                    if time_published:
                        # Format: YYYYMMDDTHHMMSS
                        created_at = datetime.strptime(
                            time_published,
                            '%Y%m%dT%H%M%S'
                        ).replace(tzinfo=timezone.utc)
                    else:
                        created_at = datetime.now(timezone.utc)

                    # Get sentiment score for this ticker
                    sentiment_score = 0
                    ticker_sentiments = article.get('ticker_sentiment', [])
                    for ts in ticker_sentiments:
                        if ts.get('ticker') == ticker:
                            sentiment_score = float(ts.get('ticker_sentiment_score', 0))
                            break

                    # Convert sentiment score to engagement score (0-100)
                    # Alpha Vantage: -1 (bearish) to +1 (bullish)
                    score = int((sentiment_score + 1) * 50)  # Map to 0-100

                    post = {
                        'asset_id': asset_id,
                        'source': 'alphavantage',
                        'post_id': post_id,
                        'author': ', '.join(article.get('authors', ['Alpha Vantage']))[:255],
                        'title': title[:500],
                        'content': article.get('summary', '')[:5000],
                        'url': url[:500] if url else f"https://alphavantage.co/news/{post_id}",
                        'score': score,  # Use sentiment score as engagement
                        'created_at': created_at
                    }
                    posts.append(post)
                    logger.debug(f"Found article: {post['title'][:50]}... (sentiment: {sentiment_score:.2f})")

                except Exception as e:
                    logger.error(f"Error processing AlphaVantage article: {e}")
                    continue

            logger.info(f"AlphaVantage: Collected {len(posts)} articles for {ticker} (Calls: {self.calls_made}/25)")

        except requests.RequestException as e:
            logger.error(f"AlphaVantage request error for {ticker}: {e}")
        except Exception as e:
            logger.error(f"AlphaVantage error for {ticker}: {e}")

        return posts
