.PHONY: help install test test-coverage lint format check clean docker-up docker-down docker-logs docker-build

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package and the dev dependencies from the lockfile
	uv sync --locked

test:  ## Run the suite
	uv run pytest src/tests -q

test-coverage:  ## Run the suite with the coverage gate of CI
	uv run pytest src/tests -q --cov=newstrading --cov-report=term-missing --cov-fail-under=80

lint:  ## Run ruff and the format check
	uv run ruff check src && uv run ruff format --check src

format:  ## Format the package with ruff
	uv run ruff format src

check:  ## Run every gate (lint, format, tests)
	@make lint
	@make test

clean:  ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf .ruff_cache

docker-up:  ## Start the PostgreSQL stack and the app
	docker compose up -d

docker-down:  ## Stop the stack
	docker compose down

docker-logs:  ## Follow the logs of the stack
	docker compose logs -f

docker-build:  ## Build the package image
	docker compose build
