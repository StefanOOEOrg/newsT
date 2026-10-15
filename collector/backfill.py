"""
Historical Data Backfill Script

Collects historical data for all assets using enabled collectors.
This is useful for:
- Initial setup: Populate database with historical data
- New assets: Backfill data when adding new assets to track
- Data recovery: Re-collect data if needed

Usage:
    python backfill.py [--days DAYS] [--assets ASSET_IDS] [--collectors COLLECTORS]

Examples:
    # Backfill 30 days for all assets with all collectors
    python backfill.py

    # Backfill 7 days
    python backfill.py --days 7

    # Backfill specific assets (by ID)
    python backfill.py --assets 1,2,3

    # Backfill with specific collectors only
    python backfill.py --collectors NewsAPICollector,FinnhubCollector

Note: After backfilling, the analyzer service will automatically process the new posts
on its next scheduled run. To analyze immediately, restart the analyzer container:
    docker-compose restart analyzer
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from dotenv import load_dotenv
import logging

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from logging_config import setup_logging
from collector_factory import get_factory
from config import ENABLED_COLLECTORS, CONSOLE_LOG_LEVEL, DATABASE_LOG_LEVEL, LOG_FORMAT
import psycopg2

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')

logger = logging.getLogger(__name__)


def get_db_connection():
    """Create a database connection."""
    return psycopg2.connect(DATABASE_URL)


def get_all_assets() -> List[Dict]:
    """
    Fetch all assets from database.

    Returns:
        List of asset dictionaries with id, name, ticker, keywords, status
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    name,
                    ticker,
                    search_keywords,
                    initialization_status,
                    initialization_completed_at
                FROM asset
                ORDER BY id
            """)
            rows = cur.fetchall()
            return [
                {
                    'id': row[0],
                    'name': row[1],
                    'ticker': row[2],
                    'keywords': row[3],
                    'status': row[4],
                    'completed_at': row[5]
                }
                for row in rows
            ]
    finally:
        conn.close()


def update_asset_status(asset_id: int, status: str):
    """
    Update asset initialization status.

    Args:
        asset_id: Asset ID to update
        status: New status ('pending', 'in_progress', 'completed', 'failed')
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if status == 'in_progress':
                cur.execute("""
                    UPDATE asset
                    SET initialization_status = %s,
                        initialization_started_at = NOW()
                    WHERE id = %s
                """, (status, asset_id))
            elif status == 'completed':
                cur.execute("""
                    UPDATE asset
                    SET initialization_status = %s,
                        initialization_completed_at = NOW()
                    WHERE id = %s
                """, (status, asset_id))
            else:
                cur.execute("""
                    UPDATE asset
                    SET initialization_status = %s
                    WHERE id = %s
                """, (status, asset_id))
            conn.commit()
    finally:
        conn.close()


