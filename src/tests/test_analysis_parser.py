"""Tests for newstrading.analysis.parser.

Every case here is a shape a model answer really takes: fenced, prefixed, suffixed,
with a number as a string, with a category nobody configured. The parser is the seam
between "text a model produced" and "number a trader acts on", so the strictness is
deliberate and differs per field — see the module docstring of the parser.
"""

import dataclasses
import json

import pytest

from newstrading.analysis.parser import Analysis, AnalysisParseError, parse_analysis

GOOD = {
    "sentiment": "positive",
    "sentiment_score": 0.7,
    "category": "Hiring",
    "key_topics": ["hiring", "AI"],
    "summary": "The company is hiring in its AI division.",
    "special_events": ["partnership_announced"],
}


def as_json(**overrides) -> str:
    return json.dumps({**GOOD, **overrides})


def test_a_plain_json_object_is_parsed():
    analysis = parse_analysis(as_json())

    assert analysis == Analysis(
        sentiment="positive",
        sentiment_score=0.7,
        category="Hiring",
        key_topics=("hiring", "AI"),
        summary="The company is hiring in its AI division.",
        special_events=("partnership_announced",),
    )


@pytest.mark.parametrize("fence", ["```json", "```"])
def test_a_fenced_answer_is_parsed(fence):
    analysis = parse_analysis(f"{fence}\n{as_json()}\n```")

    assert analysis.sentiment == "positive"


def test_prose_around_the_object_is_ignored():
    text = f"Here is the analysis:\n{as_json()}\nLet me know if you need more."

    analysis = parse_analysis(text)

    assert analysis.category == "Hiring"


def test_sentiment_is_matched_without_case_and_whitespace():
    analysis = parse_analysis(as_json(sentiment="  NEUTRAL "))

    assert analysis.sentiment == "neutral"


def test_an_unknown_sentiment_is_an_error():
    with pytest.raises(AnalysisParseError, match="sentiment"):
        parse_analysis(as_json(sentiment="bullish"))


def test_a_missing_sentiment_is_an_error():
    payload = {k: v for k, v in GOOD.items() if k != "sentiment"}

    with pytest.raises(AnalysisParseError, match="sentiment"):
        parse_analysis(json.dumps(payload))


def test_a_score_sent_as_a_string_becomes_a_float():
    analysis = parse_analysis(as_json(sentiment_score="0.25"))

    assert analysis.sentiment_score == 0.25


@pytest.mark.parametrize(("raw", "expected"), [(3.0, 1.0), (-5, -1.0)])
def test_a_score_outside_the_range_is_clamped(raw, expected):
    analysis = parse_analysis(as_json(sentiment_score=raw))

    assert analysis.sentiment_score == expected


def test_a_boolean_score_is_refused():
    with pytest.raises(AnalysisParseError, match="sentiment_score"):
        parse_analysis(as_json(sentiment_score=True))


def test_a_non_numeric_score_is_refused():
    with pytest.raises(AnalysisParseError, match="sentiment_score"):
        parse_analysis(as_json(sentiment_score="very positive"))


@pytest.mark.parametrize(
    "raw",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        "nan",
        "Infinity",
        "-Infinity",
    ],
)
def test_a_non_finite_score_is_refused(raw):
    with pytest.raises(AnalysisParseError, match="sentiment_score"):
        parse_analysis(as_json(sentiment_score=raw))


def test_an_unknown_category_becomes_other():
    analysis = parse_analysis(as_json(category="Technology"))

    assert analysis.category == "Other"


def test_a_category_is_matched_without_case():
    analysis = parse_analysis(as_json(category="growth"))

    assert analysis.category == "Growth"


def test_topics_sent_as_a_comma_separated_string_are_split():
    analysis = parse_analysis(as_json(key_topics="hiring, ai , growth"))

    assert analysis.key_topics == ("hiring", "ai", "growth")


def test_topics_sent_as_a_json_array_string_are_decoded():
    analysis = parse_analysis(as_json(key_topics='["hiring", "ai"]'))

    assert analysis.key_topics == ("hiring", "ai")


def test_absent_topics_and_events_become_empty_tuples():
    payload = {k: v for k, v in GOOD.items() if k not in {"key_topics", "special_events"}}

    analysis = parse_analysis(json.dumps(payload))

    assert analysis.key_topics == ()
    assert analysis.special_events == ()


def test_an_empty_summary_is_an_error():
    with pytest.raises(AnalysisParseError, match="summary"):
        parse_analysis(as_json(summary="   "))


def test_text_without_a_json_object_is_an_error():
    with pytest.raises(AnalysisParseError, match=r"^.*no JSON object"):
        parse_analysis("I cannot analyse this post.")


def test_an_unparsable_object_names_the_input_but_does_not_dump_it():
    text = "{sentiment: positive, " + "x" * 400

    with pytest.raises(AnalysisParseError) as error:
        parse_analysis(text)

    message = str(error.value)
    assert "sentiment: positive" in message
    assert "x" * 400 not in message


def test_an_analysis_is_frozen():
    analysis = parse_analysis(as_json())

    with pytest.raises(dataclasses.FrozenInstanceError):
        analysis.summary = "changed"
