# Архитектура KommoMCP Server

> Software Design Document — Архитектура системы

## 1. Обзор

### 1.1 Назначение
KommoMCP — MCP сервер для интеграции LLM (Claude, GPT) с amoCRM/Kommo CRM. Позволяет ИИ-ассистенту выполнять операции с CRM данными, включая аналитику больших объемов данных.

### 1.2 Ключевые решения

| Аспект | Решение | Обоснование |
|--------|---------|-------------|
| **Язык** | Python 3.11+ | Лучшая экосистема для Big Data (Pandas, NumPy), отличная поддержка MCP (FastMCP), async/await |
| **MCP Framework** | FastMCP 2.x | Декораторный API, Pydantic валидация, полная поддержка транспортов |
| **База данных** | PostgreSQL 15+ | Масштабируемость, JSON поддержка, оконные функции для аналитики |
| **Async** | asyncio + httpx | Неблокирующие HTTP запросы к Kommo API |
| **ORM** | SQLAlchemy 2.0 + asyncpg | Async поддержка PostgreSQL |

### 1.3 Принципы архитектуры
- **Async-first** — все I/O операции асинхронные
- **Big Data Ready** — данные обрабатываются в БД, не в памяти LLM
- **Modular** — независимые модули для каждой сущности
- **Analytics Focus** — приоритет на аналитические функции

---

## 2. Высокоуровневая архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        LLM Client                                │
│              (Claude Desktop / Cursor / Windsurf)                │
└─────────────────────────┬───────────────────────────────────────┘
                          │ MCP Protocol (stdio/HTTP)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     KommoMCP Server                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    MCP Layer (FastMCP)                     │  │
│  │  • Tools Registration                                      │  │
│  │  • Resources                                               │  │
│  │  • Prompts                                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │                    Business Logic Layer                    │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐  │  │
│  │  │  Leads  │ │Contacts │ │Companies│ │    Analytics    │  │  │
│  │  │ Service │ │ Service │ │ Service │ │     Engine      │  │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────────┬────────┘  │  │
│  │       │           │           │               │            │  │
│  │  ┌────┴───────────┴───────────┴───────────────┴────────┐  │  │
│  │  │              Data Access Layer                       │  │  │
│  │  │  • Kommo API Client (httpx async)                   │  │  │
│  │  │  • PostgreSQL Repository (SQLAlchemy async)         │  │  │
│  │  │  • Cache Manager (optional Redis)                   │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │                   Infrastructure Layer                     │  │
│  │  • Config Management                                       │  │
│  │  • Logging & Monitoring                                    │  │
│  │  • Rate Limiter                                            │  │
│  │  • Webhook Server (FastAPI)                                │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │                    │
                          ▼                    ▼
              ┌───────────────────┐  ┌─────────────────┐
              │   Kommo API       │  │   PostgreSQL    │
              │   (External)      │  │   (Local DB)    │
              └───────────────────┘  └─────────────────┘
```

---

## 3. Компоненты системы

### 3.1 MCP Layer

```python
# Структура MCP сервера
from fastmcp import FastMCP

mcp = FastMCP('KommoMCP')

@mcp.tool()
async def get_leads_analytics(
    pipeline_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None
) -> dict:
    '''Получить аналитику по сделкам'''
    ...

@mcp.resource('kommo://pipelines')
async def get_pipelines() -> list:
    '''Список воронок'''
    ...
```

**Ответственность:**
- Регистрация MCP tools, resources, prompts
- Валидация входных параметров (Pydantic)
- Сериализация ответов для LLM
- Управление транспортом (stdio/HTTP)

### 3.2 Business Logic Layer

#### Services
| Service | Ответственность |
|---------|-----------------|
| `LeadsService` | CRUD операции со сделками |
| `ContactsService` | CRUD операции с контактами |
| `CompaniesService` | CRUD операции с компаниями |
| `TasksService` | CRUD операции с задачами |
| `PipelinesService` | Управление воронками и этапами |
| `AnalyticsEngine` | Аналитические запросы и агрегации |
| `ScriptsEngine` | Выполнение пользовательских скриптов |

#### Analytics Engine (Ключевой компонент)
```python
class AnalyticsEngine:
    async def pipeline_summary(self, pipeline_id: int) -> PipelineSummary:
        '''Сводка по воронке: конверсии, суммы, средние'''
        
    async def sales_forecast(self, days: int = 30) -> SalesForecast:
        '''Прогноз продаж на основе исторических данных'''
        
    async def manager_performance(self, user_id: int) -> ManagerStats:
        '''Статистика менеджера'''
        
    async def cohort_analysis(self, period: str = 'month') -> CohortData:
        '''Когортный анализ'''
        
    async def funnel_conversion(self, pipeline_id: int) -> FunnelData:
        '''Конверсия воронки по этапам'''
