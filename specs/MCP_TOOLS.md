# MCP Tools Specification

> Software Design Document — Спецификация MCP инструментов

## 1. Обзор

### 1.1 Категории инструментов

| Категория | Приоритет | Описание |
|-----------|-----------|----------|
| **Analytics** | 🔴 HIGH | Аналитика и отчеты (фокус MVP) |
| **Leads** | 🔴 HIGH | CRUD операции со сделками |
| **Contacts** | 🟡 MEDIUM | CRUD операции с контактами |
| **Companies** | 🟡 MEDIUM | CRUD операции с компаниями |
| **Tasks** | 🟡 MEDIUM | CRUD операции с задачами |
| **Pipelines** | 🟡 MEDIUM | Управление воронками |
| **Scripts** | 🟢 LOW | Кастомные скрипты |
| **Sync** | 🟢 LOW | Синхронизация данных |

### 1.2 Naming Convention
- `kommo_` prefix для всех tools
- `_list`, `_get`, `_create`, `_update`, `_delete` суффиксы для CRUD
- `_analytics`, `_report`, `_summary` для аналитики

---

## 2. Analytics Tools (Приоритет: HIGH)

### 2.1 kommo_pipeline_analytics

```python
@mcp.tool()
async def kommo_pipeline_analytics(
    pipeline_id: int | None = None,
    date_from: str | None = None,  # ISO format: 2024-01-01
    date_to: str | None = None,
    include_stages: bool = True
) -> dict:
    '''
    Получить аналитику по воронке продаж.
    
    Возвращает:
    - Общее количество сделок
    - Сумма и средний чек
    - Конверсия по этапам
    - Средний цикл сделки
    
    Args:
        pipeline_id: ID воронки (если не указан - все воронки)
        date_from: Начало периода (ISO format)
        date_to: Конец периода (ISO format)
        include_stages: Включить детализацию по этапам
    
    Returns:
        Аналитика воронки с метриками
    '''
```

**Пример ответа:**
```json
{
  "pipeline": {
    "id": 123,
    "name": "Основная воронка"
  },
  "period": {
    "from": "2024-01-01",
    "to": "2024-01-31"
  },
  "summary": {
    "total_leads": 150,
    "total_value": 5000000,
    "avg_value": 33333,
    "won_leads": 45,
    "lost_leads": 30,
    "in_progress": 75,
    "conversion_rate": 0.30,
    "avg_cycle_days": 14.5
  },
  "stages": [
    {
      "id": 456,
      "name": "Первичный контакт",
      "leads_count": 50,
      "total_value": 1500000,
      "conversion_to_next": 0.70
    }
  ]
}
```

### 2.2 kommo_sales_forecast

```python
@mcp.tool()
async def kommo_sales_forecast(
    pipeline_id: int | None = None,
    forecast_days: int = 30,
    method: str = 'weighted'  # 'weighted', 'historical', 'optimistic'
) -> dict:
    '''
    Прогноз продаж на основе текущей воронки и исторических данных.
    
    Args:
        pipeline_id: ID воронки
        forecast_days: Горизонт прогноза в днях
        method: Метод прогнозирования
            - weighted: взвешенный по вероятности этапов
            - historical: на основе исторической конверсии
            - optimistic: оптимистичный сценарий
    
    Returns:
        Прогноз с разбивкой по сценариям
    '''
```

### 2.3 kommo_manager_performance

```python
@mcp.tool()
async def kommo_manager_performance(
    user_id: int | None = None,  # если не указан - все менеджеры
    period: str = 'month',  # 'day', 'week', 'month', 'quarter', 'year'
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int | None = None  # топ N менеджеров
) -> dict:
    '''
    Статистика эффективности менеджеров.
    
    Метрики:
    - Созданные/выигранные/проигранные сделки
    - Win rate
    - Выручка и средний чек
    - Выполненные задачи
    - Среднее время ответа
    
    Args:
        user_id: ID менеджера (все если не указан)
        period: Период агрегации
        date_from: Начало периода
        date_to: Конец периода
        top_n: Вернуть только топ N
    
    Returns:
        Статистика по менеджерам
    '''
```

### 2.4 kommo_funnel_analysis

