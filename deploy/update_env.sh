#!/bin/bash
cat > /opt/kommo-mcp/.env << 'EOF'
# Kommo API Configuration
KOMMO_SUBDOMAIN=your-subdomain
KOMMO_ACCESS_TOKEN=your-access-token

# Database (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://kommo_mcp:kommo_mcp_password@localhost:5432/kommo_mcp

# MCP Server
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8000

# Webhook Server (optional)
WEBHOOK_ENABLED=true
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8001
WEBHOOK_SECRET=your-webhook-secret

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=text

# Sync settings
SYNC_BATCH_SIZE=50
EOF
echo ".env updated"
