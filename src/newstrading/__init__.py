"""News and congressional trading signal monitor."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("newstrading")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = Path(__file__).resolve().parents[2].joinpath("VERSION").read_text().strip()
