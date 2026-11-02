"""Tests for newstrading.notify.senders: one channel each, no network involved."""

from dataclasses import replace
from datetime import datetime

import pytest

from newstrading.errors import NotificationError
from newstrading.notify.senders import Alert, EmailSender, PushSender, SmsSender, WebhookSender
from newstrading.notify.service import NotificationSettings

ALERT = Alert(
    id=7,
    asset_id=3,
    timestamp=datetime(2025, 11, 17, 14, 30, 15),
    alert_type="long_signal",
    description="Hiring surge detected",
    confidence_score=0.92,
    asset_name="Genpact",
    ticker="G",
)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
WEBHOOK_URL = "https://hooks.example.com/alert"


class FakeResponse:
    """Minimal stand-in for a ``requests`` response."""

    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeHttp:
    """Records every HTTP call and replays one response, or raises."""

    def __init__(self, *, status_code=200, text="ok", fail_with=None):
        self.status_code = status_code
        self.text = text
        self.fail_with = fail_with
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.fail_with is not None:
            raise self.fail_with
        return FakeResponse(self.status_code, self.text)


class FakeSmtpServer:
    """Stand-in for ``smtplib.SMTP`` used as a context manager."""

    def __init__(self, fail_with=None):
        self.fail_with = fail_with
        self.starttls_calls = 0
        self.logins = []
        self.messages = []

    def starttls(self):
        self.starttls_calls += 1

    def login(self, user, password):
        self.logins.append((user, password))

    def send_message(self, message):
        if self.fail_with is not None:
            raise self.fail_with
        self.messages.append(message)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def install_smtp(*, fail_with=None):
    """Build an SMTP transport and return it with its recorded calls."""

    connections = []
    servers = []

    def transport(host, port):
        connections.append((host, port))
        servers.append(FakeSmtpServer(fail_with))
        return servers[-1]

    return transport, connections, servers


def email_settings(**overrides):
    """Return complete SMTP settings with ``overrides`` applied."""
    base = NotificationSettings(
        notification_email="ops@example.com",
        smtp_host="smtp.example.com",
        smtp_port=2525,
        smtp_user="bot@example.com",
        smtp_password="app-password",
    )
    return replace(base, **overrides)


def sms_settings(**overrides):
    """Return complete Twilio settings with ``overrides`` applied."""
    base = NotificationSettings(
        notification_phone="+431234567",
        twilio_account_sid="AC123",
        twilio_auth_token="token",
        twilio_from_number="+1555000",
    )
    return replace(base, **overrides)


def push_settings(**overrides):
    """Return complete Pushover settings with ``overrides`` applied."""
    return replace(
        NotificationSettings(pushover_token="push-token", pushover_user="push-user"), **overrides
    )


def webhook_settings(**overrides):
    """Return complete webhook settings with ``overrides`` applied."""
    return replace(NotificationSettings(webhook_url=WEBHOOK_URL), **overrides)


def test_email_sends_the_legacy_message():
    """The email carries the legacy subject, sender, recipient and HTML body."""
    transport, connections, servers = install_smtp()

    recipient = EmailSender(transport).send(ALERT, email_settings())

    assert recipient == "ops@example.com"
    assert connections == [("smtp.example.com", 2525)]
    server = servers[0]
    assert server.starttls_calls == 1
    assert server.logins == [("bot@example.com", "app-password")]
    message = server.messages[0]
    assert message["Subject"] == "🔔 Alert: Genpact (G) - Long Signal"
    assert message["From"] == "bot@example.com"
    assert message["To"] == "ops@example.com"
    body = message.get_payload(0).get_payload(decode=True).decode()
    assert "<h3>Genpact (G)</h3>" in body
    assert "<strong>Alert Type:</strong> Long Signal" in body
    assert "<strong>Confidence:</strong> 0.92" in body
    assert "<strong>Time:</strong> 2025-11-17 14:30:15" in body
    assert "Hiring surge detected" in body
    assert 'href="http://localhost:8501"' in body


