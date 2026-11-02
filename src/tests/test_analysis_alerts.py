"""Tests for newstrading.analysis.alerts.

The generator ports ``AlertGenerator`` of ``analyzer/analysis_helpers.py``, so every
expectation here is the legacy one: the thresholds are strict (a score of exactly
``-0.3`` is no signal), the ``Problems`` category has its own two short-signal
thresholds, a long signal needs a bullish category, and the description strings are
copied verbatim. No database is involved — a fake connection records the statements.

``parser.Analysis`` carries no asset id, so the tests build :class:`StoredAnalysis`, the
subclass the analyzer's ``on_analysis`` callback has to pass (open question of #38).
"""

from dataclasses import dataclass

import pytest

from newstrading.analysis.alerts import (
    ALERT_SUMMARY_MAX_LENGTH,
    EVENT_DESCRIPTION_MAX_LENGTH,
    INSERT_SQL,
    AlertError,
    AlertGenerator,
)
from newstrading.analysis.parser import Analysis
from newstrading.config import Settings

URL = "postgresql://app:***@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")

ASSET_ID = 7
SUMMARY = "A short summary of the post."


@dataclass(frozen=True)
class StoredAnalysis(Analysis):
    """An analysis plus the asset it was stored for (the seam #38 still needs)."""

    asset_id: int = ASSET_ID


def analysis(sentiment_score=0.0, category="Other", summary=SUMMARY, events=()):
    """Build a stored analysis of :data:`ASSET_ID`."""
    return StoredAnalysis(
        sentiment="neutral",
        sentiment_score=sentiment_score,
        category=category,
        key_topics=(),
        summary=summary,
        special_events=tuple(events),
    )


class FakeCursor:
    """Records every statement and can fail on the ones it is told to."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement, parameters=None):
        self._connection.statements.append((statement, parameters))
        if self._connection.fail_on and self._connection.fail_on in statement:
            raise RuntimeError("connection lost")


class FakeConnection:
    """A connection that records commit, rollback and close."""

    def __init__(self, fail_on=None):
        self.statements = []
        self.fail_on = fail_on
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def make_generator(fail_on=None):
    """Return a generator over a fake connection and the connection itself."""
    connection = FakeConnection(fail_on=fail_on)
    opened = []

    def connector(database_url):
        opened.append(database_url)
        return connection

    return AlertGenerator(SETTINGS, connector=connector), connection


def inserted(connection):
    """Return the parameters of the ``alerts`` inserts the fake connection saw."""
    return [
        parameters for statement, parameters in connection.statements if statement == INSERT_SQL
    ]


@pytest.mark.parametrize(
    ("score", "severity", "prefix"),
    [
        (-0.3, None, None),  # exactly the threshold: the legacy comparison is strict
        (-0.31, "low", "Weak short signal"),
        (-0.5, "low", "Weak short signal"),  # strict: ``-0.5`` is not below ``-0.5``
        (-0.51, "medium", "Moderate short signal"),
        (-0.7, "medium", "Moderate short signal"),
        (-0.71, "high", "Strong short signal"),
    ],
)
def test_the_short_signal_bands_are_the_legacy_ones(score, severity, prefix):
    """Each band of a non-``Problems`` short signal, boundaries included."""
    generator, connection = make_generator()

    written = generator.generate(analysis(score))

    if severity is None:
        assert written == 0
        assert inserted(connection) == []
        return
    assert written == 1
    assert inserted(connection) == [
        (
            ASSET_ID,
            "short_signal",
            severity,
            f"{prefix}: Negative sentiment detected - {SUMMARY}",
            abs(score),
        )
    ]


@pytest.mark.parametrize(
    ("score", "severity", "prefix"),
    [
        (-0.4, "low", "Weak short signal"),  # strict: ``-0.4`` is not below ``-0.4``
        (-0.41, "medium", "Moderate short signal"),
        (-0.5, "medium", "Moderate short signal"),
        (-0.51, "high", "Strong short signal"),
    ],
)
def test_problems_shifts_the_short_signal_bands(score, severity, prefix):
    """``Problems`` reaches ``medium`` at -0.4 and ``high`` at -0.5, not before."""
    generator, connection = make_generator()

    generator.generate(analysis(score, category="Problems"))

    assert inserted(connection) == [
        (
            ASSET_ID,
            "short_signal",
            severity,
            f"{prefix}: Problem reported - {SUMMARY}",
            abs(score),
        )
    ]


def test_problems_is_more_sensitive_than_the_general_short_signal_band():
    """The same score is ``low`` in another category and ``medium`` in ``Problems``."""
    general, general_connection = make_generator()
    problems, problems_connection = make_generator()

    general.generate(analysis(-0.41, category="Other"))
    problems.generate(analysis(-0.41, category="Problems"))

    assert inserted(general_connection)[0][2] == "low"
    assert inserted(problems_connection)[0][2] == "medium"


@pytest.mark.parametrize(
    ("score", "severity", "prefix"),
    [
        (0.3, None, None),  # exactly the threshold: the legacy comparison is strict
        (0.31, "low", "Weak long signal"),
        (0.5, "low", "Weak long signal"),
        (0.51, "medium", "Moderate long signal"),
        (0.7, "medium", "Moderate long signal"),
        (0.71, "high", "Strong long signal"),
    ],
)
def test_the_long_signal_bands_are_the_legacy_ones(score, severity, prefix):
    """Each band of a long signal in a bullish category, boundaries included."""
    generator, connection = make_generator()

    written = generator.generate(analysis(score, category="Product"))

    if severity is None:
        assert written == 0
        assert inserted(connection) == []
        return
    assert inserted(connection) == [
        (
            ASSET_ID,
            "long_signal",
            severity,
            f"{prefix}: Product activity detected - {SUMMARY}",
            score,
        )
    ]


def test_a_long_signal_needs_both_the_threshold_and_a_bullish_category():
    """``Product`` triggers and ``Legal`` does not, at the same high score."""
    bullish, bullish_connection = make_generator()
    legal, legal_connection = make_generator()
    problems, problems_connection = make_generator()

    assert bullish.generate(analysis(0.8, category="Product")) == 1
    assert legal.generate(analysis(0.8, category="Legal")) == 0
    assert problems.generate(analysis(0.8, category="Problems")) == 0

    assert inserted(bullish_connection)[0][1] == "long_signal"
    assert inserted(legal_connection) == []
    assert inserted(problems_connection) == []


def test_an_analysis_can_warrant_a_short_signal_and_events_together():
    """One short signal plus one alert per event, in the legacy order."""
    generator, connection = make_generator()
    stored = analysis(-0.6, events=("partnership_announced", "guidance_cut"))

    assert generator.generate(stored) == 3

    assert [parameters[1] for parameters in inserted(connection)] == [
        "short_signal",
        "partnership",
        "guidance",
    ]
    assert connection.commits == 1


def test_special_events_produce_one_alert_each_with_the_legacy_type_and_description():
    """Two events become two alerts with the legacy display names and severities."""
    generator, connection = make_generator()

    assert generator.generate(analysis(0.2, events=("partnership_announced", "guidance_cut"))) == 2

    assert inserted(connection) == [
        (
            ASSET_ID,
            "partnership",
            "medium",
            f"Partnership Announced: {SUMMARY}",
            0.2,
        ),
        (
            ASSET_ID,
            "guidance",
            "high",
            f"Guidance Cut: {SUMMARY}",
            0.2,
        ),
    ]


def test_no_special_events_produce_no_event_alert():
    """An empty event list is no alert, not an alert with an empty type."""
    generator, connection = make_generator()

    assert generator.generate(analysis(0.2, events=())) == 0

    assert inserted(connection) == []
    assert connection.commits == 1
    assert connection.closes == 1


@pytest.mark.parametrize(
    ("score", "event", "description", "severity", "confidence"),
    [
        (0.8, "partnership_announced", "Partnership Announced", "high", 0.8),
        (-0.8, "customer_loss", "Customer Loss", "high", 0.8),
        (-0.8, "insider_selling", "Insider Selling", "medium", 0.8),
        (0.2, "partnership_announced", "Partnership Announced", "medium", 0.2),
        (0.9, "executive_change", "Executive Change", "medium", 0.5),
    ],
)
def test_an_event_raises_its_severity_with_a_strong_sentiment(
    score, event, description, severity, confidence
):
    """The legacy adjustment of an event's severity and confidence."""
    generator, connection = make_generator()

    generator.generate(analysis(score, events=(event,)))

    event_alert = next(
        parameters for parameters in inserted(connection) if parameters[1] != "short_signal"
    )
    assert event_alert[2] == severity
    assert event_alert[3] == f"{description}: {SUMMARY}"
    assert event_alert[4] == confidence


