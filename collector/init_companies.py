"""
Company Initialization Script
Runs historical data collection for companies pending initialization.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from logging_config import setup_logging

# Load environment variables
load_dotenv()

# Import config
from config import CONSOLE_LOG_LEVEL, DATABASE_LOG_LEVEL, LOG_FORMAT

# Database URL
DATABASE_URL = os.getenv('DATABASE_URL')

# Set up logging
logger = setup_logging(
    service_name='collector_init',
    database_url=DATABASE_URL,
    console_level=CONSOLE_LOG_LEVEL,
    database_level=DATABASE_LOG_LEVEL,
    log_format=LOG_FORMAT
)

# Import collectors
from collector_factory import get_factory
from collectors.base import BaseCollector
import psycopg2


def get_pending_companies():
    """Get list of companies pending initialization."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, ticker, search_keywords, initialization_days
                FROM asset
                WHERE initialization_status = 'pending'
                ORDER BY created_at
            """)
            return cur.fetchall()
    finally:
        conn.close()


def run_initialization():
    """Run initialization for all pending companies."""
    logger.info("Starting company initialization process...")

    # Get factory and discover collectors
    factory = get_factory()
    factory.auto_discover()

    available_collectors = factory.list_available()
    logger.info(f"Available collectors: {', '.join(available_collectors)}")

    # Get pending companies
    pending = get_pending_companies()

    if not pending:
        logger.info("No companies pending initialization")
        return

    logger.info(f"Found {len(pending)} companies pending initialization")

    # Create collectors that support historical data
    # NewsAPI is best for historical (30 days free tier)
    collectors_to_use = []

    if 'newsapi' in available_collectors:
        collector = factory.create('newsapi', DATABASE_URL)
        if collector:
            collectors_to_use.append(collector)
            logger.info("Using NewsAPI collector for historical data")

    if not collectors_to_use:
        logger.warning("No collectors with historical support available")
        return

    # Initialize each company
    for company_id, name, ticker, keywords, days in pending:
        logger.info(f"Initializing company: {name} ({ticker}) - {days} days")

        for collector in collectors_to_use:
            try:
                result = collector.initialize_company(company_id, days or 30)
                logger.info(f"{collector.name}: Initialized {name} - {result['total_saved']} posts saved")
            except Exception as e:
                logger.error(f"{collector.name}: Failed to initialize {name}: {e}")

    logger.info("Company initialization process complete")


if __name__ == "__main__":
    try:
        run_initialization()
    except Exception as e:
        logger.error(f"Initialization process failed: {e}")
        sys.exit(1)