```python
@mcp.tool()
async def kommo_funnel_analysis(
    pipeline_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    cohort: str | None = None  # 'week', 'month'
) -> dict:
    '''
    Детальный анализ воронки: конверсии между этапами, 
    время на этапе, точки потерь.
    
    Args:
        pipeline_id: ID воронки
        date_from: Начало периода
        date_to: Конец периода
        cohort: Группировка по когортам
    
    Returns:
        Детальный анализ воронки
    '''
```

### 2.5 kommo_revenue_report

```python
@mcp.tool()
async def kommo_revenue_report(
    group_by: str = 'month',  # 'day', 'week', 'month', 'quarter'
    date_from: str | None = None,
    date_to: str | None = None,
    pipeline_id: int | None = None,
    compare_previous: bool = False
) -> dict:
    '''
    Отчет по выручке с группировкой по периодам.
    
    Args:
        group_by: Группировка по периоду
        date_from: Начало периода
        date_to: Конец периода
        pipeline_id: Фильтр по воронке
        compare_previous: Сравнить с предыдущим периодом
    
    Returns:
        Отчет по выручке с динамикой
    '''
```

### 2.6 kommo_leads_summary

```python
@mcp.tool()
async def kommo_leads_summary(
    pipeline_id: int | None = None,
    status_id: int | None = None,
    responsible_user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None
) -> dict:
    '''
    Краткая сводка по сделкам без загрузки всех данных.
    Идеально для быстрого обзора состояния.
    
    Returns:
        Сводка: количество, суммы, распределение по этапам
    '''
```

### 2.7 kommo_activity_report

```python
@mcp.tool()
async def kommo_activity_report(
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_types: list[str] | None = None  # 'tasks', 'calls', 'notes', 'emails'
) -> dict:
    '''
    Отчет по активности: задачи, звонки, примечания.
    
    Returns:
        Статистика активности по типам и пользователям
    '''
```

---

## 3. Leads Tools

### 3.1 kommo_leads_list

```python
@mcp.tool()
async def kommo_leads_list(
    pipeline_id: int | None = None,
    status_id: int | None = None,
    responsible_user_id: int | None = None,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    page: int = 1,
    order_by: str = 'created_at',
    order_dir: str = 'desc'
) -> dict:
    '''
    Получить список сделок с фильтрацией.
    
    Args:
        pipeline_id: Фильтр по воронке
        status_id: Фильтр по этапу
        responsible_user_id: Фильтр по ответственному
        query: Текстовый поиск
        date_from: Дата создания от
        date_to: Дата создания до
        limit: Количество на странице (макс 250)
        page: Номер страницы
        order_by: Поле сортировки
        order_dir: Направление сортировки
    
    Returns:
        Список сделок с пагинацией
    '''
```

### 3.2 kommo_lead_get

```python
@mcp.tool()
async def kommo_lead_get(
    lead_id: int,
    with_contacts: bool = True,
    with_companies: bool = True,
    with_tasks: bool = False,
    with_notes: bool = False
) -> dict:
    '''
    Получить детальную информацию о сделке.
    
    Args:
        lead_id: ID сделки
        with_contacts: Включить связанные контакты
        with_companies: Включить связанные компании
        with_tasks: Включить задачи
        with_notes: Включить примечания
    
    Returns:
        Полная информация о сделке
    '''
```

### 3.3 kommo_lead_create

```python
@mcp.tool()
async def kommo_lead_create(
    name: str,
    pipeline_id: int,
    status_id: int | None = None,
    price: int = 0,
    responsible_user_id: int | None = None,
    contact_id: int | None = None,
    company_id: int | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''
    Создать новую сделку.
    
    Args:
        name: Название сделки
        pipeline_id: ID воронки
        status_id: ID этапа (первый этап если не указан)
        price: Бюджет сделки
        responsible_user_id: ID ответственного
        contact_id: ID контакта для привязки
        company_id: ID компании для привязки
        custom_fields: Кастомные поля {field_id: value}
    
    Returns:
        Созданная сделка
    '''
```

### 3.4 kommo_lead_update

