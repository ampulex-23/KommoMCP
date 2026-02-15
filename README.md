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
  - `templates` - List available pipeline templates (10 built-in)
  - `apply_template` - Apply template (capture, qualification, followup, demo, proposal, autoservice, realestate, education, ecommerce, b2b_sales)
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

### Export
- `kommo_export` - **Data export** with actions:
  - `leads_csv` - Export leads as CSV table
  - `contacts_csv` - Export contacts as CSV table
  - `analytics` - Summary analytics across all pipelines

### Digest
- `kommo_digest` - **CRM digests and summaries** with actions:
  - `morning` - Morning briefing (deals, tasks, overdue, stale)
  - `weekly` - Weekly report (new/won/lost deals, tasks completed)
  - `my_tasks` - Personal task list (overdue, today, upcoming)

### AI Advisor
- `kommo_advisor` - **AI-powered recommendations** with actions:
  - `next_action` - What to do next with a deal
  - `pipeline_tips` - Pipeline optimization recommendations
  - `loss_analysis` - Lost deals analysis and patterns
  - `closing_tips` - Deal closing advice
  - `objections` - Objection handling guide based on CRM data

### Pipeline Health
- `kommo_pipeline_health` - **Deep pipeline analysis** with actions:
  - `check` - Overall health score (0-100) with key metrics
  - `velocity` - Sales speed: cycle times, daily velocity, median/fastest/slowest
  - `bottlenecks` - Stage-level analysis: stale deals, avg age, congestion
  - `win_loss` - Win/loss ratio, value comparison, cycle time analysis
  - `optimize` - Optimization recommendations per stage

### Forecasting
- `kommo_forecast` - **Sales forecasting** with actions:
  - `pipeline` - Weighted pipeline forecast by stage proximity
  - `revenue` - Monthly revenue prediction with growth trend
  - `deal_probability` - Per-deal win probability scoring (lead_id)
  - `trends` - Weekly trend analysis: new deals, value, won/lost

### Proactive Alerts
- `kommo_alerts` - **CRM health alerts** with actions:
  - `check` - All alerts: stale deals, overdue tasks, missing data
  - `risks` - At-risk deals with risk score and factors
  - `performance` - Team performance alerts: overload, stale ratio
  - `opportunities` - Reactivation, follow-up, no-next-step opportunities

### Period Comparison
- `kommo_compare` - **Data comparison and analysis** with actions:
  - `periods` - This period vs previous: deals, revenue, conversion
  - `trends` - Weekly metric trends with direction detection
  - `patterns` - Day/hour patterns, seasonal conversion analysis
  - `correlations` - Price vs conversion, source performance analysis

### Smart Automation
- `kommo_automation` - **Lead distribution and follow-up** with actions:
  - `auto_assign` - Assign leads by workload (least busy first)
  - `round_robin` - Equal distribution among team members
  - `auto_followup` - Create follow-up tasks for inactive deals

### Personal View
- `kommo_my` - **Personal CRM dashboard** with actions:
  - `pipeline` - My active deals by stage with top deals
  - `workload` - My task/deal load with workload score
  - `team` - Team overview: deals, value, stale per user
  - `insights` - Pipeline insights: health, win rate, cycle time

### Gamification
- `kommo_gamification` - **Team gamification** with actions:
  - `leaderboard` - Ranked team leaderboard by metric (deals, revenue, conversion)
  - `achievements` - Badge system: Deal Machine, Whale Hunter, Speed Closer, etc.
  - `challenges` - Sales competitions: Deal Sprint, Revenue Race
  - `points` - Points breakdown: deals, revenue bonus, big deals, fast closes

### Loss Analysis
- `kommo_loss_analysis` - **Deep lost deals analysis** with actions:
  - `reasons` - Loss reasons from notes, price range breakdown
  - `patterns` - Timing patterns: by month, day, deal age at loss
  - `by_manager` - Manager comparison: loss rate, value, avg loss age

### Smart Timing
- `kommo_smart_time` - **Timing intelligence** with actions:
  - `best_call_time` - Optimal hours/days for calls based on won deals
  - `customer_journey` - Touch-to-purchase path: cycle times, fast vs slow deals

### Team Planning
- `kommo_team_planner` - **Capacity planning** with actions:
  - `capacity` - Team workload forecast: load score, available slots, status

### Customer Segments
- `kommo_segments` - **Customer segmentation** with actions:
  - `by_volume` - Purchase tier segmentation with win rates
  - `lookalike` - Find deals similar to best performers
  - `best_manager` - Manager-client fit by deal size segment
  - `basket` - Product mix analysis (catalogs or tag-based)

### Extended Search
- `kommo_search` - **Enhanced search** with filters:
  - `min_price` / `max_price` - Price range filtering
  - `created_from` / `created_to` - Date range filtering
  - `sort_by` / `sort_order` - Sort by price, created_at, updated_at
  - `top_deals` - Top N deals by amount

### Extended Tasks
- `kommo_tasks_ext` - **Extended task management** (new actions):
  - `prioritize` - AI-scored task prioritization
  - `reassign` - Reassign task to another user
  - `postpone` - Postpone task by N days
  - `plan_day` - AI daily plan with overdue/today/tomorrow

### Extended Contacts
- `kommo_contacts_ext` - **Contact analysis** (new actions):
  - `without_deals` - Find contacts with no linked deals
  - `inactive` - Find contacts with no activity > N days

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
