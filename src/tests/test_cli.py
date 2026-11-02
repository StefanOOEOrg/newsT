"""Tests for newstrading.cli: the four commands, their dispatch and their exit codes."""

import logging
import re
from dataclasses import replace
from pathlib import Path

import pytest

from newstrading import __version__
from newstrading.cli import build_parser, collect_once, init_db, main
from newstrading.config import Settings

ROOT = Path(__file__).resolve().parents[2]
URL = "postgresql://app:secret@db.internal:5432/newstrading"
SETTINGS = Settings(database_url=URL, anthropic_api_key="sk-test")
KEYED_SETTINGS = replace(
    SETTINGS,
    newsapi_key="newsapi-key",
    finnhub_api_key="finnhub-key",
    alphavantage_api_key="alphavantage-key",
)

COMMANDS = ("init-db", "collect", "analyze", "notify")

CONFIGURED = (
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "NEWSAPI_KEY",
    "FINNHUB_API_KEY",
    "ALPHAVANTAGE_API_KEY",
    "CONGRESS_TRADES_API_KEY",
    "CONGRESS_TRADES_API_URL",
)


class FakeCursor:
    """Collects the statements executed on a fake connection."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement, parameters=None):
        self._connection.statements.append((statement, parameters))


class FakeConnection:
    """A connection that records commit, rollback and close."""

    def __init__(self):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    """Clear every variable the CLI reads, and keep logging away from the database."""
    for name in CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("newstrading.cli.configure_logging", lambda settings: None)
    return monkeypatch


class StaticCollector:
    """A collector that returns the posts it was given."""

    def __init__(self, posts):
        self._posts = posts
        self.assets = []

    def collect_for_asset(self, asset):
        self.assets.append(asset)
        return list(self._posts)


class BrokenCollector:
    """A collector whose source is down."""

    def __init__(self, error="feed exploded"):
        self._error = error
        self.calls = 0

    def collect_for_asset(self, asset):
        self.calls += 1
        raise RuntimeError(self._error)


class FakeAssetStore:
    """Serves a fixed asset list; usable as the ``AssetStore`` class double."""

    def __init__(self, assets):
        self._assets = tuple(assets)

    def __call__(self, settings):
        return self

    def list_for_collection(self):
        return list(self._assets)


class RecordingStore:
    """Records what the collectors hand to the store."""

    def __init__(self):
        self.saved = []

    def __call__(self, settings, *, keyword_tracker):
        return self

    def save(self, collected):
        self.saved.append(list(collected))
        return len(collected)


def install_collection(environment, collectors, assets=("first",)):
    """Patch the collaborators of ``collect_once`` and record the sources it builds."""
    names = []
    store = RecordingStore()

    class FakeRegistry:
        def create_all(self, requested, settings):
            names.extend(requested)
            return collectors

    environment.setattr("newstrading.cli.build_registry", lambda settings: FakeRegistry())
    environment.setattr("newstrading.cli.AssetStore", FakeAssetStore(assets))
    environment.setattr("newstrading.cli.PostStore", store)
    environment.setattr("newstrading.cli.KeywordTracker", lambda settings: object())
    return names, store


def test_build_parser_exposes_the_four_commands():
    """Each command is its own sub-parser, and the parser knows its name."""
    parser = build_parser()

    assert [parser.parse_args([command]).command for command in COMMANDS] == list(COMMANDS)


def test_main_without_a_command_exits_2_with_the_usage_line(capsys):
    """No command is a usage error, not a silent success."""
    assert main([]) == 2

    assert "usage:" in capsys.readouterr().err


def test_main_with_version_prints_the_version_and_exits_0(capsys):
    """``--version`` is a successful run."""
    assert main(["--version"]) == 0

    assert __version__ in capsys.readouterr().out


def test_main_init_db_dispatches_to_the_bootstrap(environment, capsys):
    """``init-db`` hands the resolved settings to the bootstrap."""
    environment.setenv("DATABASE_URL", URL)
    seen = []
    environment.setattr("newstrading.cli.init_db", seen.append)

    assert main(["init-db"]) == 0

    assert [settings.database_url for settings in seen] == [URL]
    assert capsys.readouterr().err == ""


def test_main_collect_dispatches_to_the_collection_pass(environment):
    """``collect`` runs exactly one pass."""
    environment.setenv("DATABASE_URL", URL)
    calls = []
    environment.setattr(
        "newstrading.cli.collect_once", lambda settings: calls.append(settings) or 3
    )

    assert main(["collect"]) == 0

    assert [settings.database_url for settings in calls] == [URL]


def test_main_analyze_dispatches_to_the_analysis_pass(environment):
    """``analyze`` runs exactly one pass and needs the model key."""
    environment.setenv("DATABASE_URL", URL)
    environment.setenv("ANTHROPIC_API_KEY", "sk-test")
    calls = []
    environment.setattr(
        "newstrading.cli.analyze_pending", lambda settings: calls.append(settings) or 0
    )

    assert main(["analyze"]) == 0

    assert [settings.anthropic_api_key for settings in calls] == ["sk-test"]


def test_main_notify_dispatches_to_the_notification_service(environment):
    """``notify`` builds the service with the settings and runs one pass."""
    environment.setenv("DATABASE_URL", URL)
    services = []

    class FakeNotificationService:
        def __init__(self, settings):
            self.settings = settings
            self.runs = 0
            services.append(self)

        def run(self):
            self.runs += 1
            return 0

    environment.setattr("newstrading.cli.NotificationService", FakeNotificationService)

    assert main(["notify"]) == 0

    assert services[0].runs == 1
    assert services[0].settings.database_url == URL


@pytest.mark.parametrize("command", COMMANDS)
def test_missing_database_url_exits_2_and_names_the_variable(environment, capsys, command):
    """A missing variable is a configuration error — exit 2, one line, no success."""
    assert main([command]) == 2

    error = capsys.readouterr().err
    assert "DATABASE_URL" in error
    assert "error:" in error
    assert "Traceback" not in error
    assert error.strip().count("\n") == 0


def test_missing_database_url_does_not_run_the_bootstrap(environment, capsys):
    """The command must not run with half a configuration."""
    seen = []
    environment.setattr("newstrading.cli.init_db", seen.append)

    assert main(["init-db"]) == 2

    assert seen == []
    assert "DATABASE_URL" in capsys.readouterr().err


def test_analyze_without_the_model_key_exits_2_and_names_it(environment, capsys):
    """``analyze`` alone needs ``ANTHROPIC_API_KEY``; it exits 2 before any analysis."""
    environment.setenv("DATABASE_URL", URL)
    calls = []
    environment.setattr("newstrading.cli.analyze_pending", calls.append)

    assert main(["analyze"]) == 2

    error = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in error
    assert calls == []


def test_collect_builds_only_the_sources_without_a_key(environment):
    """Only ``DATABASE_URL``: the two free sources run and the keyed ones are never built."""
    environment.setenv("DATABASE_URL", URL)
    posts = [object(), object()]
    names, store = install_collection(
        environment,
        {"rss": StaticCollector(posts), "congressional_trades": StaticCollector([])},
    )

    assert main(["collect"]) == 0

    assert names == ["rss", "congressional_trades"]
    assert store.saved == [posts, []]


@pytest.mark.parametrize(
    ("variable", "source"),
    [
        ("NEWSAPI_KEY", "newsapi"),
        ("FINNHUB_API_KEY", "finnhub"),
        ("ALPHAVANTAGE_API_KEY", "alphavantage"),
    ],
)
def test_a_configured_key_adds_exactly_its_own_source(environment, variable, source):
    """One key enables its source; the other keyed sources stay out of the pass."""
    environment.setenv("DATABASE_URL", URL)
    environment.setenv(variable, "secret")
    names, _ = install_collection(environment, {source: StaticCollector([])})

    assert main(["collect"]) == 0

    assert names == ["rss", source, "congressional_trades"]


def test_a_failing_source_does_not_stop_the_others(environment, caplog):
    """A broken source is logged with its name, the pass continues and exits 0."""
    environment.setenv("DATABASE_URL", URL)
    broken = BrokenCollector()
    posts = [object()]
    names, store = install_collection(
        environment, {"rss": broken, "congressional_trades": StaticCollector(posts)}
    )

    with caplog.at_level(logging.ERROR, logger="newstrading.cli"):
        assert main(["collect"]) == 0

    assert names == ["rss", "congressional_trades"]
    assert broken.calls == 1
    assert store.saved == [posts]
    assert "rss" in caplog.text
    assert "feed exploded" in caplog.text


def test_collect_exits_1_when_every_source_fails(environment, capsys):
    """A pass in which no source delivered anything is a runtime failure, not a success."""
    environment.setenv("DATABASE_URL", URL)
    install_collection(
        environment,
        {"rss": BrokenCollector(), "congressional_trades": BrokenCollector("api down")},
    )

    assert main(["collect"]) == 1

    error = capsys.readouterr().err
    assert "every source failed" in error
    assert "Traceback" not in error


def test_a_failing_command_returns_1_and_prints_the_error(environment, capsys):
    """A runtime failure is exit 1 with the exception text and no traceback."""
    environment.setenv("DATABASE_URL", URL)
    environment.setattr(
        "newstrading.cli.collect_once",
        lambda settings: (_ for _ in ()).throw(RuntimeError("source exploded")),
    )

    assert main(["collect"]) == 1

    error = capsys.readouterr().err
    assert "source exploded" in error
    assert "Traceback" not in error


def test_verbose_prints_the_traceback_of_a_runtime_failure(environment, capsys):
    """``--verbose`` is the only way to see the traceback."""
    environment.setenv("DATABASE_URL", URL)
    environment.setattr(
        "newstrading.cli.collect_once",
        lambda settings: (_ for _ in ()).throw(RuntimeError("source exploded")),
    )

    assert main(["--verbose", "collect"]) == 1

    error = capsys.readouterr().err
    assert "source exploded" in error
    assert "Traceback (most recent call last)" in error


def test_init_db_applies_the_consolidated_schema(environment):
    """The bootstrap executes ``sql/schema.sql`` and commits once."""
    connection = FakeConnection()
    seen = []

    def fake_connect(url):
        seen.append(url)
        return connection

    environment.setattr("newstrading.cli.connect", fake_connect)

    init_db(SETTINGS)

    assert seen == [URL]
    assert "CREATE TABLE" in connection.statements[0][0]
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 0, 1)


def test_init_db_rolls_back_when_the_schema_fails(environment):
    """A failing schema leaves no half-applied transaction and closes the connection."""
    connection = FakeConnection()

    def failing_cursor():
        raise RuntimeError("cannot apply the schema")

    connection.cursor = failing_cursor
    environment.setattr("newstrading.cli.connect", lambda url: connection)

    with pytest.raises(RuntimeError, match="cannot apply"):
        init_db(SETTINGS)

    assert (connection.commits, connection.rollbacks, connection.closes) == (0, 1, 1)


def test_collect_once_stores_what_the_collectors_return(environment):
    """Every asset is collected from every configured source, and every post is stored."""
    assets = ["first", "second"]
    posts = [object(), object()]
    saved = []

    class FakeAssets:
        def __init__(self, settings):
            self.settings = settings

        def list_for_collection(self):
            return assets

    class FakeCollector:
        def __init__(self, posts):
            self._posts = posts

        def collect_for_asset(self, asset):
            assert asset in assets
            return self._posts

    class FakeStore:
        def __init__(self, settings, *, keyword_tracker):
            assert settings is KEYED_SETTINGS
            assert keyword_tracker is not None

        def save(self, collected):
            saved.append(len(collected))
            return len(collected)

    class FakeRegistry:
        def create_all(self, names, settings):
            assert names == ("rss", "newsapi", "finnhub", "alphavantage", "congressional_trades")
            assert settings is KEYED_SETTINGS
            return {"rss": FakeCollector(posts), "newsapi": FakeCollector([])}

    environment.setattr("newstrading.cli.build_registry", lambda settings: FakeRegistry())
    environment.setattr("newstrading.cli.AssetStore", FakeAssets)
    environment.setattr("newstrading.cli.PostStore", FakeStore)
    environment.setattr("newstrading.cli.KeywordTracker", lambda settings: object())

    assert collect_once(KEYED_SETTINGS) == 4
    assert saved == [2, 0, 2, 0]


def test_compose_defines_postgres_and_the_app():
    """The compose file carries the database and one app built from the root Dockerfile."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    services = text.split("services:", 1)[1].split("\nvolumes:", 1)[0]

    assert re.findall(r"^  ([a-z][a-z0-9_-]*):\s*$", services, re.MULTILINE) == ["postgres", "app"]
    assert "./sql/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql" in text
    assert "healthcheck:" in text
    assert "dockerfile: Dockerfile" in text
    assert "service_healthy" in text


def test_compose_references_no_legacy_service_path():
    """The legacy collector, analyzer, notifier and dashboard are not part of the image."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    legacy = (
        "collector/",
        "analyzer/",
        "notifier/",
        "dashboard/",
        "shared/",
        "./collector",
        "./analyzer",
        "./notifier",
        "./dashboard",
        "./shared",
    )

    for path in legacy:
        assert path not in text, f"{path} is a legacy path"


def test_dockerfile_installs_the_package_and_runs_the_cli():
    """The image installs from ``pyproject.toml`` and starts the package, without sys.path."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY src" in text
    assert "uv pip install" in text
    assert "newstrading.cli" in text
    assert "sys.path" not in text
    assert (ROOT / ".dockerignore").is_file()
