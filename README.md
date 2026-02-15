# KommoMCP

AI-powered CRM assistant for Kommo/amoCRM. Telegram bot with natural language interface for full CRM management — analytics, setup, entity operations, monitoring.

## Features

- 🤖 **Telegram Bot** — AI assistant (`@kommo_wizard_bot`) for CRM via natural language
- 🧠 **RAG Architecture** — Dynamic tool retrieval, compact prompts (~500 tokens vs 3000+)
- 🏢 **Multi-Tenant SaaS** — Each user gets isolated CRM connection, own API keys
- � **20+ Tool Handlers** — Setup, analytics, reports, entities, bulk ops, cleanup, templates
- 🎨 **React Admin Panel** — Dashboard, users/CRM monitoring, AI session logs
- 🔄 **Data Sync** — Incremental sync from Kommo API to PostgreSQL
- ⚡ **Async** — Built with asyncio + aiohttp for high performance
- 🗄️ **PostgreSQL** — Local database for big data analytics
- 🌐 **MCP Protocol** — Works with Claude Desktop, Cursor, Windsurf, n8n
- 🛡️ **Pipeline Templates** — 5 ready-made pipeline templates (capture, qualification, followup, demo, proposal)

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Telegram Bot   │────▶│  AI Chat Engine  │────▶│   Kommo API     │
│ (@kommo_wizard) │     │  (GPT-4o + RAG)  │     │  (per tenant)   │
└─────────────────┘     └────────┬─────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Tenant A │ │ Tenant B │ │ Tenant C │
              │ (own DB) │ │ (own DB) │ │ (own DB) │
              └──────────┘ └──────────┘ └──────────┘

┌─────────────────┐     ┌──────────────────┐
│  React Admin    │────▶│  Logs Server     │
│  (SPA /logs/)   │     │  (aiohttp:8765)  │
└─────────────────┘     └──────────────────┘
```

### RAG-Based Tool Retrieval

The Telegram bot uses **RAG (Retrieval-Augmented Generation)** architecture for scalable tool management:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  User Request   │────▶│  Tool Retriever  │────▶│  Dynamic Prompt │
│                 │     │  (keyword match) │     │  (base + tools) │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌──────────────────┐              ▼
                        │   Tool Registry  │     ┌─────────────────┐
                        │   (YAML files)   │────▶│   LLM + Tools   │
                        └──────────────────┘     │   (execution)   │
                                                 └─────────────────┘
```

**Benefits:**
- **Compact prompts**: ~500 tokens instead of 3000+ (only relevant tools loaded)
- **Scalability**: Add hundreds of tools without prompt size growth
- **Maintainability**: Tool definitions in separate YAML files
- **Accuracy**: Better tool selection through keyword matching

### Conversation Memory

The bot maintains **conversation history** per user for context retention:

- **Per-user isolation**: Each Telegram user has separate history
- **Context window**: Last 10 messages included in each request
- **Smart confirmations**: Bot remembers pending actions (e.g., "Delete pipeline?" → "Yes")

**Tool Registry** (`src/kommo_mcp/telegram/tools/*.yaml`):
```yaml
name: kommo_pipeline_analytics
category: analytics
keywords: [воронка, конверсия, аналитика, статистика]
description: Аналитика воронки продаж
examples:
  - query: "Покажи аналитику воронки"
  - query: "Конверсия по этапам"
```

### AI-Powered Analytics Engine

The system uses **AI scripting** approach where natural language queries are translated into structured tool calls:

1. **Natural Language → Tool Selection**: AI assistant analyzes user request and selects appropriate MCP tool
2. **Tool Execution**: MCP server executes the tool against local PostgreSQL or Kommo API
3. **Big Data Processing**: Complex analytics run on local PostgreSQL for speed (millions of records)
4. **Response Generation**: AI formats results into human-readable insights

### Big Data Strategy

Instead of querying Kommo API for every analytics request (slow, rate-limited), we:

1. **Sync Once**: `kommo_sync_start` pulls all data to local PostgreSQL
2. **Analyze Locally**: All analytics tools query local DB (fast, no limits)
3. **Incremental Updates**: Only new/changed records synced on subsequent runs

This enables:
- **Complex aggregations** across millions of deals/contacts
- **Historical analysis** without API pagination limits
- **Real-time dashboards** without hitting rate limits
- **Custom SQL** for advanced analytics not available in Kommo UI

### Multi-Tenant SaaS Mode

For production deployments, the system supports multi-tenant architecture:

```
┌─────────────────┐     ┌──────────────────┐
│  Telegram Bot   │────▶│  Tenant Manager  │
│  (@kommo_wizard)│     │                  │
└─────────────────┘     └────────┬─────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Tenant A │ │ Tenant B │ │ Tenant C │
              │ (own DB) │ │ (own DB) │ │ (own DB) │
              └──────────┘ └──────────┘ └──────────┘
```

Each tenant gets:
- Isolated PostgreSQL database
- Own Kommo API credentials
- Own OpenAI API key for AI features
- Rate limiting per tenant

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

## AI Tool Handlers (Telegram Bot)

