"""
One-time script to analyze all unanalyzed posts.
Useful after historical data collection.
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

DATABASE_URL = os.getenv('DATABASE_URL')

# Set up logging
logger = setup_logging(
    service_name='analyzer_batch',
    database_url=DATABASE_URL,
    console_level=CONSOLE_LOG_LEVEL,
    database_level=DATABASE_LOG_LEVEL,
    log_format=LOG_FORMAT
)

# Import main analyzer
from main import AIAnalyzer

def main():
    """Run analysis on all unanalyzed posts."""
    analyzer = AIAnalyzer()

    total_processed = 0
    batch_num = 1

    while True:
        logger.info(f"Running batch {batch_num}...")
        processed = analyzer.process_posts()
        total_processed += processed

        if processed == 0:
            logger.info(f"All posts analyzed! Total: {total_processed}")
            break

        logger.info(f"Batch {batch_num} complete: {processed} posts processed")
        batch_num += 1

    return total_processed

if __name__ == "__main__":
    try:
        total = main()
        print(f"\n✓ Analysis complete! Processed {total} posts total")
    except Exception as e:
        logger.error(f"Batch analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
