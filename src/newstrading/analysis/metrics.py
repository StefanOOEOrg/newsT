"""Refresh ``daily_metrics`` from the stored analyses.

Ports ``update_daily_metrics`` of ``analyzer/main.py``: for every asset one insert-select
that aggregates the analysed posts per day and upserts the row, so the table is rebuilt
without deleting what no longer has posts.

The module is the third seam to the database in this package: it gets its connection
factory injected, opens exactly one connection per call and is tested against a fake.
"""

from __future__ import annotations

import psycopg2

from newstrading.config import Settings
from newstrading.db import Connector, connection
from newstrading.errors import NewsTradingError

ASSET_IDS_SQL = "SELECT id FROM asset"
"""The legacy asset loop: one metrics statement per row of this select."""

DAILY_METRICS_SQL = """
    INSERT INTO daily_metrics
    (asset_id, date, mention_count, sentiment_avg,
     hiring_mentions, problem_mentions, growth_mentions)
    SELECT
        sp.asset_id,
        DATE(sp.created_at) as post_date,
        COUNT(*),
        AVG(aa.sentiment_score),
        SUM(CASE WHEN aa.category = 'Hiring' THEN 1 ELSE 0 END),
        SUM(CASE WHEN aa.category = 'Problems' THEN 1 ELSE 0 END),
        SUM(CASE WHEN aa.category = 'Growth' THEN 1 ELSE 0 END)
    FROM social_posts sp
    JOIN ai_analysis aa ON sp.id = aa.post_id
    WHERE sp.asset_id = %s
    GROUP BY sp.asset_id, DATE(sp.created_at)
    ON CONFLICT (asset_id, date)
    DO UPDATE SET
        mention_count = EXCLUDED.mention_count,
        sentiment_avg = EXCLUDED.sentiment_avg,
        hiring_mentions = EXCLUDED.hiring_mentions,
        problem_mentions = EXCLUDED.problem_mentions,
        growth_mentions = EXCLUDED.growth_mentions
"""
"""The legacy statement, verbatim; the asset id binds as the only parameter."""


class MetricsError(NewsTradingError):
    """Raised when the daily metrics cannot be recomputed."""


def update_daily_metrics(settings: Settings, *, connector: Connector = psycopg2.connect) -> int:
    """Recompute `daily_metrics` for every asset from the analyses; return the assets touched.

    Args:
        settings: Settings holding ``database_url``.
        connector: Factory used to open the connection. Injected in tests; production
            callers leave it at :func:`psycopg2.connect`.

    Returns:
        The number of assets the run looked at, whether or not they had analyses.

    Raises:
        MetricsError: If the assets cannot be read or a statement fails. A failed run
            rolls the whole call back.

    Contract:
        * One connection per call, one commit at the end, closed in every case.
        * One :data:`DAILY_METRICS_SQL` execution per asset, in the order the ids came
          back, with the asset id as the only parameter.
        * An asset without analyses inserts nothing; the statements are idempotent
          through their ``ON CONFLICT`` clause.
    """
    asset_ids: list[int] = []
    try:
        with connection(settings, connector=connector) as db:
            with db.cursor() as cursor:
                cursor.execute(ASSET_IDS_SQL)
                asset_ids = [row[0] for row in cursor.fetchall()]
                for asset_id in asset_ids:
                    cursor.execute(DAILY_METRICS_SQL, (asset_id,))
    # boundary: driver failures become the module's own error type
    except Exception as error:
        raise MetricsError("cannot update the daily metrics") from error
    return len(asset_ids)
