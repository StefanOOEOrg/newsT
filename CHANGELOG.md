# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-04

The analysis runs against the configured OpenAI-compatible endpoint instead of a hard-wired vendor,
and the database gets a read-only monitoring dashboard.

### Added

- **Vendor-neutral model calls.** `src/newstrading/analysis/llm.py` holds the `LLMClient` protocol,
  an `OpenAICompatibleClient` for any OpenAI-compatible chat-completions endpoint and an optional
  `FallbackClient`; `build_client(settings)` builds the pair from configuration. Retry
  classification lives in the adapters, so the analyzer no longer imports a provider SDK.
- **Optional fallback endpoint.** `LLM_FALLBACK` names a second endpoint that is asked once when the
  primary call fails in a way a retry can fix (rate limit, timeout, connection failure, 5xx, an
  empty or truncated answer); a rejected request is not repeated there.
- **Bounded analyze concurrency.** `LLM_MAX_CONCURRENCY` (1 to 16) runs the model calls of one pass
  through `ThreadPoolExecutor.map`, and the answers are stored in submission order for any value —
  `1` is simply the serial case. One failing post does not cancel the batch.
- **Dashboard API.** A read-only FastAPI application with seven `GET` endpoints under `/api`:
  overview counters, paged posts with their analysis, paged alerts with their performance, paged
  keyword performance, per-source health, paged `system_logs`, and the alert-performance aggregate.
  The `dashboard` command serves the API and the built Angular app from one process on
  `127.0.0.1:8088`.
- **Six dashboard screens.** Angular 22 with standalone components and no zone.js; one signal store
  per screen: overview, posts, alerts, performance, sources and logs. Paging with 25, 50, 100 or
  200 rows on posts, alerts and logs, a manual refresh per screen, deep links (a refresh on
  `/posts` returns the app, not a 404) and an honest empty state for an empty database.
- **Three-horizon performance.** `/api/performance` reports alerts, correct and hit rate for the
  1d, 3d and 7d horizon and per alert type; the performance screen reads that one answer instead of
  deriving a single horizon from `/api/alerts`.
- **Own logo.** The wordmark and mark live as SVG in `web/public/` and are used in the header and as
  the favicon.

### Changed

- **Configuration — analysis.** The vendor-specific settings are gone; the model is chosen with
  `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT`, `LLM_MAX_TOKENS` and
  `LLM_MAX_CONCURRENCY`, plus the optional `LLM_FALLBACK`, `LLM_FALLBACK_MODEL` and
  `LLM_FALLBACK_API_KEY`. The defaults point at `gb10-writing` on the GX10
  (`http://192.168.178.87:8004/v1`), 1024 tokens and one call in flight.
- **`analyze` flags.** The nine `LLM_*` values can be replaced for one run with the matching
  `--llm-*` flags.
- **Dependencies.** `anthropic` is removed; `fastapi` and `uvicorn[standard]` are added, `httpx` as
  a dev dependency for the API tests.
- **Requirements.** The analysis needs no key by default, and an empty `LLM_API_KEY` sends no
  `Authorization` header.

### Breaking changes against 1.0.0

- `ANTHROPIC_API_KEY` is no longer read and no longer required; `AI_MODEL` and `MAX_TOKENS` are
  removed. An existing `.env` that still sets them keeps starting, but the values are ignored. The
  replacements are `LLM_BASE_URL`/`LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT`, `LLM_MAX_TOKENS`,
  `LLM_MAX_CONCURRENCY` and the optional `LLM_FALLBACK*` trio.
- The model call is OpenAI-compatible only: a deployment that speaks Anthropic's native API has to
  point `LLM_BASE_URL` at an OpenAI-compatible gateway. There is no `LLM_PROVIDER` switch.
- An empty model answer is a retryable failure, never a stored neutral analysis; with a token
  budget smaller than the reasoning prefix the post stays unanalysed instead of gaining a neutral
  `ai_analysis` row.

### Fixed

- `alert_performance.correct_1d/3d/7d` is recomputed when each horizon closes, so a hit rate is no
  longer `0 %` for alerts that are simply not judged yet; a neutral prediction stays `NULL` in
  every horizon.
- An empty model answer is retried (2 s and 4 s) and, after the last attempt, leaves the post
  unanalysed instead of storing a neutral row.

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

[1.1.0]: https://github.com/StefanOOEOrg/newsT/releases/tag/v1.1.0
[1.0.0]: https://github.com/StefanOOEOrg/newsT/releases/tag/v1.0.0
