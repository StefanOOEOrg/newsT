"""Release metadata: the version sources and the documented settings.

The configuration table of the README is a contract: every variable it lists is
read by :class:`newstrading.config.Settings`, and every variable ``Settings`` reads
is in the table. The test compares both sets instead of trusting the prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import newstrading
from newstrading.config import REQUIRED_VARIABLES, Settings

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"
VERSION = ROOT / "VERSION"
PYPROJECT = ROOT / "pyproject.toml"
DOCS = ROOT / "docs"

# Archived documents keep the paths of the legacy tree on purpose; the release
# moves them, so the path check skips them by name.
ARCHIVED_DOCUMENTS = (
    "docs/archive/HISTORICAL_INIT.md",
    "docs/archive/IDEAS.md",
)

# Variables of the legacy notification setup; the package configures the senders
# through the ``notification_settings`` row instead.
LEGACY_NOTIFICATION_VARIABLES = ("NOTIFICATION_EMAIL", "SMTP_", "TWILIO_", "PUSHOVER_")

# Paths of the reference implementation; the release removes them for good.
LEGACY_PATHS = (
    "collector/",
    "analyzer/",
    "dashboard/",
    "notifier/",
    "shared/",
    "postgres/",
    "scripts/",
    "run_tests.sh",
    "migrate.sql",
    "requirements-dev.txt",
    "test-docker.sh",
    ".claude/guidelines.md",
)

_TABLE_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`", re.MULTILINE)
_DOCSTRING_VARIABLE = re.compile(r"\(``([A-Z][A-Z0-9_]*)``\)")
# A line of the example, active or commented out: `NAME=value` or `# NAME=value`.
_ENV_ASSIGNMENT = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)
# Connection strings are not repository paths, so they are dropped before the search.
_URL = re.compile(r"\w+://\S+")
# A file with a known suffix, optionally behind directories: `config.py`, `sql/schema.sql`.
_PATH = re.compile(r"(?<![\w/.])([\w.-]+(?:/[\w.-]+)*\.(?:py|md|sql|toml|ya?ml|json|txt))")


def _documented_variables() -> set[str]:
    """Return the variable names of the README configuration table."""
    return set(_TABLE_ROW.findall(README.read_text(encoding="utf-8")))


def _read_variables() -> set[str]:
    """Return the variables ``Settings`` reads, as its docstring names them."""
    return set(_DOCSTRING_VARIABLE.findall(Settings.__doc__ or ""))


def _env_example_variables() -> set[str]:
    """Return the variables ``.env.example`` assigns, commented out or not."""
    return set(_ENV_ASSIGNMENT.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def _env_example_paths() -> list[str]:
    """Return the repository paths ``.env.example`` names, connection strings aside."""
    text = _URL.sub("", ENV_EXAMPLE.read_text(encoding="utf-8"))
    return _PATH.findall(text)


def test_version_file_holds_the_release_number() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "1.0.0"


def test_package_version_is_the_version_file() -> None:
    assert newstrading.__version__ == VERSION.read_text(encoding="utf-8").strip()


def test_pyproject_keeps_no_second_version() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert "[tool.hatch.version]" in pyproject
    assert re.search(r"^version\s*=", pyproject, re.MULTILINE) is None


def test_readme_documents_exactly_the_variables_settings_reads() -> None:
    documented = _documented_variables()
    read = _read_variables()
    assert read, "the Settings docstring must name the environment variables"
    assert documented == read
    assert set(REQUIRED_VARIABLES) <= documented


def test_readme_mentions_no_legacy_path() -> None:
    text = README.read_text(encoding="utf-8")
    assert [path for path in LEGACY_PATHS if path in text] == []


def test_env_example_documents_exactly_the_variables_settings_reads() -> None:
    documented = _env_example_variables()
    read = _read_variables()
    assert documented == read
    assert set(REQUIRED_VARIABLES) <= documented


def test_env_example_mentions_no_path_that_does_not_exist() -> None:
    paths = _env_example_paths()
    assert paths, "the check needs at least one path to be meaningful"
    assert [path for path in paths if not (ROOT / path).exists()] == []


def _documented_markdown() -> list[Path]:
    """Return the current Markdown files at the root and under ``docs/``."""
    candidates = [*ROOT.glob("*.md"), *DOCS.rglob("*.md")]
    return [
        path
        for path in sorted(candidates)
        if path.relative_to(ROOT).as_posix() not in ARCHIVED_DOCUMENTS
    ]


def _markdown_paths(path: Path) -> list[str]:
    """Return the repository paths one Markdown file names, URLs aside."""
    text = _URL.sub("", path.read_text(encoding="utf-8"))
    return _PATH.findall(text)


def test_every_documented_markdown_path_exists() -> None:
    assert not (ROOT / "ARCHITECTURE.md").exists(), (
        "the README is the single architecture description"
    )
    documents = _documented_markdown()
    assert documents, "the check needs at least one document to be meaningful"
    missing = {
        f"{document.relative_to(ROOT).as_posix()}: {path}"
        for document in documents
        for path in _markdown_paths(document)
        if not (ROOT / path).exists()
    }
    assert missing == set()


def test_notifications_guide_names_no_legacy_setup() -> None:
    text = (ROOT / "NOTIFICATIONS.md").read_text(encoding="utf-8")
    assert [name for name in LEGACY_NOTIFICATION_VARIABLES if name in text] == []
    assert "dashboard" not in text.lower()
