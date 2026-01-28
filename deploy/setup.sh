#!/bin/bash
# KommoMCP deployment script

set -e

APP_DIR="/opt/kommo-mcp"
VENV_DIR="$APP_DIR/venv"

echo "=== KommoMCP Deployment ==="

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y python3-pip python3-venv postgresql postgresql-contrib

# Create app directory
echo "Creating app directory..."
mkdir -p $APP_DIR
cd $APP_DIR

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

# Install Poetry in venv
echo "Installing Poetry..."
pip install poetry

# Copy project files (should be done before running this script)
# Install dependencies
echo "Installing dependencies..."
cd $APP_DIR
poetry config virtualenvs.create false
poetry install --no-dev

# Setup PostgreSQL
echo "Setting up PostgreSQL..."
sudo -u postgres psql -c "CREATE USER kommo_mcp WITH PASSWORD 'kommo_mcp_password';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE kommo_mcp OWNER kommo_mcp;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE kommo_mcp TO kommo_mcp;" 2>/dev/null || true

echo "=== Setup complete ==="
echo "Next steps:"
echo "1. Edit /opt/kommo-mcp/.env with your Kommo credentials"
echo "2. Run: systemctl start kommo-mcp"
