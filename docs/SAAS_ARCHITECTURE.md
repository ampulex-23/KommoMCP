# KommoMCP SaaS Architecture

## Overview

Multi-tenant SaaS platform for Kommo CRM AI assistant via Telegram.

**Key principle:** 1 client = 1 isolated instance (database + container)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Bot (aiogram)                    │
│                   /start → регистрация                       │
│                   /connect → ввод API ключей                 │
│                   /ask → запросы к CRM                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   Orchestrator Service                       │
│  - TenantManager: регистрация, хранение credentials         │
│  - Orchestrator: создание DB, запуск контейнеров            │
│  - AIChat: интеграция OpenAI + MCP                          │
└─────────────────────────┬───────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│   Tenant 1    │ │   Tenant 2    │ │   Tenant N    │
│ ┌───────────┐ │ │ ┌───────────┐ │ │ ┌───────────┐ │
│ │ MCP Server│ │ │ │ MCP Server│ │ │ │ MCP Server│ │
│ │ Port 9000 │ │ │ │ Port 9001 │ │ │ │ Port 900N │ │
│ └───────────┘ │ │ └───────────┘ │ │ └───────────┘ │
│ ┌───────────┐ │ │ ┌───────────┐ │ │ ┌───────────┐ │
│ │ PostgreSQL│ │ │ │ PostgreSQL│ │ │ │ PostgreSQL│ │
│ │  Database │ │ │ │  Database │ │ │ │  Database │ │
│ └───────────┘ │ │ └───────────┘ │ │ └───────────┘ │
└───────────────┘ └───────────────┘ └───────────────┘
```

## Components

### 1. Telegram Bot (`src/kommo_mcp/telegram/`)

- **bot.py** - Main bot with command handlers
- **ai_chat.py** - OpenAI integration with function calling
- **__main__.py** - Entry point

Commands:
- `/start` - Register new user
- `/connect` - Setup Kommo API credentials
- `/openai` - Setup OpenAI API key
- `/status` - Show connection status
- `/ask <question>` - Ask AI about CRM
- `/sync` - Trigger data sync
- `/disconnect` - Deprovision infrastructure

### 2. SaaS Core (`src/kommo_mcp/saas/`)

- **tenant.py** - Tenant model and status enum
- **manager.py** - TenantManager for CRUD operations
- **orchestrator.py** - Infrastructure provisioning

### 3. Docker Infrastructure (`docker/`)

- **Dockerfile.tenant** - MCP server container
- **Dockerfile.bot** - Telegram bot container
- **docker-compose.saas.yml** - Full stack

## Tenant Lifecycle

```
PENDING → PROVISIONING → SYNCING → ACTIVE
    ↓           ↓            ↓
  ERROR ←───────┴────────────┘
    ↓
SUSPENDED
```

1. **PENDING** - User registered, waiting for API keys
2. **PROVISIONING** - Creating database and container
3. **SYNCING** - Initial data sync from Kommo
4. **ACTIVE** - Ready for requests
5. **ERROR** - Provisioning failed
6. **SUSPENDED** - Manually disabled

## Provisioning Flow

```python
async def provision(tenant_id):
    # 1. Create PostgreSQL database
    db_name = f"kommo_tenant_{tenant_id[:8]}"
    await create_database(db_name)
    
    # 2. Run migrations
    await run_migrations(db_name)
    
    # 3. Allocate port (9000-9999)
    port = allocate_port()
    
    # 4. Start Docker container
    container_id = await start_container(
        db_name=db_name,
        port=port,
        kommo_domain=tenant.kommo_domain,
        kommo_token=tenant.kommo_access_token,
    )
    
    # 5. Trigger initial sync
    await trigger_sync(tenant_id)
```

## AI Integration

Uses OpenAI function calling to invoke MCP tools:

```python
# User: "Покажи аналитику воронки"
# ↓
# OpenAI decides to call: kommo_pipeline_analytics
# ↓
# MCP HTTP request to tenant container
# ↓
# Response formatted and sent to user
```

Available tools:
- `kommo_pipeline_analytics`
- `kommo_manager_stats`
- `kommo_deals_ext`
- `kommo_tasks_ext`
- `kommo_contacts_ext`
- `kommo_communications`
- `kommo_insights`
- `kommo_search`
- `kommo_ltv`

## Security

1. **Credential Storage**
   - API keys stored in tenant JSON file
   - TODO: Encrypt with master key

2. **Isolation**
   - Separate PostgreSQL database per tenant
   - Separate Docker container per tenant
   - No cross-tenant data access

3. **Rate Limiting**
   - 1000 requests/day per tenant
   - Configurable per tenant

## Deployment

### Quick Start

```bash
# 1. Configure
cp docker/.env.example docker/.env
# Edit docker/.env with your TELEGRAM_BOT_TOKEN

# 2. Build and run
./scripts/run_saas.sh
```

### Manual

```bash
# Build images
docker build -t kommo-mcp:latest -f docker/Dockerfile.tenant .
docker build -t kommo-bot:latest -f docker/Dockerfile.bot .

# Start stack
cd docker
docker-compose -f docker-compose.saas.yml up -d
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| TELEGRAM_BOT_TOKEN | Bot token from @BotFather | required |
| POSTGRES_HOST | PostgreSQL host | localhost |
| POSTGRES_PORT | PostgreSQL port | 5432 |
| POSTGRES_USER | PostgreSQL user | postgres |
| POSTGRES_PASSWORD | PostgreSQL password | kommo_secret |
| DATA_DIR | Tenant data directory | /var/lib/kommo-saas |

## Scaling

### Current Limits

- Port range: 9000-9999 (1000 tenants max)
- Single PostgreSQL server

### Future Improvements

1. **Kubernetes** - Replace Docker with K8s for auto-scaling
2. **PostgreSQL Cluster** - Separate DB servers per tenant group
3. **Redis Cluster** - Distributed caching
4. **Billing Integration** - Stripe/Paddle for subscriptions
5. **Admin Dashboard** - Web UI for tenant management

## Monitoring

TODO:
- Prometheus metrics
- Grafana dashboards
- Alert rules for container health
- Usage analytics

## Cost Estimation

Per tenant:
- PostgreSQL: ~50MB base + data
- Container: ~256MB RAM
- Storage: depends on CRM size

For 100 tenants:
- RAM: ~25GB
- Storage: ~50GB
- Recommended: 8 vCPU, 32GB RAM VPS
