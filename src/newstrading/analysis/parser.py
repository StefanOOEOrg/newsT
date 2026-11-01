"""Turn one model answer into a validated :class:`Analysis`.

The model is asked for a single JSON object, but the answer that arrives is not always
that: it may be wrapped in a ``` fence, prefixed with a sentence, followed by
commentary, or carry a number as a string. Only two things are treated as hard errors —
the sentiment (a wrong one is a wrong trading signal) and the summary (it is the text a
human reads). Everything else is normalised, because dropping a whole analysis over a
label costs more than mapping it.
"""

import json
from dataclasses import dataclass

from newstrading.errors import NewsTradingError

SENTIMENTS = frozenset({"positive", "negative", "neutral"})
"""Accepted values of ``sentiment``. Anything else is a hard error."""

CATEGORIES = (
    "Hiring",
    "Growth",
    "Problems",
    "Product",
    "Earnings",
    "Other",
)
"""Known values of ``category``. An unknown category becomes ``Other``."""

_JSON_FENCE = "```"

_EXCERPT_LENGTH = 80


class AnalysisParseError(NewsTradingError):
    """Raised when a model answer cannot be turned into an :class:`Analysis`."""


@dataclass(frozen=True)
class Analysis:
    """A validated analysis of one post.

    Frozen on purpose: a parsed analysis is a result, not a buffer. Callers that need
    to add context (post id, asset id) keep it next to this object, they do not mutate
    it.

    Attributes:
        sentiment: ``positive``, ``negative`` or ``neutral``.
        sentiment_score: Bullish/bearish strength in ``[-1.0, 1.0]``.
        category: One of :data:`CATEGORIES`; ``Other`` when the model named an
            unknown one.
        key_topics: Themes the model named, in model order, without empties.
        summary: One to two sentences, the text a human reads.
        special_events: Named events, empty tuple when the model named none.
    """

    sentiment: str
    sentiment_score: float
    category: str
    key_topics: tuple[str, ...]
    summary: str
    special_events: tuple[str, ...] = ()


def parse_analysis(text: str) -> Analysis:
    """Parse a model answer into an :class:`Analysis`.

    Args:
        text: The raw answer of the model, as returned by the completion client.

    Returns:
        The validated analysis.

    Raises:
        AnalysisParseError: If no JSON object can be found in ``text``, if it is not a
            JSON object, or if a field is missing or carries an unusable value. The
            message names the field or shows at most the first 80 characters of
            ``text`` — never the whole answer, which may be long.

    Contract:
        * A leading ``` fence with or without a language tag (``json``) is stripped, and
          so is a trailing fence.
        * Text before or after the JSON object is ignored: the first ``{`` starts the
          object, and everything the decoder accepts from there on is the answer.
        * ``sentiment`` must be one of :data:`SENTIMENTS` (compared case-insensitively
          and stripped); an unknown value raises.
        * ``sentiment_score`` may be a number or a numeric string; it is clamped into
          ``[-1.0, 1.0]``. A non-numeric value raises.
        * ``category`` is matched case-insensitively against :data:`CATEGORIES`;
          anything else becomes ``Other``.
        * ``key_topics`` and ``special_events`` may be a list, a comma-separated string
          or a JSON-array string; they become tuples of stripped, non-empty strings.
          Absent or ``null`` becomes the empty tuple. Neither is required.
        * ``summary`` must be a non-empty string after stripping; missing or empty
          raises.
    """
    data = _json_object(text)

    sentiment = data.get("sentiment")
    if not isinstance(sentiment, str) or sentiment.strip().lower() not in SENTIMENTS:
        raise AnalysisParseError(f"sentiment is not one of {sorted(SENTIMENTS)}: {sentiment!r}")

    if "sentiment_score" not in data:
        raise AnalysisParseError("sentiment_score is missing")

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise AnalysisParseError("summary is missing or empty")

    return Analysis(
        sentiment=sentiment.strip().lower(),
        sentiment_score=_score(data["sentiment_score"]),
        category=_category(data.get("category")),
        key_topics=_topics(data.get("key_topics"), "key_topics"),
        summary=summary.strip(),
        special_events=_topics(data.get("special_events"), "special_events"),
    )


