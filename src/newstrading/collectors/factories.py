"""The registry the CLI builds: every source name this package implements.

Registration only stores factories. A missing API key is not swallowed here; it fails in
:meth:`~newstrading.collectors.registry.CollectorRegistry.create`, so the CLI reports a
configuration error instead of silently collecting from fewer sources than configured.
"""

from __future__ import annotations

from newstrading.collectors.alphavantage import AlphaVantageCollector
from newstrading.collectors.congress import CongressionalTradesCollector
from newstrading.collectors.finnhub import FinnhubCollector
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.collectors.registry import CollectorRegistry
from newstrading.collectors.rss import RSSCollector
from newstrading.config import Settings

SOURCE_NAMES: tuple[str, ...] = (
    "rss",
    "newsapi",
    "finnhub",
    "alphavantage",
    "congressional_trades",
)


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
    registry.register("rss", lambda _settings: RSSCollector())
    registry.register("newsapi", lambda settings: NewsAPICollector(settings))
    registry.register("finnhub", lambda settings: FinnhubCollector(settings))
    registry.register("alphavantage", lambda settings: AlphaVantageCollector(settings))
    registry.register(
        "congressional_trades", lambda settings: CongressionalTradesCollector(settings)
    )
    return registry
