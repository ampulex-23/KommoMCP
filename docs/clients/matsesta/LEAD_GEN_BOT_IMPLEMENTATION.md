# Реализация сбора B2B базы в боте KommoMCP

## Концепция

Новый мета-инструмент `kommo_lead_gen` — агент, который по запросу пользователя:
1. Определяет целевые сегменты (ОКВЭД, регион, размер)
2. Собирает компании из внешних API (DaData, 2GIS, Контур)
3. Обогащает контактами (телефоны, email ЛПР)
4. Создаёт лиды/контакты/компании в AmoCRM пользователя
5. Назначает теги, источник, ответственного

Пользователь общается на естественном языке:
> «Собери базу оптовиков чая в Москве и Краснодаре, загрузи в воронку Холодные продажи»

---

## Архитектура

```
User → Planner → kommo_lead_gen tool → LeadGenAgent
                                            │
                           ┌────────────────┼────────────────┐
                           ▼                ▼                ▼
                      DaData API       2GIS API       Kontour API
                           │                │                │
                           └────────┬───────┘                │
                                    ▼                        │
                             Deduplication                   │
                                    │                        │
                                    ▼                        │
                              Enrichment  ◄──────────────────┘
                                    │
                                    ▼
                            AmoCRM API (create leads/contacts/companies)
```

---

## Новый tool: `kommo_lead_gen`

### Actions

| Action | Описание | Параметры |
|--------|----------|-----------|
| `search_companies` | Поиск компаний по ОКВЭД/региону/запросу | okved, region, query, min_revenue, limit |
| `search_horeca` | Поиск HoReCa через 2GIS по городу/рубрике | city, rubric (рестораны, кафе, гостиницы), radius_km |
| `enrich` | Обогащение списка компаний контактами | company_ids (из предыдущего шага) |
| `import_to_crm` | Загрузка в AmoCRM | pipeline_id, tag, source, responsible_user_id |
| `preview` | Показать что будет собрано без загрузки | (те же что search) |
| `status` | Статус текущего сбора | task_id |

### Пример вызова LLM

```json
{
  "name": "kommo_lead_gen",
  "arguments": {
    "action": "search_companies",
    "okved": "46.37",
    "region": ["Москва", "Краснодарский край"],
    "min_revenue": 1000000,
    "limit": 100
  }
}
```

---

## Внешние API — интеграции

### 1. DaData (suggest/party) — основной источник

```python
async def search_by_okved(self, okved: str, region: str = None, limit: int = 20):
    '''Поиск компаний по ОКВЭД через DaData suggest/party API.'''
    url = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party'
    headers = {
        'Authorization': f'Token {self.dadata_token}',
        'Content-Type': 'application/json',
    }
    payload = {
        'query': '*',
        'count': limit,
        'filters': [
            {'okved': okved},
            {'status': 'ACTIVE'},
        ],
    }
    if region:
        payload['locations'] = [{'kladr_id': region_to_kladr(region)}]

    # Возвращает: название, ИНН, ОГРН, адрес, ФИО руководителя, ОКВЭД
```

**Env:** `DADATA_API_TOKEN` — у каждого тенанта свой или общий.

**Лимит:** 10 000 запросов/день (бесплатно). Каждый запрос возвращает до 20 компаний.
Итого: ~200 000 компаний/день бесплатно.

### 2. 2GIS API (places) — для HoReCa

```python
async def search_horeca(self, city: str, rubric: str, limit: int = 50):
    '''Поиск организаций через 2GIS Places API.'''
    url = 'https://catalog.api.2gis.com/3.0/items'
    params = {
        'q': rubric,  # 'рестораны', 'кафе', 'гостиницы'
        'region_id': city_to_2gis_region(city),
        'type': 'branch',
        'fields': 'items.contact_groups,items.org',
        'key': self.twogis_key,
        'page_size': limit,
    }
    # Возвращает: название, адрес, телефоны, сайт, часы работы, рубрики
```

**Env:** `TWOGIS_API_KEY`

**Лимит:** 100 запросов/день (free trial). Платный — по запросу.

### 3. Контур.Компас API (опционально, дорого)

Контур предоставляет API, но тарифы начинаются от ~50 000 ₽/год.
Для MVP — лучше использовать DaData + 2GIS, а Компас рекомендовать клиенту для ручной работы.

---

## Хранение данных

### Новая таблица `lead_gen_tasks`

```sql
CREATE TABLE lead_gen_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, running, done, error
    params JSONB NOT NULL,          -- {okved, region, limit, ...}
    results JSONB,                  -- {found: 150, imported: 142, errors: 8}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
```

### Новая таблица `lead_gen_companies` (кэш найденных компаний)

```sql
CREATE TABLE lead_gen_companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    task_id UUID REFERENCES lead_gen_tasks(id),
    inn TEXT,
    name TEXT,
    okved TEXT,
    region TEXT,
    address TEXT,
    director_name TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    revenue BIGINT,
    employees INT,
    source TEXT,           -- 'dadata', '2gis', 'kontour'
    crm_lead_id INT,       -- ID созданного лида в AmoCRM (NULL если не импортирован)
    crm_contact_id INT,
    crm_company_id INT,
    enriched BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, inn)  -- дедупликация по ИНН
);
```

