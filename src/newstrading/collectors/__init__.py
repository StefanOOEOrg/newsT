"""Collectors: one module per data source, one registry to build them."""

from newstrading.collectors.alphavantage import AlphaVantageCollector
from newstrading.collectors.congress import CongressionalTradesCollector
from newstrading.collectors.events import Event, EventCollector, EventStore
from newstrading.collectors.finnhub import FinnhubCollector
from newstrading.collectors.models import Asset, Post
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.collectors.registry import Collector, CollectorError, CollectorRegistry
from newstrading.collectors.rss import Feed, RSSCollector

__all__ = [
    "AlphaVantageCollector",
    "Asset",
    "Collector",
    "CollectorError",
    "CollectorRegistry",
    "CongressionalTradesCollector",
    "Event",
    "EventCollector",
    "EventStore",
    "Feed",
    "FinnhubCollector",
    "NewsAPICollector",
    "Post",
    "RSSCollector",
]
