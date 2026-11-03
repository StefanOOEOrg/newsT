/**
 * Payload fixtures for the specs of #58.
 *
 * Every value here is the one a spec asserts, so a change in a fixture fails the spec that names
 * it. The shapes are the ones the endpoints of #56 answer with (see the SQL schema for the
 * nullability of a column): `null` stays `null`, never `0`.
 *
 * This file is imported by specs only; it is not part of the application bundle.
 */
import { AlertRow, LogRow, Overview, Page, PostRow, SourceRow } from '../models';

/** One tabular answer with `total` rows and `items` on the page. */
export function pageOf<T>(items: T[], total = items.length, page = 1, perPage = 25): Page<T> {
  return { items, total, page, per_page: perPage };
}

/** `/api/overview` with data in every column. */
export function overviewFixture(): Overview {
  return {
    assets: 12,
    posts: 4210,
    analyses: 3980,
    alerts: 57,
    open_alerts: 9,
    last_collector_run: '2026-11-03T06:15:42',
    database_size_bytes: 4194304,
  };
}

/** `/api/overview` on a database that was initialized and never filled. */
export function emptyOverviewFixture(): Overview {
  return {
    assets: 0,
    posts: 0,
    analyses: 0,
    alerts: 0,
    open_alerts: 0,
    last_collector_run: null,
    database_size_bytes: null,
  };
}

/** Two `/api/posts` rows: one fully populated, one whose joins found nothing. */
export function postRowsFixture(): PostRow[] {
  return [
    {
      id: 501,
      asset_id: 7,
      asset: 'AAPL',
      source: 'rss',
      title: 'Apple supplier reports a record quarter',
      url: 'https://example.test/p/501',
      score: 88,
      created_at: '2026-11-03T05:41:00',
      sentiment: 'bullish',
      sentiment_score: 0.72,
      category: 'earnings',
      summary: 'The supplier beat estimates and raised guidance.',
    },
    {
      id: 500,
      asset_id: null,
      asset: null,
      source: 'newsapi',
      title: null,
      url: null,
      score: null,
      created_at: '2026-11-03T04:20:00',
      sentiment: null,
      sentiment_score: null,
      category: null,
      summary: null,
    },
  ];
}

/** Two `/api/alerts` rows: one with a performance row, one without. */
export function alertRowsFixture(): AlertRow[] {
  return [
    {
      id: 91,
      asset_id: 7,
      asset: 'AAPL',
      alert_type: 'long_signal',
      severity: 'high',
      description: 'Strong bullish signal on AAPL',
      confidence_score: 0.87,
      timestamp: '2026-11-02T18:02:11',
      notified: true,
      return_7d: 0.0412,
      correct_7d: true,
    },
    {
      id: 90,
      asset_id: null,
      asset: null,
      alert_type: 'short_signal',
      severity: 'low',
      description: 'Mild bearish signal',
      confidence_score: null,
      timestamp: '2026-11-01T09:30:00',
      notified: null,
      return_7d: null,
      correct_7d: null,
    },
  ];
}

/** Two `/api/sources` rows: an unlimited collector and a disabled, capped one. */
export function sourceRowsFixture(): SourceRow[] {
  return [
    {
      collector: 'rss',
      last_run: '2026-11-03T06:15:42',
      total_errors: 3,
      calls_today: 120,
      failures_today: 2,
      quota_limit: null,
      quota_remaining: null,
      enabled: true,
    },
    {
      collector: 'newsapi',
      last_run: null,
      total_errors: 0,
      calls_today: 0,
      failures_today: 0,
      quota_limit: 100,
      quota_remaining: 100,
      enabled: false,
    },
  ];
}

/** Two `/api/logs` rows: one error with an exception, one info without metadata. */
export function logRowsFixture(): LogRow[] {
  return [
    {
      id: 77,
      timestamp: '2026-11-03T06:05:00',
      level: 'ERROR',
      logger: 'newstrading.collectors.rss',
      service: 'collector',
      message: 'feed unavailable',
      function: 'collect',
      line_number: 142,
      exception: 'TimeoutError: 30s',
      metadata: { url: 'https://example.test/feed' },
    },
    {
      id: 76,
      timestamp: '2026-11-03T06:00:00',
      level: 'INFO',
      logger: 'newstrading.cli',
      service: 'cli',
      message: 'collect finished',
      function: null,
      line_number: null,
      exception: null,
      metadata: null,
    },
  ];
}
