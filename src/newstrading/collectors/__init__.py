"""Collectors: one module per data source, one registry to build them."""

from newstrading.collectors.models import Asset, Post
from newstrading.collectors.registry import Collector, CollectorError, CollectorRegistry

__all__ = ["Asset", "Collector", "CollectorError", "CollectorRegistry", "Post"]
