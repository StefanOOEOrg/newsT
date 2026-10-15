"""
AI Analyzer Service
Uses Claude API to analyze social media posts and extract trading signals.
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from apscheduler.schedulers.blocking import BlockingScheduler
from anthropic import Anthropic
from dotenv import load_dotenv

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

from logging_config import setup_logging
from analysis_helpers import PromptBuilder, ResponseParser, AlertGenerator

# Load environment variables
load_dotenv()

# Import config
from config import (
    CONSOLE_LOG_LEVEL, DATABASE_LOG_LEVEL, LOG_FORMAT,
    AI_MODEL, MAX_TOKENS,
    BATCH_SIZE, BATCH_SLEEP_SECONDS,
    ANALYSIS_INTERVAL_MINUTES
)

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Module logger (will be configured in main())
import logging
logger = logging.getLogger(__name__)


class AIAnalyzer:
    """Analyzes social media posts using Claude AI."""

    def __init__(self, database_url: str, anthropic_client: Optional[Anthropic] = None):
        """
        Initialize analyzer with dependency injection.

        Args:
            database_url: PostgreSQL connection string
            anthropic_client: Optional Anthropic client (for testing with mocks)
        """
        self.database_url = database_url
        self.client = anthropic_client or Anthropic(api_key=ANTHROPIC_API_KEY)
        self.prompt_builder = PromptBuilder(database_url)
        self.alert_generator = AlertGenerator(database_url)
        logger.info("Claude AI client initialized")

    def get_db_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.database_url)

    def get_unanalyzed_posts(self, limit: int = BATCH_SIZE) -> List[Dict]:
        """Fetch posts that haven't been analyzed yet."""
        conn = self.get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT sp.id, sp.asset_id, sp.title, sp.content, sp.source, sp.url,
                           c.name as asset_name, c.ticker
                    FROM social_posts sp
                    JOIN asset c ON sp.asset_id = c.id
                    LEFT JOIN ai_analysis aa ON sp.id = aa.post_id
                    WHERE aa.id IS NULL
                    ORDER BY sp.created_at DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        finally:
            conn.close()

    def analyze_post(self, post: Dict) -> Optional[Dict]:
        """Analyze a single post using Claude AI with retry logic."""
        import time
        from anthropic import RateLimitError, InternalServerError, APITimeoutError, APIConnectionError

        max_retries = 3
        base_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Build prompt using PromptBuilder
                prompt = self.prompt_builder.build_analysis_prompt(post)

                # Call Claude API with prefilling to enforce TOON format
                # Prefilling forces Claude to continue in TOON format instead of JSON
                message = self.client.messages.create(
                    model=AI_MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": "sentiment:"}
                    ]
                )

                # Parse and validate response using ResponseParser
                if not message.content or len(message.content) == 0:
                    logger.warning(
                        f"Empty content in API response for post {post['id']} "
                        f"(title: '{post['title'][:60]}...'). "
                        f"This may be due to content moderation filters. Marking as unanalyzable."
                    )
                    # Save a neutral analysis to prevent retrying
                    return {
                        'post_id': post['id'],
                        'asset_id': post['asset_id'],
                        'sentiment': 'neutral',
                        'sentiment_score': 0.0,
                        'category': 'Other',
                        'key_topics': ['Content moderation filtered'],
                        'summary': 'Content could not be analyzed due to API content filters.',
                        'special_events': []
                    }

                # Prepend the prefilled text to the response (Claude continues from "sentiment:")
                response_text = "sentiment:" + message.content[0].text
                analysis = ResponseParser.parse_analysis_response(response_text, post)

                return analysis

            except (RateLimitError, InternalServerError, APITimeoutError, APIConnectionError) as e:
                # Retryable errors: 529 overloaded, rate limits, timeouts, connection errors
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff: 2s, 4s, 8s
                    logger.warning(
                        f"Retryable error for post {post['id']} (attempt {attempt + 1}/{max_retries}): "
                        f"{type(e).__name__}: {e}. Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Failed to analyze post {post['id']} after {max_retries} attempts: "
                        f"{type(e).__name__}: {e}"
                    )
                    return None

            except Exception as e:
                # Non-retryable errors (parsing errors, etc.)
                logger.error(f"Error analyzing post {post['id']}: {type(e).__name__}: {e}")
                return None

        return None

    def save_analysis(self, analysis: Dict):
        """Save analysis results to database."""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ai_analysis
                    (post_id, sentiment, sentiment_score, category, key_topics, summary, special_events)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    analysis['post_id'],
                    analysis['sentiment'],
                    analysis['sentiment_score'],
                    analysis['category'],
                    analysis['key_topics'],
                    analysis['summary'],
                    analysis.get('special_events', [])
                ))
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving analysis: {e}")
            raise
        finally:
            conn.close()

    def update_daily_metrics(self):
        """Aggregate daily metrics for all assets for ALL dates with analyzed posts."""
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                # Get all assets
                cur.execute("SELECT id FROM asset")
                asset_ids = [row[0] for row in cur.fetchall()]

                for asset_id in asset_ids:
                    # Calculate metrics for ALL dates (not just today)
                    # This aggregates historical data as well
                    cur.execute("""
                        INSERT INTO daily_metrics
                        (asset_id, date, mention_count, sentiment_avg,
                         hiring_mentions, problem_mentions, growth_mentions)
                        SELECT
                            sp.asset_id,
                            DATE(sp.created_at) as post_date,
                            COUNT(*),
                            AVG(aa.sentiment_score),
                            SUM(CASE WHEN aa.category = 'Hiring' THEN 1 ELSE 0 END),
                            SUM(CASE WHEN aa.category = 'Problems' THEN 1 ELSE 0 END),
                            SUM(CASE WHEN aa.category = 'Growth' THEN 1 ELSE 0 END)
                        FROM social_posts sp
                        JOIN ai_analysis aa ON sp.id = aa.post_id
                        WHERE sp.asset_id = %s
                        GROUP BY sp.asset_id, DATE(sp.created_at)
                        ON CONFLICT (asset_id, date)
                        DO UPDATE SET
                            mention_count = EXCLUDED.mention_count,
                            sentiment_avg = EXCLUDED.sentiment_avg,
                            hiring_mentions = EXCLUDED.hiring_mentions,
                            problem_mentions = EXCLUDED.problem_mentions,
                            growth_mentions = EXCLUDED.growth_mentions
                    """, (asset_id,))

                conn.commit()
                logger.info("Daily metrics updated for all dates")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating daily metrics: {e}")
        finally:
            conn.close()

    def generate_alerts(self, analysis: Dict):
        """Generate alerts based on analysis results using AlertGenerator."""
        self.alert_generator.generate_alerts(analysis)

    def process_posts(self):
        """Main processing function - analyze unanalyzed posts."""
        logger.info("Starting post analysis...")

        try:
            posts = self.get_unanalyzed_posts()

            if not posts:
                logger.info("No unanalyzed posts found")
                return 0

            logger.info(f"Found {len(posts)} posts to analyze")

            analyzed_count = 0
            for post in posts:
                logger.info(f"Analyzing post {post['id']}: {post['title'][:50]}...")

                analysis = self.analyze_post(post)

                if analysis:
                    self.save_analysis(analysis)
                    self.generate_alerts(analysis)
                    analyzed_count += 1
                    logger.info(f"Analysis saved: {analysis['sentiment']} ({analysis['sentiment_score']:.2f})")

            # Update daily metrics after processing
            if analyzed_count > 0:
                self.update_daily_metrics()

            logger.info(f"Analysis complete. Processed {analyzed_count}/{len(posts)} posts")
            return analyzed_count

        except Exception as e:
            logger.error(f"Error in process_posts: {e}")
            raise

    def process_all_pending(self):
        """Process all pending posts in batches with rate limiting."""
        import time

        logger.info("Starting batch processing of all pending posts...")

        total_processed = 0
        batch_num = 1

        while True:
            logger.info(f"Processing batch {batch_num}...")

            try:
                processed = self.process_posts()

                if processed == 0:
                    logger.info(f"All posts processed! Total: {total_processed}")
                    break

                total_processed += processed
                logger.info(f"Batch {batch_num} complete: {processed} posts processed. Total: {total_processed}")

                # Check if there are more posts to process
                conn = self.get_db_connection()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT COUNT(*) as count
                            FROM social_posts sp
                            LEFT JOIN ai_analysis aa ON sp.id = aa.post_id
                            WHERE aa.id IS NULL
                        """)
                        remaining = cur.fetchone()['count']
                finally:
                    conn.close()

                if remaining == 0:
                    logger.info(f"All posts processed! Total: {total_processed}")
                    break

                logger.info(f"Remaining posts: {remaining}. Waiting {BATCH_SLEEP_SECONDS}s before next batch...")
                time.sleep(BATCH_SLEEP_SECONDS)
                batch_num += 1

            except Exception as e:
                logger.error(f"Error in batch {batch_num}: {e}")
                break

        return total_processed


def main():
    """Main entry point."""
    # Set up logging
    logger = setup_logging(
        service_name='analyzer',
        database_url=DATABASE_URL,
        console_level=CONSOLE_LOG_LEVEL,
        database_level=DATABASE_LOG_LEVEL,
        log_format=LOG_FORMAT
    )

    logger.info("Starting AI Analyzer Service")
    logger.info(f"Logging configured: Console={CONSOLE_LOG_LEVEL}, Database={DATABASE_LOG_LEVEL}")

    # Validate environment variables
    if not all([DATABASE_URL, ANTHROPIC_API_KEY]):
        logger.error("Missing required environment variables")
        return

    analyzer = AIAnalyzer(database_url=DATABASE_URL)

    # Initialize performance tracker
    from performance_tracker import PerformanceTracker
    performance_tracker = PerformanceTracker(database_url=DATABASE_URL)

    # Run immediately on startup - process ALL pending posts
    logger.info("Running initial analysis...")
    try:
        analyzer.process_all_pending()
    except Exception as e:
        logger.error(f"Initial analysis failed: {e}")

    # Run initial performance tracking
    logger.info("Running initial performance tracking...")
    try:
        performance_tracker.run_full_update()
    except Exception as e:
        logger.error(f"Initial performance tracking failed: {e}")

    # Schedule regular analysis (processes all pending in batches)
    from datetime import timedelta
    scheduler = BlockingScheduler()

    # Calculate next run time
    next_run = datetime.now() + timedelta(minutes=ANALYSIS_INTERVAL_MINUTES)

    scheduler.add_job(
        analyzer.process_all_pending,
        'interval',
        minutes=ANALYSIS_INTERVAL_MINUTES,
        next_run_time=next_run
    )

    # Schedule daily performance tracking (runs once per day)
    perf_next_run = datetime.now() + timedelta(hours=24)
    scheduler.add_job(
        performance_tracker.run_full_update,
        'interval',
        hours=24,
        next_run_time=perf_next_run
    )

    logger.info(f"Scheduler started. Running every {ANALYSIS_INTERVAL_MINUTES} minutes. Next run at: {next_run}")
    logger.info(f"Performance tracking scheduled daily. Next run at: {perf_next_run}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Analyzer service stopped")


if __name__ == "__main__":
    main()
