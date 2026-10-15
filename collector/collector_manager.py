"""
Collector Manager - orchestrates multiple collectors.
"""
import logging
from typing import List, Dict
from collector_factory import get_factory

logger = logging.getLogger(__name__)


class CollectorManager:
    """Manages multiple collectors and coordinates data collection."""

    def __init__(self, database_url: str, enabled_collectors: List[str]):
        """
        Initialize the collector manager.

        Args:
            database_url: PostgreSQL connection string
            enabled_collectors: List of collector names to enable (e.g., ['rss', 'newsapi'])
        """
        self.database_url = database_url

        # Get the factory and create collectors
        factory = get_factory()
        self.collectors = factory.create_all(database_url, enabled_collectors)

        if not self.collectors:
            logger.warning("No collectors were successfully initialized!")
        else:
            collector_names = [c.name for c in self.collectors]
            logger.info(f"Initialized {len(self.collectors)} collector(s): {', '.join(collector_names)}")

    def collect_all(self) -> Dict[str, Dict[str, int]]:
        """
        Run all enabled collectors.

        Returns:
            Dictionary mapping collector names to their statistics
        """
        logger.info(f"Starting collection with {len(self.collectors)} collector(s)")

        results = {}

        for collector in self.collectors:
            try:
                logger.info(f"Running {collector.name}...")
                stats = collector.collect_all()
                results[collector.name] = stats
                logger.info(
                    f"{collector.name} complete: "
                    f"{stats['total_posts']} posts ({stats['total_saved']} new)"
                )
            except Exception as e:
                logger.error(f"Error running {collector.name}: {e}")
                results[collector.name] = {'error': str(e)}
                continue

        # Summary
        total_posts = sum(r.get('total_posts', 0) for r in results.values())
        total_saved = sum(r.get('total_saved', 0) for r in results.values())

        logger.info(f"Collection complete! Total: {total_posts} posts ({total_saved} new)")

        return results

    def get_collector_info(self) -> List[Dict[str, str]]:
        """
        Get information about all registered collectors.

        Returns:
            List of dictionaries with collector info
        """
        return [
            {
                'name': collector.name,
                'class': collector.__class__.__name__,
                'type': collector.get_collector_name()
            }
            for collector in self.collectors
        ]
