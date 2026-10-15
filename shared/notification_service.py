"""
Notification Service for Alert Delivery

Supports multiple notification channels:
- Email (SMTP)
- SMS (Twilio)
- Push (Pushover, Telegram)
- Webhook (Custom HTTP endpoints)
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, time
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)


class NotificationService:
    """Handles alert notifications via multiple channels."""

    def __init__(self, db_config: Dict[str, str]):
        """Initialize notification service with database connection."""
        self.db_config = db_config
        self._settings_cache = None
        self._settings_cache_time = None

    def _get_settings(self) -> Optional[Dict]:
        """Get notification settings from database with 60-second cache."""
        from datetime import timedelta

        # Return cached settings if less than 60 seconds old
        if (self._settings_cache and self._settings_cache_time and
            datetime.now() - self._settings_cache_time < timedelta(seconds=60)):
            return self._settings_cache

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=DictCursor)

            cursor.execute("SELECT * FROM notification_settings WHERE id = 1")
            settings = cursor.fetchone()

            cursor.close()
            conn.close()

            if settings:
                self._settings_cache = dict(settings)
                self._settings_cache_time = datetime.now()
                return self._settings_cache
            else:
                logger.warning("No notification settings found in database")
                return None

        except Exception as e:
            logger.error(f"Error loading notification settings from database: {e}")
            return None

    def _get_db_connection(self):
        """Create database connection."""
        return psycopg2.connect(**self.db_config)

    def _is_quiet_hours(self, quiet_start: time, quiet_end: time) -> bool:
        """Check if current time is within quiet hours."""
        now = datetime.now().time()

        if quiet_start < quiet_end:
            # Normal case: quiet hours within same day (e.g., 22:00-07:00 invalid, but 08:00-18:00)
            return quiet_start <= now <= quiet_end
        else:
            # Quiet hours span midnight (e.g., 22:00-07:00)
            return now >= quiet_start or now <= quiet_end

    def check_and_send_notifications(self):
        """Check for new alerts and send notifications based on preferences."""
        conn = self._get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            # Find unnotified alerts
            cursor.execute("""
                SELECT
                    a.id,
                    a.asset_id,
                    a.timestamp,
                    a.alert_type,
                    a.description,
                    a.confidence_score,
                    c.name as asset_name,
                    c.ticker
                FROM alerts a
                JOIN asset c ON a.asset_id = c.id
                WHERE a.notified = FALSE
                ORDER BY a.timestamp DESC
            """)

            alerts = cursor.fetchall()
            logger.info(f"Found {len(alerts)} unnotified alerts")

            for alert in alerts:
                self._process_alert_notification(alert, cursor)

            conn.commit()

        except Exception as e:
            logger.error(f"Error checking notifications: {e}")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    def _process_alert_notification(self, alert: Dict, cursor):
        """Process notification for a single alert."""
        # Get notification preferences for this alert
        cursor.execute("""
            SELECT
                min_confidence,
                notification_channels,
                quiet_hours_start,
                quiet_hours_end,
                enabled
            FROM alert_notification_preferences
            WHERE asset_id = %s AND alert_type = %s
        """, (alert['asset_id'], alert['alert_type']))

        pref = cursor.fetchone()

        # If no specific preference, check for wildcard (all alert types)
        if not pref:
            cursor.execute("""
                SELECT
                    min_confidence,
                    notification_channels,
                    quiet_hours_start,
                    quiet_hours_end,
                    enabled
                FROM alert_notification_preferences
                WHERE asset_id = %s AND alert_type IS NULL
            """, (alert['asset_id'],))
            pref = cursor.fetchone()

        # Skip if no preferences or disabled
        if not pref or not pref['enabled']:
            logger.debug(f"No notification preferences for alert {alert['id']}, marking as notified")
            self._mark_alert_notified(alert['id'], cursor)
            return

        # Check confidence threshold
        if alert['confidence_score'] < pref['min_confidence']:
            logger.debug(
                f"Alert {alert['id']} confidence {alert['confidence_score']:.2f} "
                f"below threshold {pref['min_confidence']:.2f}"
            )
            self._mark_alert_notified(alert['id'], cursor)
            return

        # Check quiet hours
        if self._is_quiet_hours(pref['quiet_hours_start'], pref['quiet_hours_end']):
            logger.info(f"Skipping notification for alert {alert['id']} during quiet hours")
            return

        # Send notifications via configured channels
        channels = pref['notification_channels']
        sent_count = 0

        for channel in channels:
            try:
                if channel == 'email':
                    success = self._send_email_notification(alert, cursor)
                elif channel == 'sms':
                    success = self._send_sms_notification(alert, cursor)
                elif channel == 'push':
                    success = self._send_push_notification(alert, cursor)
                elif channel == 'webhook':
                    success = self._send_webhook_notification(alert, cursor)
                else:
                    logger.warning(f"Unknown notification channel: {channel}")
                    continue

                if success:
                    sent_count += 1
            except Exception as e:
                logger.error(f"Error sending {channel} notification for alert {alert['id']}: {e}")
                self._log_notification(alert['id'], channel, 'unknown', 'error', str(e), cursor)

        # Mark alert as notified if at least one channel succeeded
        if sent_count > 0:
            self._mark_alert_notified(alert['id'], cursor)
            logger.info(f"Alert {alert['id']} notified via {sent_count} channel(s)")

    def _send_email_notification(self, alert: Dict, cursor) -> bool:
        """Send email notification."""
        settings = self._get_settings()
        if not settings:
            logger.warning("Email not configured - no settings found in database")
            return False

        smtp_user = settings.get('smtp_user')
        smtp_password = settings.get('smtp_password')
        notification_recipient = settings.get('notification_email')
        smtp_host = settings.get('smtp_host') or 'smtp.gmail.com'
        smtp_port = settings.get('smtp_port') or 587
        smtp_from = settings.get('smtp_from') or smtp_user

        if not smtp_user or not smtp_password or not notification_recipient:
            logger.warning("Email not configured (smtp_user, smtp_password, notification_email required)")
            return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"🔔 Alert: {alert['asset_name']} ({alert['ticker']}) - {alert['alert_type'].replace('_', ' ').title()}"
            msg['From'] = smtp_from
            msg['To'] = notification_recipient

            # Email body
            html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #d62728;">🔔 Trading Alert</h2>
                <div style="background-color: #f8f9fa; padding: 15px; border-left: 5px solid #d62728; margin: 20px 0;">
                  <h3>{alert['asset_name']} ({alert['ticker']})</h3>
                  <p><strong>Alert Type:</strong> {alert['alert_type'].replace('_', ' ').title()}</p>
                  <p><strong>Confidence:</strong> {alert['confidence_score']:.2f}</p>
                  <p><strong>Time:</strong> {alert['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div style="margin: 20px 0;">
                  <h4>Description:</h4>
                  <p>{alert['description']}</p>
                </div>
                <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">
                <p style="color: #666; font-size: 12px;">
                  This alert was generated by your News Trading System.<br>
                  <a href="http://localhost:8501">View Dashboard</a>
                </p>
              </body>
            </html>
            """

            msg.attach(MIMEText(html, 'html'))

            # Send email
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)

            self._log_notification(alert['id'], 'email', notification_recipient, 'sent', None, cursor)
            logger.info(f"Email notification sent for alert {alert['id']}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            self._log_notification(alert['id'], 'email', notification_recipient or 'unknown', 'error', str(e), cursor)
            return False

    def _send_sms_notification(self, alert: Dict, cursor) -> bool:
        """Send SMS notification via Twilio."""
        settings = self._get_settings()
        if not settings:
            logger.warning("SMS not configured - no settings found in database")
            return False

        twilio_account_sid = settings.get('twilio_account_sid')
        twilio_auth_token = settings.get('twilio_auth_token')
        twilio_from_number = settings.get('twilio_from_number')
        sms_recipient = settings.get('notification_phone')

        if not twilio_account_sid or not twilio_auth_token or not sms_recipient or not twilio_from_number:
            logger.warning("SMS not configured (twilio_account_sid, twilio_auth_token, twilio_from_number, notification_phone required)")
            return False

        try:
            from twilio.rest import Client

            client = Client(twilio_account_sid, twilio_auth_token)

            message_body = (
                f"🔔 Alert: {alert['asset_name']} ({alert['ticker']})\n"
                f"{alert['alert_type'].replace('_', ' ').title()}\n"
                f"Confidence: {alert['confidence_score']:.2f}\n"
                f"{alert['description'][:100]}..."
            )

            message = client.messages.create(
                body=message_body,
                from_=twilio_from_number,
                to=sms_recipient
            )

            self._log_notification(alert['id'], 'sms', sms_recipient, 'sent', None, cursor)
            logger.info(f"SMS notification sent for alert {alert['id']}: {message.sid}")
            return True

        except ImportError:
            logger.warning("Twilio library not installed. Run: pip install twilio")
            return False
        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            self._log_notification(alert['id'], 'sms', sms_recipient or 'unknown', 'error', str(e), cursor)
            return False

    def _send_push_notification(self, alert: Dict, cursor) -> bool:
        """Send push notification via Pushover."""
        settings = self._get_settings()
        if not settings:
            logger.warning("Push not configured - no settings found in database")
            return False

        pushover_token = settings.get('pushover_token')
        pushover_user = settings.get('pushover_user')

        if not pushover_token or not pushover_user:
            logger.warning("Push not configured (pushover_token and pushover_user required)")
            return False

        try:
            import requests

            data = {
                'token': pushover_token,
                'user': pushover_user,
                'title': f"{alert['asset_name']} ({alert['ticker']}) Alert",
                'message': f"{alert['alert_type'].replace('_', ' ').title()}: {alert['description']}",
                'priority': 1 if alert['confidence_score'] >= 0.9 else 0,
                'url': 'http://localhost:8501',
                'url_title': 'View Dashboard'
            }

            response = requests.post('https://api.pushover.net/1/messages.json', data=data)

            if response.status_code == 200:
                self._log_notification(alert['id'], 'push', pushover_user, 'sent', None, cursor)
                logger.info(f"Push notification sent for alert {alert['id']}")
                return True
            else:
                raise Exception(f"Pushover API returned {response.status_code}: {response.text}")

        except ImportError:
            logger.warning("Requests library not installed. Run: pip install requests")
            return False
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")
            self._log_notification(alert['id'], 'push', pushover_user or 'unknown', 'error', str(e), cursor)
            return False

    def _send_webhook_notification(self, alert: Dict, cursor) -> bool:
        """Send notification via webhook."""
        settings = self._get_settings()
        if not settings:
            logger.warning("Webhook not configured - no settings found in database")
            return False

        webhook_url = settings.get('webhook_url')

        if not webhook_url:
            logger.warning("Webhook not configured (webhook_url required)")
            return False

        try:
            import requests

            payload = {
                'alert_id': alert['id'],
                'asset_name': alert['asset_name'],
                'ticker': alert['ticker'],
                'alert_type': alert['alert_type'],
                'description': alert['description'],
                'confidence_score': float(alert['confidence_score']),
                'timestamp': alert['timestamp'].isoformat()
            }

            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )

            if response.status_code in [200, 201, 204]:
                self._log_notification(alert['id'], 'webhook', webhook_url, 'sent', None, cursor)
                logger.info(f"Webhook notification sent for alert {alert['id']}")
                return True
            else:
                raise Exception(f"Webhook returned {response.status_code}: {response.text}")

        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            self._log_notification(alert['id'], 'webhook', webhook_url or 'unknown', 'error', str(e), cursor)
            return False

    def _mark_alert_notified(self, alert_id: int, cursor):
        """Mark alert as notified."""
        cursor.execute("""
            UPDATE alerts
            SET notified = TRUE, notified_at = NOW()
            WHERE id = %s
        """, (alert_id,))

    def _log_notification(self, alert_id: int, channel: str, recipient: str,
                         status: str, error_msg: Optional[str], cursor):
        """Log notification attempt to database."""
        cursor.execute("""
            INSERT INTO notification_log (alert_id, channel, recipient, status, error_message)
            VALUES (%s, %s, %s, %s, %s)
        """, (alert_id, channel, recipient, status, error_msg))


def main():
    """Run notification check as standalone script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'database': os.getenv('POSTGRES_DB', 'newstrading'),
        'user': os.getenv('POSTGRES_USER', 'trading'),
        'password': os.getenv('POSTGRES_PASSWORD', 'trading123')
    }

    service = NotificationService(db_config)
    service.check_and_send_notifications()
    logger.info("Notification check completed")


if __name__ == '__main__':
    main()
