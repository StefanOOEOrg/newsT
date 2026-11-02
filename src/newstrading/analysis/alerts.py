"""Turn one stored analysis into the alerts it warrants.

Ports ``AlertGenerator`` of ``analyzer/analysis_helpers.py``: the thresholds, the
severity bands, the description strings, the special-event table and the insert SQL are
the legacy ones, so old and new rows stay comparable.

The generator is the second seam to the database in this package: it gets its connection
factory injected, opens exactly one connection per call and is tested against a fake.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg2

from newstrading.analysis.parser import Analysis
from newstrading.config import Settings
from newstrading.db import Connector, connection
from newstrading.errors import NewsTradingError

logger = logging.getLogger(__name__)

SHORT_SIGNAL_THRESHOLD = -0.3
"""Below this sentiment score a short signal is generated (legacy, strict)."""

SHORT_SIGNAL_MEDIUM_THRESHOLD = -0.5
"""Below this score a short signal is ``medium`` (legacy, strict)."""

SHORT_SIGNAL_HIGH_THRESHOLD = -0.7
"""Below this score a short signal is ``high`` (legacy, strict)."""

SHORT_SIGNAL_PROBLEM_MEDIUM = -0.4
"""``Problems`` reaches ``medium`` below this score instead of the general one."""

SHORT_SIGNAL_PROBLEM_HIGH = -0.5
"""``Problems`` reaches ``high`` below this score instead of the general one."""

LONG_SIGNAL_THRESHOLD = 0.3
"""Above this sentiment score a long signal is generated (legacy, strict)."""

LONG_SIGNAL_MEDIUM_THRESHOLD = 0.5
"""Above this score a long signal is ``medium`` (legacy, strict)."""

LONG_SIGNAL_HIGH_THRESHOLD = 0.7
"""Above this score a long signal is ``high`` (legacy, strict)."""

BULLISH_CATEGORIES = ("Hiring", "Growth", "Earnings", "Product")
"""Categories a long signal needs; ``Problems`` and ``Other`` never trigger one."""

ALERT_SUMMARY_MAX_LENGTH = 180
"""Characters of ``analysis.summary`` that reach a signal description."""

EVENT_DESCRIPTION_MAX_LENGTH = ALERT_SUMMARY_MAX_LENGTH + 50
"""The legacy limit of an event description: 50 characters more than a signal's."""

_EVENT_STRONG_SENTIMENT = 0.3
"""Below this absolute score an event keeps its default severity."""

_NEUTRAL_EVENT_CONFIDENCE = 0.5
"""Confidence of an event that is neither bullish nor bearish."""

EVENT_ALERT_CONFIG: dict[str, tuple[str, str, bool | None]] = {
    "partnership_announced": ("partnership", "medium", True),
    "product_launch": ("product_launch", "medium", True),
    "regulatory_risk": ("regulatory_risk", "high", False),
    "analyst_upgrade": ("analyst_upgrade", "medium", True),
    "analyst_downgrade": ("analyst_downgrade", "medium", False),
    "market_share_gain": ("market_share", "medium", True),
    "customer_loss": ("customer_loss", "medium", False),
    "executive_change": ("executive_change", "medium", None),
    "guidance_raise": ("guidance", "high", True),
    "guidance_cut": ("guidance", "high", False),
    "insider_buying": ("insider_trading", "low", True),
    "insider_selling": ("insider_trading", "low", False),
}
"""Legacy ``EVENT_ALERT_CONFIG``: event -> ``(alert_type, severity, is_bullish)``."""

EVENT_NAMES = {
    "partnership_announced": "Partnership Announced",
    "product_launch": "Product Launch",
    "regulatory_risk": "Regulatory Risk",
    "analyst_upgrade": "Analyst Upgrade",
    "analyst_downgrade": "Analyst Downgrade",
    "market_share_gain": "Market Share Gain",
    "customer_loss": "Customer Loss",
    "executive_change": "Executive Change",
    "guidance_raise": "Guidance Raised",
    "guidance_cut": "Guidance Cut",
    "insider_buying": "Insider Buying",
    "insider_selling": "Insider Selling",
}
"""Legacy display names of the special events, used at the start of a description."""

INSERT_SQL = """
    INSERT INTO alerts
    (asset_id, alert_type, severity, description, confidence_score)
    VALUES (%s, %s, %s, %s, %s)
"""
"""The legacy insert, column for column."""


class AlertError(NewsTradingError):
    """Raised when the alerts of an analysis cannot be built or stored."""


@dataclass(frozen=True, slots=True)
class Alert:
    """One ``alerts`` row, complete except for the columns the database fills.

    Attributes:
        asset_id: Asset the alert belongs to; the notification pass joins ``asset`` on
            it, so an alert without one is never delivered.
        alert_type: ``short_signal``, ``long_signal`` or the event's legacy type.
        severity: ``low``, ``medium`` or ``high``.
        description: The legacy description string.
        confidence_score: ``abs(sentiment)`` for a short signal and an event that knows
            its direction, the raw sentiment for a long signal, ``0.5`` for a neutral
            event.
    """

    asset_id: int
    alert_type: str
    severity: str
    description: str
    confidence_score: float