```

### 3.3 Data Access Layer

#### Kommo API Client
```python
class KommoClient:
    def __init__(self, subdomain: str, access_token: str):
        self.base_url = f'https://{subdomain}.kommo.com/api/v4'
        self.client = httpx.AsyncClient(...)
        self.rate_limiter = RateLimiter(max_rps=7)
    
    async def get_leads(self, **filters) -> AsyncIterator[Lead]:
        '''Получить сделки с автопагинацией'''
        
    async def create_lead(self, data: LeadCreate) -> Lead:
        '''Создать сделку'''
```

#### PostgreSQL Repository
```python
class LeadsRepository:
    async def sync_from_api(self, leads: list[Lead]) -> int:
        '''Синхронизировать данные из API в БД'''
        
    async def get_aggregated(self, query: AnalyticsQuery) -> DataFrame:
        '''Выполнить аналитический запрос'''
```

### 3.4 Infrastructure Layer

#### Rate Limiter
```python
class RateLimiter:
    '''Ограничение 7 req/sec для Kommo API'''
    
    def __init__(self, max_rps: int = 7):
        self.semaphore = asyncio.Semaphore(max_rps)
        self.window = 1.0  # секунда
    
    async def acquire(self):
        async with self.semaphore:
            await asyncio.sleep(self.window / self.max_rps)
```

#### Webhook Server
```python
# Отдельный FastAPI сервер для входящих webhooks
from fastapi import FastAPI

webhook_app = FastAPI()

@webhook_app.post('/webhook/kommo')
async def handle_webhook(payload: WebhookPayload):
    '''Обработка событий от Kommo'''
    await event_processor.process(payload)
```

---

## 4. Структура проекта

```
kommo-mcp/
├── src/
│   └── kommo_mcp/
│       ├── __init__.py
│       ├── server.py              # Точка входа MCP сервера
│       ├── config.py              # Конфигурация
│       │
│       ├── mcp/                   # MCP Layer
│       │   ├── __init__.py
│       │   ├── tools/             # MCP Tools
│       │   │   ├── __init__.py
│       │   │   ├── leads.py
│       │   │   ├── contacts.py
│       │   │   ├── companies.py
│       │   │   ├── tasks.py
│       │   │   ├── analytics.py   # Аналитические tools
│       │   │   └── scripts.py     # Кастомные скрипты
│       │   ├── resources/         # MCP Resources
│       │   │   ├── __init__.py
│       │   │   ├── pipelines.py
│       │   │   └── users.py
│       │   └── prompts/           # MCP Prompts
│       │       └── __init__.py
│       │
│       ├── services/              # Business Logic
│       │   ├── __init__.py
│       │   ├── leads.py
│       │   ├── contacts.py
│       │   ├── companies.py
│       │   ├── tasks.py
│       │   ├── pipelines.py
│       │   └── analytics.py       # Analytics Engine
│       │
│       ├── api/                   # Kommo API Client
│       │   ├── __init__.py
│       │   ├── client.py          # HTTP клиент
│       │   ├── endpoints/         # Endpoint классы
│       │   │   ├── leads.py
│       │   │   ├── contacts.py
│       │   │   └── ...
│       │   └── rate_limiter.py
│       │
│       ├── db/                    # Database Layer
│       │   ├── __init__.py
│       │   ├── models.py          # SQLAlchemy models
│       │   ├── repositories/      # Repository pattern
│       │   │   ├── leads.py
│       │   │   ├── contacts.py
│       │   │   └── ...
│       │   └── migrations/        # Alembic migrations
│       │
│       ├── webhooks/              # Webhook Server
│       │   ├── __init__.py
│       │   ├── server.py          # FastAPI app
│       │   └── handlers.py
│       │
│       └── utils/                 # Utilities
│           ├── __init__.py
│           ├── logging.py
│           └── helpers.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── scripts/                       # Utility scripts
│   └── sync_data.py
│
├── specs/                         # SDD документация
│
├── pyproject.toml                 # Poetry config
├── alembic.ini                    # Migrations config
├── .env.example
└── README.md
```

---

## 5. Потоки данных

### 5.1 Синхронный запрос (малый объем)

```
LLM Request: "Покажи сделки на этапе Переговоры"
     │
     ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  MCP Tool   │────▶│   Service   │────▶│ Kommo API   │
│ get_leads() │     │ LeadsService│     │   Client    │
└─────────────┘     └─────────────┘     └──────┬──────┘
     ▲                                         │
     │                                         ▼
     │                                  ┌─────────────┐
     │                                  │  Kommo API  │
     │                                  │  (External) │
     │                                  └──────┬──────┘
     │                                         │
     └─────────────────────────────────────────┘
                    Response (≤250 records)
```

### 5.2 Аналитический запрос (большой объем)

```
LLM Request: "Аналитика продаж за год по всем менеджерам"
     │
     ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  MCP Tool   │────▶│  Analytics  │────▶│ PostgreSQL  │
