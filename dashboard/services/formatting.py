"""Formatting utilities for dashboard UI."""
from typing import Optional


def get_sentiment_color(sentiment_score: Optional[float]) -> str:
    """
    Map sentiment score to color for UI display.

    Args:
        sentiment_score: Float between -1 and 1, or None

    Returns:
        Color string for UI ("gray", "green", "red", "orange")
    """
    if sentiment_score is None:
        return "gray"
    elif sentiment_score > 0.3:
        return "green"
    elif sentiment_score < -0.3:
        return "red"
    else:
        return "orange"


def get_sentiment_emoji(sentiment: str) -> str:
    """
    Map sentiment category to emoji.

    Args:
        sentiment: Sentiment category ("positive", "negative", "neutral")

    Returns:
        Emoji string
    """
    emoji_map = {
        "positive": "🟢",
        "negative": "🔴",
        "neutral": "🟡"
    }
    return emoji_map.get(sentiment, "⚪")
