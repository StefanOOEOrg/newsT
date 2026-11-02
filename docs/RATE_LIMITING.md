# API Rate Limiting

## Overview

The sources with an API quota (NewsAPI, Finnhub, Alpha Vantage, congressional trades) have free-tier
limits. The package tracks every call and asks the database before a call whether another one is
allowed, so a collection pass stops short of a quota instead of being rejected by the source.

The quota itself lives in PostgreSQL, not in the process: `sql/schema.sql` creates the tables, the
view and the `check_rate_limit` function; `src/newstrading/rate_limiter.py` is the thin client the
collectors use, so no collector talks to those tables directly.

## Components

| Piece | Where | What it does |
|---|---|---|
| `RateLimiter` | `src/newstrading/rate_limiter.py` | asks for a decision, records the call |
| `RateLimitDecision` | `src/newstrading/rate_limiter.py` | `allowed`, `reason`, `wait_seconds` |
| `check_rate_limit(name)` | `sql/schema.sql` | answers `(can_proceed, reason, wait_seconds)` |
| `api_usage` | `sql/schema.sql` | one row per call: source, endpoint, status, success, error |
| `rate_limit_config` | `sql/schema.sql` | the limits per source, keyed by `collector_name` |
| `api_usage_stats` | `sql/schema.sql` | view with calls per day, hour and minute |

## How a check works

1. `RateLimiter.can_make_request()` calls `check_rate_limit(<collector name>)`.
2. `check_rate_limit` compares `api_usage_stats` against the `rate_limit_config` row. A missing row,
   or a row with `enabled = FALSE`, allows the call with the reason `No rate limit configured`.
3. A failing query never blocks the collection: the limiter logs a warning and allows the call with
   the reason `Rate limit check failed: ...`. A broken database must not stop a pass.
4. `RateLimiter.record_request(...)` writes the call to `api_usage`. Recording is best effort: a
   failure is rolled back, logged and swallowed. Error texts are truncated to 500 characters.

## Default limits

The rows `sql/schema.sql` inserts into `rate_limit_config`:

| `collector_name` | Daily | Hourly | Per minute | Min interval |
|---|---:|---:|---:|---:|
| `newsapi` | 100 | – | – | 1 s |
| `finnhub` | – | – | 60 | 1 s |
| `alphavantage` | 25 | 5 | – | 12 s |
| `rss` | – | – | – | 10 s |
| `congressional_trades` | – | – | – | 60 s |
| `StockPriceCollector` | – | 100 | – | 300 s |

The five source rows are keyed by the collector `name` — the same key the collector writes into
`posts.source`. `rss` has a row for completeness, but no limiter is wired for it (see below), so the
row is never consulted.
`StockPriceCollector` is a row from the legacy schema; the package builds no collector for it.

## Which collectors get a limiter

`build_registry` in `src/newstrading/collectors/factories.py` passes one `RateLimiter` per collector
for the four collectors that call a quota-limited API and accept a `limiter` argument:

| Source | Collector | Limiter |
|---|---|---|
| `newsapi` | `NewsAPICollector` | yes |
| `finnhub` | `FinnhubCollector` | yes |
| `alphavantage` | `AlphaVantageCollector` | yes |
| `congressional_trades` | `CongressionalTradesCollector` | yes |
| `rss` | `RSSCollector` | no |

`rss` is registered without a limiter: it has no API key and no hard quota, so a check would only add
a database round trip and a usage row of noise. `RSSCollector` takes no `limiter` argument, and its
signature is not changed for this. A plain `newstrading collect` therefore checks and records quotas
for the four keyed sources and leaves `rss` untracked.

## What a denied call does

When `check_rate_limit` answers "no", every wired collector logs a warning with the reason (for
example `Daily limit exceeded (100/100)`) and skips that request: no HTTP call is made and nothing is
written to `api_usage`. Nothing is raised — the collection pass continues with the next asset, and the
quota is checked again on the next pass once `wait_seconds` has elapsed.

## Using a limiter

Every keyed collector takes an optional `limiter` argument. It is `None` by default, which means no
quota check and no usage row — a `None` limiter disables tracking, never the call.

```python
from newstrading.collectors.newsapi import NewsAPICollector
from newstrading.config import from_env
from newstrading.rate_limiter import RateLimiter

settings = from_env()
limiter = RateLimiter(settings, "newsapi")
collector = NewsAPICollector(settings, limiter=limiter)
```

Inside `collect_for_asset` the collector then asks the limiter before the request and records the
outcome after it; see `src/newstrading/collectors/newsapi.py` for the pattern the other keyed
collectors follow.

The name passed to `RateLimiter` is the collector `name` and the `collector_name` of the
`rate_limit_config` row: `newsapi`, `finnhub`, `alphavantage`, `congressional_trades` (and `rss`,
which has a row but no limiter). The registry uses the same five strings, so no mapping is needed
between the source key and the quota row.

## Monitoring

Current usage per source:

```sql
SELECT * FROM api_usage_stats;
```

The last calls of a day:

```sql
SELECT collector_name, timestamp, status_code, success, error_message
FROM api_usage
WHERE timestamp >= NOW() - INTERVAL '1 day'
ORDER BY timestamp DESC
LIMIT 50;
```

The configured limits:

```sql
SELECT * FROM rate_limit_config ORDER BY collector_name;
```

Calls against their daily limit:

```sql
SELECT
    s.collector_name,
    s.calls_today,
    r.max_calls_per_day,
    ROUND(s.calls_today::NUMERIC / r.max_calls_per_day * 100, 1) AS usage_percent
FROM api_usage_stats s
JOIN rate_limit_config r USING (collector_name)
WHERE r.max_calls_per_day IS NOT NULL
ORDER BY usage_percent DESC;
```

## Changing limits

```sql
UPDATE rate_limit_config
SET max_calls_per_day = 50,
    min_interval_seconds = 2
WHERE collector_name = 'newsapi';
```

Disable the quota of a source without removing its row:

```sql
UPDATE rate_limit_config
SET enabled = FALSE
WHERE collector_name = 'rss';
```

## Troubleshooting

**No quota is enforced.** Either no limiter was passed to the collector (see above), or
`rate_limit_config` has no row for the name the limiter asked for — `check_rate_limit` then allows
every call. Compare the two sets:

```sql
SELECT collector_name FROM rate_limit_config ORDER BY collector_name;
```

**A daily limit does not reset when expected.** The function counts the calls of
`date_trunc('day', NOW())` of the database server, so the day boundary is the server's timezone, and
`wait_seconds` is the time left until that boundary. Check the server:

```sql
SHOW timezone;
```

**`Rate limit check failed:` in the log.** The limiter could not reach `api_usage` or
`rate_limit_config`; the pass continued without a quota. Check the connection and that
`newstrading init-db` ran:

```sql
SELECT EXISTS (
    SELECT FROM information_schema.tables WHERE table_name = 'api_usage'
);
```

**High error rates.** Group the failures of a day by message:

```sql
SELECT collector_name, error_message, COUNT(*) AS occurrences
FROM api_usage
WHERE success = FALSE AND timestamp >= NOW() - INTERVAL '1 day'
GROUP BY collector_name, error_message
ORDER BY occurrences DESC;
```

## Cost notes

Free tiers are small: NewsAPI 100 requests/day, Finnhub 60 calls/minute, Alpha Vantage 25 calls/day.
The default rows keep a five-asset collection under those limits, and a keyed source whose key is
empty is not built at all — `_configured_sources` in `src/newstrading/cli.py` skips it — so no quota
is spent on a source you do not use.
