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
VERSION = ROOT / "VERSION"
PYPROJECT = ROOT / "pyproject.toml"

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


def _documented_variables() -> set[str]:
    """Return the variable names of the README configuration table."""
    return set(_TABLE_ROW.findall(README.read_text(encoding="utf-8")))


def _read_variables() -> set[str]:
    """Return the variables ``Settings`` reads, as its docstring names them."""
    return set(_DOCSTRING_VARIABLE.findall(Settings.__doc__ or ""))


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
