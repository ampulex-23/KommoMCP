# Предложение: Оптимизированные композитные Tools

## Проблема текущего подхода

**Сейчас:** 21 tool → покрывает ~30 stories из 1000
**При текущем темпе:** 1000 stories = 700+ tools = невозможно

**Ограничения:**
- GPT Actions: max 20-30 tools
- MCP: описания tools занимают context window
- UX: сложно найти нужный tool среди сотен

---

## Новая стратегия: Композитные Tools

**Принцип:** Один tool с параметром `action` покрывает целую категорию сценариев

### Пример трансформации

**Было (10 tools):**
```
kommo_pipeline_analytics
kommo_funnel_analysis
kommo_revenue_trend
kommo_sales_forecast
kommo_manager_performance
kommo_stale_deals
kommo_lead_sources
kommo_churn_risk
kommo_lead_score
kommo_duplicates_find
```

**Стало (1 tool):**
```
kommo_analytics(action, params)
  action: pipeline | funnel | revenue | forecast | managers | 
          stale | sources | churn | scoring | duplicates
```

---

## Предложение: 5 новых композитных Tools

### 1. `kommo_report` — Универсальные отчёты

**Покрывает stories:** 81-90, 291-300, 701-800 (~120 stories)

```python
kommo_report(
    report_type: str,  # summary | detailed | comparison | trend | custom
    entity: str,       # leads | contacts | companies | tasks | deals
    metrics: list,     # revenue, count, conversion, avg_check, cycle_time
    group_by: str,     # day | week | month | manager | pipeline | stage
    filters: dict,     # date_from, date_to, pipeline_id, user_id, etc.
    format: str,       # json | table | chart_data
)
```

**Примеры использования:**
- "Отчёт по выручке за квартал по менеджерам" → `report_type=summary, entity=deals, metrics=[revenue], group_by=manager`
- "Сравнение конверсии по воронкам" → `report_type=comparison, entity=leads, metrics=[conversion], group_by=pipeline`
- "Тренд количества сделок по неделям" → `report_type=trend, entity=deals, metrics=[count], group_by=week`

---

### 2. `kommo_smart_search` — Умный поиск

**Покрывает stories:** 301-400 (~100 stories)

```python
kommo_smart_search(
    query: str,           # Естественный язык: "крупные сделки в работе"
    entity_types: list,   # leads | contacts | companies | tasks | notes
    search_mode: str,     # semantic | exact | fuzzy | pattern
    filters: dict,        # Дополнительные фильтры
    include_related: bool,# Включить связанные сущности
    limit: int,
)
```

**Примеры:**
- "Найди все сделки с Газпромом" → semantic search по companies
- "Контакты без email" → pattern search с фильтром
- "Похожие сделки на #12345" → similarity search

---

### 3. `kommo_bulk_action` — Массовые операции

**Покрывает stories:** 101-200 (автоматизация), 601-700 (задачи) (~150 stories)

```python
kommo_bulk_action(
    action: str,          # create | update | move | assign | tag | notify
    entity_type: str,     # leads | contacts | tasks | notes
    targets: dict,        # Критерии выбора: {pipeline_id, stage_id, user_id, tags, ...}
    changes: dict,        # Что изменить: {status_id, responsible_user_id, tags, ...}
    options: dict,        # create_tasks, send_notifications, log_changes
)
```

**Примеры:**
- "Назначь все сделки без ответственного на Иванова" → `action=assign, targets={responsible_user_id: null}`
- "Создай задачи 'Перезвонить' для всех зависших сделок" → `action=create, entity_type=tasks, targets={stale_days: 14}`
- "Перенеси сделки из 'Новые' в 'В работе'" → `action=move, targets={stage_id: 123}, changes={stage_id: 456}`

---

### 4. `kommo_insights` — AI-инсайты и рекомендации

**Покрывает stories:** 71-80 (предиктивная), 421-440 (рекомендации), 441-450 (возражения) (~80 stories)

```python
kommo_insights(
    insight_type: str,    # prediction | recommendation | anomaly | pattern | risk
    context: str,         # sales | marketing | support | management
    entity_id: int,       # Опционально: конкретная сделка/контакт
    time_horizon: str,    # week | month | quarter
)
```

