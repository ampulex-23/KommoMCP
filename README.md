# KommoMCP

MCP Server for Kommo/amoCRM with analytics focus. Enables AI assistants to interact with your CRM data through natural language.

## Coverage

**106 / 1000 user stories implemented** (10.6%)

| Category | Implemented | Total |
|----------|-------------|-------|
| Analytics & Reports | 29 | 100 |
| Automation | 23 | 100 |
| Communications | 9 | 100 |
| Contacts & Companies | 11 | 100 |
| Search & Navigation | 16 | 100 |
| Deal Management | 15 | 100 |

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
  - `ranking` - Manager ranking by revenue/conversion/deals
  - `compare` - Period comparison (month/quarter/year)
  - `yoy` - Year-over-year comparison

### Deals Extended
- `kommo_deals_ext` - **Extended deal management** with actions:
  - `by_stage` - Deals grouped by stage
  - `health` - Deal health analysis (stale, no tasks)
  - `velocity` - Win rate, cycle time, deals per day
  - `at_risk` - Deals at risk of being lost
  - `by_user` - Deals by responsible user

### LTV Analytics
- `kommo_ltv` - **Customer Lifetime Value** with actions:
  - `by_source` - LTV by lead source
  - `by_pipeline` - LTV by pipeline
  - `cohorts` - Cohort analysis by first purchase
  - `segments` - Customer segmentation (VIP, Regular, Low)

### Tasks
- `kommo_tasks_ext` - **Extended task management** with actions:
  - `overdue` - Get overdue tasks
  - `stats` - Task statistics (completion rate, by user)
  - `today` - Tasks due today
  - `by_entity` - Tasks for specific entity
  - `without_responsible` - Tasks without assigned user

### Contacts
- `kommo_contacts_ext` - **Extended contact management** with actions:
  - `search` - Smart contact search with filters
  - `without_deals` - Find contacts without deals
  - `linked` - Get linked entities (deals, companies, tasks)
  - `duplicates` - Find duplicate contacts
  - `merge_preview` - Preview merge of contacts
  - `activity` - Contact activity summary
  - `by_responsible` - Contacts by responsible user
  - `recent` - Recently created contacts

### Search
- `kommo_search` - **Advanced search** with actions:
  - `all` - Search across leads, contacts, companies
  - `leads` - Lead search with filters (pipeline, price, status)
  - `contacts` - Contact search
  - `query` - API text search
  - `related` - Get related entities
  - `recent` - Recently updated
  - `similar` - Find similar entities

### Communications
- `kommo_communications` - **Communication history** with actions:
  - `history` - Full communication history for entity
  - `calls` - Call statistics (incoming/outgoing, duration)
  - `timeline` - Activity timeline for period
  - `last_contact` - When was last contact with entity
  - `by_user` - Communication stats by user
  - `summary` - Overall communication summary
  - `no_contact` - Clients with no recent contact

### CRM Setup
- `kommo_setup` - **CRM configuration** with actions:
  - `templates` - List available pipeline templates
  - `apply_template` - Apply template (sales, services, rental, realestate, education, ecommerce)
  - `create_pipeline` - Create a new pipeline
  - `create_stage` - Add stage to pipeline
  - `create_field` - Create custom field
  - `create_source` - Add lead source

### Data Quality
- `kommo_data_quality` - **Data quality analysis** with actions:
  - `report` - Full quality report with scores
  - `deals` - Check deal quality (missing fields)
  - `duplicates` - Find duplicate contacts/companies
  - `validate` - Validate data completeness

### Smart Alerts
- `kommo_alerts` - **Notifications and digests** with actions:
  - `check` - Generate all alerts (stale deals, overdue tasks, churn, performance)
  - `digest` - Daily/weekly/monthly digest with key metrics
  - `stale` - Stale deals alerts only
  - `overdue` - Overdue tasks alerts only
  - `performance` - Manager performance drop alerts

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
- "Покажи все алерты"
- "Дайжест за неделю"
- "Какие задачи просрочены?"
- "Рейтинг менеджеров по конверсии"
- "Сравни этот месяц с прошлым"
- "Как мы работаем по сравнению с прошлым годом?"
- "Проверь качество данных"
- "Найди дубликаты контактов"
- "Настрой CRM для автосервиса"
- "Покажи шаблоны воронок"
- "Создай воронку для интернет-магазина"
- "Покажи историю общения с клиентом"
- "Когда последний раз звонили клиенту?"
- "Статистика звонков за месяц"
- "Найди контакты без сделок"
- "Поиск сделок дороже 100к"
- "Какие сделки связаны с контактом?"
- "Покажи просроченные задачи"
- "Статистика задач за месяц"
- "Задачи на сегодня"
- "LTV клиентов по каналам"
- "Когортный анализ клиентов"
- "Сегментация клиентов"
- "Здоровье сделок"
- "Сделки под угрозой"
- "Скорость закрытия сделок"
- "Контакты по менеджерам"
- "Клиенты без контакта"
- "Сводка по коммуникациям"

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
