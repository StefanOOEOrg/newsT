"""
RSS Feed Collector - fetches news from RSS feeds.
"""
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict
import feedparser
from .base import BaseCollector

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """Collects news articles from RSS feeds."""

    # RSS Feed sources configuration
    RSS_FEEDS = [
        {
            'name': 'Google News',
            'url': 'https://news.google.com/rss/search?q={keyword}+when:7d&hl=en-US&gl=US&ceid=US:en',
            'use_keyword': True
        },
        {
            'name': 'Yahoo Finance',
            'url': 'https://finance.yahoo.com/rss/headline?s={ticker}',
            'use_ticker': True
        },
        {
            'name': 'Seeking Alpha',
            'url': 'https://seekingalpha.com/api/sa/combined/{ticker}.xml',
            'use_ticker': True
        }
    ]

    def __init__(self, database_url: str):
        """Initialize RSS collector."""
        super().__init__(database_url)

    def generate_post_id(self, url: str) -> str:
        """Generate a unique post ID from URL using hash."""
        return f"rss_{hashlib.md5(url.encode()).hexdigest()}"

    def fetch_rss_feed(self, feed_config: Dict, asset_id: int,
                      asset_name: str, ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Fetch and parse a single RSS feed.

        Args:
            feed_config: Feed configuration dict with 'name' and 'url'
            asset_id: Asset database ID
            asset_name: Asset name
            ticker: Stock ticker
            keywords: Search keywords

        Returns:
            List of post dictionaries
        """
        posts = []

        try:
            # Format URL with ticker or keyword
            url = feed_config['url']
            feed_name = feed_config['name']

            if feed_config.get('use_ticker'):
                url = url.format(ticker=ticker)
            elif feed_config.get('use_keyword'):
                url = url.format(keyword=asset_name.replace(' ', '+'))

            logger.info(f"Fetching {feed_name} for {asset_name}")

            # Parse RSS feed
            feed = feedparser.parse(url)

            if feed.bozo:
                logger.warning(f"Feed parsing warning for {feed_name}: {feed.bozo_exception}")

            # Process entries
            for entry in feed.entries[:50]:  # Limit to 50 most recent
                try:
                    # Extract entry data
                    title = entry.get('title', 'No title')
                    link = entry.get('link', '')

                    if not link:
                        continue

                    summary = entry.get('summary', entry.get('description', ''))
                    author = entry.get('author', feed.feed.get('title', feed_name))

                    # Parse published date
                    published = entry.get('published_parsed') or entry.get('updated_parsed')
                    if published:
                        created_at = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        created_at = datetime.now(timezone.utc)

                    # Check if keywords match (for generic feeds)
                    if not feed_config.get('use_ticker') and not feed_config.get('use_keyword'):
                        text_to_search = (title + ' ' + summary).lower()
                        keyword_match = any(
                            keyword.lower() in text_to_search
                            for keyword in keywords + [ticker]
                        )
                        if not keyword_match:
                            continue

                    # Generate unique post ID
                    post_id = self.generate_post_id(link)

                    # Skip if already exists
                    if self.post_exists(post_id):
                        continue

                    post = {
                        'asset_id': asset_id,
                        'source': f'rss_{feed_name.lower().replace(" ", "_")}',
                        'post_id': post_id,
                        'author': author[:255] if author else feed_name,
                        'title': title[:500] if title else 'No title',
                        'content': summary[:5000] if summary else None,
                        'url': link[:500],
                        'score': 0,  # RSS feeds don't have scores
                        'created_at': created_at
                    }
                    posts.append(post)
                    logger.debug(f"Found article: {title[:50]}...")

                except Exception as e:
                    logger.error(f"Error processing RSS entry: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error fetching RSS feed {feed_config['name']}: {e}")

        return posts

    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect news articles from RSS feeds for a specific asset.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Stock ticker symbol
            keywords: List of keywords to search for

        Returns:
            List of post dictionaries
        """
        all_posts = []

        # Fetch from each RSS feed
        for feed_config in self.RSS_FEEDS:
            posts = self.fetch_rss_feed(
                feed_config,
                asset_id,
                asset_name,
                ticker,
                keywords
            )
            all_posts.extend(posts)

        return all_posts
