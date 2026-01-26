# Implementation Plan

> Software Design Document — План реализации

## 1. Обзор

### 1.1 Приоритеты
1. **🔴 Аналитика** — ключевой дифференциатор, впечатляет клиентов
2. **🟡 CRUD операции** — базовая функциональность
3. **🟢 Расширенные функции** — webhooks, скрипты, multi-tenant

### 1.2 Timeline

| Фаза | Срок | Фокус | Статус |
|------|------|-------|--------|
| **Phase 1: Foundation** | 3-4 дня | Инфраструктура, API клиент, БД | ✅ DONE |
| **Phase 2: Analytics MVP** | 4-5 дней | Аналитические tools (приоритет) | ✅ DONE |
| **Phase 3: CRUD** | 3-4 дня | Базовые операции со всеми сущностями | ✅ DONE |
| **Phase 4: Advanced** | 3-4 дня | Webhooks, скрипты, оптимизация | ✅ DONE |
| **Total MVP** | ~2 недели | Полнофункциональный MCP сервер | ✅ 100% |

---

## 2. Phase 1: Foundation (3-4 дня)

### 2.1 День 1: Project Setup

#### Задачи
- [x] Инициализация проекта (Poetry)
- [x] Структура директорий
- [ ] Базовая конфигурация
- [ ] Настройка линтеров и форматтеров

#### Артефакты
```bash
# Создание проекта
poetry new kommo-mcp
cd kommo-mcp

# Зависимости
poetry add fastmcp httpx pydantic pydantic-settings
poetry add sqlalchemy[asyncio] asyncpg alembic
poetry add pandas numpy

# Dev зависимости
poetry add -D pytest pytest-asyncio pytest-cov ruff mypy
```

```python
# pyproject.toml
[tool.poetry]
name = "kommo-mcp"
version = "0.1.0"
description = "MCP Server for Kommo/amoCRM"
authors = ["Your Name"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
```

### 2.2 День 2: Kommo API Client

#### Задачи
- [ ] HTTP клиент с httpx
- [ ] Rate limiter (7 req/sec)
- [ ] Автоматическая пагинация
- [ ] Обработка ошибок
- [ ] Retry логика

#### Код
```python
# src/kommo_mcp/api/client.py
class KommoClient:
    def __init__(self, subdomain: str, access_token: str):
        self.base_url = f'https://{subdomain}.kommo.com/api/v4'
        self.client = httpx.AsyncClient(
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=30.0
        )
        self.rate_limiter = RateLimiter(max_rps=7)
    
    async def get(self, endpoint: str, params: dict = None) -> dict:
        async with self.rate_limiter:
            response = await self.client.get(
                f'{self.base_url}/{endpoint}',
                params=params
            )
            response.raise_for_status()
            return response.json()
    
    async def iterate(self, endpoint: str, **params) -> AsyncIterator[dict]:
        '''Автопагинация'''
        page = 1
        while True:
            data = await self.get(endpoint, {**params, 'page': page, 'limit': 250})
            items = data.get('_embedded', {}).get(endpoint, [])
            if not items:
                break
            for item in items:
                yield item
            page += 1
```

### 2.3 День 3: Database Setup

#### Задачи
- [ ] SQLAlchemy models
- [ ] Alembic migrations
- [ ] Repository pattern
- [ ] Connection pool

#### Код
```python
# src/kommo_mcp/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(settings.database_url, pool_size=10)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
```

```bash
# Миграции
alembic init alembic
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

### 2.4 День 4: MCP Server Skeleton

#### Задачи
- [ ] FastMCP инициализация
- [ ] Базовые tools (ping, status)
- [ ] Resources (pipelines, users)
- [ ] Тестирование с Claude Desktop

#### Код
```python
# src/kommo_mcp/server.py
from fastmcp import FastMCP

mcp = FastMCP('KommoMCP')

@mcp.tool()
async def kommo_ping() -> dict:
    '''Проверка подключения к Kommo API'''
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}

@mcp.resource('kommo://pipelines')
async def get_pipelines() -> list:
    '''Список воронок'''
    async with get_session() as session:
        result = await session.execute(select(PipelineDB))
        return [p.to_dict() for p in result.scalars()]

if __name__ == '__main__':
    mcp.run()
