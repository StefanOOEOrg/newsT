#!/bin/bash
# Test runner script for News Trading System

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}News Trading System - Test Runner${NC}"
echo "===================================="
echo ""

# Check if running in Docker or locally
if [ -f /.dockerenv ]; then
    echo "Running in Docker container"
    IN_DOCKER=true
else
    echo "Running locally"
    IN_DOCKER=false
fi

# Install test dependencies if needed
if ! python3 -c "import pytest" 2>/dev/null; then
    echo -e "${YELLOW}Installing test dependencies...${NC}"
    if [ "$IN_DOCKER" = true ]; then
        pip install -q -r tests/requirements.txt
    else
        python3 -m pip install -q -r tests/requirements.txt 2>/dev/null || {
            echo -e "${RED}Error: Cannot install dependencies. Please create a virtual environment:${NC}"
            echo "  python3 -m venv venv"
            echo "  source venv/bin/activate"
            echo "  pip install -r tests/requirements.txt"
            exit 1
        }
    fi
fi

# Parse command line arguments
COVERAGE=false
VERBOSE=false
MARKERS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage|-c)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --unit)
            MARKERS="unit"
            shift
            ;;
        --integration)
            MARKERS="integration"
            shift
            ;;
        --collector)
            MARKERS="collector"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--coverage] [--verbose] [--unit|--integration|--collector]"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="pytest"

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -vv"
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov --cov-report=html --cov-report=term"
fi

if [ -n "$MARKERS" ]; then
    PYTEST_CMD="$PYTEST_CMD -m $MARKERS"
fi

# Run tests
echo -e "${YELLOW}Running tests...${NC}"
echo "Command: $PYTEST_CMD"
echo ""

if $PYTEST_CMD; then
    echo ""
    echo -e "${GREEN}✓ All tests passed!${NC}"

    if [ "$COVERAGE" = true ]; then
        echo ""
        echo -e "${YELLOW}Coverage report generated in htmlcov/index.html${NC}"
    fi

    exit 0
else
    echo ""
    echo -e "${RED}✗ Tests failed!${NC}"
    exit 1
fi
