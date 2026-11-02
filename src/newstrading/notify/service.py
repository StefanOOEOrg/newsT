"""The notification pass: read the alerts that wait, send them, log and mark them."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

import psycopg2

from newstrading import db
from newstrading.config import Settings
from newstrading.notify.senders import (
    Alert,
    EmailSender,
    PushSender,
    Sender,
    SmsSender,
    WebhookSender,
)

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500
ALERT_BATCH_LIMIT = 100
UNDELIVERED_ATTEMPTS_LIMIT = 3

Now = Callable[[], datetime]

_SETTINGS_QUERY = """
    SELECT
        notification_email,
        notification_phone,
        smtp_host,
        smtp_port,
        smtp_user,
        smtp_password,
        smtp_from,
        twilio_account_sid,
        twilio_auth_token,
        twilio_from_number,
        pushover_token,
        pushover_user,
        webhook_url
    FROM notification_settings
    WHERE id = 1
"""

_ALERTS_QUERY = """
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
    ORDER BY a.timestamp ASC
    LIMIT %s
"""

_PREFERENCE_QUERY = """
    SELECT
        min_confidence,
        notification_channels,
        quiet_hours_start,
        quiet_hours_end,
        enabled
    FROM alert_notification_preferences
    WHERE asset_id = %s AND alert_type = %s
"""

_WILDCARD_PREFERENCE_QUERY = """
    SELECT
        min_confidence,
        notification_channels,
        quiet_hours_start,
        quiet_hours_end,
        enabled
    FROM alert_notification_preferences
    WHERE asset_id = %s AND alert_type IS NULL
"""

_INSERT_LOG = """
    INSERT INTO notification_log (alert_id, channel, recipient, status, error_message)
    VALUES (%s, %s, %s, %s, %s)
"""

_MARK_NOTIFIED = """
    UPDATE alerts
    SET notified = TRUE, notified_at = NOW()
    WHERE id = %s
"""

_UNDELIVERED_COUNT = """
    SELECT COUNT(*)
    FROM notification_log
    WHERE alert_id = %s AND status IN ('failed', 'skipped')
