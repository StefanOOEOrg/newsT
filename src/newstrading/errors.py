"""Exception types of the newstrading package.

Every error the package raises derives from :class:`NewsTradingError`, so callers can
catch one type and still narrow by class (guideline §6). Library exceptions never
leave the package unwrapped.
"""


class NewsTradingError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(NewsTradingError):
    """Raised when the environment does not provide a usable configuration."""


class CollectorConfigError(NewsTradingError):
    """Raised when a collector is built without its required API key."""