def test_an_unknown_special_event_is_skipped():
    """A type the legacy table does not know is logged and produces no alert."""
    generator, connection = make_generator()

    assert generator.generate(analysis(0.2, events=("not_a_type",))) == 0

    assert inserted(connection) == []


def test_a_signal_description_carries_at_most_the_summary_limit():
    """The legacy ``summary[:ALERT_SUMMARY_MAX_LENGTH]`` cut."""
    generator, connection = make_generator()
    long_summary = "x" * (ALERT_SUMMARY_MAX_LENGTH + 50)

    generator.generate(analysis(-0.8, summary=long_summary))

    description = inserted(connection)[0][3]
    assert description.endswith("x" * ALERT_SUMMARY_MAX_LENGTH)
    assert len(description) == len("Strong short signal: Negative sentiment detected - ") + (
        ALERT_SUMMARY_MAX_LENGTH
    )


def test_an_event_description_carries_the_legacy_fifty_extra_characters():
    """An event description is cut at ``ALERT_SUMMARY_MAX_LENGTH + 50``."""
    generator, connection = make_generator()
    long_summary = "y" * (EVENT_DESCRIPTION_MAX_LENGTH + 50)

    generator.generate(analysis(0.2, summary=long_summary, events=("partnership_announced",)))

    description = inserted(connection)[0][3]
    assert len(description) == EVENT_DESCRIPTION_MAX_LENGTH
    assert description.startswith("Partnership Announced: ")


def test_a_database_error_rolls_back_and_raises_the_named_error():
    """A failing insert leaves no half-written transaction behind."""
    generator, connection = make_generator(fail_on="INSERT INTO alerts")

    with pytest.raises(AlertError):
        generator.generate(analysis(-0.8, events=("product_launch",)))

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.closes == 1


def test_an_analysis_without_an_asset_id_is_refused():
    """A row nobody could deliver is not written: the callback must name the asset."""
    opened = []

    def connector(database_url):
        opened.append(database_url)
        return FakeConnection()

    generator = AlertGenerator(SETTINGS, connector=connector)

    with pytest.raises(AlertError, match="asset_id"):
        generator.generate(
            Analysis(
                sentiment="neutral",
                sentiment_score=0.0,
                category="Other",
                key_topics=(),
                summary=SUMMARY,
            )
        )

    assert opened == []
