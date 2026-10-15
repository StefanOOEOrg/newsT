#!/bin/bash

# News Trading System - Quick Start Script

echo "=================================="
echo "News Trading System"
echo "=================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo ""
    echo "Please create a .env file from .env.example:"
    echo "  cp .env.example .env"
    echo ""
    echo "Then edit .env and add your API credentials:"
    echo "  - Reddit API credentials (https://www.reddit.com/prefs/apps)"
    echo "  - Anthropic API key (https://console.anthropic.com/)"
    echo ""
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running!"
    echo "Please start Docker and try again."
    exit 1
fi

echo "✅ Pre-flight checks passed"
echo ""
echo "Starting services..."
echo ""

# Start Docker Compose
docker-compose up --build

# Note: Press Ctrl+C to stop
