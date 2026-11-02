"""Tests for newstrading.notify.service: the notification pass, without a database."""

import logging
from datetime import datetime, time

import pytest

from newstrading.config import Settings
from newstrading.errors import NotificationError
from newstrading.notify.service import (
    ALERT_BATCH_LIMIT,
    NotificationService,
    utcnow,
)

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")

CHANNELS = ("email", "sms", "push", "webhook")

NOON = datetime(2025, 11, 17, 12, 0, 0)
NIGHT = datetime(2025, 11, 17, 23, 30, 0)

SETTINGS_COLUMNS = (
    "notification_email",
    "notification_phone",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_from_number",
    "pushover_token",
    "pushover_user",
    "webhook_url",
)

INSERT_LOG = (
    "INSERT INTO notification_log "
    "(alert_id, channel, recipient, status, error_message) "
    "VALUES (%s, %s, %s, %s, %s)"
)
MARK_NOTIFIED = "UPDATE alerts SET notified = TRUE, notified_at = NOW() WHERE id = %s"


def settings_row(**overrides):
    """Return a complete ``notification_settings`` row in the query order."""
    values = {
        "notification_email": "ops@example.com",
        "notification_phone": "+431234567",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "bot@example.com",
        "smtp_password": "app-password",
        "smtp_from": None,
        "twilio_account_sid": "AC123",
        "twilio_auth_token": "token",
        "twilio_from_number": "+1555000",
        "pushover_token": "push-token",
        "pushover_user": "push-user",
        "webhook_url": "https://hooks.example.com/alert",
    }
    values.update(overrides)
    return tuple(values[name] for name in SETTINGS_COLUMNS)


def alert_row(
    *, alert_id=7, asset_id=3, alert_type="long_signal", confidence=0.92, description="Hiring surge"
):
    """Return one row of the alert query: id, asset, time, type, text, score, name, ticker."""
    return (
        alert_id,
        asset_id,
        datetime(2025, 11, 17, 14, 30, 15),
        alert_type,
        description,
        confidence,
        "Genpact",
        "G",
    )


def preference(
    *,
    asset_id=3,
    alert_type="long_signal",
    channels=CHANNELS,
    min_confidence=0.8,
    quiet=(time(22, 0), time(7, 0)),
    enabled=True,
):
    """Return a ``(params, row)`` pair for the preference lookup."""
    row = (min_confidence, list(channels), quiet[0], quiet[1], enabled)
    return ((asset_id, alert_type), row)


class FakeCursor:
    """Answers every statement from the fake database and records it."""

    def __init__(self, database):
        self._database = database
        self._rows = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self._database.statements.append((normalized, params))
        if self._database.fail_with is not None:
            raise self._database.fail_with
        if "FROM notification_settings" in normalized:
            row = self._database.settings
            self._rows = [] if row is None else [row]
        elif "FROM alerts a" in normalized:
            self._rows = list(self._database.alerts)
        elif "FROM alert_notification_preferences" in normalized:
            self._rows = [
                row
                for expected, row in self._database.preferences
                if tuple(expected) == tuple(params)
            ]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeConnection:
    """Connection double handing out cursors over one fake database."""

    def __init__(self, database):
        self._database = database
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self._database)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class FakeDatabase:
    """In-memory stand-in for the tables the notification pass reads."""

    def __init__(self, *, settings=None, alerts=(), preferences=(), fail_with=None):
        self.settings = settings
        self.alerts = list(alerts)
        self.preferences = list(preferences)
        self.fail_with = fail_with
        self.statements = []
        self.connection = None

    def matching(self, fragment):
        """Return the ``(query, params)`` statements containing ``fragment``."""
        return [entry for entry in self.statements if fragment in entry[0]]

    def logs(self):
        """Return the parameters of every notification log insert, in order."""
        return [params for query, params in self.statements if query.startswith(INSERT_LOG)]

    def marked(self):
        """Return the parameters of every mark-notified update, in order."""
        return [params for query, params in self.statements if query.startswith("UPDATE alerts")]


class FakeSender:
    """Sender double that records the alerts it was asked to send."""

    def __init__(self, channel, *, recipient="destination", skip=None, fail_with=None):
        self.channel = channel
        self.recipient = recipient
        self.skip = skip
        self.fail_with = fail_with
        self.sent = []

    def skip_reason(self, settings):
        return self.skip

    def send(self, alert, settings):
        self.sent.append(alert.id)
        if self.fail_with is not None:
            raise self.fail_with
        return self.recipient


def connector(database):
    """Build a connector returning the fake connection of ``database``."""

    def _connector(url):
        database.connection = FakeConnection(database)
        return database.connection

    return _connector


def build(database, *, senders=(), now=NOON):
    """Build a service over the fake database."""
    return NotificationService(
        SETTINGS, connector=connector(database), senders=list(senders), now=lambda: now
    )