│ analytics() │     │   Engine    │     │ Repository  │
└─────────────┘     └─────────────┘     └──────┬──────┘
     ▲                                         │
     │                                         ▼
     │                                  ┌─────────────┐
     │                                  │ PostgreSQL  │
     │                                  │  (10M rows) │
     │                                  └──────┬──────┘
     │                                         │
     │              Aggregated Result          │
     └─────────────────────────────────────────┘
              (summary, not raw data)
```

### 5.3 Фоновая синхронизация

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Scheduler  │────▶│ Sync Worker │────▶│ Kommo API   │
│  (cron)     │     │             │     │   Client    │
└─────────────┘     └─────────────┘     └──────┬──────┘
                           │                   │
                           │                   ▼
                           │            ┌─────────────┐
                           │            │  Kommo API  │
                           │            └──────┬──────┘
                           │                   │
                           ▼                   │
                    ┌─────────────┐            │
                    │ PostgreSQL  │◀───────────┘
                    │  (upsert)   │     Paginated fetch
                    └─────────────┘
```

### 5.4 Webhook события

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Kommo     │────▶│  Webhook    │────▶│   Event     │
│  (event)    │     │   Server    │     │  Processor  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                           ┌───────────────────┼───────────────────┐
                           ▼                   ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
                    │  Update DB  │     │   Notify    │     │   Trigger   │
                    │             │     │    LLM      │     │  Automation │
                    └─────────────┘     └─────────────┘     └─────────────┘
```

---

## 6. Конфигурация

### 6.1 Environment Variables

```bash
# Kommo API
KOMMO_SUBDOMAIN=mycompany
KOMMO_ACCESS_TOKEN=xxx
KOMMO_REFRESH_TOKEN=xxx  # для OAuth (post-MVP)
KOMMO_CLIENT_ID=xxx       # для OAuth (post-MVP)
KOMMO_CLIENT_SECRET=xxx   # для OAuth (post-MVP)

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/kommo_mcp

# MCP Server
MCP_TRANSPORT=stdio  # или http
MCP_HOST=127.0.0.1
MCP_PORT=8000

# Webhook Server
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8001
WEBHOOK_SECRET=xxx

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### 6.2 Config Model

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Kommo
    kommo_subdomain: str
    kommo_access_token: str
    
    # Database
    database_url: str
    
    # MCP
    mcp_transport: str = 'stdio'
    mcp_host: str = '127.0.0.1'
    mcp_port: int = 8000
    
    # Webhook
    webhook_enabled: bool = True
    webhook_host: str = '0.0.0.0'
    webhook_port: int = 8001
    
    class Config:
        env_file = '.env'
```

---

## 7. Безопасность

### 7.1 Хранение credentials
- Access Token хранится в `.env` (не в коде)
- `.env` добавлен в `.gitignore`
- Для production — использовать secrets manager

### 7.2 API Security
- Все запросы через HTTPS
- Rate limiting для защиты от блокировки
- Валидация всех входных данных через Pydantic

### 7.3 Webhook Security
- Проверка подписи webhook (если Kommo поддерживает)
- Whitelist IP адресов Kommo
- HTTPS endpoint

---

## 8. Масштабирование (Post-MVP)

### 8.1 Multi-tenant
```python
class TenantManager:
    async def get_client(self, tenant_id: str) -> KommoClient:
        '''Получить клиент для конкретного tenant'''
        credentials = await self.get_credentials(tenant_id)
        return KommoClient(**credentials)
```

### 8.2 Horizontal Scaling
- Stateless MCP server
- Shared PostgreSQL
- Redis для кэширования и очередей

### 8.3 Background Jobs
- Celery или arq для фоновых задач
- Scheduled sync jobs
- Long-running analytics

---

## 9. Зависимости

### 9.1 Core
```toml
[tool.poetry.dependencies]
python = "^3.11"
fastmcp = "^2.0"
httpx = "^0.27"
pydantic = "^2.0"
pydantic-settings = "^2.0"
sqlalchemy = {extras = ["asyncio"], version = "^2.0"}
asyncpg = "^0.29"
alembic = "^1.13"
```

### 9.2 Analytics
```toml
pandas = "^2.2"
numpy = "^1.26"
polars = "^0.20"  # для больших данных
```

### 9.3 Webhooks
```toml
fastapi = "^0.109"
uvicorn = "^0.27"
```

### 9.4 Dev
```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.23"
pytest-cov = "^4.1"
ruff = "^0.2"
mypy = "^1.8"
```

---

## 10. Следующие шаги

1. **DATA_MODELS.md** — модели данных и схема БД
2. **MCP_TOOLS.md** — спецификация всех MCP инструментов
3. **ANALYTICS_ENGINE.md** — детальное описание аналитического движка
4. **IMPLEMENTATION_PLAN.md** — план реализации с приоритетами