def backfill_historical_data(
    days: int = 30,
    asset_ids: List[int] = None,
    collector_names: List[str] = None
) -> Dict:
    """
    Backfill historical data for assets.

    Args:
        days: Number of days to backfill (default 30)
        asset_ids: List of specific asset IDs to backfill (None = all)
        collector_names: List of collector names to use (None = all enabled)

    Returns:
        Dictionary with backfill statistics
    """
    logger.info("=" * 80)
    logger.info("HISTORICAL DATA BACKFILL")
    logger.info("=" * 80)
    logger.info(f"Configuration:")
    logger.info(f"  Days to backfill: {days}")
    logger.info(f"  Asset filter: {asset_ids if asset_ids else 'All assets'}")
    logger.info(f"  Collector filter: {collector_names if collector_names else 'All enabled collectors'}")
    logger.info("=" * 80)

    # Get assets
    all_assets = get_all_assets()
    if asset_ids:
        assets = [a for a in all_assets if a['id'] in asset_ids]
    else:
        assets = all_assets

    if not assets:
        logger.error("No assets found to backfill")
        return {'error': 'No assets found'}

    logger.info(f"Found {len(assets)} asset(s) to backfill:")
    for asset in assets:
        status_str = f"[{asset['status']}]" if asset['status'] else "[new]"
        logger.info(f"  - {asset['name']} ({asset['ticker']}) {status_str}")

    # Initialize collector factory
    factory = get_factory()
    factory.auto_discover()

    # Determine which collectors to use
    collectors_to_use = collector_names if collector_names else ENABLED_COLLECTORS

    logger.info("")
    logger.info(f"Using collectors: {', '.join(collectors_to_use)}")
    logger.info("")

    # Track overall statistics
    overall_stats = {
        'assets_processed': 0,
        'assets_succeeded': 0,
        'assets_failed': 0,
        'total_posts_collected': 0,
        'total_posts_saved': 0,
        'collectors_used': len(collectors_to_use),
        'start_time': datetime.now(),
        'asset_results': []
    }

    # Process each asset
    for asset in assets:
        asset_id = asset['id']
        asset_name = asset['name']
        ticker = asset['ticker']
        keywords = asset['keywords']

        logger.info("-" * 80)
        logger.info(f"Processing: {asset_name} ({ticker}) [Asset ID: {asset_id}]")
        logger.info("-" * 80)

        asset_stats = {
            'asset_id': asset_id,
            'asset_name': asset_name,
            'posts_collected': 0,
            'posts_saved': 0,
            'collectors_succeeded': 0,
            'collectors_failed': 0,
            'collector_results': []
        }

        # Mark as in progress
        update_asset_status(asset_id, 'in_progress')

        asset_success = False

        # Run each collector for this asset
        for collector_name in collectors_to_use:
            try:
                logger.info(f"  Running {collector_name}...")

                # Create collector instance
                collector = factory.create(collector_name, DATABASE_URL)

                if not collector:
                    logger.warning(f"  Could not create {collector_name} - skipping")
                    asset_stats['collectors_failed'] += 1
                    continue

                # Check if collector supports historical collection
                if not hasattr(collector, 'collect_for_asset_historical'):
                    logger.info(f"  {collector_name} does not support historical collection - skipping")
                    continue

                # Collect historical data
                posts = collector.collect_for_asset_historical(
                    asset_id, asset_name, ticker, keywords, days
                )

                # Save posts
                saved = 0
                if posts:
                    saved = collector.save_posts(posts)
                    logger.info(f"  ✓ {collector_name}: Collected {len(posts)} posts ({saved} new)")
                    asset_stats['posts_collected'] += len(posts)
                    asset_stats['posts_saved'] += saved
                    asset_stats['collectors_succeeded'] += 1
                    asset_success = True
                else:
                    logger.info(f"  {collector_name}: No posts found")
                    asset_stats['collectors_succeeded'] += 1

                asset_stats['collector_results'].append({
                    'collector': collector_name,
                    'status': 'success',
                    'posts_collected': len(posts),
                    'posts_saved': saved
                })

            except Exception as e:
                logger.error(f"  ✗ {collector_name}: Error - {e}")
                asset_stats['collectors_failed'] += 1
                asset_stats['collector_results'].append({
                    'collector': collector_name,
                    'status': 'error',
                    'error': str(e)
                })

        # Update asset status
        if asset_success:
            update_asset_status(asset_id, 'completed')
            overall_stats['assets_succeeded'] += 1
            logger.info(f"✓ Asset {asset_name} backfill completed: {asset_stats['posts_saved']} new posts saved")
        else:
            update_asset_status(asset_id, 'failed')
            overall_stats['assets_failed'] += 1
            logger.error(f"✗ Asset {asset_name} backfill failed")

        overall_stats['assets_processed'] += 1
        overall_stats['total_posts_collected'] += asset_stats['posts_collected']
        overall_stats['total_posts_saved'] += asset_stats['posts_saved']
        overall_stats['asset_results'].append(asset_stats)

    # Print summary
    overall_stats['end_time'] = datetime.now()
    duration = (overall_stats['end_time'] - overall_stats['start_time']).total_seconds()

    logger.info("")
    logger.info("=" * 80)
    logger.info("BACKFILL COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Duration: {duration:.1f} seconds")
    logger.info(f"Assets processed: {overall_stats['assets_processed']}")
    logger.info(f"  Succeeded: {overall_stats['assets_succeeded']}")
    logger.info(f"  Failed: {overall_stats['assets_failed']}")
    logger.info(f"Total posts collected: {overall_stats['total_posts_collected']}")
    logger.info(f"Total new posts saved: {overall_stats['total_posts_saved']}")
    logger.info("")

    # Detailed breakdown by asset
    logger.info("Per-Asset Results:")
    for asset_result in overall_stats['asset_results']:
        logger.info(f"  {asset_result['asset_name']}:")
        logger.info(f"    Posts: {asset_result['posts_saved']} saved (out of {asset_result['posts_collected']} collected)")
        logger.info(f"    Collectors: {asset_result['collectors_succeeded']} succeeded, {asset_result['collectors_failed']} failed")

    logger.info("=" * 80)

    # Print next steps if posts were saved
    if overall_stats['total_posts_saved'] > 0:
        logger.info("")
        logger.info("NEXT STEPS:")
        logger.info(f"  {overall_stats['total_posts_saved']} new posts have been saved to the database.")
        logger.info("  The analyzer service will process them on its next scheduled run.")
        logger.info("")
        logger.info("  To analyze immediately, restart the analyzer container:")
        logger.info("    docker-compose restart analyzer")
        logger.info("")

    return overall_stats


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Backfill historical data for assets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backfill 30 days for all assets
  python backfill.py

  # Backfill 7 days
  python backfill.py --days 7

  # Backfill specific assets
  python backfill.py --assets 1,2,3

  # Backfill with specific collectors
  python backfill.py --collectors NewsAPICollector,FinnhubCollector
        """
    )

    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days to backfill (default: 30)'
    )

    parser.add_argument(
        '--assets',
        type=str,
        help='Comma-separated asset IDs to backfill (default: all)'
    )

    parser.add_argument(
        '--collectors',
        type=str,
        help='Comma-separated collector names to use (default: all enabled)'
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(
        service_name='backfill',
        database_url=DATABASE_URL,
        console_level=CONSOLE_LOG_LEVEL,
        database_level=DATABASE_LOG_LEVEL,
        log_format=LOG_FORMAT
    )

    # Validate environment
    if not DATABASE_URL:
        logger.error("Missing DATABASE_URL environment variable")
        sys.exit(1)

    # Parse asset IDs
    asset_ids = None
    if args.assets:
        try:
            asset_ids = [int(x.strip()) for x in args.assets.split(',')]
        except ValueError:
            logger.error("Invalid asset IDs format. Use comma-separated integers (e.g., 1,2,3)")
            sys.exit(1)

    # Parse collector names
    collector_names = None
    if args.collectors:
        collector_names = [x.strip() for x in args.collectors.split(',')]

    # Run backfill
    try:
        stats = backfill_historical_data(
            days=args.days,
            asset_ids=asset_ids,
            collector_names=collector_names
        )

        # Exit with error code if any assets failed
        if stats.get('assets_failed', 0) > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
