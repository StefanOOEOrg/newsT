# newstrading

`newstrading` watches the news and the public congressional trading disclosures for the assets you
track, asks Claude for a structured verdict on every new post, stores the result in PostgreSQL and
turns strong signals into alerts and notifications.

## What it does

- **Collects** news from RSS feeds, NewsAPI, Finnhub and Alpha Vantage, and congressional trade
  disclosures from the public House Stock Watcher data.
- **Analyses** each new post once: sentiment and score, category, key topics, a short summary, and
  whether the post looks like a signal. The model call is retried and every answer is parsed from
  TOON or JSON.
- **Alerts** on strong signals, tracks how past alerts performed, and aggregates daily metrics per
  asset.
- **Notifies** by email, SMS, push or webhook, one channel per configured notification.
- **Stores** everything in one PostgreSQL schema: assets and keywords, posts, analyses, alerts,
  metrics, collector statistics and API usage.

## Architecture

| Component | Module | Responsibility |
|---|---|---|
| CLI | `src/newstrading/cli.py` | the four commands, settings resolution, exit codes |
| Configuration | `src/newstrading/config.py` | typed `Settings` built from the environment, one place |
| Database | `src/newstrading/db.py`, `sql/schema.sql` | connection handling and the single schema |
| Collectors | `src/newstrading/collectors/` | one module per source, registry, dedupe, rate limiting |
| Analysis | `src/newstrading/analysis/` | prompt, parser, analyzer service, alerts, metrics |
| Notifications | `src/newstrading/notify/` | email, SMS, push and webhook senders |
| Packaging | `pyproject.toml`, `Dockerfile`, `docker-compose.yml` | wheel, image, local PostgreSQL stack |

## Requirements

- Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 15 (the compose file starts one)
- An Anthropic API key; the news and congressional sources work without one

## Install

```bash
git clone https://github.com/StefanOOEOrg/newsT.git
cd newsT
uv sync --locked
cp .env.example .env
```

Set at least `DATABASE_URL` in `.env`, then create the schema. The analysis calls need no key:
their default provider is the local `gb10-writing` model; `ANTHROPIC_API_KEY` is read only when
`LLM_PROVIDER=anthropic`.

```bash
uv run newstrading init-db
```

`init-db` is non-destructive: it applies `sql/schema.sql`, which only creates the tables and
indexes that are missing and keeps every row of a populated database. It is therefore safe to run
on an existing database after an upgrade. Only the explicit `--reset` flag drops the tables
first (`sql/reset.sql`) — that destroys all data:

```bash
uv run newstrading init-db --reset
```

## Configuration

Every variable below is read by `Settings`; nothing else is read from the environment. Required
variables have no default and abort the command with exit code 2 when they are missing or empty.
Optional variables fall back to their default when absent **or empty**.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DATABASE_URL` | yes | – | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | only with `LLM_PROVIDER=anthropic` | – | Anthropic API key for the analysis calls |
| `AI_MODEL` | no | `claude-3-5-haiku-20241022` | model id the Anthropic provider uses |
| `MAX_TOKENS` | no | `512` | maximum tokens of one Anthropic answer |
| `LLM_PROVIDER` | no | `local` | provider of the analysis calls: `local` (OpenAI-compatible) or `anthropic` |
| `LLM_BASE_URL` | no | `http://192.168.178.87:8004/v1` | base URL of the local provider (`gb10-writing` on the GX10) |
| `LLM_MODEL` | no | `gb10-writing` | model id sent to the local provider |
| `LLM_API_KEY` | no | empty | bearer token of the local provider; empty sends no authorization header |
| `LLM_TIMEOUT` | no | `60` | seconds one model call may take |
| `LLM_MAX_TOKENS` | no | `1024` | maximum tokens of one local answer; leaves room for the reasoning prefix |
| `LLM_MAX_CONCURRENCY` | no | `1` | model calls in flight in one analyze pass, between 1 and 16 |
| `ANALYSIS_INTERVAL_MINUTES` | no | `5` | minutes between two analysis runs, greater than zero |
| `CONTENT_MAX_LENGTH` | no | `2000` | characters of post content sent to the model |
| `ALERT_SUMMARY_MAX_LENGTH` | no | `180` | characters of the alert summary |
| `LOG_LEVEL` | no | `INFO` | console log level, upper-cased |
| `DATABASE_LOG_LEVEL` | no | `INFO` | database log level, upper-cased |
| `NEWSAPI_KEY` | no | empty | NewsAPI.org key; empty disables the source |
| `FINNHUB_API_KEY` | no | empty | Finnhub key; empty disables the source |
| `ALPHAVANTAGE_API_KEY` | no | empty | Alpha Vantage key; empty disables the source |
| `CONGRESS_TRADES_API_KEY` | no | empty | premium congressional trades key; empty keeps the public source only |
| `CONGRESS_TRADES_API_URL` | no | empty | premium congressional trades endpoint; empty keeps the public source only |

