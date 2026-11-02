"""The registry the CLI builds: every source name this package implements.

Registration only stores factories. A missing API key is not swallowed here; it fails in
:meth:`~newstrading.collectors.registry.CollectorRegistry.create`, so the CLI reports a
configuration error instead of silently collecting from fewer sources than configured.
"""

from __future__ import annotations

from collections.abc import Callable

from newstrading.collectors.alphavantage import AlphaVantageCollector
from newstrading.collectors.congress import CongressionalTradesCollector
from newstrading.collectors.finnhub import FinnhubCollector
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.collectors.registry import Collector, CollectorRegistry, Factory
from newstrading.collectors.rss import RSSCollector
from newstrading.config import Settings
from newstrading.rate_limiter import RateLimiter

SOURCE_NAMES: tuple[str, ...] = (
    "rss",
    "newsapi",
    "finnhub",
    "alphavantage",
    "congressional_trades",
)


def _limited(collector_class: Callable[..., Collector], name: str) -> Factory:
    """Return a factory that gives every collector it builds its own limiter for ``name``."""
    return lambda settings: collector_class(settings, limiter=RateLimiter(settings, name))


def build_registry(settings: Settings) -> CollectorRegistry:
    """Register every collector of the package under its source name.

    Args:
        settings: Settings handed to every factory when a collector is created.

    Returns:
        A registry with ``rss``, ``newsapi``, ``finnhub``, ``alphavantage`` and
        ``congressional_trades``.

    Contract:
        * Registering builds nothing, so it never needs an API key.
        * ``rss`` and ``congressional_trades`` build without a key.
    """
    registry = CollectorRegistry()
    # rss has no API key and no hard quota, so a quota check would only add noise.
    registry.register("rss", lambda _settings: RSSCollector())
    registry.register("newsapi", _limited(NewsAPICollector, "newsapi"))
    registry.register("finnhub", _limited(FinnhubCollector, "finnhub"))
    registry.register("alphavantage", _limited(AlphaVantageCollector, "alphavantage"))
    registry.register(
        "congressional_trades", _limited(CongressionalTradesCollector, "congressional_trades")
    )
    return registry