def test_no_settings_row_returns_zero_and_logs_a_warning(caplog):
    """Nothing configured means no work, not an exception."""
    database = FakeDatabase(settings=None, alerts=[alert_row()])
    email = FakeSender("email")

    with caplog.at_level(logging.WARNING, logger="newstrading.notify.service"):
        handled = build(database, senders=[email]).run()

    assert handled == 0
    assert "No notification settings" in caplog.text
    assert email.sent == []
    assert database.matching("FROM alerts a") == []


def test_every_configured_channel_sends_and_is_logged_as_sent():
    """An alert over all four channels produces four sent rows and one marker."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference()]
    )
    senders = [FakeSender(channel, recipient=f"dest-{channel}") for channel in CHANNELS]

    handled = build(database, senders=senders).run()

    assert handled == 1
    assert [sender.sent for sender in senders] == [[7], [7], [7], [7]]
    assert database.logs() == [
        (7, "email", "dest-email", "sent", None),
        (7, "sms", "dest-sms", "sent", None),
        (7, "push", "dest-push", "sent", None),
        (7, "webhook", "dest-webhook", "sent", None),
    ]
    assert database.marked() == [(7,)]


def test_an_unconfigured_channel_is_logged_as_skipped_and_not_called():
    """A channel without recipient or credentials is skipped with its reason."""
    database = FakeDatabase(
        settings=settings_row(webhook_url=None),
        alerts=[alert_row()],
        preferences=[preference(channels=("email", "webhook"))],
    )
    email = FakeSender("email")
    webhook = FakeSender("webhook", skip="webhook_url is not configured")

    handled = build(database, senders=[email, webhook]).run()

    assert handled == 1
    assert email.sent == [7]
    assert webhook.sent == []
    assert database.logs() == [
        (7, "email", "destination", "sent", None),
        (7, "webhook", "unknown", "skipped", "webhook_url is not configured"),
    ]
    assert database.marked() == [(7,)]


def test_one_failing_channel_does_not_stop_the_others():
    """A failing channel produces a failed row, the rest still sends."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row()],
        preferences=[preference(channels=("email", "webhook"))],
    )
    email = FakeSender("email", fail_with=NotificationError("smtp is down"))
    webhook = FakeSender("webhook", recipient="https://hooks.example.com/alert")

    handled = build(database, senders=[email, webhook]).run()

    assert handled == 1
    assert email.sent == [7]
    assert webhook.sent == [7]
    assert database.logs() == [
        (7, "email", "unknown", "failed", "smtp is down"),
        (7, "webhook", "https://hooks.example.com/alert", "sent", None),
    ]
    assert database.marked() == [(7,)]


def test_a_failed_channel_text_is_truncated():
    """An unexpected transport error is logged cut to 500 characters."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference(channels=("email",))]
    )
    email = FakeSender("email", fail_with=RuntimeError("z" * 600))

    build(database, senders=[email]).run()

    (logged,) = database.logs()
    assert logged[3] == "failed"
    assert len(logged[4]) == 500


def test_an_alert_whose_channels_all_fail_stays_unnotified():
    """Without a single successful send the alert waits for the next run."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference(channels=("email",))]
    )
    email = FakeSender("email", fail_with=NotificationError("smtp is down"))

    handled = build(database, senders=[email]).run()

    assert handled == 1
    assert database.marked() == []


def test_the_alert_is_marked_notified_with_the_legacy_statement():
    """The marker is the legacy update, keyed by the alert id."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference(channels=("email",))]
    )

    build(database, senders=[FakeSender("email")]).run()

    (statement,) = database.matching("UPDATE alerts")
    assert statement == (MARK_NOTIFIED, (7,))


def test_each_attempt_is_logged_with_the_legacy_statement():
    """The audit row is the legacy insert into notification_log."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference(channels=("email",))]
    )

    build(database, senders=[FakeSender("email")]).run()

    (statement,) = database.matching("INSERT INTO notification_log")
    assert statement == (INSERT_LOG, (7, "email", "destination", "sent", None))


def test_an_alert_outside_quiet_hours_is_sent():
    """Noon is outside the default 22:00-07:00 window."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference(channels=("email",))]
    )
    email = FakeSender("email")

    handled = build(database, senders=[email], now=NOON).run()

    assert handled == 1
    assert email.sent == [7]
    assert database.marked() == [(7,)]


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2025, 11, 17, 23, 30, 0),
        datetime(2025, 11, 18, 2, 0, 0),
        datetime(2025, 11, 17, 22, 0, 0),
        datetime(2025, 11, 18, 7, 0, 0),
    ],
)
def test_an_alert_inside_a_window_across_midnight_is_kept_for_the_next_run(moment):
    """Inside quiet hours nothing is sent, logged or marked."""
    database = FakeDatabase(
        settings=settings_row(), alerts=[alert_row()], preferences=[preference(channels=("email",))]
    )
    email = FakeSender("email")

    handled = build(database, senders=[email], now=moment).run()

    assert handled == 0
    assert email.sent == []
    assert database.logs() == []
    assert database.marked() == []


@pytest.mark.parametrize(
    ("quiet", "moment", "sends"),
    [
        ((time(12, 0), time(14, 0)), datetime(2025, 11, 17, 13, 0, 0), False),
        ((time(12, 0), time(14, 0)), datetime(2025, 11, 17, 15, 0, 0), True),
        ((time(22, 0), time(7, 0)), datetime(2025, 11, 18, 8, 0, 0), True),
        ((time(22, 0), time(7, 0)), datetime(2025, 11, 18, 21, 59, 0), True),
    ],
)
def test_a_window_inside_one_day_is_respected(quiet, moment, sends):
    """The window works both directions: within one day and across midnight."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row()],
        preferences=[preference(channels=("email",), quiet=quiet)],
    )
    email = FakeSender("email")

    build(database, senders=[email], now=moment).run()

    assert email.sent == ([7] if sends else [])


