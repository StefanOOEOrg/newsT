.PHONY: help install install-test test test-verbose test-coverage test-unit test-integration clean lint format docker-up docker-down docker-logs

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	pip install -r collector/requirements.txt
	pip install -r analyzer/requirements.txt
	pip install -r dashboard/requirements.txt

install-test:  ## Install test dependencies
	pip install -r tests/requirements.txt

test:  ## Run all tests in Docker
	./test-docker.sh

test-verbose:  ## Run tests with verbose output in Docker
	./test-docker.sh -vv

test-coverage:  ## Run tests with coverage report in Docker
	./test-docker.sh --coverage

test-unit:  ## Run only unit tests in Docker
	./test-docker.sh --unit

test-integration:  ## Run only integration tests in Docker
	./test-docker.sh --integration

test-collector:  ## Run collector tests only in Docker
	./test-docker.sh

test-local:  ## Run tests locally (requires venv)
	pytest tests/test_collectors/ -v

test-watch:  ## Run tests in watch mode
	pytest-watch

clean:  ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf .mypy_cache

lint:  ## Run code linting
	flake8 collector/ analyzer/ dashboard/ tests/ --max-line-length=120 --exclude=__pycache__,venv,env

format:  ## Format code with black
	black collector/ analyzer/ dashboard/ tests/ --line-length=120

type-check:  ## Run type checking with mypy
	mypy collector/ analyzer/ dashboard/ --ignore-missing-imports

docker-up:  ## Start all Docker services
	docker-compose up -d

docker-down:  ## Stop all Docker services
	docker-compose down

docker-logs:  ## Show Docker logs
	docker-compose logs -f

docker-build:  ## Build all Docker images
	docker-compose build

docker-restart:  ## Restart all Docker services
	docker-compose restart

docker-ps:  ## Show running containers
	docker-compose ps

check:  ## Run all checks (lint, type-check, test)
	@echo "Running linting..."
	@make lint
	@echo "\nRunning type checking..."
	@make type-check
	@echo "\nRunning tests..."
	@make test
	@echo "\nAll checks passed!"
