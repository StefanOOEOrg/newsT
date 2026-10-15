"""
Generate Historical Alerts
Analyzes existing AI analysis data and generates alerts retroactively.
"""
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL)


def generate_historical_alerts():
    """Generate alerts for all existing AI analyses."""
    conn = get_db_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all AI analyses that haven't been processed for alerts yet
            # We'll check by looking at analyses whose posts don't have corresponding alerts
            cur.execute("""
                SELECT
                    aa.id,
                    aa.post_id,
                    aa.sentiment_score,
                    aa.category,
                    aa.summary,
                    sp.asset_id,
                    sp.created_at as post_created_at
                FROM ai_analysis aa
                JOIN social_posts sp ON aa.post_id = sp.id
                ORDER BY sp.created_at ASC
            """)

            analyses = cur.fetchall()

            if not analyses:
                logger.info("No analyses found to process")
                return

            logger.info(f"Found {len(analyses)} analyses to process for historical alerts")

            # First, clear existing alerts to avoid duplicates
            # Need to delete notification_log first due to foreign key constraint
            logger.info("Clearing notification log and existing alerts...")
            cur.execute("DELETE FROM notification_log")
            cur.execute("DELETE FROM alerts")
            conn.commit()
            logger.info("Existing alerts and notification log cleared")

            alerts_generated = 0

            for analysis in analyses:
                sentiment = analysis['sentiment_score']
                category = analysis['category']
                asset_id = analysis['asset_id']
                summary = analysis['summary'] or ''
                post_timestamp = analysis['post_created_at']

                # Short signal (bearish) - negative sentiment or problems
                if sentiment < -0.3:
                    # Determine severity level
                    if sentiment < -0.7 or (category == 'Problems' and sentiment < -0.5):
                        severity = 'high'
                        description_prefix = "Strong short signal"
                    elif sentiment < -0.5 or (category == 'Problems' and sentiment < -0.4):
                        severity = 'medium'
                        description_prefix = "Moderate short signal"
                    else:
                        severity = 'low'
                        description_prefix = "Weak short signal"

                    # Context-aware description
                    if category == 'Problems':
                        description = f"{description_prefix}: Problem reported - {summary[:180]}"
                    else:
                        description = f"{description_prefix}: Negative sentiment detected - {summary[:180]}"

                    cur.execute("""
                        INSERT INTO alerts
                        (asset_id, alert_type, severity, description, confidence_score, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        asset_id,
                        'short_signal',
                        severity,
                        description,
                        abs(sentiment),
                        post_timestamp  # Use post creation time for historical accuracy
                    ))
                    alerts_generated += 1

                # Long signal (bullish) - positive indicators (hiring, partnerships, growth)
                if sentiment > 0.3 and category in ['Hiring', 'Growth', 'Earnings', 'Product']:
                    # Determine severity level based on strength
                    if sentiment > 0.7:
                        severity = 'high'
                        description_prefix = "Strong long signal"
                    elif sentiment > 0.5:
                        severity = 'medium'
                        description_prefix = "Moderate long signal"
                    else:
                        severity = 'low'
                        description_prefix = "Weak long signal"

                    cur.execute("""
                        INSERT INTO alerts
                        (asset_id, alert_type, severity, description, confidence_score, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        asset_id,
                        'long_signal',
                        severity,
                        f"{description_prefix}: {category} activity detected - {summary[:180]}",
                        sentiment,
                        post_timestamp  # Use post creation time for historical accuracy
                    ))
                    alerts_generated += 1

            conn.commit()
            logger.info(f"Successfully generated {alerts_generated} historical alerts from {len(analyses)} analyses")

            # Show summary by company
            cur.execute("""
                SELECT
                    c.name,
                    c.ticker,
                    COUNT(*) as alert_count,
                    COUNT(*) FILTER (WHERE a.alert_type = 'long_signal') as long_signals,
                    COUNT(*) FILTER (WHERE a.alert_type = 'short_signal') as short_signals
                FROM alerts a
                JOIN asset c ON a.asset_id = c.id
                GROUP BY c.name, c.ticker
                ORDER BY c.name
            """)

            summary = cur.fetchall()
            logger.info("\nAlert Summary by Company:")
            for row in summary:
                logger.info(f"  {row['name']} ({row['ticker']}): {row['alert_count']} alerts "
                          f"({row['long_signals']} long, {row['short_signals']} short)")

    except Exception as e:
        conn.rollback()
        logger.error(f"Error generating historical alerts: {e}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    logger.info("Starting historical alert generation...")
    try:
        generate_historical_alerts()
        logger.info("Historical alert generation completed successfully!")
    except Exception as e:
        logger.error(f"Failed to generate historical alerts: {e}")
        sys.exit(1)