def _category(value: object) -> str:
    """Match ``value`` against :data:`CATEGORIES`, case-insensitively.

    Args:
        value: The raw ``category`` field, any type.

    Returns:
        The matching entry of :data:`CATEGORIES`, or ``Other`` for anything unknown.
    """
    if not isinstance(value, str):
        return "Other"
    wanted = value.strip().lower()
    for category in CATEGORIES:
        if category.lower() == wanted:
            return category
    return "Other"


def _json_object(text: str) -> dict:
    """Cut the first JSON object out of ``text`` and decode it.

    Args:
        text: Raw answer, fences and surrounding prose allowed.

    Returns:
        The decoded object.

    Raises:
        AnalysisParseError: If ``text`` holds no ``{``, nothing decodable from it, or
            the decoded value is not an object.

    Contract:
        * Fences are removed before searching, so a fenced object is found the same way
          as a bare one.
        * ``json.JSONDecoder().raw_decode`` is used from the first ``{``: valid JSON
          followed by prose must still parse, and the prose must be ignored.
        * Error messages carry at most the first 80 characters of the cleaned text.
    """
    cleaned = _unfence(text)
    start = cleaned.find("{")
    if start == -1:
        raise AnalysisParseError(f"no JSON object in the answer: {_excerpt(cleaned)}")
    try:
        decoded, _end = json.JSONDecoder().raw_decode(cleaned[start:])
    except ValueError as error:
        raise AnalysisParseError(
            f"cannot decode the JSON object in the answer: {_excerpt(cleaned)}"
        ) from error
    if not isinstance(decoded, dict):
        raise AnalysisParseError(f"the answer does not hold a JSON object: {_excerpt(cleaned)}")
    return decoded


def _unfence(text: str) -> str:
    """Strip a leading fence with an optional language tag and a trailing fence.

    Args:
        text: Raw answer that may be wrapped in a ``` fence.

    Returns:
        The text without its fence lines.
    """
    cleaned = text.strip()
    if cleaned.startswith(_JSON_FENCE):
        cleaned = cleaned[len(_JSON_FENCE) :].lstrip()
        if not cleaned.startswith("{") and "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
    if cleaned.rstrip().endswith(_JSON_FENCE):
        cleaned = cleaned.rstrip()[: -len(_JSON_FENCE)]
    return cleaned.strip()


def _excerpt(text: str) -> str:
    """Return at most the first :data:`_EXCERPT_LENGTH` characters of ``text``.

    Args:
        text: The cleaned model answer.

    Returns:
        The short excerpt used in error messages.
    """
    return text[:_EXCERPT_LENGTH]


def _topics(value: object, field: str) -> tuple[str, ...]:
    """Normalise a list-like field into a tuple of non-empty strings.

    Args:
        value: ``None``, a list, a comma-separated string or a JSON-array string.
        field: Field name, used in the error message.

    Returns:
        The normalised tuple; empty when ``value`` is ``None``.

    Raises:
        AnalysisParseError: If ``value`` is a JSON-array string that does not decode, or
            a type that is neither string nor list.
    """
    if value is None:
        return ()
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            decoded = json.loads(value)
        except ValueError as error:
            raise AnalysisParseError(
                f"{field} is not a valid JSON array: {_excerpt(value)}"
            ) from error
        items = decoded if isinstance(decoded, list) else [decoded]
    elif isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        raise AnalysisParseError(f"{field} must be a list or a string, got {type(value).__name__}")

    topics = []
    for item in items:
        entry = str(item).strip()
        if entry:
            topics.append(entry)
    return tuple(topics)


def _score(value: object) -> float:
    """Turn ``sentiment_score`` into a float inside ``[-1.0, 1.0]``.

    Args:
        value: Number or numeric string. Booleans are rejected (``True`` is an int in
            Python and would silently become ``1.0``).

    Returns:
        The clamped float.

    Raises:
        AnalysisParseError: If ``value`` is missing, a boolean, or not numeric.
    """
    if isinstance(value, bool):
        raise AnalysisParseError(f"sentiment_score must be a number, got {value!r}")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise AnalysisParseError(f"sentiment_score must be a number, got {value!r}") from error
    return min(1.0, max(-1.0, number))
