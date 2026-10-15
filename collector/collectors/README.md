# Collector Modules

This directory contains modular collectors for fetching news from different sources.

## Architecture

All collectors inherit from `BaseCollector` which provides:
- Database connection management
- Duplicate detection
- Batch saving of posts
- Standard interface for collection

## Available Collectors

### ✅ RSSCollector (Enabled)

Fetches news from RSS feeds. **No API keys required!**

**Sources:**
- Google News (company-specific news, past 7 days)
- Yahoo Finance (ticker-specific news)
- Seeking Alpha (financial analysis)

**Status:** ✅ Active and working

---

### 🔒 RedditCollector (Disabled)

Fetches posts from Reddit subreddits.

**Status:** ⏸️ Template only - requires Reddit API approval

**To enable:**
1. Get Reddit API credentials from https://www.reddit.com/prefs/apps
2. Add to `.env`:
   ```
   REDDIT_CLIENT_ID=your_client_id
   REDDIT_CLIENT_SECRET=your_secret
   REDDIT_USER_AGENT=newstrading-bot/1.0
   ```
3. Install dependency: `pip install praw==7.7.1`
4. Uncomment implementation in `reddit_collector.py`
5. Enable in `collector/config.py`

---

### 🔒 TwitterCollector (Disabled)

Fetches tweets from Twitter/X.

**Status:** 📝 Template only - not yet implemented

**To enable:**
1. Get Twitter API credentials from https://developer.twitter.com/
2. Add to `.env`:
   ```
   TWITTER_API_KEY=your_api_key
   TWITTER_API_SECRET=your_api_secret
   TWITTER_ACCESS_TOKEN=your_access_token
   TWITTER_ACCESS_SECRET=your_access_secret
   ```
3. Install dependency: `pip install tweepy`
4. Implement `collect_for_company()` in `twitter_collector.py`
5. Enable in `collector/config.py`

---

## Creating a New Collector

To add a new data source:

### 1. Create Collector Class

Create `my_collector.py`:

```python
from typing import List, Dict
from .base import BaseCollector

class MyCollector(BaseCollector):
    """Collects data from My Source."""

    def __init__(self, database_url: str):
        super().__init__(database_url)
        # Initialize your API client here

    def collect_for_company(self, company_id: int, company_name: str,
                           ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect posts for a specific company.

        Returns:
            List of dicts with required fields:
            - company_id: int
            - source: str (e.g., 'my_source')
            - post_id: str (unique)
            - author: str
            - title: str
            - content: str or None
            - url: str
            - score: int
            - created_at: datetime (with timezone)
        """
        posts = []

        # Your collection logic here
        # ...

        return posts
```

### 2. Update `__init__.py`

Add your collector to `collectors/__init__.py`:

```python
from .my_collector import MyCollector

__all__ = ['BaseCollector', 'RSSCollector', 'MyCollector']
```

### 3. Enable in Configuration

Add to `collector/config.py`:

```python
from collectors.my_collector import MyCollector

ENABLED_COLLECTORS = [
    RSSCollector,
    MyCollector,  # Add your collector
]
```

That's it! Your collector will now run alongside the others.

## Testing a Collector

To test a collector in isolation:

```python
from collectors.rss_collector import RSSCollector

collector = RSSCollector('postgresql://user:pass@localhost/db')

# Test for one company
posts = collector.collect_for_company(
    company_id=1,
    company_name="Tesla",
    ticker="TSLA",
    keywords=["tesla", "elon musk"]
)

print(f"Found {len(posts)} posts")
```

## Enabling/Disabling Collectors

Edit `collector/config.py`:

```python
ENABLED_COLLECTORS = [
    RSSCollector,        # Active
    # RedditCollector,   # Disabled (commented out)
    # TwitterCollector,  # Disabled (commented out)
]
```

Only collectors in this list will be initialized and run.

## Collector Methods

### Required Method

- `collect_for_company(company_id, company_name, ticker, keywords)` → List[Dict]
  - **Must implement** - fetches data for one company
  - Returns list of post dictionaries

### Inherited Methods

From `BaseCollector`:

- `get_db_connection()` → connection
- `get_companies()` → List[(id, name, ticker, keywords)]
- `post_exists(post_id)` → bool
- `save_posts(posts)` → int
- `collect_all()` → Dict[str, int]

## Post Format

All collectors must return posts in this format:

```python
{
    'company_id': 1,                    # Database ID
    'source': 'rss_google_news',        # Source identifier
    'post_id': 'unique_id_here',        # Globally unique
    'author': 'John Doe',               # Author/publisher
    'title': 'Article title',           # Title/headline
    'content': 'Full text...',          # Content (can be None)
    'url': 'https://...',               # URL to original
    'score': 42,                        # Score/likes (0 if N/A)
    'created_at': datetime(2024, ...)   # With timezone
}
```

## Error Handling

Collectors should:
- ✅ Log errors but continue processing
- ✅ Skip individual failures, don't crash entire collection
- ✅ Return empty list `[]` if source is unavailable
- ✅ Raise exception only for fatal configuration errors

## Best Practices

1. **Use unique post_ids**: Prefix with source name (e.g., `reddit_abc123`)
2. **Handle rate limits**: Add delays between requests
3. **Check duplicates**: Use `self.post_exists()` before adding
4. **Limit content length**: Truncate to avoid database errors
5. **Log progress**: Use `logger.info()` for important events
6. **Fail gracefully**: Don't crash on missing data

## Example: Adding a News API Collector

```python
# collectors/newsapi_collector.py
import os
import requests
from datetime import datetime, timezone
from typing import List, Dict
from .base import BaseCollector

class NewsAPICollector(BaseCollector):
    """Collects news from NewsAPI.org"""

    API_URL = "https://newsapi.org/v2/everything"

    def __init__(self, database_url: str):
        super().__init__(database_url)
        self.api_key = os.getenv('NEWSAPI_KEY')
        if not self.api_key:
            raise ValueError("NEWSAPI_KEY not found in environment")

    def collect_for_company(self, company_id: int, company_name: str,
                           ticker: str, keywords: List[str]) -> List[Dict]:
        posts = []

        query = f'{company_name} OR {ticker}'

        response = requests.get(self.API_URL, params={
            'q': query,
            'apiKey': self.api_key,
            'language': 'en',
            'sortBy': 'publishedAt'
        })

        if response.status_code != 200:
            return []

        data = response.json()

        for article in data.get('articles', []):
            post_id = f"newsapi_{article['url']}"

            if self.post_exists(post_id):
                continue

            posts.append({
                'company_id': company_id,
                'source': 'newsapi',
                'post_id': post_id,
                'author': article.get('author', 'Unknown'),
                'title': article['title'],
                'content': article.get('description'),
                'url': article['url'],
                'score': 0,
                'created_at': datetime.fromisoformat(
                    article['publishedAt'].replace('Z', '+00:00')
                )
            })

        return posts
```

Then enable in `config.py` and you're done!
