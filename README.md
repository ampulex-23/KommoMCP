# KommoMCP

MCP Server for Kommo/amoCRM with analytics focus. Enables AI assistants to interact with your CRM data through natural language.

## Features

- 🔌 **MCP Protocol** - Works with Claude Desktop, Cursor, Windsurf, n8n
- 📊 **Analytics** - Pipeline analytics, manager performance, sales forecasts
- 🔄 **Data Sync** - Incremental sync from Kommo API to PostgreSQL
- ⚡ **Async** - Built with asyncio for high performance
- 🗄️ **PostgreSQL** - Local database for big data analytics
- 🌐 **HTTP Transport** - REST API for n8n and other integrations

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

### n8n Configuration

Use MCP Client node with HTTP transport:
- **URL**: `https://your-domain.com/mcp`
- **Transport**: HTTP Streamable

## Available Tools

### Sync & Status
- `kommo_ping` - Check API connection
- `kommo_sync_start` - Start data synchronization (full or incremental)
- `kommo_sync_status` - Get sync status

### Data Access
- `kommo_pipelines_list` - List all pipelines with stages
- `kommo_users_list` - List all users
- `kommo_leads_list` - List leads with filtering, sorting, date ranges
- `kommo_lead_get` - Get lead details with contacts
- `kommo_lead_create` - Create new lead
- `kommo_contacts_list` - List contacts
- `kommo_contact_create` - Create new contact

### Analytics
- `kommo_pipeline_analytics` - Pipeline performance metrics (conversion, avg check, cycle time)
- `kommo_manager_performance` - Manager statistics (leads, revenue, win rate)
- `kommo_sales_forecast` - Sales predictions (expected, optimistic, pessimistic)
- `kommo_funnel_analysis` - Conversion analysis by stage
- `kommo_stale_deals` - Find deals stuck without activity
- `kommo_lead_sources` - Lead sources analytics by pipeline
- `kommo_revenue_trend` - Revenue dynamics by day/week/month
- `kommo_churn_risk` - Identify customers at risk of churn
- `kommo_lead_score` - Score leads to prioritize sales efforts
- `kommo_duplicates_find` - Find duplicate contacts/companies

### Actions
- `kommo_task_create` - Create tasks linked to leads/contacts/companies
- `kommo_note_create` - Add notes to any entity

## Example Queries

Ask your AI assistant:
- "Покажи аналитику по основной воронке за последний месяц"
- "Сделай прогноз продаж на 30 дней"
- "Сравни показатели менеджеров"
- "Покажи последние 10 сделок"
- "Где теряются сделки в воронке?"
- "Найди зависшие сделки без активности более 14 дней"
- "Покажи динамику выручки по месяцам"
- "Какие клиенты в зоне риска оттока?"
- "Оцени качество текущих лидов"
- "Найди дубликаты контактов"

## Deployment

### VDS with nginx + SSL

```bash
# Install on server
cd /opt/kommo-mcp
python -m venv venv
source venv/bin/activate
pip install -e .

# Create systemd service
sudo systemctl enable kommo-webhooks
sudo systemctl start kommo-webhooks

# Configure nginx with SSL
sudo certbot --nginx -d your-domain.com
```

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
