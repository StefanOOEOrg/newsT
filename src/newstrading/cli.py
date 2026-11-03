"""The ``newstrading`` command line: one process, one command, one exit code.

The legacy entry points returned success when the configuration was missing (finding 10 of
issue #3). Here every command resolves the variables it needs before it does any work, and
a missing variable is exit code 2 with a message that names it.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from newstrading import __version__
from newstrading.analysis.alerts import AlertGenerator
from newstrading.analysis.metrics import update_daily_metrics
from newstrading.analysis.parser import Analysis
from newstrading.collectors.assets import AssetStore
from newstrading.collectors.factories import SOURCE_NAMES, build_registry
from newstrading.collectors.posts import PostStore
from newstrading.collectors.prices import PriceStore, StockPriceCollector
from newstrading.collectors.registry import CollectorError
from newstrading.config import Settings, from_env
from newstrading.db import connect
from newstrading.errors import CollectorConfigError, ConfigError, NewsTradingError
from newstrading.keywords import KeywordTracker
from newstrading.logging_config import configure_logging
from newstrading.notify.service import NotificationService
from newstrading.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2

DEFAULT_DASHBOARD_PORT = 8088
"""Default port of ``newstrading dashboard``; the server's default is the same."""

COMMANDS = ("init-db", "collect", "analyze", "notify", "dashboard")

REQUIRED_VARIABLES: dict[str, tuple[str, ...]] = {
    "init-db": ("DATABASE_URL",),
    "collect": ("DATABASE_URL",),
    # ``LLM_PROVIDER=anthropic`` additionally needs ``ANTHROPIC_API_KEY``; that
    # condition depends on a value and is therefore checked by ``config.from_env``.
    "analyze": ("DATABASE_URL",),
    "notify": ("DATABASE_URL",),
    "dashboard": ("DATABASE_URL",),
}

_SCHEMA_FILE = "schema.sql"
_RESET_FILE = "reset.sql"
_UNUSED_ANALYSIS_KEY = "not-configured"
_PREFILL = "sentiment:"