### CRM Setup
- `kommo_setup` - **CRM configuration** with actions:
  - `templates` - List available pipeline templates (5 built-in)
  - `apply_template` - Apply template (capture, qualification, followup, demo, proposal)
  - `create_pipeline` - Create a new pipeline
  - `create_stage` - Add stage to pipeline
  - `update_pipeline` / `update_stage` - Rename, recolor
  - `delete_pipeline` / `delete_stage` - Delete with lead migration
  - `reorder_stages` - Change stage order
  - `create_field` / `update_field` / `delete_field` - Custom fields CRUD
  - `create_source` - Add lead source

### Entity Actions
- `kommo_entity_actions` - **Entity operations** with actions:
  - `add_note` - Add note to entity
  - `get_notes` / `get_history` - Get notes and history
  - `create_task` / `get_tasks` / `complete_task` - Task management
  - `update_lead` / `move_lead` - Lead updates
  - `link_contact` / `unlink_contact` - Contact linking

### Bulk Operations
- `kommo_bulk_actions` - **Mass operations** with actions:
  - `mass_move` - Move multiple leads to stage
  - `mass_tag` - Add tags to entities
  - `mass_assign` - Reassign entities
  - `mass_update` - Update fields in bulk

### Users & Teams
- `kommo_users` - **User management** with actions:
  - `list` - List all CRM users
  - `workload` - Manager workload distribution
  - `activity` - User activity stats

### Reports
- `kommo_reports` - **CRM reports** with actions:
  - `top_deals` - Top deals by amount
  - `pipeline_summary` - Pipeline overview
  - `manager_stats` - Manager performance

### Additional Tools
- `kommo_webhooks` - Webhook management (list, create, delete)
- `kommo_tags` - Tag management (list, create, delete, assign)
- `kommo_custom_fields` - Custom fields CRUD + mass operations
- `kommo_sources` - Lead sources management and analytics
- `kommo_companies` - Company management (list, get, create, update)
- `kommo_duplicates` - Duplicate detection and merge
- `kommo_links` - Entity relationship management
- `kommo_catalogs` - Product catalogs management
- `kommo_events` - CRM event log
- `kommo_calls` - Call records management
- `kommo_cleanup` - Data cleanup and CRM reset
- `kommo_mock_data` - Generate test data (contacts, companies, leads)

### Quick Actions
- `kommo_list_pipelines` - List all pipelines with stages
- `kommo_search_contacts` - Quick contact search

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

## Admin Panel

React SPA for monitoring and management, served at `/logs/`.

**Stack:** React + Vite + TailwindCSS + Recharts

**Pages:**
- **Login** — Cookie-based session auth
- **Dashboard** — Session stats, charts (sessions over time, activity by user), recent sessions
- **Users & CRM** — Telegram users, connected CRM tenants, statuses (active/pending/error), Kommo domains
- **Sessions** — AI interaction sessions with search and status filter
- **Session Detail** — Full iteration breakdown: user message, tool calls, results, errors, response

**API Endpoints:**
- `POST /api/login` — JSON auth
- `GET /api/me` — Current user
- `GET /api/users` — All TG users with CRM tenants
- `GET /api/sessions` — Session list with stats
- `GET /api/session/{id}` — Session detail

```bash
# Dev
cd admin && npm run dev

# Build
cd admin && npm run build
# Output: admin/dist/ → served by logs_server
```

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start, show welcome |
| `/connect` | Connect new CRM |
| `/crm_list` | List all connected CRMs |
| `/switch` | Switch active CRM |
| `/status` | Current CRM status |
| `/openai` | Set OpenAI API key |
| `/sync` | Sync CRM data to local DB |
| `/wizard` | CRM setup wizard |
| `/remove_crm` | Disconnect a CRM |
| `/help` | All commands |
| `/cancel` | Cancel current operation |

Any plain text message is treated as an AI query to the active CRM.

## Deployment

### VDS with nginx + systemd

```bash
# Server setup
cd /opt/kommo-mcp
python -m venv venv
source venv/bin/activate
pip install -e .

# Build admin panel
cd admin && npm install && npm run build

# systemd service
sudo systemctl enable kommo-telegram-bot
sudo systemctl start kommo-telegram-bot

# nginx proxy
# /logs/ → localhost:8765 (admin panel + API)
# /mcp   → localhost:8001 (MCP HTTP transport)
sudo certbot --nginx -d your-domain.com
```

## Project Structure

```
KommoMCP/
├── src/kommo_mcp/
│   ├── telegram/
│   │   ├── bot.py              # Telegram bot (aiogram)
│   │   ├── ai_chat.py          # AI chat engine (GPT-4o + tools)
│   │   ├── logs_server.py      # Admin panel backend + SPA serving
│   │   └── tools/              # YAML tool definitions for RAG
│   ├── saas/
│   │   ├── manager.py          # TenantManager (multi-tenant)
│   │   └── orchestrator.py     # DB orchestration per tenant
│   └── server.py               # MCP server (stdio + HTTP)
├── admin/                       # React admin panel
│   ├── src/
│   │   ├── pages/              # Login, Dashboard, Users, Sessions, SessionDetail
│   │   ├── components/         # Layout with sidebar
│   │   └── api.js              # API client
│   └── vite.config.js
├── deploy/
│   └── amomcp-nginx.conf
└── README.md
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run bot locally
python -m kommo_mcp.telegram

# Run admin panel dev server
cd admin && npm run dev

# Lint
ruff check src/
```

## License

MIT
