"""Parsing, prompt building, analysis runs and performance tracking for collected posts.

Four modules, two kinds of purity:

* :mod:`newstrading.analysis.parser` turns a model answer into an
  :class:`~newstrading.analysis.parser.Analysis`; :mod:`newstrading.analysis.prompt`
  builds the prompt that is sent to the model. Both are pure: the parts that can be
  wrong silently are the ones that touch text, so they get tested without a database,
  a socket or a model.
* :mod:`newstrading.analysis.service` runs one analysis batch: it selects the posts
  without an analysis, calls the model through an injected callable and stores what
  comes back. :mod:`newstrading.analysis.performance` scores an alert against later
  prices. Both get their connection factory injected, so they open no socket of their
  own and never import ``yfinance``.

The service and the tracker are the two seams to the database: their SQL is the legacy
SQL, so old and new rows remain comparable.
"""

from newstrading.analysis.parser import Analysis, AnalysisParseError, parse_analysis
from newstrading.analysis.performance import PerformanceError, PerformanceTracker, PriceProvider
from newstrading.analysis.prompt import (
    DEFAULT_PROMPT_TEMPLATE,
    PromptBuilder,
    database_prompt_loader,
)
from newstrading.analysis.service import AnalysisError, Analyzer

__all__ = [
    "DEFAULT_PROMPT_TEMPLATE",
    "Analysis",
    "AnalysisError",
    "AnalysisParseError",
    "Analyzer",
    "PerformanceError",
    "PerformanceTracker",
    "PriceProvider",
    "PromptBuilder",
    "database_prompt_loader",
    "parse_analysis",
]
