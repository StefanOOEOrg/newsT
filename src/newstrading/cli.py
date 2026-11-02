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
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from newstrading import __version__
from newstrading.collectors.assets import AssetStore
from newstrading.collectors.factories import SOURCE_NAMES, build_registry
from newstrading.collectors.posts import PostStore
from newstrading.collectors.registry import CollectorError
from newstrading.config import Settings, from_env
from newstrading.db import connect
from newstrading.errors import CollectorConfigError, ConfigError, NewsTradingError
from newstrading.keywords import KeywordTracker
from newstrading.logging_config import configure_logging
from newstrading.notify.service import NotificationService

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2

COMMANDS = ("init-db", "collect", "analyze", "notify")

REQUIRED_VARIABLES: dict[str, tuple[str, ...]] = {
    "init-db": ("DATABASE_URL",),
    "collect": ("DATABASE_URL",),
    "analyze": ("DATABASE_URL", "ANTHROPIC_API_KEY"),
    "notify": ("DATABASE_URL",),
}

_SCHEMA_PATH = ("sql", "schema.sql")
_UNUSED_ANALYSIS_KEY = "not-configured"


def build_parser() -> argparse.ArgumentParser:
    """The CLI: sub-commands ``init-db``, ``collect``, ``analyze``, ``notify``; ``--version``."""
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
    commands.add_parser("init-db", help="create the schema in the configured database")
    commands.add_parser("collect", help="run one collection pass over every source")
    commands.add_parser("analyze", help="run one analysis pass over the waiting posts")
    commands.add_parser("notify", help="run one notification pass")
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
        return run_command(arguments.command, settings)
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
        # ``from_env`` validates the model key for every command; only ``analyze`` uses it,
        # so the other commands hand it a placeholder and drop it again below.
        values.setdefault("ANTHROPIC_API_KEY", _UNUSED_ANALYSIS_KEY)
    settings = from_env(values)
    if command == "analyze":
        return settings
    return replace(settings, anthropic_api_key=source.get("ANTHROPIC_API_KEY", ""))


def run_command(command: str, settings: Settings) -> int:
    """Run ``command`` and return its exit code.

    Args:
        command: One of :data:`COMMANDS`.
        settings: Resolved settings of the process.

    Returns:
        ``0`` when the command finished.

    Raises:
        Exception: Whatever the command raises; :func:`main` maps it to an exit code.
    """
    if command == "init-db":
        init_db(settings)
        logger.info("database schema applied")
    elif command == "collect":
        logger.info("%d post(s) stored", collect_once(settings))
    elif command == "analyze":
        logger.info("%d post(s) analyzed", analyze_pending(settings))
    else:
        logger.info("%d alert(s) handled", NotificationService(settings).run())
    return EXIT_OK


def init_db(settings: Settings) -> None:
    """Apply the consolidated schema to the configured database.

    Args:
        settings: Settings holding ``database_url``.

    Raises:
        ConfigError: If ``sql/schema.sql`` is not next to the working directory or the
            package.
        DatabaseError: If the database cannot be opened.
    """
    schema = _schema_file().read_text(encoding="utf-8")
    # ``db.Connection`` names only commit/rollback/close, so the cursor is not visible here.
    connection: Any = connect(settings.database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(schema)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _schema_file() -> Path:
    """Return the schema file of the repository or of the image, wherever it is."""
    for directory in (Path.cwd(), Path(__file__).resolve().parents[2]):
        candidate = directory.joinpath(*_SCHEMA_PATH)
        if candidate.is_file():
            return candidate
    raise ConfigError("sql/schema.sql not found; run the command from the repository root")


def collect_once(settings: Settings) -> int:
    """Run one collection pass over every source and store what came back.

    Args:
        settings: Settings handed to the registry, the store and the collectors.

    Returns:
        The number of posts that were new.

    Raises:
        CollectorError: When a collector cannot be built — a missing API key is a
            configuration error, not a skipped source.
    """
    registry = build_registry(settings)
    collectors = registry.create_all(SOURCE_NAMES, settings)
    store = PostStore(settings, keyword_tracker=KeywordTracker(settings))
    stored = 0
    for asset in AssetStore(settings).list_for_collection():
        for collector in collectors.values():
            stored += store.save(collector.collect_for_asset(asset))
    return stored


def analyze_pending(settings: Settings) -> int:
    """Run one analysis pass over the posts that wait for a verdict.

    Args:
        settings: Settings holding the database and the model configuration.

    Returns:
        The number of posts the pass handled.

    Raises:
        NewsTradingError: Until the analysis service is ported. The package has the
            prompt builder and the parser, but no service that calls the model and writes
            ``ai_analysis`` rows yet (open question of #22).
    """
    raise NewsTradingError("the analysis service is not part of the package yet")


if __name__ == "__main__":
    raise SystemExit(main())