```python
@mcp.tool()
async def kommo_lead_update(
    lead_id: int,
    name: str | None = None,
    status_id: int | None = None,
    price: int | None = None,
    responsible_user_id: int | None = None,
    loss_reason_id: int | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''
    Обновить сделку.
    
    Args:
        lead_id: ID сделки
        name: Новое название
        status_id: Новый этап
        price: Новый бюджет
        responsible_user_id: Новый ответственный
        loss_reason_id: Причина проигрыша (для закрытых)
        custom_fields: Кастомные поля для обновления
    
    Returns:
        Обновленная сделка
    '''
```

### 3.5 kommo_lead_move

```python
@mcp.tool()
async def kommo_lead_move(
    lead_id: int,
    status_id: int,
    pipeline_id: int | None = None
) -> dict:
    '''
    Переместить сделку на другой этап.
    
    Args:
        lead_id: ID сделки
        status_id: ID нового этапа
        pipeline_id: ID воронки (если перемещение между воронками)
    
    Returns:
        Обновленная сделка
    '''
```

### 3.6 kommo_leads_bulk_update

```python
@mcp.tool()
async def kommo_leads_bulk_update(
    lead_ids: list[int],
    status_id: int | None = None,
    responsible_user_id: int | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''
    Массовое обновление сделок.
    
    Args:
        lead_ids: Список ID сделок
        status_id: Новый этап для всех
        responsible_user_id: Новый ответственный для всех
        custom_fields: Кастомные поля для обновления
    
    Returns:
        Результат обновления
    '''
```

---

## 4. Contacts Tools

### 4.1 kommo_contacts_list

```python
@mcp.tool()
async def kommo_contacts_list(
    query: str | None = None,
    responsible_user_id: int | None = None,
    limit: int = 50,
    page: int = 1
) -> dict:
    '''Получить список контактов с фильтрацией.'''
```

### 4.2 kommo_contact_get

```python
@mcp.tool()
async def kommo_contact_get(
    contact_id: int,
    with_leads: bool = True,
    with_companies: bool = True
) -> dict:
    '''Получить детальную информацию о контакте.'''
```

### 4.3 kommo_contact_create

```python
@mcp.tool()
async def kommo_contact_create(
    name: str,
    first_name: str | None = None,
    last_name: str | None = None,
    responsible_user_id: int | None = None,
    phone: str | None = None,
    email: str | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''Создать новый контакт.'''
```

### 4.4 kommo_contact_update

```python
@mcp.tool()
async def kommo_contact_update(
    contact_id: int,
    name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    responsible_user_id: int | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''Обновить контакт.'''
```

### 4.5 kommo_contact_find

```python
@mcp.tool()
async def kommo_contact_find(
    phone: str | None = None,
    email: str | None = None
) -> dict:
    '''
    Найти контакт по телефону или email.
    Полезно для проверки дубликатов.
    '''
```

---

## 5. Companies Tools

### 5.1 kommo_companies_list

```python
@mcp.tool()
async def kommo_companies_list(
    query: str | None = None,
    responsible_user_id: int | None = None,
    limit: int = 50,
    page: int = 1
) -> dict:
    '''Получить список компаний.'''
```

### 5.2 kommo_company_get

```python
@mcp.tool()
async def kommo_company_get(
    company_id: int,
    with_leads: bool = True,
    with_contacts: bool = True
) -> dict:
    '''Получить информацию о компании.'''
```

### 5.3 kommo_company_create

```python
@mcp.tool()
async def kommo_company_create(
    name: str,
    responsible_user_id: int | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''Создать компанию.'''
```

### 5.4 kommo_company_update

```python
@mcp.tool()
async def kommo_company_update(
    company_id: int,
    name: str | None = None,
    responsible_user_id: int | None = None,
    custom_fields: dict | None = None
) -> dict:
    '''Обновить компанию.'''
```

---

## 6. Tasks Tools

### 6.1 kommo_tasks_list

```python
@mcp.tool()
async def kommo_tasks_list(
    responsible_user_id: int | None = None,
    entity_type: str | None = None,  # 'leads', 'contacts', 'companies'
    entity_id: int | None = None,
    is_completed: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    page: int = 1
) -> dict:
    '''Получить список задач.'''
```

### 6.2 kommo_task_create

