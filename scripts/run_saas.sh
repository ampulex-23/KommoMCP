#!/bin/bash
# Script to run KommoMCP SaaS infrastructure

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Check for .env file
if [ ! -f "docker/.env" ]; then
    echo "Creating docker/.env from example..."
    cp docker/.env.example docker/.env
    echo "Please edit docker/.env with your configuration"
    exit 1
fi

# Build tenant image
echo "Building tenant Docker image..."
docker build -t kommo-mcp:latest -f docker/Dockerfile.tenant .

# Build bot image
echo "Building bot Docker image..."
docker build -t kommo-bot:latest -f docker/Dockerfile.bot .

# Start services
echo "Starting SaaS infrastructure..."
cd docker
docker-compose -f docker-compose.saas.yml up -d

echo ""
echo "✅ KommoMCP SaaS started!"
echo ""
echo "Services:"
echo "  - PostgreSQL: localhost:5432"
echo "  - Redis: localhost:6379"
echo "  - Telegram Bot: running"
echo ""
echo "Logs: docker-compose -f docker/docker-compose.saas.yml logs -f"
