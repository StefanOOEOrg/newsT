"""
Twitter/X Collector - fetches tweets (TEMPLATE - not yet implemented).

To enable this collector:
1. Get Twitter API credentials from https://developer.twitter.com/
2. Add to .env:
   TWITTER_API_KEY=your_api_key
   TWITTER_API_SECRET=your_api_secret
   TWITTER_ACCESS_TOKEN=your_access_token
   TWITTER_ACCESS_SECRET=your_access_secret
3. Install tweepy: pip install tweepy
4. Implement the collect_for_company method below
5. Enable in collector/config.py
"""
import os
import logging
from typing import List, Dict
from .base import BaseCollector

logger = logging.getLogger(__name__)

# Uncomment when tweepy is installed:
# import tweepy


class TwitterCollector(BaseCollector):
    """
    Collects tweets from Twitter/X.

    TEMPLATE - Not yet implemented.
    """

    def __init__(self, database_url: str):
        """Initialize Twitter collector."""
        super().__init__(database_url)

        # Check for Twitter credentials
        self.api_key = os.getenv('TWITTER_API_KEY')
        self.api_secret = os.getenv('TWITTER_API_SECRET')
        self.access_token = os.getenv('TWITTER_ACCESS_TOKEN')
        self.access_secret = os.getenv('TWITTER_ACCESS_SECRET')

        if not all([self.api_key, self.api_secret, self.access_token, self.access_secret]):
            raise ValueError(
                "Twitter credentials not found in environment. "
                "Please set TWITTER_API_KEY, TWITTER_API_SECRET, "
                "TWITTER_ACCESS_TOKEN, and TWITTER_ACCESS_SECRET"
            )

        # Uncomment when ready to use:
        # auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
        # auth.set_access_token(self.access_token, self.access_secret)
        # self.api = tweepy.API(auth)

    def collect_for_asset(self, asset_id: int, asset_name: str,
                         ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect tweets for a specific asset.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Ticker symbol (stock, crypto, etc.) (useful for $TICKER searches)
            keywords: List of keywords to search for

        Returns:
            List of post dictionaries
        """
        posts = []

        # TEMPLATE IMPLEMENTATION - Modify when tweepy is available:
        #
        # # Search for tweets mentioning the asset
        # search_query = ' OR '.join([f'${ticker}'] + keywords)
        #
        # try:
        #     tweets = self.api.search_tweets(
        #         q=search_query,
        #         lang='en',
        #         count=100,
        #         result_type='recent'
        #     )
        #
        #     for tweet in tweets:
        #         post_id = f"twitter_{tweet.id}"
        #
        #         if self.post_exists(post_id):
        #             continue
        #
        #         post = {
        #             'asset_id': asset_id,
        #             'source': 'twitter',
        #             'post_id': post_id,
        #             'author': tweet.user.screen_name,
        #             'title': tweet.text[:500],
        #             'content': tweet.text,
        #             'url': f"https://twitter.com/{tweet.user.screen_name}/status/{tweet.id}",
        #             'score': tweet.favorite_count + tweet.retweet_count,
        #             'created_at': tweet.created_at
        #         }
        #         posts.append(post)
        #
        # except Exception as e:
        #     logger.error(f"Error fetching tweets: {e}")

        logger.warning(
            f"TwitterCollector is not yet implemented. "
            f"See collector/collectors/twitter_collector.py for template."
        )

        return posts