```python
@mcp.tool()
async def kommo_task_create(
    text: str,
    complete_till: str,  # ISO datetime
    entity_type: str | None = None,
    entity_id: int | None = None,
    responsible_user_id: int | None = None,
    task_type: str = 'call'  # 'call', 'meeting', 'email'
) -> dict:
    '''Создать задачу.'''
```

### 6.3 kommo_task_complete

```python
@mcp.tool()
async def kommo_task_complete(
    task_id: int,
    result: str | None = None
) -> dict:
    '''Завершить задачу.'''
```

### 6.4 kommo_tasks_overdue

```python
@mcp.tool()
async def kommo_tasks_overdue(
    responsible_user_id: int | None = None
) -> dict:
    '''Получить просроченные задачи.'''
```

---

## 7. Pipelines Tools

### 7.1 kommo_pipelines_list

```python
@mcp.tool()
async def kommo_pipelines_list() -> dict:
    '''Получить список всех воронок с этапами.'''
```

### 7.2 kommo_pipeline_get

```python
@mcp.tool()
async def kommo_pipeline_get(
    pipeline_id: int
) -> dict:
    '''Получить воронку с детальной информацией об этапах.'''
```

---

## 8. Users Tools

### 8.1 kommo_users_list

```python
@mcp.tool()
async def kommo_users_list(
    with_rights: bool = False
) -> dict:
    '''Получить список пользователей аккаунта.'''
```

### 8.2 kommo_user_get

```python
@mcp.tool()
async def kommo_user_get(
    user_id: int
) -> dict:
    '''Получить информацию о пользователе.'''
```

---

## 9. Notes Tools

### 9.1 kommo_notes_list

```python
@mcp.tool()
async def kommo_notes_list(
    entity_type: str,  # 'leads', 'contacts', 'companies'
    entity_id: int,
    limit: int = 50
) -> dict:
    '''Получить примечания сущности.'''
```

### 9.2 kommo_note_create

```python
@mcp.tool()
async def kommo_note_create(
    entity_type: str,
    entity_id: int,
    text: str,
    note_type: str = 'common'  # 'common', 'call_in', 'call_out'
) -> dict:
    '''Добавить примечание к сущности.'''
```

---

## 10. Scripts Tools

### 10.1 kommo_script_run

```python
@mcp.tool()
async def kommo_script_run(
    script_name: str,
    params: dict | None = None
) -> dict:
    '''
    Запустить предопределенный скрипт для работы с большими данными.
    
    Доступные скрипты:
    - export_leads: Экспорт сделок в файл
    - bulk_update_status: Массовое обновление статусов
    - find_duplicates: Поиск дубликатов контактов
    - recalculate_analytics: Пересчет аналитики
    
    Args:
        script_name: Имя скрипта
        params: Параметры скрипта
    
    Returns:
        Результат выполнения или ID задачи для асинхронных скриптов
    '''
```

### 10.2 kommo_script_status

```python
@mcp.tool()
async def kommo_script_status(
    job_id: str
) -> dict:
    '''
    Проверить статус асинхронного скрипта.
    
    Args:
        job_id: ID задачи
    
    Returns:
        Статус: pending, running, completed, failed
    '''
```

### 10.3 kommo_custom_query

```python
@mcp.tool()
async def kommo_custom_query(
    query_type: str,  # 'aggregate', 'filter', 'export'
    entity: str,  # 'leads', 'contacts', 'companies'
    filters: dict | None = None,
    group_by: list[str] | None = None,
    metrics: list[str] | None = None,
    limit: int = 1000
) -> dict:
    '''
    Выполнить кастомный аналитический запрос.
    Данные берутся из локальной БД (требуется синхронизация).
    
    Args:
        query_type: Тип запроса
        entity: Сущность
        filters: Фильтры
        group_by: Группировка
        metrics: Метрики для агрегации
        limit: Лимит результатов
    
    Returns:
        Результат запроса
    '''
```

---

## 11. Sync Tools

### 11.1 kommo_sync_start

```python
@mcp.tool()
async def kommo_sync_start(
    entities: list[str] | None = None,  # ['leads', 'contacts', ...]
    full_sync: bool = False
) -> dict:
    '''
    Запустить синхронизацию данных из Kommo в локальную БД.
    
    Args:
        entities: Список сущностей для синхронизации (все если не указано)
        full_sync: Полная синхронизация (иначе инкрементальная)
    
    Returns:
        ID задачи синхронизации
    '''
```