class AlertGenerator:
    """Turns one analysis into the rows of ``alerts`` it warrants."""

    def __init__(self, settings: Settings, *, connector: Connector = psycopg2.connect) -> None:
        """Store the settings and the connection factory.

        Args:
            settings: Settings holding ``database_url``.
            connector: Factory used to open the connection. Injected in tests;
                production callers leave it at :func:`psycopg2.connect`.
        """
        self._settings = settings
        self._connector = connector

    def generate(self, analysis: Analysis) -> int:
        """Insert the alerts one analysis warrants; return how many rows were written.

        Args:
            analysis: The stored analysis to act on. It must carry the ``asset_id`` it
                was stored for; ``parser.Analysis`` has no such field, so the analyzer's
                ``on_analysis`` callback has to supply one (open question of #38).

        Returns:
            The number of alerts written: none for a neutral analysis in an ``Other``
            category without special events.

        Raises:
            AlertError: If the analysis carries no asset id, or if the rows cannot be
                stored. A failed write rolls the whole call back.

        Contract:
            * At most one alert per event plus at most one short and one long signal.
            * One connection per call, one commit at the end, closed in every case.
            * The SQL and the description strings are the legacy ones.
        """
        alerts = _alerts_for(analysis)
        try:
            with connection(self._settings, connector=self._connector) as db:
                with db.cursor() as cursor:
                    for alert in alerts:
                        cursor.execute(
                            INSERT_SQL,
                            (
                                alert.asset_id,
                                alert.alert_type,
                                alert.severity,
                                alert.description,
                                alert.confidence_score,
                            ),
                        )
        # boundary: driver failures become the generator's own error type
        except Exception as error:
            raise AlertError("cannot store the alerts of an analysis") from error
        return len(alerts)


def _alerts_for(analysis: Analysis) -> list[Alert]:
    """Build every alert ``analysis`` warrants, in the legacy order.

    Args:
        analysis: The analysis to act on, carrying its ``asset_id``.

    Returns:
        The short signal, then the long signal, then one alert per known event.

    Raises:
        AlertError: If the analysis carries no asset id.
    """
    asset_id = _asset_id(analysis)
    alerts = []
    short_signal = _short_signal(asset_id, analysis)
    if short_signal is not None:
        alerts.append(short_signal)
    long_signal = _long_signal(asset_id, analysis)
    if long_signal is not None:
        alerts.append(long_signal)
    alerts.extend(_event_alerts(asset_id, analysis))
    return alerts


def _asset_id(analysis: Analysis) -> int:
    """Return the asset the analysis belongs to.

    Args:
        analysis: The analysis to act on.

    Returns:
        Its ``asset_id``.

    Raises:
        AlertError: If the analysis carries no asset id. The notification pass joins
            ``asset`` on ``alerts.asset_id``, so a row without one would never be
            delivered — refusing it is better than storing it.
    """
    asset_id = getattr(analysis, "asset_id", None)
    if asset_id is None:
        raise AlertError(
            "the analysis carries no asset_id; the on_analysis callback of the analyzer "
            "must pass an analysis that names the asset it was stored for (#38)"
        )
    return int(asset_id)


def _short_signal(asset_id: int, analysis: Analysis) -> Alert | None:
    """Build the short signal of an analysis, if its sentiment is low enough.

    Args:
        asset_id: Asset the alert belongs to.
        analysis: The analysis to act on.

    Returns:
        The alert, or ``None`` when ``sentiment_score`` does not fall below
        :data:`SHORT_SIGNAL_THRESHOLD`.
    """
    sentiment = analysis.sentiment_score
    if not sentiment < SHORT_SIGNAL_THRESHOLD:
        return None
    severity, prefix = _short_severity(sentiment, analysis.category)
    if analysis.category == "Problems":
        context = "Problem reported"
    else:
        context = "Negative sentiment detected"
    description = f"{prefix}: {context} - {_summary(analysis)}"
    return Alert(asset_id, "short_signal", severity, description, abs(sentiment))


def _short_severity(sentiment: float, category: str) -> tuple[str, str]:
    """Return the legacy severity and description prefix of a short signal.

    Args:
        sentiment: The sentiment score, already below :data:`SHORT_SIGNAL_THRESHOLD`.
        category: The analysis category; ``Problems`` has its own two thresholds.

    Returns:
        ``(severity, description prefix)`` for the band the score falls into.
    """
    problem = category == "Problems"
    if sentiment < SHORT_SIGNAL_HIGH_THRESHOLD or (
        problem and sentiment < SHORT_SIGNAL_PROBLEM_HIGH
    ):
        return "high", "Strong short signal"
    if sentiment < SHORT_SIGNAL_MEDIUM_THRESHOLD or (
        problem and sentiment < SHORT_SIGNAL_PROBLEM_MEDIUM
    ):
        return "medium", "Moderate short signal"
    return "low", "Weak short signal"


