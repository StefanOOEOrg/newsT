"""Registry of collectors: one place maps a source name to its implementation.

The legacy factory returned ``None`` for an unknown name and dropped collectors whose
constructor failed — both failures were only visible in a log line. Here every one of
them raises :class:`CollectorError`, so the scheduler decides what to do instead of
silently collecting from fewer sources than configured.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from newstrading.collectors.models import Asset, Post
from newstrading.errors import NewsTradingError


class CollectorError(NewsTradingError):
    """Raised when a collector cannot be registered or built."""


class Collector(Protocol):
    """What the scheduler needs from a collector."""

    name: str

    def collect_for_asset(self, asset: Asset) -> list[Post]:
        """Collect every new post for ``asset``.

        Args:
            asset: The asset to search for.

        Returns:
            Newly found posts; an empty list when the source has nothing new.
        """


Factory = Callable[[object], Collector]


class CollectorRegistry:
    """Maps source names to factories and builds collectors on demand."""

    def __init__(self) -> None:
        """Start with an empty registry."""
        self._factories: dict[str, Factory] = {}

    def register(self, name: str, factory: Factory) -> None:
        """Register ``factory`` under ``name``.

        Args:
            name: Source key used in configuration, e.g. ``rss``.
            factory: Called with the settings object to build the collector.

        Raises:
            CollectorError: If ``name`` is empty or already registered. The message
                names the offending key: ``collector 'rss' is already registered``.
        """
        if not name:
            raise CollectorError("collector name must not be empty")
        if name in self._factories:
            raise CollectorError(f"collector '{name}' is already registered")
        self._factories[name] = factory

    def create(self, name: str, settings: object) -> Collector:
        """Build the collector registered under ``name``.

        Args:
            name: Source key.
            settings: Passed through to the factory unchanged.

        Returns:
            The collector instance.

        Raises:
            CollectorError: If ``name`` is unknown — the message lists the known names
                sorted and comma separated — or if the factory raises; in that case the
                original exception is chained as ``__cause__``.
        """
        if name not in self._factories:
            known = ", ".join(self.names)
            raise CollectorError(f"collector '{name}' is not registered; known: {known}")
        try:
            return self._factories[name](settings)
        # boundary: any factory failure becomes a CollectorError with the source name
        except Exception as error:
            raise CollectorError(f"could not build collector '{name}': {error}") from error

    def create_all(self, names: Sequence[str], settings: object) -> dict[str, Collector]:
        """Build several collectors, keeping the order of ``names``.

        Args:
            names: Source keys to build.
            settings: Passed through to every factory.

        Returns:
            Mapping of name to collector, in the order of ``names``.

        Raises:
            CollectorError: On the first name that cannot be built — unlike the legacy
                factory, a missing source is not skipped.
        """
        return {name: self.create(name, settings) for name in names}

    def is_available(self, name: str) -> bool:
        """Return whether ``name`` is registered.

        Args:
            name: Source key.

        Returns:
            ``True`` if a factory is registered under that name.
        """
        return name in self._factories

    @property
    def names(self) -> tuple[str, ...]:
        """Return every registered name, sorted."""
        return tuple(sorted(self._factories))
