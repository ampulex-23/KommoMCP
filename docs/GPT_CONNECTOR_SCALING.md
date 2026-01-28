# Масштабирование KommoMCP для официального GPT коннектора OpenAI

## Текущее состояние

**Архитектура:**
- MCP Server (stdio) для Claude Desktop, Cursor, Windsurf
- MCP HTTP Server (JSON-RPC 2.0) для n8n и веб-интеграций
- PostgreSQL для хранения данных
- Webhooks для real-time синхронизации

**Текущие инструменты:** 21 tool
**Покрытие user stories:** ~30 из 1000

---

## Требования для GPT Actions (OpenAI)

### 1. OpenAPI Specification

GPT Actions требуют OpenAPI 3.0+ спецификацию. Нужно:

```yaml
openapi: 3.0.0
info:
  title: Kommo CRM Connector
  version: 1.0.0
  description: AI-powered CRM analytics and automation
servers:
  - url: https://api.kommo-connector.com/v1
paths:
  /analytics/pipeline:
    get:
      operationId: getPipelineAnalytics
      summary: Get pipeline performance metrics
      parameters:
        - name: pipeline_id
          in: query
          schema:
            type: integer
        - name: date_from
          in: query
          schema:
            type: string
            format: date
```

### 2. OAuth 2.0 Authentication

OpenAI требует OAuth 2.0 для GPT Actions:

```
Authorization Flow:
1. User clicks "Connect" in ChatGPT
2. Redirect to Kommo OAuth
3. User authorizes access
4. Callback with auth code
5. Exchange for access token
6. Store token per user
```

**Изменения в архитектуре:**
- Добавить OAuth endpoints (`/oauth/authorize`, `/oauth/callback`, `/oauth/token`)
- Multi-tenant: хранить токены по user_id
- Token refresh механизм

### 3. Rate Limiting & Quotas

```python
# Рекомендуемые лимиты
RATE_LIMITS = {
    'requests_per_minute': 60,
    'requests_per_day': 10000,
    'max_response_size': '100KB',
    'timeout_seconds': 30,
}
```

---

## План масштабирования

### Фаза 1: REST API Layer (1-2 недели)

**Задача:** Создать REST API поверх существующей логики

```
/api/v1/
├── /analytics
│   ├── GET /pipeline/{id}
│   ├── GET /funnel/{id}
│   ├── GET /revenue/trend
│   ├── GET /managers/performance
│   └── GET /forecast
├── /leads
│   ├── GET /
│   ├── GET /{id}
│   ├── POST /
│   └── GET /stale
├── /contacts
│   ├── GET /
│   ├── POST /
│   └── GET /duplicates
├── /tasks
│   └── POST /
└── /notes
    └── POST /
```

**Реализация:**
```python
# Новый модуль: src/kommo_mcp/api/rest.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2AuthorizationCodeBearer

app = FastAPI(title='Kommo Connector API')

@app.get('/api/v1/analytics/pipeline/{pipeline_id}')
async def get_pipeline_analytics(
    pipeline_id: int,
    date_from: date = None,
    date_to: date = None,
    user: User = Depends(get_current_user),
):
    engine = AnalyticsEngine(user.session)
    return await engine.pipeline_analytics(pipeline_id, date_from, date_to)
```

### Фаза 2: Multi-tenancy (1 неделя)

**Текущее:** Один аккаунт Kommo, одна БД

**Целевое:** Много пользователей, изолированные данные

```python
# Модель tenant
class Tenant(Base):
    __tablename__ = 'tenants'
    
    id = Column(UUID, primary_key=True)
    kommo_account_id = Column(String, unique=True)
    access_token = Column(String)  # encrypted
    refresh_token = Column(String)  # encrypted
    token_expires_at = Column(DateTime)
    created_at = Column(DateTime)

# Изоляция данных
class LeadDB(Base):
    tenant_id = Column(UUID, ForeignKey('tenants.id'), index=True)
```

### Фаза 3: OAuth 2.0 Integration (1 неделя)

```python
# OAuth endpoints
@app.get('/oauth/authorize')
async def oauth_authorize(state: str):
    """Redirect to Kommo OAuth."""
    return RedirectResponse(
        f'https://www.kommo.com/oauth?'
        f'client_id={CLIENT_ID}&'
        f'state={state}&'
        f'redirect_uri={CALLBACK_URL}'
    )

@app.get('/oauth/callback')
async def oauth_callback(code: str, state: str):
    """Handle OAuth callback, create tenant."""
    tokens = await exchange_code(code)
    tenant = await create_or_update_tenant(tokens)
    return {'status': 'connected', 'tenant_id': tenant.id}
```

### Фаза 4: OpenAPI Spec Generation (3 дня)