The collectors that need no key — RSS and the public congressional disclosures — always run. A keyed
collector runs exactly when its key is set.

## Commands

```bash
uv run newstrading init-db           # create the missing tables, keep the existing rows
uv run newstrading init-db --reset   # drop every table first (destroys all data)
uv run newstrading collect           # one collection pass over every configured source
uv run newstrading analyze           # one analysis pass over the waiting posts
uv run newstrading analyze --llm-max-concurrency 3   # same pass, three calls in flight
uv run newstrading notify            # one notification pass over the alerts
```

| Command | Needs | Does |
|---|---|---|
| `init-db` | `DATABASE_URL` | creates the missing tables and indexes of `sql/schema.sql`; non-destructive, `--reset` drops the tables first (see `sql/reset.sql`) |
| `collect` | `DATABASE_URL` | runs every configured source for every asset, stores the new posts |
| `analyze` | `DATABASE_URL`, and `ANTHROPIC_API_KEY` with `LLM_PROVIDER=anthropic` | analyses the waiting posts, stores the alerts, refreshes the daily metrics |
| `notify` | `DATABASE_URL` | sends the pending notifications over the configured channels |

Exit codes: `0` success, `2` missing or invalid configuration (the message names the variable),
`1` a runtime failure. `uv run newstrading --help` and `--version` print without touching the
database.

`analyze` also takes `--llm-provider`, `--llm-max-tokens` and `--llm-max-concurrency`; a flag
replaces its environment variable for that run only and passes the same validation.

## Tests

```bash
uv run pytest src/tests -q                                       # the suite
uv run pytest src/tests -q --cov=newstrading --cov-fail-under=80 # the coverage gate of CI
uv run ruff check src                                            # lint
uv run ruff format --check src                                   # format
```

The suite needs no database, no network and no API key; every source, sender and model call is
injected. CI runs the same three gates on Python 3.11 and 3.13 and aggregates them in `ci-ok`.

## Docker

```bash
docker compose up --build
```

One image runs every command: `docker compose run app analyze` runs one analysis pass, the default
command of the `app` service is `collect`. The `postgres` service mounts `sql/schema.sql` as its
initialisation script.

## Data sources

Free, no key needed:

- RSS feeds — asset-specific news from Google News, Yahoo Finance and Seeking Alpha
- [House Stock Watcher](https://housestockwatcher.com) — public congressional trade disclosures

Optional, with a key:

- [NewsAPI](https://newsapi.org/register) — 100 requests/day on the free tier
- [Finnhub](https://finnhub.io/register) — 60 calls/minute on the free tier
- [Alpha Vantage](https://www.alphavantage.co/support/#api-key) — 25 calls/day on the free tier

Premium alternatives for congressional trades:

- [Benzinga Government Trades API](https://www.benzinga.com/apis/cloud-product/government-trades/)
- [Financial Modeling Prep Senate Trading API](https://site.financialmodelingprep.com/developer/docs/senate-trading-api)

The analysis model behind the default provider is `gb10-writing` on the GX10 — OpenAI-compatible,
no key. Setting `LLM_PROVIDER=anthropic` switches the calls to Anthropic's Claude instead; a key for
that provider is created at [console.anthropic.com](https://console.anthropic.com/).

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

This is a prototype for educational purposes. Always do your own research before making investment
decisions. Past performance does not guarantee future results. Trading carries risk of financial
loss.
