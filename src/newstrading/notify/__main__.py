"""Run one notification pass: ``python -m newstrading.notify``."""

from __future__ import annotations

import logging

from newstrading.config import from_env
from newstrading.notify.service import NotificationService

logger = logging.getLogger(__name__)


def main() -> int:
    """Run one notification pass and return the number of alerts handled.

    The periodic loop with the legacy ``NOTIFICATION_CHECK_INTERVAL`` delay is wired in
    #22; this entry point is deliberately one pass, configured from the environment.
    """
    settings = from_env()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    handled = NotificationService(settings).run()
    logger.info("Notification check completed: %d alert(s) handled", handled)
    return handled


if __name__ == "__main__":
    raise SystemExit(main())