def test_run_returns_the_number_of_handled_alerts():
    """Two alerts waiting means a return value of two."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row(alert_id=7, asset_id=3), alert_row(alert_id=8, asset_id=4)],
        preferences=[
            preference(asset_id=3, channels=("email",)),
            preference(asset_id=4, channels=("email",)),
        ],
    )

    handled = build(database, senders=[FakeSender("email")]).run()

    assert handled == 2
    assert database.marked() == [(7,), (8,)]


def test_an_alert_without_a_preference_is_marked_notified_without_a_send():
    """The legacy behaviour: no preference row means nothing to send."""
    database = FakeDatabase(settings=settings_row(), alerts=[alert_row()], preferences=[])
    email = FakeSender("email")

    handled = build(database, senders=[email]).run()

    assert handled == 1
    assert email.sent == []
    assert database.logs() == []
    assert database.marked() == [(7,)]


def test_a_wildcard_preference_applies_when_the_alert_type_has_none():
    """The second lookup uses the wildcard row for the asset."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row(alert_type="long_signal")],
        preferences=[((3,), (0.8, ["email"], time(22, 0), time(7, 0), True))],
    )
    email = FakeSender("email")

    build(database, senders=[email]).run()

    assert email.sent == [7]
    assert [params for _query, params in database.matching("alert_type IS NULL")] == [(3,)]


def test_an_alert_below_the_confidence_threshold_is_marked_notified_without_a_send():
    """A weak alert is not worth a notification but is done with."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row(confidence=0.4)],
        preferences=[preference(channels=("email",), min_confidence=0.8)],
    )
    email = FakeSender("email")

    handled = build(database, senders=[email]).run()

    assert handled == 1
    assert email.sent == []
    assert database.marked() == [(7,)]


def test_a_disabled_preference_is_marked_notified_without_a_send():
    """A disabled preference silences the alert for good."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row()],
        preferences=[preference(channels=("email",), enabled=False)],
    )
    email = FakeSender("email")

    handled = build(database, senders=[email]).run()

    assert handled == 1
    assert email.sent == []
    assert database.marked() == [(7,)]


def test_an_unknown_channel_is_ignored_with_a_warning(caplog):
    """A channel without a sender must not break the run."""
    database = FakeDatabase(
        settings=settings_row(),
        alerts=[alert_row()],
        preferences=[preference(channels=("carrier_pigeon",))],
    )

    with caplog.at_level(logging.WARNING, logger="newstrading.notify.service"):
        handled = build(database, senders=[FakeSender("email")]).run()

    assert handled == 1
    assert "carrier_pigeon" in caplog.text
    assert database.logs() == []
    assert database.marked() == []


def test_the_alert_query_orders_newest_first_and_is_bounded():
    """The legacy order is kept and the batch carries a limit."""
    database = FakeDatabase(settings=settings_row(), alerts=[], preferences=[])

    build(database, senders=[]).run()

    (statement,) = database.matching("FROM alerts a")
    query, params = statement
    assert "WHERE a.notified = FALSE" in query
    assert "ORDER BY a.timestamp DESC" in query
    assert "LIMIT %s" in query
    assert params == (ALERT_BATCH_LIMIT,)


def test_the_settings_query_reads_the_single_row():
    """The service reads row 1 of notification_settings."""
    database = FakeDatabase(settings=settings_row(), alerts=[], preferences=[])

    build(database, senders=[]).run()

    (statement,) = database.matching("FROM notification_settings")
    query, params = statement
    assert "WHERE id = 1" in query
    assert params is None


def test_without_senders_the_service_builds_the_four_real_channels():
    """The production default is one sender per legacy channel."""
    service = NotificationService(SETTINGS, connector=connector(FakeDatabase()), now=lambda: NOON)

    assert [sender.channel for sender in service.senders] == list(CHANNELS)


def test_utcnow_is_timezone_aware():
    """The default clock is timezone aware so quiet hours can use local time."""
    assert utcnow().tzinfo is not None
