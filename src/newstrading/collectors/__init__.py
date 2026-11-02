"""Collectors: one module per data source, one registry to build them."""

from newstrading.collectors.models import Asset, Post
from newstrading.collectors.registry import Collector, CollectorError, CollectorRegistry
from newstrading.collectors.rss import Feed, RSSCollector

__all__ = [
    "Asset",
    "Collector",
    "CollectorError",
    "CollectorRegistry",
    "Feed",
    "Post",
    "RSSCollector",
]