**Примеры:**
- "Какие сделки скорее всего закроются на этой неделе?" → `insight_type=prediction, context=sales`
- "Рекомендации по улучшению конверсии" → `insight_type=recommendation, context=sales`
- "Аномалии в продажах за месяц" → `insight_type=anomaly, time_horizon=month`
- "Риски по сделке #12345" → `insight_type=risk, entity_id=12345`

---

### 5. `kommo_workflow` — Управление процессами

**Покрывает stories:** 131-180 (процессы), 171-200 (workflow) (~70 stories)

```python
kommo_workflow(
    action: str,          # trigger | schedule | status | cancel | list
    workflow_type: str,   # follow_up | nurture | onboarding | escalation | custom
    trigger_conditions: dict,  # Условия запуска
    actions_sequence: list,    # Последовательность действий
    entity_id: int,       # Для какой сущности
)
```

**Примеры:**
- "Запусти follow-up для сделки #123" → `action=trigger, workflow_type=follow_up, entity_id=123`
- "Настрой автоматическую эскалацию для зависших сделок" → `action=schedule, workflow_type=escalation`
- "Покажи активные процессы" → `action=list`

---

## Итоговая структура Tools

### После оптимизации: 15 tools → ~500 stories

| Tool | Категория | Stories |
|------|-----------|---------|
| **Существующие (оставить)** | | |
| `kommo_ping` | Статус | - |
| `kommo_sync_start` | Синхронизация | 146 |
| `kommo_sync_status` | Синхронизация | - |
| `kommo_pipelines_list` | Данные | - |
| `kommo_leads_list` | Данные | 301-310 |
| `kommo_lead_get` | Данные | 311-320 |
| `kommo_contacts_list` | Данные | 501-510 |
| **Объединить в композитные** | | |
| `kommo_analytics` | Аналитика | 1-100 |
| `kommo_report` | Отчёты | 81-90, 701-800 |
| `kommo_smart_search` | Поиск | 301-400 |
| `kommo_bulk_action` | Автоматизация | 101-200, 601-700 |
| `kommo_insights` | AI/Рекомендации | 71-80, 421-450 |
| `kommo_workflow` | Процессы | 131-200 |
| `kommo_entity_manage` | CRUD | 401-500, 501-600 |
| `kommo_communicate` | Коммуникации | 201-300 |

---

## План реализации

### Этап 1: `kommo_analytics` (объединение существующих)

Объединить текущие analytics tools в один:

```python
async def kommo_analytics(
    action: str,  # pipeline | funnel | revenue | forecast | managers | stale | sources | churn | scoring | duplicates
    **params
):
    match action:
        case 'pipeline': return await engine.pipeline_analytics(**params)
        case 'funnel': return await engine.funnel_analysis(**params)
        case 'revenue': return await engine.revenue_trend(**params)
        # ...
```

**Результат:** 10 tools → 1 tool

### Этап 2: `kommo_report` (новый)

Универсальный генератор отчётов с гибкими параметрами.

### Этап 3: `kommo_bulk_action` (новый)

Массовые операции над сущностями.

### Этап 4: `kommo_insights` (новый)

AI-powered рекомендации и предсказания.

### Этап 5: `kommo_smart_search` (новый)

Семантический поиск по всем данным CRM.

---

## Приоритет реализации

| # | Tool | Сложность | Ценность | Stories |
|---|------|-----------|----------|---------|
| 1 | `kommo_analytics` | Низкая (рефакторинг) | Высокая | ~100 |
| 2 | `kommo_report` | Средняя | Высокая | ~120 |
| 3 | `kommo_bulk_action` | Средняя | Очень высокая | ~150 |
| 4 | `kommo_entity_manage` | Низкая (рефакторинг) | Средняя | ~200 |
| 5 | `kommo_insights` | Высокая | Очень высокая | ~80 |
| 6 | `kommo_smart_search` | Высокая | Высокая | ~100 |
| 7 | `kommo_workflow` | Высокая | Средняя | ~70 |

**Рекомендация:** Начать с 1-4 (низкая/средняя сложность, высокая ценность)

---

## Следующий шаг

Реализовать `kommo_analytics` — объединение существующих analytics tools в один композитный tool с параметром `action`.

Это даст:
- Сокращение с 10 tools до 1
- Сохранение всей функциональности
- Паттерн для остальных композитных tools