def test_email_falls_back_to_the_legacy_smtp_defaults():
    """A missing host, port or sender address uses the legacy defaults."""
    transport, connections, servers = install_smtp()
    settings = NotificationSettings(
        notification_email="ops@example.com",
        smtp_user="bot@example.com",
        smtp_password="app-password",
    )

    EmailSender(transport).send(ALERT, settings)

    assert connections == [("smtp.gmail.com", 587)]
    assert servers[0].messages[0]["From"] == "bot@example.com"


def test_email_uses_the_configured_sender_address():
    """``smtp_from`` wins over the SMTP user as the From header."""
    transport, _connections, servers = install_smtp()

    EmailSender(transport).send(ALERT, email_settings(smtp_from="alerts@example.com"))

    assert servers[0].messages[0]["From"] == "alerts@example.com"


def test_email_transport_failure_becomes_a_notification_error():
    """A failing SMTP conversation is reported as a NotificationError."""
    transport, _connections, _servers = install_smtp(fail_with=RuntimeError("smtp is down"))

    with pytest.raises(NotificationError, match="smtp is down"):
        EmailSender(transport).send(ALERT, email_settings())


def test_a_long_provider_text_is_truncated_to_five_hundred_characters():
    """The error message keeps the provider text, cut to 500 characters."""
    transport, _connections, _servers = install_smtp(fail_with=RuntimeError("x" * 600))

    with pytest.raises(NotificationError) as raised:
        EmailSender(transport).send(ALERT, email_settings())

    assert len(str(raised.value)) == 500


@pytest.mark.parametrize("field", ["notification_email", "smtp_user", "smtp_password"])
def test_email_skip_reason_names_a_missing_setting(field):
    """A missing recipient or credential makes the channel unconfigured."""
    assert EmailSender().skip_reason(email_settings(**{field: None})) is not None


def test_email_is_configured_when_every_setting_is_present():
    """Complete settings mean the channel may send."""
    assert EmailSender().skip_reason(email_settings()) is None


def test_sms_posts_the_legacy_twilio_message():
    """The SMS goes to Twilio as the legacy message with form credentials."""
    http = FakeHttp(status_code=201)

    recipient = SmsSender(http).send(ALERT, sms_settings())

    assert recipient == "+431234567"
    call = http.calls[0]
    assert call["url"] == TWILIO_URL
    assert call["auth"] == ("AC123", "token")
    assert call["data"] == {
        "From": "+1555000",
        "To": "+431234567",
        "Body": "🔔 Alert: Genpact (G)\nLong Signal\nConfidence: 0.92\nHiring surge detected...",
    }


def test_sms_status_error_becomes_a_notification_error():
    """A non-success status carries the provider answer."""
    http = FakeHttp(status_code=400, text="bad number")

    with pytest.raises(NotificationError, match="Twilio API returned 400: bad number"):
        SmsSender(http).send(ALERT, sms_settings())


def test_sms_transport_failure_becomes_a_notification_error():
    """A broken HTTP call is reported as a NotificationError."""
    http = FakeHttp(fail_with=RuntimeError("connection reset"))

    with pytest.raises(NotificationError, match="connection reset"):
        SmsSender(http).send(ALERT, sms_settings())


@pytest.mark.parametrize(
    "field",
    ["notification_phone", "twilio_account_sid", "twilio_auth_token", "twilio_from_number"],
)
def test_sms_skip_reason_names_a_missing_setting(field):
    """A missing phone number or Twilio credential makes the channel unconfigured."""
    assert SmsSender().skip_reason(sms_settings(**{field: None})) is not None


def test_sms_is_configured_when_every_setting_is_present():
    """Complete settings mean the channel may send."""
    assert SmsSender().skip_reason(sms_settings()) is None


