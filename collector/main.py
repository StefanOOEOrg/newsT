"""
News Collector Service
Orchestrates multiple collectors to fetch news from various sources.
"""
import os
import sys
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from logging_config import setup_logging
from collector_manager import CollectorManager
from collector_factory import get_factory
from config import (
    ENABLED_COLLECTORS,
    CONSOLE_LOG_LEVEL,
    DATABASE_LOG_LEVEL,
    LOG_FORMAT,
    STOCK_PRICE_UPDATE_INTERVAL_MINUTES
)
from market_hours import MarketHoursScheduler

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')


def main():
    """Main entry point."""
    # Set up logging
    logger = setup_logging(
        service_name='collector',
        database_url=DATABASE_URL,
        console_level=CONSOLE_LOG_LEVEL,
        database_level=DATABASE_LOG_LEVEL,
        log_format=LOG_FORMAT
    )

    logger.info("=" * 60)
    logger.info("Starting News Collector Service")
    logger.info("=" * 60)
    logger.info(f"Logging configured: Console={CONSOLE_LOG_LEVEL}, Database={DATABASE_LOG_LEVEL}")

    # Validate environment
    if not DATABASE_URL:
        logger.error("Missing DATABASE_URL environment variable")
        return

    # Initialize market hours scheduler
    market_scheduler = MarketHoursScheduler(DATABASE_URL)
    logger.info("-" * 60)
    logger.info("Collection Schedule:")
    logger.info(market_scheduler.get_schedule_description())
    logger.info("-" * 60)

    # Auto-discover available collectors
    factory = get_factory()
    factory.auto_discover()

    logger.info(f"Available collectors: {', '.join(factory.list_available())}")
    logger.info(f"Enabled collectors: {', '.join(ENABLED_COLLECTORS)}")

    # Separate stock_price collector from news collectors for different scheduling
    news_collectors = [c for c in ENABLED_COLLECTORS if c != 'stock_price']
    has_stock_price = 'stock_price' in ENABLED_COLLECTORS

    # Initialize news collector manager
    manager = CollectorManager(DATABASE_URL, news_collectors)

    # Show collector info
    collector_info = manager.get_collector_info()
    if collector_info:
        logger.info("Registered news collectors:")
        for info in collector_info:
            logger.info(f"  - {info['name']} ({info['type']})")
    else:
        logger.warning("No news collectors registered.")

    # Initialize stock price collector separately if enabled
    stock_price_collector = None
    if has_stock_price:
        try:
            stock_price_collector = factory.create('stock_price', DATABASE_URL)
            if stock_price_collector:
                logger.info(f"Registered stock price collector (updates every {STOCK_PRICE_UPDATE_INTERVAL_MINUTES} min)")
        except Exception as e:
            logger.error(f"Failed to initialize stock price collector: {e}")

    # Run immediately on startup
    logger.info("Running initial collection...")
    try:
        results = manager.collect_all()

        # Log results summary
        logger.info("-" * 60)
        logger.info("News Collection Results:")
        for collector_name, stats in results.items():
            if 'error' in stats:
                logger.error(f"  {collector_name}: ERROR - {stats['error']}")
            else:
                logger.info(
                    f"  {collector_name}: "
                    f"{stats['total_posts']} posts ({stats['total_saved']} new)"
                )
        logger.info("-" * 60)

        # Run initial stock price collection
        if stock_price_collector:
            logger.info("Running initial stock price collection...")
            try:
                total_prices, new_prices = stock_price_collector.collect()
                logger.info(f"Stock prices: {total_prices} fetched ({new_prices} new)")
            except Exception as e:
                logger.error(f"Stock price collection failed: {e}")

    except Exception as e:
        logger.error(f"Initial collection failed: {e}")

    # Set up smart scheduling with dynamic interval
    from datetime import datetime, timedelta
    scheduler = BlockingScheduler()

    # Track current interval
    current_interval = [market_scheduler.get_current_interval()]  # Use list to modify in nested function

    # Create dynamic job that checks interval on each run
    def collect_with_smart_scheduling():
        """Wrapper that runs collection and updates scheduling."""
        try:
            # Run collection
            results = manager.collect_all()

            # Log results
            logger.info("-" * 60)
            logger.info("Collection Results:")
            for collector_name, stats in results.items():
                if 'error' in stats:
                    logger.error(f"  {collector_name}: ERROR - {stats['error']}")
                else:
                    logger.info(
                        f"  {collector_name}: "
                        f"{stats['total_posts']} posts ({stats['total_saved']} new)"
                    )

            # Reload settings and check if interval changed
            market_scheduler._load_settings()
            new_interval = market_scheduler.get_current_interval()

            if new_interval != current_interval[0]:
                # Interval changed - reschedule the job
                logger.info(f"Interval changed from {current_interval[0]} to {new_interval} minutes")
                logger.info("Rescheduling job...")

                # Update current interval
                current_interval[0] = new_interval

                # Remove old job
                scheduler.remove_job('collection_job')

                # Add new job with updated interval
                next_run = datetime.now() + timedelta(minutes=new_interval)
                scheduler.add_job(
                    collect_with_smart_scheduling,
                    IntervalTrigger(minutes=new_interval),
                    id='collection_job',
                    next_run_time=next_run,
                    replace_existing=True
                )

                logger.info(f"Next run at: {next_run}")
                logger.info(market_scheduler.get_schedule_description())

            logger.info("-" * 60)

        except Exception as e:
            logger.error(f"Collection failed: {e}")

    # Schedule first job
    next_run = datetime.now() + timedelta(minutes=current_interval[0])

    scheduler.add_job(
        collect_with_smart_scheduling,
        IntervalTrigger(minutes=current_interval[0]),
        id='collection_job',
        next_run_time=next_run
    )

    logger.info(f"News collector scheduler started with {current_interval[0]}-minute interval")
    logger.info(f"Next run at: {next_run}")

    # Add stock price collection job with separate fixed interval
    if stock_price_collector:
        def collect_stock_prices():
            """Wrapper for stock price collection."""
            try:
                logger.info("Running stock price collection...")
                total_prices, new_prices = stock_price_collector.collect()
                logger.info(f"Stock prices: {total_prices} fetched ({new_prices} new)")
            except Exception as e:
                logger.error(f"Stock price collection failed: {e}")

        stock_next_run = datetime.now() + timedelta(minutes=STOCK_PRICE_UPDATE_INTERVAL_MINUTES)

        scheduler.add_job(
            collect_stock_prices,
            IntervalTrigger(minutes=STOCK_PRICE_UPDATE_INTERVAL_MINUTES),
            id='stock_price_job',
            next_run_time=stock_next_run
        )

        logger.info(f"Stock price collector started with {STOCK_PRICE_UPDATE_INTERVAL_MINUTES}-minute interval")
        logger.info(f"Next stock price update at: {stock_next_run}")

    logger.info("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Collector service stopped")


if __name__ == "__main__":
    main()