```

---

## 3. Phase 2: Analytics MVP (4-5 дней)

### 3.1 День 5: Data Sync

#### Задачи
- [ ] SyncManager implementation
- [ ] Sync для leads, contacts, companies
- [ ] Sync для pipelines, users
- [ ] CLI команда для ручной синхронизации

#### Код
```python
# src/kommo_mcp/services/sync.py
class SyncManager:
    async def sync_leads(self, full: bool = False) -> int:
        count = 0
        async for lead in self.api.iterate('leads', updated_at_from=last_sync):
            await self.repo.upsert(lead)
            count += 1
        return count
```

### 3.2 День 6-7: Analytics Engine Core

#### Задачи
- [ ] QueryBuilder
- [ ] Pipeline summary
- [ ] Stage distribution
- [ ] Manager performance

#### Тесты
```python
# tests/test_analytics.py
@pytest.mark.asyncio
async def test_pipeline_summary():
    engine = AnalyticsEngine(session)
    result = await engine.pipeline_summary(pipeline_id=123)
    
    assert result.total_leads > 0
    assert result.conversion_rate >= 0
    assert len(result.stages) > 0
```

### 3.3 День 8: Analytics Tools

#### Задачи
- [ ] kommo_pipeline_analytics
- [ ] kommo_manager_performance
- [ ] kommo_leads_summary
- [ ] kommo_revenue_report

#### Интеграция
```python
# src/kommo_mcp/mcp/tools/analytics.py
@mcp.tool()
async def kommo_pipeline_analytics(
    pipeline_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None
) -> dict:
    '''Аналитика воронки продаж'''
    async with get_session() as session:
        engine = AnalyticsEngine(session)
        result = await engine.pipeline_summary(
            pipeline_id=pipeline_id,
            date_from=parse_date(date_from),
            date_to=parse_date(date_to)
        )
        return result.model_dump()
```

### 3.4 День 9: Advanced Analytics

#### Задачи
- [ ] Funnel conversion analysis
- [ ] Sales forecast
- [ ] Cohort analysis
- [ ] Activity report

---

## 4. Phase 3: CRUD Operations (3-4 дня)

### 4.1 День 10: Leads CRUD

#### Задачи
- [ ] kommo_leads_list
- [ ] kommo_lead_get
- [ ] kommo_lead_create
- [ ] kommo_lead_update
- [ ] kommo_lead_move

### 4.2 День 11: Contacts & Companies CRUD

#### Задачи
- [ ] kommo_contacts_list, get, create, update
- [ ] kommo_companies_list, get, create, update
- [ ] kommo_contact_find (поиск по телефону/email)

### 4.3 День 12: Tasks & Notes

#### Задачи
- [ ] kommo_tasks_list, create, complete
- [ ] kommo_tasks_overdue
- [ ] kommo_notes_list, create

### 4.4 День 13: Pipelines & Users

#### Задачи
- [ ] kommo_pipelines_list
- [ ] kommo_pipeline_get
- [ ] kommo_users_list
- [ ] kommo_user_get

---

## 5. Phase 4: Advanced Features (3-4 дня)

### 5.1 День 14: Webhooks

#### Задачи
- [ ] FastAPI webhook server
- [ ] Event handlers
- [ ] Real-time sync
- [ ] Notification to LLM (optional)

#### Код
```python
# src/kommo_mcp/webhooks/server.py
from fastapi import FastAPI, Request

app = FastAPI()

@app.post('/webhook/kommo')
async def handle_webhook(request: Request):
    payload = await request.json()
    event_type = payload.get('event')
    
    if event_type == 'lead_added':
        await sync_manager.sync_lead(payload['lead']['id'])
    elif event_type == 'lead_status_changed':
        await sync_manager.sync_lead(payload['lead']['id'])
        await cache.invalidate('pipeline_*')
    
    return {'status': 'ok'}
```

### 5.2 День 15: Scripts Engine

#### Задачи
- [ ] Predefined scripts
- [ ] Async job execution
- [ ] Progress tracking
- [ ] Result storage

#### Скрипты
```python
SCRIPTS = {
    'export_leads': ExportLeadsScript,
    'bulk_update_status': BulkUpdateStatusScript,
    'find_duplicates': FindDuplicatesScript,
    'recalculate_analytics': RecalculateAnalyticsScript,
}

