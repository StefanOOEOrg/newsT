"""
Reddit Collector - fetches posts from Reddit (DISABLED - requires API approval).

To enable this collector:
1. Get Reddit API credentials from https://www.reddit.com/prefs/apps
2. Add to .env:
   REDDIT_CLIENT_ID=your_client_id
   REDDIT_CLIENT_SECRET=your_secret
   REDDIT_USER_AGENT=your_user_agent
3. Install praw: pip install praw==7.7.1
4. Enable in collector/config.py
"""
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict
from .base import BaseCollector

logger = logging.getLogger(__name__)

# Uncomment when praw is installed:
# import praw


class RedditCollector(BaseCollector):
    """
    Collects posts from Reddit subreddits.

    CURRENTLY DISABLED - Requires Reddit API approval.
    This is a template for future implementation.
    """

    SUBREDDITS = ['stocks', 'wallstreetbets', 'investing', 'stockmarket']

    def __init__(self, database_url: str):
        """Initialize Reddit collector."""
        super().__init__(database_url)

        # Check for Reddit credentials
        self.client_id = os.getenv('REDDIT_CLIENT_ID')
        self.client_secret = os.getenv('REDDIT_CLIENT_SECRET')
        self.user_agent = os.getenv('REDDIT_USER_AGENT')

        if not all([self.client_id, self.client_secret, self.user_agent]):
            raise ValueError(
                "Reddit credentials not found in environment. "
                "Please set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT"
            )

        # Uncomment when ready to use:
        # self.reddit = praw.Reddit(
        #     client_id=self.client_id,
        #     client_secret=self.client_secret,
        #     user_agent=self.user_agent
        # )
        # self.reddit.read_only = True

    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect posts from Reddit for a specific asset.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Ticker symbol (stock, crypto, etc.)
            keywords: List of keywords to search for

        Returns:
            List of post dictionaries
        """
        posts = []

        # TEMPLATE IMPLEMENTATION - Uncomment and modify when praw is available:
        #
        # for subreddit_name in self.SUBREDDITS:
        #     try:
        #         subreddit = self.reddit.subreddit(subreddit_name)
        #
        #         for keyword in keywords:
        #             for submission in subreddit.search(keyword, limit=100, time_filter='week'):
        #                 # Skip if already exists
        #                 post_id = f"reddit_{submission.id}"
        #                 if self.post_exists(post_id):
        #                     continue
        #
        #                 # Check if keyword appears in title or body
        #                 text = (submission.title + ' ' + (submission.selftext or '')).lower()
        #                 if keyword.lower() in text:
        #                     post = {
        #                         'asset_id': asset_id,
        #                         'source': f'reddit_r_{subreddit_name}',
        #                         'post_id': post_id,
        #                         'author': str(submission.author) if submission.author else '[deleted]',
        #                         'title': submission.title,
        #                         'content': submission.selftext[:5000] if submission.selftext else None,
        #                         'url': f"https://reddit.com{submission.permalink}",
        #                         'score': submission.score,
        #                         'created_at': datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
        #                     }
        #                     posts.append(post)
        #
        #     except Exception as e:
        #         logger.error(f"Error fetching from r/{subreddit_name}: {e}")
        #         continue

        logger.warning(
            f"RedditCollector is currently disabled. "
            f"See collector/collectors/reddit_collector.py for setup instructions."
        )

        return posts
