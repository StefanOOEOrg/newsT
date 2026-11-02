"""Sending one alert over one channel.

Every sender owns the legacy payload of its channel and takes its transport as a
callable, so tests never touch the network.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any, Protocol

import requests

from newstrading.errors import NotificationError

if TYPE_CHECKING:
    from newstrading.notify.service import NotificationSettings

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500
DASHBOARD_URL = "http://localhost:8501"
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
PUSHOVER_API = "https://api.pushover.net/1/messages.json"
WEBHOOK_SUCCESS_CODES = (200, 201, 204)


@dataclass(frozen=True, slots=True)
class Alert:
    """One alert row joined with its asset, as a sender needs it.

    Attributes:
        id: Primary key in the ``alerts`` table.
        asset_id: Asset the alert belongs to.
        timestamp: Time the alert was raised.
        alert_type: Machine readable type, e.g. ``long_signal``.
        description: Human readable text of the alert.
        confidence_score: Model confidence between 0 and 1.
        asset_name: Name of the asset, from ``asset.name``.
        ticker: Symbol of the asset, from ``asset.ticker``.
    """

    id: int
    asset_id: int
    timestamp: datetime
    alert_type: str
    description: str
    confidence_score: float
    asset_name: str
    ticker: str

    @property
    def alert_type_title(self) -> str:
        """Return the alert type as the legacy messages spell it."""
        return self.alert_type.replace("_", " ").title()


class Sender(Protocol):
    """One notification channel."""

    channel: str

    def skip_reason(self, settings: NotificationSettings) -> str | None:
        """Return why the channel cannot send, or ``None`` when it is configured."""
        ...

    def send(self, alert: Alert, settings: NotificationSettings) -> str:
        """Send one alert; return the recipient used.

        Raises:
            NotificationError: When the channel is configured but the send fails. The message
                carries the provider text, truncated to 500 characters.
        """
        ...


def _truncate(text: str) -> str:
    """Cut provider text to the length one error message keeps."""
    return text[:MAX_ERROR_LENGTH]


class EmailSender:
    """Email over the legacy SMTP conversation."""

    channel = "email"

    def __init__(self, smtp: Callable[[str, int], Any] = smtplib.SMTP) -> None:
        """Take the SMTP transport.

        Args:
            smtp: Callable ``(host, port)`` returning an SMTP-like context manager with
                ``starttls``, ``login`` and ``send_message``. Tests inject a fake.
        """
        self._smtp = smtp

    def skip_reason(self, settings: NotificationSettings) -> str | None:
        """A recipient, a user and a password are required."""
        if not settings.smtp_user or not settings.smtp_password or not settings.notification_email:
            return "email not configured (smtp_user, smtp_password, notification_email required)"
        return None

    def send(self, alert: Alert, settings: NotificationSettings) -> str:
        """Send the alert email; return the recipient address."""
        recipient = settings.notification_email or ""
        sender = settings.smtp_from or settings.smtp_user
        message = MIMEMultipart("alternative")
        message["Subject"] = (
            f"🔔 Alert: {alert.asset_name} ({alert.ticker}) - {alert.alert_type_title}"
        )
        message["From"] = sender
        message["To"] = recipient
        message.attach(MIMEText(_html_body(alert), "html"))
        try:
            with self._smtp(
                settings.smtp_host or DEFAULT_SMTP_HOST, settings.smtp_port or DEFAULT_SMTP_PORT
            ) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
        except Exception as error:  # boundary: any SMTP failure is a delivery failure
            raise NotificationError(_truncate(str(error))) from error
        logger.info("email notification sent for alert %s", alert.id)
        return recipient


def _html_body(alert: Alert) -> str:
    """Build the legacy HTML body of an alert email."""
    return "\n".join(
        (
            "<html>",
            '  <body style="font-family: Arial, sans-serif; padding: 20px;">',
            '    <h2 style="color: #d62728;">🔔 Trading Alert</h2>',
            '    <div style="background-color: #f8f9fa; padding: 15px; '
            'border-left: 5px solid #d62728; margin: 20px 0;">',
            f"      <h3>{alert.asset_name} ({alert.ticker})</h3>",
            f"      <p><strong>Alert Type:</strong> {alert.alert_type_title}</p>",
            f"      <p><strong>Confidence:</strong> {alert.confidence_score:.2f}</p>",
            f"      <p><strong>Time:</strong> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>",
            "    </div>",
            '    <div style="margin: 20px 0;">',
            "      <h4>Description:</h4>",
            f"      <p>{alert.description}</p>",
            "    </div>",
            '    <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">',
            '    <p style="color: #666; font-size: 12px;">',
            "      This alert was generated by your News Trading System.<br>",
            f'      <a href="{DASHBOARD_URL}">View Dashboard</a>',
            "    </p>",
            "  </body>",
            "</html>",
        )
    )


class SmsSender:
    """SMS over the Twilio messages API, called with ``requests``."""

    channel = "sms"

    def __init__(self, http: Callable[..., Any] = requests.post) -> None:
        """Take the HTTP transport.

        Args:
            http: Callable ``(url, **kwargs)`` returning a response with ``status_code``
                and ``text``. Tests inject a fake.
        """
        self._http = http

    def skip_reason(self, settings: NotificationSettings) -> str | None:
        """Both Twilio credentials, the sender number and the recipient are required."""
        required = (
            settings.twilio_account_sid,
            settings.twilio_auth_token,
            settings.twilio_from_number,
            settings.notification_phone,
        )
        if not all(required):
            return (
                "sms not configured (twilio_account_sid, twilio_auth_token, "
                "twilio_from_number, notification_phone required)"
            )
        return None

    def send(self, alert: Alert, settings: NotificationSettings) -> str:
        """Send the alert SMS; return the recipient number."""
        recipient = settings.notification_phone or ""
        body = (
            f"🔔 Alert: {alert.asset_name} ({alert.ticker})\n"
            f"{alert.alert_type_title}\n"
            f"Confidence: {alert.confidence_score:.2f}\n"
            f"{alert.description[:100]}..."
        )
        url = TWILIO_API.format(sid=settings.twilio_account_sid)
        try:
            response = self._http(
                url,
                data={
                    "From": settings.twilio_from_number,
                    "To": recipient,
                    "Body": body,
                },
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
        except Exception as error:  # boundary: any HTTP failure is a delivery failure
            raise NotificationError(_truncate(str(error))) from error
        if response.status_code not in (200, 201):
            raise NotificationError(
                _truncate(f"Twilio API returned {response.status_code}: {response.text}")
            )
        logger.info("sms notification sent for alert %s", alert.id)
        return recipient


class PushSender:
    """Push over the Pushover messages API."""

    channel = "push"

    def __init__(self, http: Callable[..., Any] = requests.post) -> None:
        """Take the HTTP transport; tests inject a fake."""
        self._http = http

    def skip_reason(self, settings: NotificationSettings) -> str | None:
        """The application token and the user key are required."""
        if not settings.pushover_token or not settings.pushover_user:
            return "push not configured (pushover_token, pushover_user required)"
        return None

    def send(self, alert: Alert, settings: NotificationSettings) -> str:
        """Send the alert push; return the Pushover user key."""
        data = {
            "token": settings.pushover_token,
            "user": settings.pushover_user,
            "title": f"{alert.asset_name} ({alert.ticker}) Alert",
            "message": f"{alert.alert_type_title}: {alert.description}",
            "priority": 1 if alert.confidence_score >= 0.9 else 0,
            "url": DASHBOARD_URL,
            "url_title": "View Dashboard",
        }
        try:
            response = self._http(PUSHOVER_API, data=data)
        except Exception as error:  # boundary: any HTTP failure is a delivery failure
            raise NotificationError(_truncate(str(error))) from error
        if response.status_code != 200:
            raise NotificationError(
                _truncate(f"Pushover API returned {response.status_code}: {response.text}")
            )
        logger.info("push notification sent for alert %s", alert.id)
        return settings.pushover_user or ""


class WebhookSender:
    """Custom HTTP endpoint taking the legacy alert JSON."""

    channel = "webhook"

    def __init__(self, http: Callable[..., Any] = requests.post) -> None:
        """Take the HTTP transport; tests inject a fake."""
        self._http = http

    def skip_reason(self, settings: NotificationSettings) -> str | None:
        """Without a URL there is nowhere to post."""
        if not settings.webhook_url:
            return "webhook not configured (webhook_url required)"
        return None

    def send(self, alert: Alert, settings: NotificationSettings) -> str:
        """Send the alert to the webhook; return the URL used."""
        url = settings.webhook_url or ""
        payload = {
            "alert_id": alert.id,
            "asset_name": alert.asset_name,
            "ticker": alert.ticker,
            "alert_type": alert.alert_type,
            "description": alert.description,
            "confidence_score": float(alert.confidence_score),
            "timestamp": alert.timestamp.isoformat(),
        }
        try:
            response = self._http(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        except Exception as error:  # boundary: any HTTP failure is a delivery failure
            raise NotificationError(_truncate(str(error))) from error
        if response.status_code not in WEBHOOK_SUCCESS_CODES:
            raise NotificationError(
                _truncate(f"Webhook returned {response.status_code}: {response.text}")
            )
        logger.info("webhook notification sent for alert %s", alert.id)
        return url