def test_push_posts_the_legacy_pushover_payload():
    """The push carries the legacy Pushover fields."""
    http = FakeHttp(status_code=200)

    recipient = PushSender(http).send(ALERT, push_settings())

    assert recipient == "push-user"
    call = http.calls[0]
    assert call["url"] == PUSHOVER_URL
    assert call["data"] == {
        "token": "push-token",
        "user": "push-user",
        "title": "Genpact (G) Alert",
        "message": "Long Signal: Hiring surge detected",
        "priority": 1,
        "url": "http://localhost:8501",
        "url_title": "View Dashboard",
    }


@pytest.mark.parametrize(("confidence", "priority"), [(0.95, 1), (0.9, 1), (0.89, 0), (0.5, 0)])
def test_push_priority_follows_the_legacy_threshold(confidence, priority):
    """A confidence of at least 0.9 makes the push a high-priority one."""
    http = FakeHttp()
    alert = replace(ALERT, confidence_score=confidence)

    PushSender(http).send(alert, push_settings())

    assert http.calls[0]["data"]["priority"] == priority


def test_push_status_error_becomes_a_notification_error():
    """A non-success status carries the provider answer."""
    http = FakeHttp(status_code=500, text="rate limited")

    with pytest.raises(NotificationError, match="Pushover API returned 500: rate limited"):
        PushSender(http).send(ALERT, push_settings())


def test_push_transport_failure_becomes_a_notification_error():
    """A broken HTTP call is reported as a NotificationError."""
    http = FakeHttp(fail_with=RuntimeError("dns failure"))

    with pytest.raises(NotificationError, match="dns failure"):
        PushSender(http).send(ALERT, push_settings())


@pytest.mark.parametrize("field", ["pushover_token", "pushover_user"])
def test_push_skip_reason_names_a_missing_setting(field):
    """A missing token or user makes the channel unconfigured."""
    assert PushSender().skip_reason(push_settings(**{field: None})) is not None


def test_push_is_configured_when_every_setting_is_present():
    """Complete settings mean the channel may send."""
    assert PushSender().skip_reason(push_settings()) is None


def test_webhook_posts_the_legacy_json_payload():
    """The webhook receives the legacy JSON body for the configured URL."""
    http = FakeHttp(status_code=200)

    recipient = WebhookSender(http).send(ALERT, webhook_settings())

    assert recipient == WEBHOOK_URL
    call = http.calls[0]
    assert call["url"] == WEBHOOK_URL
    assert call["json"] == {
        "alert_id": 7,
        "asset_name": "Genpact",
        "ticker": "G",
        "alert_type": "long_signal",
        "description": "Hiring surge detected",
        "confidence_score": 0.92,
        "timestamp": "2025-11-17T14:30:15",
    }
    assert call["headers"] == {"Content-Type": "application/json"}
    assert call["timeout"] == 10


@pytest.mark.parametrize("status_code", [200, 201, 204])
def test_webhook_accepts_the_legacy_success_codes(status_code):
    """Every legacy success code counts as delivered."""
    http = FakeHttp(status_code=status_code)

    assert WebhookSender(http).send(ALERT, webhook_settings()) == WEBHOOK_URL


def test_webhook_status_error_becomes_a_notification_error():
    """A non-success status carries the provider answer, truncated to 500 characters."""
    http = FakeHttp(status_code=500, text="y" * 600)

    with pytest.raises(NotificationError) as raised:
        WebhookSender(http).send(ALERT, webhook_settings())

    assert str(raised.value).startswith("Webhook returned 500: ")
    assert len(str(raised.value)) == 500


def test_webhook_transport_failure_becomes_a_notification_error():
    """A broken HTTP call is reported as a NotificationError."""
    http = FakeHttp(fail_with=RuntimeError("timeout"))

    with pytest.raises(NotificationError, match="timeout"):
        WebhookSender(http).send(ALERT, webhook_settings())


def test_webhook_skip_reason_names_the_missing_url():
    """Without a URL there is nowhere to post."""
    assert WebhookSender().skip_reason(webhook_settings(webhook_url=None)) is not None
    assert WebhookSender().skip_reason(webhook_settings()) is None
