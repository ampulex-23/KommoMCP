# KommoMCP

MCP Server for Kommo/amoCRM with analytics focus.

## Features

- 🔌 **MCP Protocol** - Works with Claude Desktop, Cursor, Windsurf
- 📊 **Analytics** - Pipeline analytics, manager performance, sales forecasts
- 🔄 **Data Sync** - Incremental sync from Kommo API to PostgreSQL
- ⚡ **Async** - Built with asyncio for high performance
- 🗄️ **PostgreSQL** - Local database for big data analytics

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 15+
- Kommo account with API access

### Installation

```bash
# Clone repository
git clone https://github.com/your-repo/kommo-mcp.git
cd kommo-mcp

# Install dependencies
poetry install

# Copy environment file
cp .env.example .env
# Edit .env with your Kommo credentials

# Create database
createdb kommo_mcp

# Run server
poetry run kommo-mcp
```

### Claude Desktop Configuration

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kommo": {
      "command": "poetry",
      "args": ["run", "kommo-mcp"],
      "cwd": "/path/to/kommo-mcp"
    }
  }
}
```

## Available Tools

### Sync & Status
- `kommo_ping` - Check API connection
- `kommo_sync_start` - Start data synchronization
- `kommo_sync_status` - Get sync status

### Data Access
- `kommo_pipelines_list` - List all pipelines with stages
- `kommo_users_list` - List all users
- `kommo_leads_list` - List leads with filtering
- `kommo_lead_get` - Get lead details
- `kommo_leads_summary` - Quick leads summary

### Analytics (Coming Soon)
- `kommo_pipeline_analytics` - Pipeline performance metrics
- `kommo_manager_performance` - Manager statistics
- `kommo_sales_forecast` - Sales predictions
- `kommo_funnel_analysis` - Conversion analysis

## Development

```bash
# Install dev dependencies
poetry install --with dev

# Run tests
poetry run pytest

# Lint
poetry run ruff check .

# Type check
poetry run mypy src
```

## License

MIT