### 11.2 kommo_sync_status

```python
@mcp.tool()
async def kommo_sync_status() -> dict:
    '''
    Получить статус синхронизации и свежесть данных.
    
    Returns:
        Статус по каждой сущности: last_sync, records_count
    '''
```

---

## 12. MCP Resources

### 12.1 Pipelines Resource

```python
@mcp.resource('kommo://pipelines')
async def get_pipelines_resource() -> list:
    '''
    Список воронок для контекста LLM.
    Автоматически предоставляется при запросах о воронках.
    '''
```

### 12.2 Users Resource

```python
@mcp.resource('kommo://users')
async def get_users_resource() -> list:
    '''
    Список пользователей для контекста LLM.
    '''
```

### 12.3 Custom Fields Resource

```python
@mcp.resource('kommo://custom_fields/{entity_type}')
async def get_custom_fields_resource(entity_type: str) -> list:
    '''
    Список кастомных полей для сущности.
    '''
```

---

## 13. MCP Prompts

### 13.1 Analytics Prompt

```python
@mcp.prompt('analytics_report')
async def analytics_report_prompt(
    report_type: str = 'pipeline'
) -> str:
    '''
    Шаблон промпта для аналитического отчета.
    '''
    return f'''
    Создай аналитический отчет типа "{report_type}".
    
    Используй инструменты:
    - kommo_pipeline_analytics для данных воронки
    - kommo_manager_performance для статистики менеджеров
    - kommo_revenue_report для выручки
    
    Формат отчета:
    1. Краткое резюме (3-5 предложений)
    2. Ключевые метрики
    3. Тренды и изменения
    4. Рекомендации
    '''
```

### 13.2 Lead Qualification Prompt

```python
@mcp.prompt('lead_qualification')
async def lead_qualification_prompt() -> str:
    '''
    Шаблон для квалификации лида.
    '''
    return '''
    Проанализируй сделку и определи:
    1. Качество лида (hot/warm/cold)
    2. Вероятность закрытия
    3. Рекомендуемые следующие шаги
    4. Риски
    
    Используй kommo_lead_get для получения данных.
    '''
```

---

## 14. Error Handling

### 14.1 Error Responses

```python
class MCPError(BaseModel):
    error: str
    code: str
    details: dict | None = None

# Коды ошибок
ERROR_CODES = {
    'KOMMO_API_ERROR': 'Ошибка Kommo API',
    'RATE_LIMIT': 'Превышен лимит запросов',
    'NOT_FOUND': 'Сущность не найдена',
    'VALIDATION_ERROR': 'Ошибка валидации',
    'SYNC_REQUIRED': 'Требуется синхронизация данных',
    'PERMISSION_DENIED': 'Недостаточно прав',
}
```

### 14.2 Graceful Degradation

```python
async def kommo_pipeline_analytics(...):
    try:
        # Попытка получить из локальной БД
        result = await analytics_engine.pipeline_summary(...)
    except SyncRequiredError:
        # Fallback на API (медленнее, но работает)
        result = await api_client.get_pipeline_analytics(...)
    return result
```

---

## 15. Response Formatting

### 15.1 Для LLM

```python
def format_for_llm(data: dict, max_items: int = 10) -> dict:
    '''
    Форматирование ответа для LLM:
    - Ограничение количества элементов
    - Добавление summary
    - Человекочитаемые даты
    '''
    if 'items' in data and len(data['items']) > max_items:
        data['items'] = data['items'][:max_items]
        data['truncated'] = True
        data['message'] = f'Показано {max_items} из {data["total"]}'
    return data
```

### 15.2 Summary Generation

```python
def generate_summary(analytics_data: dict) -> str:
    '''
    Генерация текстового summary для аналитики.
    '''
    return f'''
    📊 Сводка по воронке "{analytics_data['pipeline']['name']}":
    • Всего сделок: {analytics_data['summary']['total_leads']}
    • Общая сумма: {analytics_data['summary']['total_value']:,.0f} ₽
    • Конверсия: {analytics_data['summary']['conversion_rate']:.1%}
    • Средний цикл: {analytics_data['summary']['avg_cycle_days']:.1f} дней
    '''
```
