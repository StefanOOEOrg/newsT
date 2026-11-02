"""Parsing, prompt building and performance tracking for the AI analysis of collected posts.

Three modules, two kinds of purity:

* :mod:`newstrading.analysis.parser` turns a model answer into an
  :class:`~newstrading.analysis.parser.Analysis`; :mod:`newstrading.analysis.prompt`
  builds the prompt that is sent to the model. Both are pure: the parts that can be
  wrong silently are the ones that touch text, so they get tested without a database,
  a socket or a model.
* :mod:`newstrading.analysis.performance` scores an alert against later prices. It gets
  its connection factory and its price provider injected, so it opens no socket of its
  own and never imports ``yfinance``.

The tracker is the one seam to the database: its SQL is the legacy SQL, so old and new
rows remain comparable.
"""

from newstrading.analysis.parser import Analysis, AnalysisParseError, parse_analysis
from newstrading.analysis.performance import PerformanceError, PerformanceTracker, PriceProvider
from newstrading.analysis.prompt import (
    DEFAULT_PROMPT_TEMPLATE,
    PromptBuilder,
    database_prompt_loader,
)

__all__ = [
    "DEFAULT_PROMPT_TEMPLATE",
    "Analysis",
    "AnalysisParseError",
    "PerformanceError",
    "PerformanceTracker",
    "PriceProvider",
    "PromptBuilder",
    "database_prompt_loader",
    "parse_analysis",
]
