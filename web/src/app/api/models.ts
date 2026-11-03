/**
 * The wire models of the dashboard API (#56) and the view models the screens render (#58).
 *
 * The wire models mirror the JSON the six GET endpoints answer with: `null` is a column the
 * database has as NULL and stays `null` here, never `0`. A view model carries the strings the
 * template prints, so the template never formats and never decides what a missing value looks
 * like - `format.ts` does that once.
 */

/** One page of a list answer: `{"items": [...], "total": n, "page": p, "per_page": pp}`. */
export interface Page<T> {
  readonly items: T[];
  readonly total: number;
  readonly page: number;
  readonly per_page: number;
}

/** `GET /api/overview`: the counters of *Is it running?*. */
export interface Overview {
  readonly assets: number;
  readonly posts: number;
  readonly analyses: number;
  readonly alerts: number;
  readonly open_alerts: number;
  /** `MAX(collector_statistics.last_run_completed_at)`, `null` when nothing ever ran. */
  readonly last_collector_run: string | null;
  /** `pg_database_size`, `null` when the query could not report it. */
  readonly database_size_bytes: number | null;
}

/** One row of `GET /api/posts`: a post left-joined with its asset and its analysis. */
export interface PostRow {
  readonly id: number;
  readonly asset_id: number | null;
  readonly asset: string | null;
  readonly source: string;
  /** `social_posts.title` is nullable. */
  readonly title: string | null;
  readonly url: string | null;
  readonly score: number | null;
  readonly created_at: string;
  readonly sentiment: string | null;
  readonly sentiment_score: number | null;
  readonly category: string | null;
  readonly summary: string | null;
}

/** One row of `GET /api/alerts`: an alert with the newest 7-day performance row, if any. */
export interface AlertRow {
  readonly id: number;
  readonly asset_id: number | null;
  readonly asset: string | null;
  readonly alert_type: string | null;
  readonly severity: string | null;
  readonly description: string | null;
  readonly confidence_score: number | null;
  readonly timestamp: string;
  readonly notified: boolean | null;
  readonly return_7d: number | null;
  readonly correct_7d: boolean | null;
}

/** One horizon of `GET /api/performance`; `hit_rate` is `null` when the horizon has no alert. */
export interface HorizonRow {
  /** `1d`, `3d` or `7d`. */
  readonly horizon: string;
  readonly alerts: number;
  readonly correct: number;
  /** `correct / alerts`, rounded to three decimals by the API; `null` without an alert. */
  readonly hit_rate: number | null;
}

/** One per-type row of `GET /api/performance`, reported for the 7d horizon. */
export interface TypePerformanceRow {
  readonly alert_type: string;
  readonly horizon: string;
  readonly alerts: number;
  readonly correct: number;
  readonly hit_rate: number | null;
}

/** `GET /api/performance`: the three horizons and the rows per alert type for 7d (#69). */
export interface PerformanceAnswer {
  readonly horizons: HorizonRow[];
  readonly by_type: TypePerformanceRow[];
}

/** One row of `GET /api/sources`: the rate-limit config joined with usage and statistics. */
export interface SourceRow {
  readonly collector: string;
  readonly last_run: string | null;
  readonly total_errors: number;
  readonly calls_today: number;
  readonly failures_today: number;
  /** `rate_limit_config.max_calls_per_day`; `null` means "no hard limit". */
  readonly quota_limit: number | null;
  /** `max_calls_per_day - calls_today`, floored at 0; `null` for an unlimited collector. */
  readonly quota_remaining: number | null;
  readonly enabled: boolean;
}

/** One row of `GET /api/logs`. */
export interface LogRow {
  readonly id: number;
  readonly timestamp: string;
  readonly level: string;
  readonly logger: string;
  readonly service: string;
  readonly message: string;
  readonly function: string | null;
  readonly line_number: number | null;
  readonly exception: string | null;
  readonly metadata: unknown;
}

/** One counter of the overview: `value` is already the string the card prints. */
export interface OverviewCard {
  readonly key: string;
  readonly label: string;
  readonly value: string;
}

/** A post as the table prints it. */
export interface PostView {
  readonly id: number;
  readonly asset: string;
  readonly source: string;
  readonly title: string;
  readonly url: string | null;
  readonly score: string;
  readonly created: string;
  readonly sentiment: string;
  readonly sentimentScore: string;
  readonly category: string;
  readonly summary: string;
}

/** An alert as the table prints it. */
export interface AlertView {
  readonly id: number;
  readonly asset: string;
  readonly alertType: string;
  readonly severity: string;
  readonly description: string;
  readonly confidence: string;
  readonly timestamp: string;
  readonly notified: string;
  readonly return7d: string;
  readonly correct7d: string;
}

/** A collector as the table prints it. */
export interface SourceView {
  readonly collector: string;
  readonly lastRun: string;
  readonly calls: string;
  readonly failures: string;
  readonly totalErrors: string;
  readonly quotaLimit: string;
  readonly quotaRemaining: string;
  readonly enabled: string;
}

/** A log line as the table prints it; `tone` is the colour class of the level pill. */
export interface LogView {
  readonly id: number;
  readonly timestamp: string;
  readonly level: string;
  readonly tone: LogTone;
  readonly logger: string;
  readonly service: string;
  readonly message: string;
  readonly function: string;
  readonly line: string;
  readonly exception: string;
  readonly metadata: string;
}

/** Colour class of a log level, mapped onto the `--err`/`--warn`/`--ok`/`--muted` tokens. */
export type LogTone = 'err' | 'warn' | 'ok' | 'muted';

/** One alert type's 7d performance, as the performance table prints it. */
export interface PerformanceView {
  readonly alertType: string;
  readonly horizon: string;
  readonly alerts: string;
  readonly correct: string;
  readonly rate: string;
}

/** The hit rate of one evaluation horizon, as the horizons table prints it. */
export interface HorizonView {
  readonly horizon: string;
  readonly alerts: string;
  readonly correct: string;
  readonly rate: string;
}

/** The three collector counters above the sources table. */
export interface SourcesSummary {
  readonly collectors: string;
  readonly failing: string;
  readonly disabled: string;
}
