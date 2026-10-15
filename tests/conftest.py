"""
Pytest configuration and fixtures for testing.
"""
import pytest
from datetime import datetime, timezone
from typing import List, Dict, Tuple


class MockDatabaseConnection:
    """Mock database connection for testing."""

    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.queries = []
        self._assets = [
            (1, 'Genpact', 'G', ['genpact', 'G']),
            (2, 'Palantir', 'PLTR', ['palantir', 'pltr']),
            (3, 'Snowflake', 'SNOW', ['snowflake', 'snow'])
        ]
        self._posts = []

    def cursor(self):
        """Return mock cursor."""
        return MockCursor(self)

    def commit(self):
        """Mock commit."""
        self.committed = True

    def rollback(self):
        """Mock rollback."""
        self.rolled_back = True

    def close(self):
        """Mock close."""
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


class MockCursor:
    """Mock database cursor for testing."""

    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0
        self._result = None

    def execute(self, query, params=None):
        """Mock execute query."""
        self.connection.queries.append((query, params))

        # Handle SELECT queries
        if query.strip().upper().startswith('SELECT'):
            if 'FROM asset' in query:
                self._result = self.connection._assets
            elif 'FROM social_posts' in query and 'post_id' in query:
                # Check if post exists
                post_id = params[0] if params else None
                self._result = [(1,)] if any(p['post_id'] == post_id for p in self.connection._posts) else []

    def fetchall(self):
        """Mock fetchall."""
        return self._result or []

    def fetchone(self):
        """Mock fetchone."""
        if self._result:
            return self._result[0] if self._result else None
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockDatabaseAdapter:
    """
    Database adapter interface for dependency injection.

    This allows us to swap real database connections with mocks during testing.
    """

    def get_connection(self):
        """Get a database connection."""
        raise NotImplementedError

    def get_assets(self) -> List[Tuple[int, str, str, List[str]]]:
        """Fetch all assets."""
        raise NotImplementedError

    def post_exists(self, post_id: str) -> bool:
        """Check if a post exists."""
        raise NotImplementedError

    def save_posts(self, posts: List[Dict]) -> int:
        """Save posts to database."""
        raise NotImplementedError


class RealDatabaseAdapter(MockDatabaseAdapter):
    """Real database adapter using psycopg2."""

    def __init__(self, database_url: str):
        import psycopg2
        from psycopg2.extras import execute_values
        self.database_url = database_url
        self.psycopg2 = psycopg2
        self.execute_values = execute_values

    def get_connection(self):
        """Get a real database connection."""
        return self.psycopg2.connect(self.database_url)

    def get_assets(self) -> List[Tuple[int, str, str, List[str]]]:
        """Fetch all assets from database."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, ticker, search_keywords FROM asset")
                return cur.fetchall()
        finally:
            conn.close()

    def post_exists(self, post_id: str) -> bool:
        """Check if a post already exists in the database."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM social_posts WHERE post_id = %s", (post_id,))
                return cur.fetchone() is not None
        finally:
            conn.close()

    def save_posts(self, posts: List[Dict]) -> int:
        """Save posts to the database."""
        if not posts:
            return 0

        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
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

                self.execute_values(
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
                return cur.rowcount
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()


class TestDatabaseAdapter(MockDatabaseAdapter):
    """Test database adapter using mocks."""

    def __init__(self):
        self.connection = MockDatabaseConnection()
        self.assets = [
            (1, 'Genpact', 'G', ['genpact', 'G']),
            (2, 'Palantir', 'PLTR', ['palantir', 'pltr']),
            (3, 'Snowflake', 'SNOW', ['snowflake', 'snow'])
        ]
        self.posts = []

    def get_connection(self):
        """Get a mock database connection."""
        return self.connection

    def get_assets(self) -> List[Tuple[int, str, str, List[str]]]:
        """Return mock assets."""
        return self.assets

    def post_exists(self, post_id: str) -> bool:
        """Check if post exists in mock storage."""
        return any(p['post_id'] == post_id for p in self.posts)

    def save_posts(self, posts: List[Dict]) -> int:
        """Save posts to mock storage."""
        saved_count = 0
        for post in posts:
            if not self.post_exists(post['post_id']):
                self.posts.append(post)
                saved_count += 1
        return saved_count


@pytest.fixture
def mock_db():
    """Provide a mock database adapter for testing."""
    return TestDatabaseAdapter()


@pytest.fixture
def sample_assets():
    """Provide sample asset data."""
    return [
        (1, 'Genpact', 'G', ['genpact', 'G']),
        (2, 'Palantir', 'PLTR', ['palantir', 'pltr']),
        (3, 'Snowflake', 'SNOW', ['snowflake', 'snow'])
    ]


@pytest.fixture
def sample_posts():
    """Provide sample post data."""
    return [
        {
            'asset_id': 1,
            'source': 'test_source',
            'post_id': 'test_post_1',
            'author': 'Test Author',
            'title': 'Test Post Title',
            'content': 'Test post content',
            'url': 'https://example.com/test',
            'score': 10,
            'created_at': datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        },
        {
            'asset_id': 2,
            'source': 'test_source',
            'post_id': 'test_post_2',
            'author': 'Another Author',
            'title': 'Another Test Post',
            'content': None,
            'url': 'https://example.com/test2',
            'score': 5,
            'created_at': datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        }
    ]


@pytest.fixture
def mock_rss_feed():
    """Provide mock RSS feed data."""
    class MockEntry:
        def __init__(self, title, link, summary, published_parsed):
            self.data = {
                'title': title,
                'link': link,
                'summary': summary,
                'published_parsed': published_parsed,
                'author': 'Test Feed'
            }

        def get(self, key, default=None):
            return self.data.get(key, default)

    class MockFeed:
        def __init__(self):
            self.bozo = False
            self.entries = [
                MockEntry(
                    'Genpact announces new AI initiative',
                    'https://example.com/news1',
                    'Genpact is launching a new AI initiative...',
                    (2025, 1, 1, 12, 0, 0)
                ),
                MockEntry(
                    'Palantir wins government contract',
                    'https://example.com/news2',
                    'Palantir has secured a major government contract...',
                    (2025, 1, 2, 14, 0, 0)
                )
            ]
            self.feed = type('obj', (object,), {'title': 'Test Feed'})()

    return MockFeed()