@mcp.tool()
async def kommo_script_run(script_name: str, params: dict = None) -> dict:
    script_class = SCRIPTS.get(script_name)
    if not script_class:
        raise ValueError(f'Unknown script: {script_name}')
    
    job_id = str(uuid4())
    asyncio.create_task(script_class(params).run(job_id))
    
    return {'job_id': job_id, 'status': 'started'}
```

### 5.3 День 16: Optimization & Testing

#### Задачи
- [ ] Caching layer
- [ ] Performance testing
- [ ] Load testing
- [ ] Documentation

### 5.4 День 17: Polish & Release

#### Задачи
- [ ] README.md
- [ ] Installation guide
- [ ] Configuration examples
- [ ] Docker setup

---

## 6. Detailed Task Breakdown

### 6.1 Foundation Tasks

| ID | Task | Priority | Estimate | Dependencies |
|----|------|----------|----------|--------------|
| F1 | Poetry project setup | HIGH | 1h | - |
| F2 | Directory structure | HIGH | 30m | F1 |
| F3 | Config management | HIGH | 2h | F2 |
| F4 | Logging setup | MEDIUM | 1h | F3 |
| F5 | KommoClient base | HIGH | 3h | F3 |
| F6 | Rate limiter | HIGH | 2h | F5 |
| F7 | Auto-pagination | HIGH | 2h | F5 |
| F8 | Error handling | HIGH | 2h | F5 |
| F9 | SQLAlchemy models | HIGH | 4h | F3 |
| F10 | Alembic setup | HIGH | 2h | F9 |
| F11 | Initial migration | HIGH | 1h | F10 |
| F12 | Repository pattern | MEDIUM | 3h | F9 |
| F13 | FastMCP skeleton | HIGH | 2h | F3 |
| F14 | Basic tools | HIGH | 2h | F13 |
| F15 | Basic resources | MEDIUM | 2h | F13 |

### 6.2 Analytics Tasks

| ID | Task | Priority | Estimate | Dependencies |
|----|------|----------|----------|--------------|
| A1 | SyncManager | HIGH | 4h | F5, F9 |
| A2 | Leads sync | HIGH | 2h | A1 |
| A3 | Contacts sync | HIGH | 2h | A1 |
| A4 | Companies sync | HIGH | 1h | A1 |
| A5 | Pipelines sync | HIGH | 1h | A1 |
| A6 | Users sync | HIGH | 1h | A1 |
| A7 | QueryBuilder | HIGH | 3h | F9 |
| A8 | AnalyticsEngine base | HIGH | 2h | A7 |
| A9 | pipeline_summary | HIGH | 3h | A8 |
| A10 | stage_distribution | HIGH | 2h | A8 |
| A11 | manager_performance | HIGH | 3h | A8 |
| A12 | funnel_conversion | HIGH | 4h | A8 |
| A13 | revenue_forecast | MEDIUM | 4h | A8 |
| A14 | cohort_analysis | MEDIUM | 4h | A8 |
| A15 | Analytics tools | HIGH | 4h | A9-A14 |
| A16 | Caching | MEDIUM | 3h | A15 |

### 6.3 CRUD Tasks

| ID | Task | Priority | Estimate | Dependencies |
|----|------|----------|----------|--------------|
| C1 | LeadsService | HIGH | 3h | F5 |
| C2 | Leads tools | HIGH | 3h | C1 |
| C3 | ContactsService | MEDIUM | 2h | F5 |
| C4 | Contacts tools | MEDIUM | 2h | C3 |
| C5 | CompaniesService | MEDIUM | 2h | F5 |
| C6 | Companies tools | MEDIUM | 2h | C5 |
| C7 | TasksService | MEDIUM | 2h | F5 |
| C8 | Tasks tools | MEDIUM | 2h | C7 |
| C9 | NotesService | LOW | 1h | F5 |
| C10 | Notes tools | LOW | 1h | C9 |
| C11 | Pipelines tools | MEDIUM | 2h | F5 |
| C12 | Users tools | MEDIUM | 1h | F5 |

### 6.4 Advanced Tasks

| ID | Task | Priority | Estimate | Dependencies |
|----|------|----------|----------|--------------|
| X1 | FastAPI webhook server | MEDIUM | 3h | F3 |
| X2 | Webhook handlers | MEDIUM | 3h | X1, A1 |
| X3 | Scripts engine | LOW | 4h | A1 |
| X4 | Predefined scripts | LOW | 4h | X3 |
| X5 | Job tracking | LOW | 2h | X3 |
| X6 | Performance optimization | MEDIUM | 4h | All |
| X7 | Unit tests | HIGH | 8h | All |
| X8 | Integration tests | MEDIUM | 4h | All |
| X9 | Documentation | HIGH | 4h | All |
| X10 | Docker setup | MEDIUM | 2h | All |

---

## 7. Testing Strategy

### 7.1 Unit Tests
```python
# tests/unit/test_analytics_engine.py
class TestAnalyticsEngine:
    @pytest.fixture
    def engine(self, mock_session):
        return AnalyticsEngine(mock_session)
    
    async def test_pipeline_summary_empty(self, engine):
        result = await engine.pipeline_summary(pipeline_id=999)
        assert result.total_leads == 0
    
    async def test_pipeline_summary_with_data(self, engine, sample_leads):
        result = await engine.pipeline_summary(pipeline_id=1)
        assert result.total_leads == len(sample_leads)
        assert result.conversion_rate >= 0
