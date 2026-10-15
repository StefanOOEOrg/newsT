"""
Notifier Service - Continuous notification checking and delivery
"""

import os
import sys
import logging
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.notification_service import NotificationService

# Configure logging
logger = logging.getLogger(__name__)


def setup_logging():
    """Setup logging with console handler."""
    log_level = os.getenv('LOG_LEVEL', 'INFO')

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    root_logger.addHandler(console_handler)

    # Try to add database handler (optional)
    try:
        from shared.db_logger import DatabaseLogHandler
        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'postgres'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'newstrading'),
            'user': os.getenv('POSTGRES_USER', 'trading'),
            'password': os.getenv('POSTGRES_PASSWORD', 'trading123')
        }
        db_handler = DatabaseLogHandler(db_config, service='notifier')
        db_handler.setLevel(logging.INFO)
        root_logger.addHandler(db_handler)
        logger.info("Database logging enabled")
    except Exception as e:
        logger.warning(f"Database logging not available: {e}")


def check_notifications():
    """Run notification check."""
    try:
        logger.info("="*60)
        logger.info(f"Starting notification check at {datetime.now()}")

        db_config = {
            'host': os.getenv('POSTGRES_HOST', 'postgres'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'newstrading'),
            'user': os.getenv('POSTGRES_USER', 'trading'),
            'password': os.getenv('POSTGRES_PASSWORD', 'trading123')
        }

        service = NotificationService(db_config)
        service.check_and_send_notifications()

        logger.info("Notification check completed successfully")

    except Exception as e:
        logger.error(f"Error in notification check: {e}", exc_info=True)


def main():
    """Main notifier service loop."""
    setup_logging()

    logger.info("="*60)
    logger.info("Notifier Service Starting")
    logger.info("="*60)

    # Log configuration
    logger.info(f"SMTP Host: {os.getenv('SMTP_HOST', 'Not configured')}")
    logger.info(f"SMTP User: {os.getenv('SMTP_USER', 'Not configured')}")
    logger.info(f"Notification Email: {os.getenv('NOTIFICATION_EMAIL', 'Not configured')}")
    logger.info(f"Notification Phone: {os.getenv('NOTIFICATION_PHONE', 'Not configured')}")
    logger.info(f"Twilio Configured: {'Yes' if os.getenv('TWILIO_ACCOUNT_SID') else 'No'}")
    logger.info(f"Pushover Configured: {'Yes' if os.getenv('PUSHOVER_TOKEN') else 'No'}")
    logger.info(f"Webhook URL: {os.getenv('WEBHOOK_URL', 'Not configured')}")

    # Check interval in minutes
    check_interval = int(os.getenv('NOTIFICATION_CHECK_INTERVAL', '5'))
    logger.info(f"Notification check interval: {check_interval} minutes")

    # Run immediate check on startup
    logger.info("Running initial notification check...")
    check_notifications()

    # Schedule periodic checks
    scheduler = BlockingScheduler()
    scheduler.add_job(
        check_notifications,
        'interval',
        minutes=check_interval,
        id='notification_check',
        name='Check and send notifications',
        max_instances=1
    )

    logger.info("Scheduler started. Waiting for next scheduled check...")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Notifier service shutting down...")
        scheduler.shutdown()


if __name__ == '__main__':
    main()
