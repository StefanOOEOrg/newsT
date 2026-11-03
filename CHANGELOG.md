# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-02

The signal path of the legacy `v1.2` tree, rebuilt as one flat `newstrading` package on the
organisation guidelines.

### Added

- **Post collectors.** Four news sources — RSS, NewsAPI, Finnhub and Alpha Vantage — behind
  one registry, with dedupe, keyword tracking and per-run collector statistics.
- **Congressional trades and events.** The congressional trades collector and the
  earnings-event collector with its `asset_events` store; `rss` and `congressional_trades`
  need no key.
- **Stock prices.** The stock price collector with its `stock_prices` store, and the
  `PriceProvider` the performance tracker reads prices through.
- **Analysis.** The analyzer service: prompt building, TOON and JSON parsing of the model
  answer, the retried model call, and one stored analysis per post.
- **Alerts and metrics.** Alert generation from strong signals, alert performance tracking,
  and the refresh of `daily_metrics`.
- **Notifications.** The notification service with four senders — email, SMS, push and
  webhook — delivered one channel per pending notification.
- **CLI.** `newstrading` with the four commands `init-db`, `collect`, `analyze` and `notify`,
  settings resolution and explicit exit codes.
- **Rate limiting.** The database-backed rate limiter, wired to `rate_limit_config` and
  `api_usage`, so a source's quota is checked before every call.
- **Packaging.** One `Dockerfile` and a `docker-compose.yml` with the local PostgreSQL
  stack, plus `uv.lock` and the coverage gate in CI.

### Changed

- **Configuration.** A single `Settings` object read from fourteen documented environment
  variables; nothing else is read from the environment.
- **Notification channels.** Configured in the `notification_settings` table instead of the
  environment; the senders take their credentials from that row.
- **Quota rows.** Keyed by source name (`newsapi`, `finnhub`, `alphavantage`, `rss`,
  `congressional_trades`) instead of the collector class name.

### Breaking changes against the legacy `v1.2`

- The flat `src/newstrading/` package replaces the legacy `collector/`, `analyzer/`,
  `dashboard/`, `notifier/` and `shared/` trees.
- The Streamlit dashboard is **not** ported.
- The entry points are the four CLI commands instead of the per-service scripts.
- `init-db` creates the missing tables and repairs an existing database without losing data:
  `sql/schema.sql` contains no `DROP`, `DELETE` or `TRUNCATE` statement, its three seed
  inserts are guarded (`ON CONFLICT` or `NOT EXISTS`) and the legacy quota rows are renamed
  in place. `newstrading init-db --reset` is the only destructive path — it drops all ten
  tables first (`sql/reset.sql`) and that destroys every row.
- A database created before this release needs one `newstrading init-db` run (safe: it
  creates and repairs in place): the quota rows are renamed to the source names, and the
  `asset_events` unique key only reaches fresh databases.

### Fixed

- Non-finite sentiment scores (NaN, Infinity) are rejected instead of stored (#25, #26).
- Alerts without a deliverable channel no longer starve the notification queue (#34).

### Credits

- Thanks to **@Kaan081** for the sentiment fix (#26).

[1.0.0]: https://github.com/StefanOOEOrg/newsT/releases/tag/v1.0.0