---

## Сценарии использования (user stories)

### Сценарий 1: Быстрый сбор по ОКВЭД

```
Дима: «Найди всех оптовиков чая в России»

Бот:
1. kommo_lead_gen.search_companies(okved='46.37', limit=100)
2. DaData → 2 847 компаний найдено
3. Бот: «Найдено 2 847 компаний с ОКВЭД 46.37. Показать первые 20? Или сразу импортировать в CRM?»

Дима: «Импортируй первые 500 в воронку Холодные продажи»

Бот:
4. kommo_lead_gen.import_to_crm(pipeline='Холодные продажи', limit=500, tag='оптовики_чай')
5. Создаёт 500 лидов + контакты + компании в AmoCRM
6. Бот: «✅ Импортировано 487 лидов (13 дубликатов пропущено). Воронка: Холодные продажи. Тег: #оптовики_чай»
```

### Сценарий 2: HoReCa по городу

```
Дима: «Собери рестораны и кафе в Сочи»

Бот:
1. kommo_lead_gen.search_horeca(city='Сочи', rubric='рестораны,кафе')
2. 2GIS → 1 240 заведений
3. Бот: «Найдено 1 240 заведений в Сочи. С телефонами: 1 180. Импортировать?»
```

### Сценарий 3: Пошаговый с обогащением

```
Дима: «Найди чайные магазины в Москве, обогати контакты и загрузи в CRM»

Бот (multi-step):
1. search_companies(okved='47.29.3', region='Москва')  → 340 компаний
2. enrich(company_ids=...)                              → +email для 210, +телефон для 280
3. import_to_crm(pipeline='Чайные магазины')            → 340 лидов
4. Отчёт: «340 лидов, 280 с телефонами, 210 с email»
```

---

## Этапы реализации

### MVP (1-2 дня)

1. Добавить `kommo_lead_gen` tool в MCP_TOOLS с actions: `search_companies`, `preview`, `import_to_crm`
2. Интегрировать DaData suggest/party API
3. Создать `_handle_lead_gen()` handler в ai_chat.py
4. Маппинг DaData → AmoCRM (компания + контакт + лид)
5. Дедупликация по ИНН

### v2 (+ 1-2 дня)

6. Интегрировать 2GIS API для HoReCa
7. Action `search_horeca`
8. Action `enrich` — обогащение через DaData find-party (по ИНН → полные данные)
9. Таблицы в PostgreSQL для кэша и истории задач

### v3 (+ 2-3 дня)

10. Фоновый сбор больших баз (>500 компаний) через async tasks
11. Action `status` для отслеживания прогресса
12. Интеграция Hunter.io для email ЛПР
13. Авто-назначение тегов по сегменту
14. Отчёт о качестве базы (% с телефонами, % с email)

---

## Конфигурация (env-переменные)

```env
# Lead Generation APIs (shared or per-tenant)
DADATA_API_TOKEN=...          # Бесплатно, 10к запросов/день
TWOGIS_API_KEY=...            # Free trial, 100 запросов/день
HUNTER_API_KEY=...            # Опционально, $49/мес
```

### Per-tenant config (в tenant.json)

```json
{
  "lead_gen_config": {
    "dadata_token": "...",         // свой или shared
    "default_pipeline_id": 12345,  // воронка для импорта
    "default_tag": "lead_gen",     // тег по умолчанию
    "dedup_by_inn": true           // дедупликация
  }
}
```

---

## Граф зависимостей (для tool_registry.yaml)

```yaml
- tool: kommo_lead_gen
  category: lead_generation
  capabilities: [search_companies, search_horeca, enrich_leads, import_leads]
  inputs: [okved, region, city, rubric, pipeline_id]
  outputs: [companies_list, import_report]

edges:
  - from: kommo_lead_gen.search_companies
    to: kommo_lead_gen.import_to_crm
    type: SEQUENCE
    weight: 0.9
    reason: Search first, then import

  - from: kommo_lead_gen.search_companies
    to: kommo_lead_gen.enrich
    type: SEQUENCE
    weight: 0.8
    reason: Search first, then enrich

  - from: kommo_lead_gen.import_to_crm
    to: kommo_list_pipelines
    type: REQUIRES
    weight: 1.0
    reason: Need pipeline_id to import

capability_map:
  - intent: lead_generation
    keywords: [собрать базу, найти компании, лидогенерация, сбор лидов, оптовики, HoReCa, ОКВЭД, поиск клиентов, b2b база, холодные продажи]
    capabilities: [search_companies, search_horeca, import_leads]
```

---

## Оценка трудозатрат

| Этап | Время | Результат |
|------|-------|-----------|
| MVP (DaData + import) | 1-2 дня | Сбор по ОКВЭД → лиды в AmoCRM |
| +2GIS | 1 день | HoReCa сегмент |
| +Enrichment + cache | 1-2 дня | Обогащение + дедупликация |
| +Background tasks | 1 день | Большие базы (>500) |
| **Итого** | **4-6 дней** | Полноценный lead gen агент |
