"""Collectors: one module per data source, one registry to build them."""

from newstrading.collectors.alphavantage import AlphaVantageCollector
from newstrading.collectors.finnhub import FinnhubCollector
from newstrading.collectors.models import Asset, Post
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.collectors.registry import Collector, CollectorError, CollectorRegistry

__all__ = [
    "AlphaVantageCollector",
    "Asset",
    "Collector",
    "CollectorError",
    "CollectorRegistry",
    "FinnhubCollector",
    "NewsAPICollector",
    "Post",
]
