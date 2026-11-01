"""Parsing and prompt building for the AI analysis of collected posts.

The analysis slice has no database and no network of its own:

* :mod:`newstrading.analysis.parser` turns a model answer into an
  :class:`~newstrading.analysis.parser.Analysis`.
* :mod:`newstrading.analysis.prompt` builds the prompt that is sent to the model.

Keeping both pure is deliberate: the parts that can be wrong silently are the ones
that touch text, so they get tested without a database, a socket or a model.
"""

from newstrading.analysis.parser import Analysis, AnalysisParseError, parse_analysis
from newstrading.analysis.prompt import (
    DEFAULT_PROMPT_TEMPLATE,
    PromptBuilder,
    database_prompt_loader,
)

__all__ = [
    "DEFAULT_PROMPT_TEMPLATE",
    "Analysis",
    "AnalysisParseError",
    "PromptBuilder",
    "database_prompt_loader",
    "parse_analysis",
]
