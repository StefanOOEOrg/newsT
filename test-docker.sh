#!/bin/bash
# Run tests in Docker container

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Running tests in Docker container...${NC}"
echo ""

# Parse arguments
COVERAGE=""
VERBOSE="-v"
MARKERS=""
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage|-c)
            COVERAGE="--cov=collector --cov=analyzer --cov-report=html --cov-report=term"
            shift
            ;;
        --verbose|-vv)
            VERBOSE="-vv"
            shift
            ;;
        --quiet|-q)
            VERBOSE=""
            shift
            ;;
        --unit)
            MARKERS="-m unit"
            shift
            ;;
        --integration)
            MARKERS="-m integration"
            shift
            ;;
        *)
            EXTRA_ARGS="$EXTRA_ARGS $1"
            shift
            ;;
    esac
done

# Build docker command (use current directory)
DOCKER_CMD="docker run --rm -v $(pwd):/app -w /app python:3.11-slim bash -c"

# Build pytest command
INSTALL_CMD="pip install -q pytest pytest-mock feedparser psycopg2-binary python-dotenv anthropic apscheduler"
if [ -n "$COVERAGE" ]; then
    INSTALL_CMD="$INSTALL_CMD pytest-cov"
fi

PYTEST_CMD="python -m pytest tests/ $VERBOSE $COVERAGE $MARKERS $EXTRA_ARGS"

# Run tests
$DOCKER_CMD "$INSTALL_CMD 2>&1 | grep -v 'notice\|WARNING' && $PYTEST_CMD"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ All tests passed!${NC}"

    if [ -n "$COVERAGE" ]; then
        echo ""
        echo "Coverage report generated in htmlcov/index.html"
    fi
else
    echo ""
    echo -e "\033[0;31m✗ Tests failed!${NC}"
fi

exit $EXIT_CODE
