# Coding Guidelines

## Python Style

- Follow PEP 8, max line length 100 chars
- Use type hints and Google-style docstrings
- No spagetti code, max file lenght two pages
- Classes: `PascalCase`, functions: `snake_case`, constants: `UPPER_SNAKE_CASE`

## Error Handling
- Never only supress Errors and Warnings. Always try to fix the root cause
- Use specific exceptions, never bare `except:`
- Always log errors with context
- Clean up resources in `finally` blocks

## Database

**Connection handling:** Always use try/except/finally blocks for database connections. Initialize `conn=None`, commit on success, rollback on errors in except block, and close connection in finally block. Use context managers (`with`) for cursors.

**Critical rules:**
- ALWAYS use parameterized queries (never f-strings in SQL)
- Use explicit column names (avoid `SELECT *`)
- Commit explicitly, rollback on errors

## Configuration

- **Never hardcode settings** - all configurable values belong in config files
- Sensitive data (API keys, credentials) in `.env` only
- Each service has `config.py` with all constants and settings
- Group settings with section headers (e.g., `# LOGGING CONFIGURATION`)
- Document each setting with comments explaining purpose, valid values, and defaults
- Examples of settings that belong in config:
  - Timeouts, intervals, thresholds
  - Cache TTLs, batch sizes, limits
  - API endpoints, model names
  - Feature flags, enabled/disabled options
- Validate required env vars on startup

## Docker Workflow

After code changes:
```bash
docker-compose restart service_name
docker-compose logs --tail=50 service_name
```

## Streamlit Dashboard

- Use expanders for collapsible sections
- Use `st.dataframe()` with `hide_index=True`
- Configure columns with `column_config` for custom widths
- Cache expensive operations with `@st.cache_data`

## Dependency Injection

Inject dependencies via constructor parameters rather than hard-coding them (e.g., `database_url`, API clients). This allows easy mocking in tests by passing Mock objects instead of real clients. Extract connection methods to separate functions for better testability.

## Unit Testing

**Maximize test coverage:**

- Aim for >80% code coverage on business logic
- Test edge cases, error paths, and happy paths
- Use `pytest` as the testing framework
- Place tests in `tests/` directory mirroring source structure

**Test structure:** Use pytest with fixtures for common setup. Mock external dependencies (database, APIs) and verify calls with assertions. Test one behavior per function with descriptive names. Structure tests in a class with `@pytest.fixture` for reusable mocks.

**Testing best practices:**
- Mock external dependencies (database, API calls, file I/O)
- Use descriptive test names that explain what is being tested
- Test one thing per test function
- Use fixtures for common setup
- Test error conditions and edge cases
- Run tests before committing: `pytest tests/ -v --cov=.`

**What to test:**
- Business logic functions
- Alert generation rules
- Sentiment scoring
- Configuration validation
- Error handling paths
- Edge cases (empty inputs, null values, boundary conditions)

**What NOT to test:**
- Third-party libraries (psycopg2, Anthropic SDK)
- Simple property getters/setters
- Trivial functions with no logic

## Logging

- Use structured logging with context: `logger.info(f"Processing {asset_name}", extra={'asset_id': id})`
- Log levels: DEBUG for verbose details, INFO for normal flow, WARNING for recoverable issues, ERROR for failures
- Never log sensitive data (API keys, credentials, PII)
- Include identifiers in logs for traceability (asset_id, post_id, etc.)

## API & External Services

- Always set timeouts on HTTP requests (default: 10 seconds)
- Implement exponential backoff for retries on transient failures
- Respect rate limits - check before calling, record after calling
- Validate API responses before processing (check status, schema)
- Use API versioning in URLs when available

## Data Validation

- Validate input at service boundaries (API endpoints, user input, external data)
- Use early returns for invalid data - fail fast
- Sanitize user input before database queries (even with parameterized queries)
- Check for None/null before accessing nested attributes
- Validate date ranges and numeric bounds

## Performance

- Use batch operations for database inserts (avoid N+1 queries)
- Index foreign keys and frequently queried columns
- Avoid loading full datasets - use LIMIT, pagination, or cursors
- Cache expensive computations with appropriate TTL
- Close connections and free resources promptly

## Security

- Never commit secrets to git (use .env and .gitignore)
- Rotate API keys periodically
- Use environment-specific credentials (dev/staging/prod)
- Validate and sanitize all external input
- Use HTTPS for all external API calls

## Code Organization

- **DRY Principle**: Do things in one place only - never duplicate functionality across services
- One class/major function per file (exceptions: related helpers)
- Group related functions into modules (collectors/, analyzers/, utils/)
- Keep functions under 50 lines - extract complex logic into helpers
- Use descriptive variable names - avoid abbreviations (except common ones: id, url, api)
- Put constants at module top, after imports
- Centralize data collection - collectors fetch and store, services consume from database
- **Minimize dependencies**: Only include packages in requirements.txt that are actually imported in the code

## Git & Version Control

- Write descriptive commit messages (what and why, not how)
- One logical change per commit
- Update requirements.txt when adding dependencies
- Tag releases with semantic versioning (v1.2.0)
- Never force push to main/master

## Documentation

- Update README.md when adding features
- Document breaking changes in commit messages
- Keep .env.example in sync with required variables
- Add inline comments only for non-obvious logic
- Document API rate limits and quotas in collector files

## Common Patterns

**Shared module access:** To access shared modules, check `parent/shared` path, then `parent.parent/shared`, and insert into `sys.path`.

**Scheduler pattern:** Use `BlockingScheduler` with `IntervalTrigger` for periodic jobs. Wrap `scheduler.start()` in try/except for `KeyboardInterrupt` and `SystemExit`.