FastAPI автоматически генерирует OpenAPI:

```python
app = FastAPI(
    title='Kommo CRM Connector',
    version='1.0.0',
    openapi_url='/openapi.json',
    docs_url='/docs',
)

# Экспорт для GPT Actions
@app.get('/gpt-actions-spec')
async def get_gpt_spec():
    """OpenAPI spec optimized for GPT Actions."""
    spec = app.openapi()
    # Упростить для GPT (убрать лишние детали)
    return simplify_for_gpt(spec)
```

### Фаза 5: Публикация в GPT Store (1 неделя)

1. **Регистрация в OpenAI:**
   - Создать GPT с Actions
   - Загрузить OpenAPI spec
   - Настроить OAuth

2. **Тестирование:**
   - Проверить все endpoints
   - Валидация ответов
   - Обработка ошибок

3. **Документация:**
   - Описание возможностей
   - Примеры использования
   - Privacy Policy

---

## Оптимизация количества Tools

### Проблема

1000 user stories → потенциально 1000 tools = невозможно:
- GPT Actions лимит: ~20-30 actions
- Context window: описания tools занимают токены
- UX: пользователь не найдёт нужный tool

### Решение: Композитные Tools

**Принцип:** Один tool с параметром `action` покрывает много сценариев

```python
# Вместо 10 отдельных analytics tools:
@app.post('/api/v1/analytics')
async def analytics(request: AnalyticsRequest):
    """
    Universal analytics endpoint.
    
    action: pipeline | funnel | revenue | forecast | managers | 
            stale_deals | lead_sources | churn_risk | lead_score
    """
    match request.action:
        case 'pipeline': return await engine.pipeline_analytics(...)
        case 'funnel': return await engine.funnel_analysis(...)
        case 'revenue': return await engine.revenue_trend(...)
        # ...
```

**Результат:**
- 10 analytics tools → 1 `analytics` tool
- 5 CRUD tools → 1 `entities` tool  
- 5 action tools → 1 `actions` tool

### Рекомендуемая структура (10-15 tools)

| Tool | Покрывает stories |
|------|-------------------|
| `crm_analytics` | 1-100 (аналитика) |
| `crm_entities` | 401-600 (сделки, контакты, компании) |
| `crm_tasks` | 601-700 (задачи, активности) |
| `crm_automation` | 101-200 (автоматизация) |
| `crm_communications` | 201-300 (коммуникации) |
| `crm_search` | 301-400 (поиск) |
| `crm_reports` | 701-800 (отчёты) |
| `crm_integrations` | 801-900 (интеграции) |
| `crm_settings` | 901-1000 (настройки) |

---

## Инфраструктура для Production

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kommo-connector
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: kommo-connector:latest
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: kommo-secrets
              key: database-url
```

### Мониторинг

```python
# Prometheus metrics
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter('requests_total', 'Total requests', ['endpoint', 'status'])
REQUEST_LATENCY = Histogram('request_latency_seconds', 'Request latency', ['endpoint'])

@app.middleware('http')
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    REQUEST_LATENCY.labels(endpoint=request.url.path).observe(time.time() - start)
    REQUEST_COUNT.labels(endpoint=request.url.path, status=response.status_code).inc()
    return response
```

### Caching

```python
from redis import asyncio as aioredis

redis = aioredis.from_url('redis://localhost')

async def get_pipeline_analytics(pipeline_id: int):
    cache_key = f'analytics:pipeline:{pipeline_id}'
    
    # Check cache
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # Compute
    result = await engine.pipeline_analytics(pipeline_id)
    
    # Cache for 5 minutes
    await redis.setex(cache_key, 300, result.json())
    return result
```

---

## Roadmap

| Фаза | Срок | Результат |
|------|------|-----------|
| REST API | 2 недели | OpenAPI-совместимый API |
| Multi-tenancy | 1 неделя | Поддержка множества аккаунтов |
| OAuth 2.0 | 1 неделя | Авторизация через Kommo |
| GPT Actions | 3 дня | Публикация в GPT Store |
| Оптимизация | 1 неделя | 10-15 композитных tools |
| Production | 2 недели | K8s, мониторинг, caching |

**Общий срок:** 6-8 недель до production-ready GPT коннектора

---

## Следующие шаги

1. [ ] Создать REST API layer (`/api/v1/`)
2. [ ] Добавить OAuth 2.0 endpoints
3. [ ] Реализовать multi-tenancy
4. [ ] Сгенерировать OpenAPI spec
5. [ ] Зарегистрировать GPT Action в OpenAI
6. [ ] Оптимизировать tools (композитные endpoints)
7. [ ] Настроить production инфраструктуру
