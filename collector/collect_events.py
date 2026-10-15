"""
Event Collection Script

Collects financial calendar events (earnings, filings, etc.) for all tracked assets.
This script is designed to be run periodically (e.g., daily or weekly) to keep the
event calendar up to date.

Usage:
    python collect_events.py [--collectors COLLECTORS]

Examples:
    # Collect events from all available collectors
    python collect_events.py

    # Collect only from specific collectors
    python collect_events.py --collectors AlphaVantageEventsCollector

Note: Event collectors have their own rate limits:
    - Alpha Vantage: 25 calls/day (free tier)
    - Yahoo Finance: No official API (web scraping - use carefully)
    - SEC EDGAR: No rate limit for reasonable use
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import logging

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from logging_config import setup_logging

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')
CONSOLE_LOG_LEVEL = os.getenv('CONSOLE_LOG_LEVEL', 'INFO')
DATABASE_LOG_LEVEL = os.getenv('DATABASE_LOG_LEVEL', 'WARNING')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

logger = logging.getLogger(__name__)

# Available event collectors
AVAILABLE_COLLECTORS = [
    'AlphaVantageEventsCollector',
]


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Collect financial calendar events for tracked assets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect events from all collectors
  python collect_events.py

  # Collect only from Alpha Vantage
  python collect_events.py --collectors AlphaVantageEventsCollector

Note: Collectors have rate limits. Alpha Vantage free tier: 25 calls/day.
        """
    )

    parser.add_argument(
        '--collectors',
        type=str,
        help='Comma-separated collector names to use (default: all available)'
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(
        service_name='event_collector',
        database_url=DATABASE_URL,
        console_level=CONSOLE_LOG_LEVEL,
        database_level=DATABASE_LOG_LEVEL,
        log_format=LOG_FORMAT
    )

    logger.info("=" * 80)
    logger.info("EVENT COLLECTION")
    logger.info("=" * 80)

    # Validate environment
    if not DATABASE_URL:
        logger.error("Missing DATABASE_URL environment variable")
        sys.exit(1)

    # Parse collector names
    collector_names = AVAILABLE_COLLECTORS
    if args.collectors:
        collector_names = [x.strip() for x in args.collectors.split(',')]
        # Validate collector names
        invalid = [c for c in collector_names if c not in AVAILABLE_COLLECTORS]
        if invalid:
            logger.error(f"Invalid collector(s): {', '.join(invalid)}")
            logger.error(f"Available: {', '.join(AVAILABLE_COLLECTORS)}")
            sys.exit(1)

    logger.info(f"Using collectors: {', '.join(collector_names)}")
    logger.info("")

    # Track overall statistics
    overall_stats = {
        'collectors_run': 0,
        'collectors_succeeded': 0,
        'collectors_failed': 0,
        'total_events_collected': 0,
        'total_events_saved': 0,
        'start_time': datetime.now()
    }

    # Run each collector
    for collector_name in collector_names:
        logger.info("-" * 80)
        logger.info(f"Running {collector_name}...")
        logger.info("-" * 80)

        try:
            # Import collector dynamically
            from collectors.alphavantage_events import AlphaVantageEventsCollector

            # Map collector names to classes
            collector_map = {
                'AlphaVantageEventsCollector': AlphaVantageEventsCollector,
            }

            collector_class = collector_map.get(collector_name)
            if not collector_class:
                logger.error(f"Collector {collector_name} not found in mapping")
                overall_stats['collectors_failed'] += 1
                continue

            # Create collector instance
            collector = collector_class(DATABASE_URL)

            # Collect events
            stats = collector.collect_all_events()

            # Update overall statistics
            overall_stats['collectors_run'] += 1
            overall_stats['collectors_succeeded'] += 1
            overall_stats['total_events_collected'] += stats['total_events']
            overall_stats['total_events_saved'] += stats['total_saved']

            logger.info(f"✓ {collector_name}: {stats['total_saved']} new events (out of {stats['total_events']} collected)")

        except Exception as e:
            logger.error(f"✗ {collector_name}: Error - {e}")
            overall_stats['collectors_run'] += 1
            overall_stats['collectors_failed'] += 1

    # Print summary
    overall_stats['end_time'] = datetime.now()
    duration = (overall_stats['end_time'] - overall_stats['start_time']).total_seconds()

    logger.info("")
    logger.info("=" * 80)
    logger.info("EVENT COLLECTION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Duration: {duration:.1f} seconds")
    logger.info(f"Collectors run: {overall_stats['collectors_run']}")
    logger.info(f"  Succeeded: {overall_stats['collectors_succeeded']}")
    logger.info(f"  Failed: {overall_stats['collectors_failed']}")
    logger.info(f"Total events collected: {overall_stats['total_events_collected']}")
    logger.info(f"Total new events saved: {overall_stats['total_events_saved']}")
    logger.info("=" * 80)

    # Exit with error code if any collectors failed
    if overall_stats['collectors_failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
