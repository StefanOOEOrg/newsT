# Testing Guide

This directory contains the test suite for the News Trading System.

## Test Structure

```
tests/
├── __init__.py                      # Test package initialization
├── conftest.py                      # Pytest fixtures and test utilities
├── requirements.txt                 # Test dependencies
├── test_collectors/                 # Collector module tests
│   ├── __init__.py
│   ├── test_base_collector.py      # BaseCollector tests
│   ├── test_rss_collector.py       # RSSCollector tests
│   ├── test_collector_factory.py   # CollectorFactory tests
│   └── test_api_collectors.py      # API collector tests (TODO)
└── README.md                        # This file
```

## Running Tests

### Prerequisites

Install test dependencies:
```bash
pip install -r tests/requirements.txt
```

Or use make:
```bash
make install-test
```

### Run All Tests

```bash
pytest
```

Or:
```bash
make test
```

### Run Tests with Coverage

```bash
pytest --cov --cov-report=html
```

Or:
```bash
make test-coverage
```

Then open `htmlcov/index.html` in your browser to view the coverage report.

### Run Specific Tests

Run tests for a specific module:
```bash
pytest tests/test_collectors/test_base_collector.py
```

Run tests for a specific class:
```bash
pytest tests/test_collectors/test_base_collector.py::TestBaseCollector
```

Run a specific test:
```bash
pytest tests/test_collectors/test_base_collector.py::TestBaseCollector::test_initialization
```

### Run Tests by Marker

Unit tests only:
```bash
pytest -m unit
```

Integration tests only:
```bash
pytest -m integration
```

Collector tests only:
```bash
pytest -m collector
```

### Verbose Output

```bash
pytest -v
```

Or:
```bash
make test-verbose
```

## Test Categories

Tests are organized by markers:

- `@pytest.mark.unit` - Unit tests that don't require external dependencies
- `@pytest.mark.integration` - Integration tests requiring database or APIs
- `@pytest.mark.slow` - Tests that take longer to run
- `@pytest.mark.collector` - Collector-related tests
- `@pytest.mark.analyzer` - Analyzer-related tests
- `@pytest.mark.dashboard` - Dashboard-related tests

## Dependency Injection for Testing

The test suite uses dependency injection to make collectors testable without requiring a real database.

### Database Adapter Pattern

Instead of directly connecting to PostgreSQL, collectors can use a `DatabaseAdapter` interface:

```python
class TestDatabaseAdapter(MockDatabaseAdapter):
    """Test database adapter using mocks."""

    def get_companies(self):
        return [(1, 'Genpact', 'G', ['genpact'])]

    def post_exists(self, post_id):
        return False

    def save_posts(self, posts):
        return len(posts)
```

### Using Mocks in Tests

```python
def test_collector_with_mock(mock_db):
    collector = TestableCollector("postgresql://test", db_adapter=mock_db)

    # Test without real database
    companies = collector.get_companies()
    assert len(companies) == 3
```

## Fixtures

Common fixtures are defined in `conftest.py`:

- `mock_db` - Mock database adapter
- `sample_companies` - Sample company data
- `sample_posts` - Sample post data
- `mock_rss_feed` - Mock RSS feed response

### Using Fixtures

```python
def test_something(mock_db, sample_posts):
    # Fixtures are automatically injected
    collector.save_posts(sample_posts)
    assert len(mock_db.posts) == 2
```

## Writing New Tests

### Test File Naming

- Test files must start with `test_`
- Test classes must start with `Test`
- Test functions must start with `test_`

### Example Test Structure

```python
"""
Unit tests for MyModule.
"""
import pytest

class TestMyModule:
    """Test suite for MyModule."""

    def test_initialization(self):
        """Test that module initializes correctly."""
        module = MyModule()
        assert module is not None

    def test_with_fixture(self, mock_db):
        """Test using a fixture."""
        result = module.do_something(mock_db)
        assert result is True

    @pytest.mark.integration
    def test_database_integration(self):
        """Integration test requiring database."""
        # This test will be skipped with -m unit
        pass
```

## Mocking External APIs

For testing collectors that use external APIs (NewsAPI, Finnhub, etc.):

```python
@patch('collectors.newsapi_collector.requests')
def test_api_call(mock_requests, mock_db):
    # Mock the API response
    mock_response = Mock()
    mock_response.json.return_value = {'articles': [...]}
    mock_requests.get.return_value = mock_response

    collector = NewsAPICollector("postgresql://test", db_adapter=mock_db)
    posts = collector.collect_for_company(1, 'Genpact', 'G', ['genpact'])

    assert len(posts) > 0
```

## CI/CD Integration

Tests run automatically on:
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`

See `.github/workflows/test.yml` for CI configuration.

## Coverage Goals

Target coverage: 80%+

Current coverage can be viewed:
- Locally: `htmlcov/index.html` after running `make test-coverage`
- CI/CD: Check the GitHub Actions workflow results

## Best Practices

1. **Isolate tests** - Each test should be independent
2. **Use fixtures** - Reuse common setup code via fixtures
3. **Mock external dependencies** - Don't make real API calls in tests
4. **Test edge cases** - Include tests for error conditions
5. **Keep tests fast** - Unit tests should run quickly
6. **Use descriptive names** - Test names should explain what they test
7. **One assertion per test** - Focus each test on one behavior
8. **Clean up** - Use fixtures and context managers for cleanup

## Troubleshooting

### Import Errors

If you get import errors, make sure the collector/analyzer directories are in your Python path:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'collector'))
```

### Database Connection Errors

For integration tests requiring a database, ensure PostgreSQL is running:

```bash
docker-compose up -d postgres
```

### Slow Tests

Skip slow tests during development:

```bash
pytest -m "not slow"
```

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [Unittest.mock](https://docs.python.org/3/library/unittest.mock.html)
- [Coverage.py](https://coverage.readthedocs.io/)