"""


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    """The ``notification_settings`` columns the channels need.

    Attributes:
        notification_email: Recipient address of the email channel.
        notification_phone: Recipient number of the SMS channel.
        smtp_host: SMTP host, ``smtp.gmail.com`` when unset.
        smtp_port: SMTP port, 587 when unset.
        smtp_user: SMTP login and default sender address.
        smtp_password: SMTP password or app password.
        smtp_from: Sender address; falls back to ``smtp_user``.
        twilio_account_sid: Twilio account SID.
        twilio_auth_token: Twilio auth token.
        twilio_from_number: Twilio sender number.
        pushover_token: Pushover application token.
        pushover_user: Pushover user key.
        webhook_url: Endpoint the alert JSON is posted to.
    """

    notification_email: str | None = None
    notification_phone: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    pushover_token: str | None = None
    pushover_user: str | None = None
    webhook_url: str | None = None


@dataclass(frozen=True, slots=True)
class _Preference:
    """One row of ``alert_notification_preferences``."""

    min_confidence: float
    channels: tuple[str, ...]
    quiet_start: time
    quiet_end: time
    enabled: bool


def utcnow() -> datetime:
    """Return the current time in UTC, timezone aware."""
    return datetime.now(UTC)


def _is_quiet(start: time, end: time, moment: datetime) -> bool:
    """Return whether ``moment`` falls inside the quiet window, both ends inclusive.

    A window whose start is later than its end crosses midnight, e.g. 22:00-07:00.
    """
    current = moment.time() if moment.tzinfo is None else moment.astimezone().time()
    if start < end:
        return start <= current <= end
    return current >= start or current <= end


def _real_senders() -> list[Sender]:
    """Build one sender per legacy channel, with the production transports."""
    return [EmailSender(), SmsSender(), PushSender(), WebhookSender()]


class NotificationService:
    """Notifies the alerts that wait, over every channel that is configured."""

    def __init__(
        self,
        settings: Settings,
        *,
        connector: db.Connector = psycopg2.connect,
        senders: Sequence[Sender] | None = None,
        now: Now = utcnow,
    ) -> None:
        """Store the configuration and the seams.

        Args:
            settings: Settings holding ``database_url``.
            connector: Connection factory; tests inject a fake.
            senders: Channels to use; ``None`` builds the four real senders.
            now: Clock for the quiet-hours check; tests inject a fixed time.
        """
        self._settings = settings
        self._connector = connector
        self.senders = list(senders) if senders is not None else _real_senders()
        self._by_channel = {sender.channel: sender for sender in self.senders}
        self._now = now

    def run(self) -> int:
        """Notify every alert that needs it; return how many alerts were handled.

        Returns:
            The number of alerts the run finished with: sent, attempted, or marked
            notified because no channel applied. Alerts deferred by quiet hours are
            not counted; they wait for the next run.

        Contract:
            * No row in ``notification_settings`` means nothing is configured: log one
              warning and return ``0`` instead of raising.
            * Every log row and marker goes through one connection and is committed
              once at the end.
        """
        handled = 0
        with db.connection(self._settings, connector=self._connector) as opened:
            # ``db.Connection`` names only commit/rollback/close, so the cursor is not
            # visible to a type checker here.
            connection: Any = opened
            with connection.cursor() as cursor:
                notification_settings = self._read_settings(cursor)
                if notification_settings is None:
                    logger.warning("No notification settings found in database")
                    return 0
                for alert in self._read_alerts(cursor):
                    if self._handle_alert(cursor, alert, notification_settings):
                        handled += 1
        logger.info("%d alert(s) handled", handled)
        return handled

    def _read_settings(self, cursor: Any) -> NotificationSettings | None:
        """Read the single settings row; ``None`` when the table is empty."""
        cursor.execute(_SETTINGS_QUERY)
        row = cursor.fetchone()
        if row is None:
            return None
        return NotificationSettings(*row)

    def _read_alerts(self, cursor: Any) -> list[Alert]:
        """Read the unnotified alerts, oldest first, at most ``ALERT_BATCH_LIMIT``."""
        cursor.execute(_ALERTS_QUERY, (ALERT_BATCH_LIMIT,))
        return [
            Alert(
                id=row[0],
                asset_id=row[1],
                timestamp=row[2],
                alert_type=row[3] or "",
                description=row[4] or "",
                confidence_score=float(row[5] or 0.0),
                asset_name=row[6] or "",
                ticker=row[7] or "",
            )
            for row in cursor.fetchall()
        ]

    def _read_preference(self, cursor: Any, alert: Alert) -> _Preference | None:
        """Read the alert's preference, falling back to the wildcard row."""
        cursor.execute(_PREFERENCE_QUERY, (alert.asset_id, alert.alert_type))
        row = cursor.fetchone()
        if row is None:
            cursor.execute(_WILDCARD_PREFERENCE_QUERY, (alert.asset_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        min_confidence, channels, quiet_start, quiet_end, enabled = row
        return _Preference(
            min_confidence=float(min_confidence),
            channels=tuple(channels or ()),
            quiet_start=quiet_start,
            quiet_end=quiet_end,
            enabled=bool(enabled),
        )

    def _handle_alert(self, cursor: Any, alert: Alert, settings: NotificationSettings) -> bool:
        """Notify one alert; return whether the run is done with it.

        Returns:
            ``False`` only while the alert has to wait for the next run (quiet hours).
            Every other outcome finishes the alert and returns ``True``.
        """
        preference = self._read_preference(cursor, alert)
        if preference is None or not preference.enabled:
            logger.debug("alert %s has no active preference, marking it notified", alert.id)
            self._mark_notified(cursor, alert.id)
            return True
        if alert.confidence_score < preference.min_confidence:
            logger.debug("alert %s is below the confidence threshold", alert.id)
            self._mark_notified(cursor, alert.id)
            return True
        if not any(channel in self._by_channel for channel in preference.channels):
            logger.warning(
                "alert %s has no deliverable channel (%s), marking it notified",
                alert.id,
                ", ".join(preference.channels) or "none configured",
            )
            self._mark_notified(cursor, alert.id)
            return True
        if _is_quiet(preference.quiet_start, preference.quiet_end, self._now()):
            logger.info("alert %s deferred: quiet hours", alert.id)
            return False
        sent = self._send_over_channels(cursor, alert, settings, preference.channels)
        if sent:
            self._mark_notified(cursor, alert.id)
            logger.info("alert %s notified over %d channel(s)", alert.id, sent)
            return True
        undelivered = self._count_undelivered(cursor, alert.id)
        if undelivered >= UNDELIVERED_ATTEMPTS_LIMIT:
            logger.warning(
                "alert %s undelivered %d time(s), giving up on it", alert.id, undelivered
            )
            self._mark_notified(cursor, alert.id)
        else:
            logger.info("alert %s undelivered %d time(s), retrying next run", alert.id, undelivered)
        return True

    @staticmethod
    def _count_undelivered(cursor: Any, alert_id: int) -> int:
        """Return how many failed or skipped attempts ``notification_log`` holds for the alert."""
        cursor.execute(_UNDELIVERED_COUNT, (alert_id,))
        row = cursor.fetchone()
        return 0 if row is None else int(row[0])

    def _send_over_channels(
        self,
        cursor: Any,
        alert: Alert,
        settings: NotificationSettings,
        channels: Sequence[str],
    ) -> int:
        """Send the alert over every channel that is configured; return the successes."""
        sent = 0
        for channel in channels:
            sender = self._by_channel.get(channel)
            if sender is None:
                logger.warning("unknown notification channel: %s", channel)
                continue
            reason = sender.skip_reason(settings)
            if reason is not None:
                logger.info("channel %s skipped for alert %s: %s", channel, alert.id, reason)
                self._log_attempt(cursor, alert, channel, "unknown", "skipped", reason)
                continue
            try:
                recipient = sender.send(alert, settings)
            except Exception as error:  # boundary: one broken channel must not stop the rest
                message = str(error)[:MAX_ERROR_LENGTH]
                logger.error("channel %s failed for alert %s: %s", channel, alert.id, message)
                self._log_attempt(cursor, alert, channel, "unknown", "failed", message)
                continue
            self._log_attempt(cursor, alert, channel, recipient, "sent", None)
            sent += 1
        return sent

    @staticmethod
    def _mark_notified(cursor: Any, alert_id: int) -> None:
        """Apply the legacy notified marker to one alert."""
        cursor.execute(_MARK_NOTIFIED, (alert_id,))

    @staticmethod
    def _log_attempt(
        cursor: Any,
        alert: Alert,
        channel: str,
        recipient: str,
        status: str,
        error: str | None,
    ) -> None:
        """Write one audit row of ``notification_log``."""
        cursor.execute(_INSERT_LOG, (alert.id, channel, recipient, status, error))
