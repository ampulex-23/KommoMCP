#!/bin/bash
sudo -u postgres psql -c "CREATE USER kommo_mcp WITH PASSWORD 'kommo_mcp_password';"
sudo -u postgres psql -c "CREATE DATABASE kommo_mcp OWNER kommo_mcp;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE kommo_mcp TO kommo_mcp;"
echo "Database setup complete"
