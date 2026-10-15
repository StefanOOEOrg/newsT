"""
RSS News Feed Collector Service
Fetches financial news from RSS feeds based on company keywords and stores them in the database.
"""
import os
import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Tuple
import feedparser
import psycopg2
from psycopg2.extras import execute_values
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# RSS Feed sources
RSS_FEEDS = [
    {
        'name': 'Google News - Business',
        'url': 'https://news.google.com/rss/search?q={keyword}+when:7d&hl=en-US&gl=US&ceid=US:en'
    },
    {
        'name': 'Yahoo Finance',
        'url': 'https://finance.yahoo.com/rss/headline?s={ticker}'
    },
    {
        'name': 'Seeking Alpha',
        'url': 'https://seekingalpha.com/api/sa/combined/{ticker}.xml'
    }
]


class RSSCollector:
    """Collects news from RSS feeds and stores them in the database."""

    def __init__(self):
        """Initialize collector."""
        logger.info("RSS Collector initialized")

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(DATABASE_URL)

    def get_assets(self) -> List[Tuple[int, str, str, List[str]]]:
        """Fetch all assets from database."""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, ticker, search_keywords
                    FROM asset
                """)
                return cur.fetchall()
        finally:
            conn.close()

    def generate_post_id(self, url: str) -> str:
        """Generate a unique post ID from URL using hash."""
        return hashlib.md5(url.encode()).hexdigest()

    def post_exists(self, post_id: str) -> bool:
        """Check if a post already exists in the database."""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM social_posts WHERE post_id = %s",
                    (post_id,)
                )
                return cur.fetchone() is not None
        finally:
            conn.close()

    def save_posts(self, posts: List[Dict]):
        """Save posts to the database."""
        if not posts:
            return

        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                # Prepare data for batch insert
                values = [
                    (
                        post['asset_id'],
                        post['source'],
                        post['post_id'],
                        post['author'],
                        post['title'],
                        post['content'],
                        post['url'],
                        post['score'],
                        post['created_at']
                    )
                    for post in posts
                ]

                # Batch insert with ON CONFLICT DO NOTHING
                execute_values(
                    cur,
                    """
                    INSERT INTO social_posts
                    (asset_id, source, post_id, author, title, content, url, score, created_at)
                    VALUES %s
                    ON CONFLICT (post_id) DO NOTHING
                    """,
                    values
                )
                conn.commit()
                logger.info(f"Saved {len(posts)} posts to database")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving posts: {e}")
            raise
        finally:
            conn.close()

    def fetch_rss_feed(self, feed_url: str, feed_name: str, asset_id: int,
                       asset_name: str, ticker: str, keywords: List[str]) -> List[Dict]:
        """Fetch and parse an RSS feed."""
        posts = []

        try:
            # Format URL with ticker or keyword
            if '{ticker}' in feed_url:
                url = feed_url.format(ticker=ticker)
            elif '{keyword}' in feed_url:
                # Use asset name as primary keyword
                url = feed_url.format(keyword=asset_name.replace(' ', '+'))
            else:
                url = feed_url

            logger.info(f"Fetching {feed_name}: {url}")

            # Parse RSS feed
            feed = feedparser.parse(url)

            if feed.bozo:
                logger.warning(f"Feed parsing warning for {feed_name}: {feed.bozo_exception}")

            # Process entries
            for entry in feed.entries[:50]:  # Limit to 50 most recent entries
                try:
                    # Extract entry data
                    title = entry.get('title', 'No title')
                    link = entry.get('link', '')
                    summary = entry.get('summary', entry.get('description', ''))
                    author = entry.get('author', feed.feed.get('title', feed_name))

                    # Parse published date
                    published = entry.get('published_parsed') or entry.get('updated_parsed')
                    if published:
                        created_at = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        created_at = datetime.now(timezone.utc)

                    # Check if keywords match
                    text_to_search = (title + ' ' + summary).lower()
                    keyword_match = any(keyword.lower() in text_to_search for keyword in keywords + [ticker])

                    if not keyword_match and '{keyword}' not in feed_url and '{ticker}' not in feed_url:
                        # Skip if no keyword match (only for generic feeds)
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
                        'url': link[:500] if link else '',
                        'score': 0,  # RSS feeds don't have scores
                        'created_at': created_at
                    }
                    posts.append(post)
                    logger.info(f"Found article: {title[:50]}...")

                except Exception as e:
                    logger.error(f"Error processing RSS entry: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error fetching RSS feed {feed_name}: {e}")

        return posts

    def collect_posts(self):
        """Main collection function - fetch posts for all companies."""
        logger.info("Starting RSS feed collection...")

        try:
            assets = self.get_assets()
            logger.info(f"Found {len(assets)} assets to track")

            total_posts = 0
            for asset_id, name, ticker, keywords in assets:
                logger.info(f"Collecting news for {name} ({ticker})")

                all_posts = []

                # Fetch from each RSS feed
                for feed in RSS_FEEDS:
                    posts = self.fetch_rss_feed(
                        feed['url'],
                        feed['name'],
                        asset_id,
                        name,
                        ticker,
                        keywords
                    )
                    all_posts.extend(posts)

                # Save all posts for this company
                if all_posts:
                    self.save_posts(all_posts)
                    total_posts += len(all_posts)
                    logger.info(f"Collected {len(all_posts)} articles for {name}")

            logger.info(f"Collection complete. Total new articles: {total_posts}")

        except Exception as e:
            logger.error(f"Error in collect_posts: {e}")
            raise


def main():
    """Main entry point."""
    logger.info("Starting RSS News Collector Service")

    # Validate environment variables
    if not DATABASE_URL:
        logger.error("Missing DATABASE_URL environment variable")
        return

    collector = RSSCollector()

    # Run immediately on startup
    logger.info("Running initial collection...")
    try:
        collector.collect_posts()
    except Exception as e:
        logger.error(f"Initial collection failed: {e}")

    # Schedule regular collections every 6 hours
    scheduler = BlockingScheduler()
    scheduler.add_job(
        collector.collect_posts,
        'interval',
        hours=6,
        next_run_time=None  # Don't run immediately, we just did
    )

    logger.info("Scheduler started. Running every 6 hours.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Collector service stopped")


if __name__ == "__main__":
    main()