def build_parser() -> argparse.ArgumentParser:
    """The CLI: sub-commands ``init-db``, ``collect``, ``analyze``, ``notify``, ``dashboard``."""
    parser = argparse.ArgumentParser(
        prog="newstrading",
        description="Collect, analyze and notify on news-driven trading signals.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print the traceback of a runtime failure",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    bootstrap = commands.add_parser(
        "init-db",
        help="create the missing tables; the data of a populated database is kept",
        description="Apply sql/schema.sql: create the tables and indexes that are missing and "
        "keep every row of a populated database. Only --reset drops the tables first.",
    )
    bootstrap.add_argument(
        "--reset",
        action="store_true",
        help="drop every table of the schema before creating it again (destroys all data)",
    )
    commands.add_parser("collect", help="run one collection pass over every source")
    commands.add_parser("analyze", help="run one analysis pass over the waiting posts")
    commands.add_parser("notify", help="run one notification pass")
    dashboard = commands.add_parser(
        "dashboard",
        help="serve the read-only dashboard API and the built web app",
        description="Serve the read-only JSON API under /api and the built Angular app "
        "under / on 127.0.0.1. The app is served when web/dist exists; build it first "
        "with 'ng build' in web/.",
    )
    dashboard.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DASHBOARD_PORT,
        help=f"TCP port of the server (default: {DEFAULT_DASHBOARD_PORT})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the process exit code.

    Exit codes: 0 success, 2 missing or invalid configuration (the message names the variable),
    1 a runtime failure. Configuration errors must not print a success line.
    """
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as stop:
        # ``--help`` and ``--version`` end here, as does a missing command (usage, code 2).
        return int(stop.code or EXIT_OK)
    try:
        settings = settings_for(arguments.command)
        configure_logging(settings)
        reset = getattr(arguments, "reset", False)
        port = getattr(arguments, "port", DEFAULT_DASHBOARD_PORT)
        return run_command(arguments.command, settings, reset=reset, port=port)
    except (ConfigError, CollectorConfigError, CollectorError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception as error:
        if arguments.verbose:
            traceback.print_exc()
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILURE


def settings_for(command: str, environ: Mapping[str, str] | None = None) -> Settings:
    """Build the settings one command needs from the environment.

    Args:
        command: The sub-command that will run.
        environ: Mapping to read; ``None`` (the default) means ``os.environ``.

    Returns:
        Settings with the variables of that command resolved.

    Raises:
        ConfigError: If a variable the command needs is missing or empty, or if a
            configured value is invalid. The message names the variables.
    """
    source = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_VARIABLES[command] if not source.get(name)]
    if missing:
        raise ConfigError(f"missing required environment variables: {', '.join(missing)}")
    values = dict(source)
    if command != "analyze":
        # Only ``analyze`` calls the model, so the other commands must not fail on a
        # missing ``ANTHROPIC_API_KEY`` even with ``LLM_PROVIDER=anthropic``: they hand
        # ``from_env`` a placeholder and drop it again below.
        values.setdefault("ANTHROPIC_API_KEY", _UNUSED_ANALYSIS_KEY)
    settings = from_env(values)
    if command == "analyze":
        return settings
    return replace(settings, anthropic_api_key=source.get("ANTHROPIC_API_KEY", ""))


def run_command(
    command: str, settings: Settings, *, reset: bool = False, port: int = DEFAULT_DASHBOARD_PORT
) -> int:
    """Run ``command`` and return its exit code.

    Args:
        command: One of :data:`COMMANDS`.
        settings: Resolved settings of the process.
        reset: ``init-db`` only: drop every table before applying the schema.
        port: ``dashboard`` only: TCP port of the server.

    Returns:
        ``0`` when the command finished.

    Raises:
        Exception: Whatever the command raises; :func:`main` maps it to an exit code.
    """
    if command == "init-db":
        init_db(settings, reset=reset)
        logger.info(
            "database recreated from an empty schema"
            if reset
            else "database schema applied; existing data kept"
        )
    elif command == "collect":
        logger.info("%d post(s) stored", collect_once(settings))
        logger.info("%d price bar(s) stored", _stored_prices(settings))
    elif command == "analyze":
        logger.info("%d post(s) analyzed", analyze_pending(settings))
    elif command == "dashboard":
        # deferred like the analyzer: only this command loads the web server
        from newstrading.dashboard.api import serve

        serve(settings, port=port)
    else:
        logger.info("%d alert(s) handled", NotificationService(settings).run())
    return EXIT_OK


def init_db(settings: Settings, *, reset: bool = False) -> None:
    """Apply the consolidated schema to the configured database.

    The default path is non-destructive: it creates the tables and indexes that are
    missing and keeps every row of a populated database. ``reset`` applies
    ``sql/reset.sql`` first, which drops the tables and therefore all data.

    Args:
        settings: Settings holding ``database_url``.
        reset: Drop every table before the schema runs; ``False`` (the default) keeps
            the data.

    Raises:
        ConfigError: If ``sql/schema.sql`` — or ``sql/reset.sql`` with ``reset`` — is
            not next to the working directory or the package.
        DatabaseError: If the database cannot be opened.
    """
    files = [_sql_file(_RESET_FILE)] if reset else []
    files.append(_sql_file(_SCHEMA_FILE))
    # ``db.Connection`` names only commit/rollback/close, so the cursor is not visible here.
    connection: Any = connect(settings.database_url)
    try:
        with connection.cursor() as cursor:
            for path in files:
                cursor.execute(path.read_text(encoding="utf-8"))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _sql_file(name: str) -> Path:
    """Return the SQL file of the repository or of the image, wherever it is."""
    for directory in (Path.cwd(), Path(__file__).resolve().parents[2]):
        candidate = directory.joinpath("sql", name)
        if candidate.is_file():
            return candidate
    raise ConfigError(f"sql/{name} not found; run the command from the repository root")


_UNKEYED_SOURCES: tuple[str, ...] = ("rss", "congressional_trades")
_KEYED_SOURCES: tuple[tuple[str, str], ...] = (
    ("newsapi", "newsapi_key"),
    ("finnhub", "finnhub_api_key"),
    ("alphavantage", "alphavantage_api_key"),
)


def _configured_sources(settings: Settings) -> tuple[str, ...]:
    """Return the sources ``collect`` builds: the keyless ones plus every keyed one with a key."""
    enabled = {*_UNKEYED_SOURCES}
    enabled.update(name for name, field in _KEYED_SOURCES if getattr(settings, field))
    return tuple(name for name in SOURCE_NAMES if name in enabled)


def collect_once(settings: Settings) -> int:
    """Run one collection pass over every configured source and store what came back.

    ``rss`` and ``congressional_trades`` need no key and always run; ``newsapi``,
    ``finnhub`` and ``alphavantage`` run only when their key is set. A failing source is
    logged with its name and does not stop the others.

    Args:
        settings: Settings handed to the registry, the store and the collectors.

    Returns:
        The number of posts that were new.

    Raises:
        CollectorError: When a collector cannot be built — a missing API key of a
            configured source is a configuration error, not a skipped source.
        NewsTradingError: When the pass ran and every source failed.
    """
    registry = build_registry(settings)
    collectors = registry.create_all(_configured_sources(settings), settings)
    store = PostStore(settings, keyword_tracker=KeywordTracker(settings))
    stored = 0
    attempted = 0
    succeeded = 0
    for asset in AssetStore(settings).list_for_collection():
        for name, collector in collectors.items():
            attempted += 1
            try:
                stored += store.save(collector.collect_for_asset(asset))
            # boundary: one broken source must not abort the pass over the others
            except Exception:
                logger.exception(
                    "source %s failed for asset %s", name, getattr(asset, "name", asset)
                )
            else:
                succeeded += 1
    if attempted and not succeeded:
        raise NewsTradingError(f"every source failed: {', '.join(collectors)}")
    return stored


_PRICE_LIMIT_NAME = StockPriceCollector.name
"""Name of the price collector's quota row in ``rate_limit_config``."""


def collect_prices_once(settings: Settings) -> int:
    """Collect and store one round of price bars for every tracked asset.

    Runs after the post collectors of :func:`collect_once`; the quota row named
    ``stock_prices`` (``StockPriceCollector.name``) is checked before every Yahoo Finance call.

    Args:
        settings: Settings handed to the collector, the store and the limiter.

    Returns:
        The number of bars that were new.

    Contract:
        A failing asset is logged like a failing source and does not stop the pass over
        the other assets.
    """
    collector = StockPriceCollector(settings, limiter=RateLimiter(settings, _PRICE_LIMIT_NAME))
    store = PriceStore(settings)
    stored = 0
    for asset in AssetStore(settings).list_for_collection():
        try:
            stored += store.save(collector.collect_for_asset(asset))
        # boundary: one broken asset must not abort the price pass
        except Exception:
            logger.exception("price collection failed for asset %s", getattr(asset, "name", asset))
    return stored


def _stored_prices(settings: Settings) -> int:
    """Run the price pass of ``collect`` and report a whole-pass failure as a log line.

    Args:
        settings: Settings handed to :func:`collect_prices_once`.

    Returns:
        The number of new bars, or ``0`` when the pass failed; a price failure never
        fails the ``collect`` command, whose posts are already stored.
    """
    try:
        return collect_prices_once(settings)
    # boundary: prices are secondary; a broken price pass must not fail the post pass
    except Exception:
        logger.exception("price collection failed")
        return 0


def analyze_pending(settings: Settings) -> int:
    """Run one analysis pass over the posts that wait for a verdict.

    The pass stores the analyses, hands each stored one to the
    :class:`~newstrading.analysis.alerts.AlertGenerator` and refreshes ``daily_metrics``
    once the batch is done.

    Args:
        settings: Settings holding the database and the model configuration.

    Returns:
        The number of posts the pass handled.

    Raises:
        NewsTradingError: Whatever the analyzer, the alert generator or the metric
            update raises; :func:`main` maps it to an exit code.
    """
    generator = AlertGenerator(settings)
    analyzer = _analyzer(
        settings,
        on_analysis=lambda analysis, asset_id: generator.generate(analysis, asset_id),
    )
    handled = analyzer.analyze_pending()
    update_daily_metrics(settings)
    return handled


def _analyzer(settings: Settings, on_analysis: Callable[[Analysis, int], Any]) -> Any:
    """Build the analyzer of the analysis service for one ``analyze`` run.

    Args:
        settings: Settings the analyzer, its prompt builder and the model call read.
        on_analysis: Called with every analysis the run stores and the ``asset_id`` it
            was stored for.

    Returns:
        The analyzer; its ``analyze_pending`` runs one batch.

    Contract:
        The import is deferred so that ``collect``, ``notify`` and ``init-db`` never
        load the analysis service.
    """
    from newstrading.analysis.service import Analyzer

    return Analyzer(settings, complete=_completion(settings), on_analysis=on_analysis)


def _completion(settings: Settings) -> Callable[[str], str]:
    """Return the model call the analyzer uses: one prompt in, raw answer text out.

    Args:
        settings: Settings holding the model id, the token limit and the API key.

    Returns:
        A callable that sends the prompt with the legacy ``sentiment:`` prefill. An
        empty answer becomes ``""`` — the analyzer stores its neutral analysis for it.
        An answer that ignored the prefill and starts with JSON or a fence is returned
        unchanged, so the parser reads what the model actually said.
    """
    client = Anthropic(api_key=settings.anthropic_api_key)

    def complete(prompt: str) -> str:
        message = client.messages.create(
            model=settings.ai_model,
            max_tokens=settings.max_tokens,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": _PREFILL},
            ],
        )
        if not message.content:
            return ""
        text = getattr(message.content[0], "text", "")
        if text.lstrip().startswith(("{", "```")):
            return text
        return _PREFILL + text

    return complete


if __name__ == "__main__":
    raise SystemExit(main())
