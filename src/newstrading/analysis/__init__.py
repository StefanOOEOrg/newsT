"""Parsing, prompt building, alerting, metrics and performance tracking of analyses.

These modules come in two kinds of purity:

* :mod:`newstrading.analysis.parser` turns a model answer into an
  :class:`~newstrading.analysis.parser.Analysis`; :mod:`newstrading.analysis.prompt`
  builds the prompt that is sent to the model. Both are pure: the parts that can be
  wrong silently are the ones that touch text, so they get tested without a database,
  a socket or a model.
* :mod:`newstrading.analysis.alerts` turns a stored analysis into ``alerts`` rows and
  :mod:`newstrading.analysis.metrics` rebuilds ``daily_metrics`` from the analyses.
  :mod:`newstrading.analysis.performance` scores an alert against later prices. All
  three get their connection factory injected, so they open no socket of their own;
  the tracker never imports ``yfinance`` either.

Those three are the seams to the database: their SQL is the legacy SQL, so old and new
rows remain comparable.
"""

from newstrading.analysis.alerts import Alert, AlertError, AlertGenerator
from newstrading.analysis.metrics import MetricsError, update_daily_metrics
from newstrading.analysis.parser import Analysis, AnalysisParseError, parse_analysis
from newstrading.analysis.performance import PerformanceError, PerformanceTracker, PriceProvider
from newstrading.analysis.prompt import (
    DEFAULT_PROMPT_TEMPLATE,
    PromptBuilder,
    database_prompt_loader,
)

__all__ = [
    "DEFAULT_PROMPT_TEMPLATE",
    "Alert",
    "AlertError",
    "AlertGenerator",
    "Analysis",
    "AnalysisParseError",
    "MetricsError",
    "PerformanceError",
    "PerformanceTracker",
    "PriceProvider",
    "PromptBuilder",
    "database_prompt_loader",
    "parse_analysis",
    "update_daily_metrics",
]
