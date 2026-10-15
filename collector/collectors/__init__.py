"""
Collector modules for fetching news from different sources.
"""
from .base import BaseCollector
from .rss_collector import RSSCollector

# Optional collectors - comment out if API keys not available
try:
    from .newsapi_collector import NewsAPICollector
except (ImportError, ValueError):
    NewsAPICollector = None

try:
    from .finnhub_collector import FinnhubCollector
except (ImportError, ValueError):
    FinnhubCollector = None

try:
    from .alphavantage_collector import AlphaVantageCollector
except (ImportError, ValueError):
    AlphaVantageCollector = None

__all__ = [
    'BaseCollector',
    'RSSCollector',
    'NewsAPICollector',
    'FinnhubCollector',
    'AlphaVantageCollector'
]
