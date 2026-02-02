# KommoMCP

MCP Server for Kommo/amoCRM with analytics focus. Enables AI assistants to interact with your CRM data through natural language.

## Coverage

**54 / 1000 user stories implemented** (5.4%)

| Category | Implemented | Total |
|----------|-------------|-------|
| Analytics & Reports | 19 | 100 |
| Automation | 11 | 100 |
| Communications | 1 | 100 |
| Search & Navigation | 11 | 100 |
| Deal Management | 10 | 100 |
| Contacts & Companies | 2 | 100 |

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
- `kommo_analytics` - **Universal analytics tool** with actions:
  - `pipeline` - Pipeline performance (conversion, avg check, cycle time)
  - `funnel` - Funnel conversion analysis by stage
  - `forecast` - Sales predictions (expected, optimistic, pessimistic)
  - `managers` - Manager performance comparison
  - `revenue` - Revenue trend by day/week/month
  - `stale` - Find stuck deals without activity
  - `sources` - Lead sources effectiveness
  - `churn` - Customers at risk of churn
  - `scoring` - Score leads to prioritize
  - `duplicates` - Find duplicate contacts/companies

*Legacy individual tools still available for backward compatibility*

### Entity Management
- `kommo_entity` - **Universal CRUD tool** with actions:
  - `get` - Get entity by ID with related entities
  - `list` - List entities with filters, sorting, pagination
  - `create` - Create new entity
  - `update` - Update entity fields
  - `link` / `unlink` - Link/unlink entities
  - `move` - Move lead to another stage
  - `history` - Get entity change history

### Bulk Operations
- `kommo_bulk` - **Mass operations** with actions:
  - `assign` - Reassign entities to user
  - `move` - Move multiple leads to stage
  - `tag` - Add tags to entities
  - `create_tasks` - Create tasks for multiple entities
  - `update` - Update multiple entities
  - `export` - Export entities

### Smart Search
- `kommo_search` - **Intelligent search** with actions:
  - `query` - Natural language search across entities
  - `related` - Find all related entities
  - `recent` - Recently modified entities
  - `similar` - Find similar entities

### Reports
- `kommo_report` - **Formatted reports** with actions:
  - `summary` - Period summary (deals, revenue, conversion)
  - `comparison` - Compare with previous period
  - `pipeline_health` - Pipeline health check with recommendations
  - `activity` - Manager activity report
  - `custom` - Custom report with selected metrics

### Automation
- `kommo_automate` - **AI-powered automation** with actions:
  - `suggest` - Get AI recommendations for automation
  - `stale_followup` - Create tasks for stale deals
  - `escalation` - Escalate deals to manager

### Business Insights
- `kommo_insights` - **Business intelligence** with actions:
  - `top_clients` - Top clients by revenue
  - `rfm` - RFM segmentation (Recency, Frequency, Monetary)
  - `workload` - Manager workload distribution
  - `opportunities` - Upsell/reactivation opportunities
  - `big_deals` - Large deals in pipeline

### Quick Actions
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
- "Сделай отчёт за месяц"
- "Сравни продажи с прошлым периодом"
- "Что можно автоматизировать?"
- "Создай задачи для зависших сделок"
- "Покажи топ-10 клиентов по выручке"
- "Сделай RFM-анализ клиентов"
- "Какая нагрузка на менеджеров?"
- "Найди возможности для допродаж"

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