def _long_signal(asset_id: int, analysis: Analysis) -> Alert | None:
    """Build the long signal of an analysis, if it warrants one.

    Args:
        asset_id: Asset the alert belongs to.
        analysis: The analysis to act on.

    Returns:
        The alert, or ``None`` when the score is not above
        :data:`LONG_SIGNAL_THRESHOLD` **or** the category is not bullish.
    """
    sentiment = analysis.sentiment_score
    if not (sentiment > LONG_SIGNAL_THRESHOLD and analysis.category in BULLISH_CATEGORIES):
        return None
    severity, prefix = _long_severity(sentiment)
    description = f"{prefix}: {analysis.category} activity detected - {_summary(analysis)}"
    return Alert(asset_id, "long_signal", severity, description, sentiment)


def _long_severity(sentiment: float) -> tuple[str, str]:
    """Return the legacy severity and description prefix of a long signal.

    Args:
        sentiment: The sentiment score, already above :data:`LONG_SIGNAL_THRESHOLD`.

    Returns:
        ``(severity, description prefix)`` for the band the score falls into.
    """
    if sentiment > LONG_SIGNAL_HIGH_THRESHOLD:
        return "high", "Strong long signal"
    if sentiment > LONG_SIGNAL_MEDIUM_THRESHOLD:
        return "medium", "Moderate long signal"
    return "low", "Weak long signal"


def _event_alerts(asset_id: int, analysis: Analysis) -> list[Alert]:
    """Build one alert per known special event of an analysis.

    Args:
        asset_id: Asset the alerts belong to.
        analysis: The analysis to act on.

    Returns:
        The alerts, in the order the model named the events. An unknown event type is
        logged and skipped, as in the legacy code.
    """
    alerts = []
    for event in analysis.special_events:
        config = EVENT_ALERT_CONFIG.get(event)
        if config is None:
            logger.warning("unknown special event type: %s", event)
            continue
        alert_type, default_severity, is_bullish = config
        severity = _event_severity(default_severity, analysis.sentiment_score, is_bullish)
        description = f"{_event_name(event)}: {analysis.summary}"
        alerts.append(
            Alert(
                asset_id,
                alert_type,
                severity,
                description[:EVENT_DESCRIPTION_MAX_LENGTH],
                _event_confidence(analysis.sentiment_score, is_bullish),
            )
        )
    return alerts


def _event_severity(default_severity: str, sentiment: float, is_bullish: bool | None) -> str:
    """Return the legacy severity of an event, raised by a strong sentiment.

    Args:
        default_severity: The event's severity from :data:`EVENT_ALERT_CONFIG`.
        sentiment: The sentiment score of the analysis.
        is_bullish: Direction of the event, ``None`` for a neutral one.

    Returns:
        ``default_severity``, or the next level up when a bullish event meets a score
        above ``0.7`` or a bearish one a score below ``-0.7``.
    """
    if is_bullish is None or abs(sentiment) < _EVENT_STRONG_SENTIMENT:
        return default_severity
    if is_bullish and sentiment > LONG_SIGNAL_HIGH_THRESHOLD:
        return _raised(default_severity)
    if not is_bullish and sentiment < SHORT_SIGNAL_HIGH_THRESHOLD:
        return _raised(default_severity)
    return default_severity


def _raised(severity: str) -> str:
    """Return the severity one level up, as the legacy code did.

    Args:
        severity: ``low``, ``medium`` or ``high``.

    Returns:
        ``medium`` for ``low``, ``high`` otherwise.
    """
    return "medium" if severity == "low" else "high"


def _event_confidence(sentiment: float, is_bullish: bool | None) -> float:
    """Return the legacy confidence score of an event.

    Args:
        sentiment: The sentiment score of the analysis.
        is_bullish: Direction of the event, ``None`` for a neutral one.

    Returns:
        ``abs(sentiment)`` for a directional event, ``0.5`` for a neutral one.
    """
    if is_bullish is None:
        return _NEUTRAL_EVENT_CONFIDENCE
    return abs(sentiment)


def _event_name(event: str) -> str:
    """Return the display name of an event type.

    Args:
        event: The event type named by the model.

    Returns:
        Its legacy display name, or the type with underscores replaced and title-cased
        for one the table does not know.
    """
    return EVENT_NAMES.get(event, event.replace("_", " ").title())


def _summary(analysis: Analysis) -> str:
    """Return the part of the summary a signal description may carry.

    Args:
        analysis: The analysis to act on.

    Returns:
        At most :data:`ALERT_SUMMARY_MAX_LENGTH` characters of its summary.
    """
    return analysis.summary[:ALERT_SUMMARY_MAX_LENGTH]
