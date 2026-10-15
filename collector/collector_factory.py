"""
Collector Factory - provides centralized collector instantiation and discovery.
"""
import logging
from typing import Dict, List, Type, Optional
from collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class CollectorFactory:
    """
    Factory for creating and managing collector instances.

    Provides:
    - Centralized collector registration
    - Auto-discovery of available collectors
    - Safe instantiation with error handling
    - Collector availability checking
    """

    def __init__(self):
        """Initialize the factory with an empty registry."""
        self._registry: Dict[str, Type[BaseCollector]] = {}

    def register(self, name: str, collector_class: Type[BaseCollector]) -> None:
        """
        Register a collector class with the factory.

        Args:
            name: Unique identifier for the collector (e.g., 'rss', 'newsapi')
            collector_class: The collector class to register
        """
        if not issubclass(collector_class, BaseCollector):
            raise ValueError(f"{collector_class.__name__} must inherit from BaseCollector")

        self._registry[name] = collector_class
        logger.debug(f"Registered collector: {name} -> {collector_class.__name__}")

    def create(self, name: str, database_url: str) -> Optional[BaseCollector]:
        """
        Create a collector instance by name.

        Args:
            name: Name of the collector to create
            database_url: Database connection string

        Returns:
            Collector instance or None if creation fails
        """
        if name not in self._registry:
            logger.error(f"Collector '{name}' not registered")
            return None

        collector_class = self._registry[name]

        try:
            collector = collector_class(database_url)
            logger.info(f"Created collector: {name} ({collector_class.__name__})")
            return collector
        except Exception as e:
            logger.error(f"Failed to create {name} collector: {e}")
            return None

    def create_all(self, database_url: str, enabled_names: List[str]) -> List[BaseCollector]:
        """
        Create multiple collectors by name.

        Args:
            database_url: Database connection string
            enabled_names: List of collector names to create

        Returns:
            List of successfully created collector instances
        """
        collectors = []

        for name in enabled_names:
            collector = self.create(name, database_url)
            if collector:
                collectors.append(collector)

        logger.info(f"Created {len(collectors)}/{len(enabled_names)} collectors")
        return collectors

    def is_available(self, name: str) -> bool:
        """
        Check if a collector is registered and available.

        Args:
            name: Name of the collector

        Returns:
            True if collector is registered, False otherwise
        """
        return name in self._registry

    def list_available(self) -> List[str]:
        """
        Get list of all registered collector names.

        Returns:
            List of collector names
        """
        return list(self._registry.keys())

    def auto_discover(self) -> None:
        """
        Auto-discover and register all available collectors.

        Attempts to import and register:
        - RSSCollector (always available)
        - NewsAPICollector (requires NEWSAPI_KEY)
        - FinnhubCollector (requires FINNHUB_API_KEY)
        - AlphaVantageCollector (requires ALPHAVANTAGE_API_KEY)
        - StockPriceCollector (always available, uses yfinance)
        - CongressionalTradesCollector (free public data sources)
        - RedditCollector (template/future use)
        - TwitterCollector (template/future use)
        """
        # Always available collectors
        try:
            from collectors.rss_collector import RSSCollector
            self.register('rss', RSSCollector)
        except ImportError as e:
            logger.error(f"Failed to import RSSCollector: {e}")

        try:
            from collectors.stock_price_collector import StockPriceCollector
            self.register('stock_price', StockPriceCollector)
        except ImportError as e:
            logger.error(f"Failed to import StockPriceCollector: {e}")

        # Optional API-based collectors
        try:
            from collectors.newsapi_collector import NewsAPICollector
            self.register('newsapi', NewsAPICollector)
        except (ImportError, ValueError) as e:
            logger.debug(f"NewsAPICollector not available: {e}")

        try:
            from collectors.finnhub_collector import FinnhubCollector
            self.register('finnhub', FinnhubCollector)
        except (ImportError, ValueError) as e:
            logger.debug(f"FinnhubCollector not available: {e}")

        try:
            from collectors.alphavantage_collector import AlphaVantageCollector
            self.register('alphavantage', AlphaVantageCollector)
        except (ImportError, ValueError) as e:
            logger.debug(f"AlphaVantageCollector not available: {e}")

        # Government data collectors
        try:
            from collectors.congressional_trades_collector import CongressionalTradesCollector
            self.register('congressional_trades', CongressionalTradesCollector)
        except (ImportError, ValueError) as e:
            logger.debug(f"CongressionalTradesCollector not available: {e}")

        # Template collectors (future use)
        try:
            from collectors.reddit_collector import RedditCollector
            self.register('reddit', RedditCollector)
        except (ImportError, ValueError) as e:
            logger.debug(f"RedditCollector not available: {e}")

        try:
            from collectors.twitter_collector import TwitterCollector
            self.register('twitter', TwitterCollector)
        except (ImportError, ValueError) as e:
            logger.debug(f"TwitterCollector not available: {e}")

        logger.info(f"Auto-discovery complete. Available collectors: {', '.join(self.list_available())}")


# Global factory instance
_factory = CollectorFactory()


def get_factory() -> CollectorFactory:
    """
    Get the global collector factory instance.

    Returns:
        The global CollectorFactory instance
    """
    return _factory