```

### 7.2 Integration Tests
```python
# tests/integration/test_mcp_tools.py
class TestMCPTools:
    async def test_kommo_pipeline_analytics(self, mcp_client):
        result = await mcp_client.call_tool(
            'kommo_pipeline_analytics',
            {'pipeline_id': 1}
        )
        assert 'summary' in result
        assert 'stages' in result
```

### 7.3 E2E Tests
```python
# tests/e2e/test_full_flow.py
async def test_analytics_flow():
    # 1. Sync data
    await mcp.call_tool('kommo_sync_start', {'entities': ['leads']})
    
    # 2. Wait for sync
    while True:
        status = await mcp.call_tool('kommo_sync_status')
        if status['leads']['status'] == 'completed':
            break
        await asyncio.sleep(1)
    
    # 3. Get analytics
    result = await mcp.call_tool('kommo_pipeline_analytics')
    assert result['summary']['total_leads'] > 0
```

---

## 8. Deployment

### 8.1 Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy project files
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-dev

COPY src/ ./src/

# Run MCP server
CMD ["poetry", "run", "python", "-m", "kommo_mcp.server"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  kommo-mcp:
    build: .
    environment:
      - KOMMO_SUBDOMAIN=${KOMMO_SUBDOMAIN}
      - KOMMO_ACCESS_TOKEN=${KOMMO_ACCESS_TOKEN}
      - DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/kommo_mcp
    depends_on:
      - db
    ports:
      - "8000:8000"
  
  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=kommo_mcp
      - POSTGRES_PASSWORD=postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### 8.2 Claude Desktop Config

```json
{
  "mcpServers": {
    "kommo": {
      "command": "poetry",
      "args": ["run", "python", "-m", "kommo_mcp.server"],
      "cwd": "/path/to/kommo-mcp",
      "env": {
        "KOMMO_SUBDOMAIN": "mycompany",
        "KOMMO_ACCESS_TOKEN": "xxx",
        "DATABASE_URL": "postgresql+asyncpg://..."
      }
    }
  }
}
```

---

## 9. Success Metrics

### 9.1 MVP Criteria
- [ ] Все аналитические tools работают
- [ ] CRUD для leads, contacts, companies
- [ ] Синхронизация данных < 5 минут для 10K записей
- [ ] Аналитические запросы < 2 секунд
- [ ] 0 критических багов

### 9.2 Performance Targets
| Metric | Target |
|--------|--------|
| API response time | < 500ms |
| Analytics query time | < 2s |
| Sync throughput | > 100 records/sec |
| Memory usage | < 512MB |

---

## 10. Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Kommo API rate limits | HIGH | MEDIUM | Rate limiter, caching, batch operations |
| Large data volumes | MEDIUM | HIGH | PostgreSQL aggregations, pagination, streaming |
| Token expiration | MEDIUM | LOW | Refresh token logic (post-MVP) |
| Schema changes | LOW | MEDIUM | Flexible JSON storage for custom fields |

---

## 11. Next Steps After MVP

1. **OAuth 2.0 Full Flow** — автоматическое обновление токенов
2. **Multi-tenant** — поддержка нескольких аккаунтов
3. **Real-time Updates** — WebSocket для live данных
4. **Advanced Scripts** — пользовательские скрипты
5. **Marketplace** — публикация в Kommo Marketplace
