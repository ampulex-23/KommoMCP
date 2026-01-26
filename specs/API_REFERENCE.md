# Kommo (amoCRM) API Reference

> Полное описание API для разработки MCP сервера

## Общая информация

- **Base URL**: `https://{subdomain}.kommo.com/api/v4/`
- **Протокол**: HTTPS (TLS 1.2)
- **Формат данных**: JSON
- **Авторизация**: OAuth 2.0 / Long-lived Token

## Аутентификация

### OAuth 2.0

1. **Authorization Code** — временный код (20 минут), получается при установке интеграции
2. **Access Token** — JWT токен для запросов (24 часа)
3. **Refresh Token** — для обновления access token (3 месяца)

#### Получение токенов

```
POST /oauth2/access_token
Content-Type: application/json

{
  "client_id": "integration_id",
  "client_secret": "secret_key",
  "grant_type": "authorization_code",
  "code": "authorization_code",
  "redirect_uri": "https://your-app.com/callback"
}
```

#### Обновление токенов

```
POST /oauth2/access_token
Content-Type: application/json

{
  "client_id": "integration_id",
  "client_secret": "secret_key",
  "grant_type": "refresh_token",
  "refresh_token": "current_refresh_token",
  "redirect_uri": "https://your-app.com/callback"
}
```

#### Заголовок авторизации

```
Authorization: Bearer {access_token}
```

---

## Rate Limits и ограничения

| Ограничение | Значение |
|-------------|----------|
| Запросов в секунду | 7 |
| Макс. сущностей в ответе | 250 |
| Макс. сущностей в запросе (add/update) | 250 (рекомендуется 50) |
| Макс. pipelines на аккаунт | 50 |
| Макс. stages в pipeline | 100 |
| Макс. webhooks на аккаунт | 100 |
| Макс. lists на аккаунт | 10 |
| Макс. sources на интеграцию | 100 |

### HTTP коды ошибок

- **429** — Too Many Requests (превышен лимит)
- **403** — IP заблокирован (повторные нарушения)
- **504** — Timeout (уменьшить batch size)

---

## API Endpoints

### Account

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/account` | Параметры аккаунта |

### Leads (Сделки)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/leads` | Список сделок |
| GET | `/api/v4/leads/{id}` | Сделка по ID |
| POST | `/api/v4/leads` | Создать сделки |
| PATCH | `/api/v4/leads` | Обновить сделки |
| PATCH | `/api/v4/leads/{id}` | Обновить сделку |
| POST | `/api/v4/leads/complex` | Комплексное создание (lead + contact + company) |
| GET | `/api/v4/leads/loss_reasons` | Причины проигрыша |

#### Query параметры для GET /leads

- `page` — номер страницы
- `limit` — количество (макс 250)
- `query` — поиск по тексту
- `filter[id]` — фильтр по ID
- `filter[name]` — фильтр по имени
- `filter[price]` — фильтр по бюджету
- `filter[statuses]` — фильтр по статусам `[{pipeline_id, status_id}]`
- `filter[pipeline_id]` — фильтр по воронке
- `filter[created_at]` — фильтр по дате создания (from/to)
- `filter[updated_at]` — фильтр по дате обновления
- `filter[closed_at]` — фильтр по дате закрытия
- `filter[responsible_user_id]` — фильтр по ответственному
- `with` — связанные сущности (contacts, catalog_elements, loss_reason, etc.)
- `order[created_at]` — сортировка (asc/desc)
- `order[updated_at]` — сортировка

### Pipelines & Stages (Воронки и этапы)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/leads/pipelines` | Список воронок |
| GET | `/api/v4/leads/pipelines/{id}` | Воронка по ID |
| POST | `/api/v4/leads/pipelines` | Создать воронки |
| PATCH | `/api/v4/leads/pipelines/{id}` | Редактировать воронку |
| DELETE | `/api/v4/leads/pipelines/{id}` | Удалить воронку |
| GET | `/api/v4/leads/pipelines/{id}/statuses` | Этапы воронки |
| GET | `/api/v4/leads/pipelines/{id}/statuses/{status_id}` | Этап по ID |
| POST | `/api/v4/leads/pipelines/{id}/statuses` | Создать этапы |
| PATCH | `/api/v4/leads/pipelines/{id}/statuses/{status_id}` | Редактировать этап |
| DELETE | `/api/v4/leads/pipelines/{id}/statuses/{status_id}` | Удалить этап |

**Системные этапы:**
- ID 142 — Closed Won
- ID 143 — Closed Lost

### Contacts (Контакты)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/contacts` | Список контактов |
| GET | `/api/v4/contacts/{id}` | Контакт по ID |
| POST | `/api/v4/contacts` | Создать контакты |
| PATCH | `/api/v4/contacts` | Обновить контакты |
| PATCH | `/api/v4/contacts/{id}` | Обновить контакт |

### Companies (Компании)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/companies` | Список компаний |
| GET | `/api/v4/companies/{id}` | Компания по ID |
| POST | `/api/v4/companies` | Создать компании |
| PATCH | `/api/v4/companies` | Обновить компании |
| PATCH | `/api/v4/companies/{id}` | Обновить компанию |

### Tasks (Задачи)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/tasks` | Список задач |
| GET | `/api/v4/tasks/{id}` | Задача по ID |
| POST | `/api/v4/tasks` | Создать задачи |
| PATCH | `/api/v4/tasks` | Обновить задачи |
| PATCH | `/api/v4/tasks/{id}` | Обновить задачу |

### Notes (Примечания/События)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/{entity_type}/{entity_id}/notes` | Примечания сущности |
| GET | `/api/v4/{entity_type}/notes` | Все примечания по типу |
| GET | `/api/v4/{entity_type}/notes/{id}` | Примечание по ID |
| POST | `/api/v4/{entity_type}/{entity_id}/notes` | Создать примечания |
| PATCH | `/api/v4/{entity_type}/notes` | Обновить примечания |
| PATCH | `/api/v4/{entity_type}/notes/{id}` | Обновить примечание |

**entity_type**: leads, contacts, companies

### Events (События)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/events` | Список событий |
| GET | `/api/v4/events/{id}` | Событие по ID |
| GET | `/api/v4/events/types` | Типы событий |

### Custom Fields (Кастомные поля)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/{entity_type}/custom_fields` | Список полей |
| GET | `/api/v4/{entity_type}/custom_fields/{id}` | Поле по ID |
| POST | `/api/v4/{entity_type}/custom_fields` | Создать поля |
| PATCH | `/api/v4/{entity_type}/custom_fields` | Обновить поля |
| PATCH | `/api/v4/{entity_type}/custom_fields/{id}` | Обновить поле |
| DELETE | `/api/v4/{entity_type}/custom_fields/{id}` | Удалить поле |

**Типы полей:**
- text, numeric, checkbox, select, multiselect
- date, url, textarea, radiobutton
- streetaddress, smart_address, birthday
- legal_entity, price, category, items, tracking_data

### Users & Roles

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/users` | Список пользователей |
| GET | `/api/v4/users/{id}` | Пользователь по ID |
| POST | `/api/v4/users` | Создать пользователей |
| GET | `/api/v4/roles` | Список ролей |
| GET | `/api/v4/roles/{id}` | Роль по ID |
| POST | `/api/v4/roles` | Создать роли |
| PATCH | `/api/v4/roles` | Обновить роли |
| DELETE | `/api/v4/roles/{id}` | Удалить роль |

### Tags (Теги)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/{entity_type}/tags` | Список тегов |
| POST | `/api/v4/{entity_type}/tags` | Создать теги |
| PATCH | `/api/v4/{entity_type}/{id}/tags` | Добавить теги к сущности |

### Links (Связи между сущностями)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/{entity_type}/{id}/links` | Связанные сущности |
| POST | `/api/v4/{entity_type}/{id}/link` | Связать сущности |
| POST | `/api/v4/{entity_type}/{id}/unlink` | Отвязать сущности |

### Lists (Каталоги/Списки)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/catalogs` | Список каталогов |
| GET | `/api/v4/catalogs/{id}` | Каталог по ID |
| POST | `/api/v4/catalogs` | Создать каталоги |
| PATCH | `/api/v4/catalogs` | Обновить каталоги |
| GET | `/api/v4/catalogs/{id}/elements` | Элементы каталога |
| GET | `/api/v4/catalogs/{id}/elements/{element_id}` | Элемент по ID |
| POST | `/api/v4/catalogs/{id}/elements` | Создать элементы |
| PATCH | `/api/v4/catalogs/{id}/elements` | Обновить элементы |

### Incoming Leads (Неразобранное)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/leads/unsorted` | Список неразобранных |
| GET | `/api/v4/leads/unsorted/{uid}` | Неразобранная по UID |
| POST | `/api/v4/leads/unsorted/sip` | Создать из звонка |
| POST | `/api/v4/leads/unsorted/forms` | Создать из формы |
| POST | `/api/v4/leads/unsorted/{uid}/accept` | Принять |
| DELETE | `/api/v4/leads/unsorted/{uid}/decline` | Отклонить |
| POST | `/api/v4/leads/unsorted/{uid}/link` | Связать |
| GET | `/api/v4/leads/unsorted/summary` | Сводка |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/webhooks` | Список webhooks |
| POST | `/api/v4/webhooks` | Создать webhook |
| DELETE | `/api/v4/webhooks/{id}` | Удалить webhook |

**События webhooks:**
- lead_added, lead_deleted, lead_restored, lead_status_changed, lead_responsible_changed
- contact_added, contact_deleted, contact_restored, contact_responsible_changed
- company_added, company_deleted, company_restored, company_responsible_changed
- task_added, task_deleted, task_completed
- incoming_lead_added, incoming_message_received
- note_added, talk_added

### Sources (Источники)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/sources` | Список источников |
| GET | `/api/v4/sources/{id}` | Источник по ID |
| POST | `/api/v4/sources` | Создать источники |
| PATCH | `/api/v4/sources/{id}` | Обновить источник |
| DELETE | `/api/v4/sources/{id}` | Удалить источник |

### Calls (Звонки)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v4/calls` | Добавить звонок |
| POST | `/api/v4/calls/notifications` | Уведомление о звонке |

### Conversations (Беседы)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/conversations/{id}` | Беседа по ID |
| POST | `/api/v4/conversations/{id}/close` | Закрыть беседу |

### Salesbot

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v4/bots/{bot_id}/run` | Запустить бота |

### Widgets

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v4/widgets` | Список виджетов |
| GET | `/api/v4/widgets/{code}` | Виджет по коду |
| POST | `/api/v4/widgets/{code}/install` | Установить виджет |
| DELETE | `/api/v4/widgets/{code}` | Удалить виджет |

---

## Структуры данных

### Lead (Сделка)

```json
{
  "id": 123,
  "name": "Сделка #1",
  "price": 50000,
  "responsible_user_id": 456,
  "group_id": 0,
  "status_id": 142,
  "pipeline_id": 789,
  "loss_reason_id": null,
  "created_by": 456,
  "updated_by": 456,
  "created_at": 1609459200,
  "updated_at": 1609545600,
  "closed_at": null,
  "closest_task_at": null,
  "is_deleted": false,
  "custom_fields_values": [
    {
      "field_id": 111,
      "field_name": "Источник",
      "field_code": "SOURCE",
      "field_type": "select",
      "values": [
        {"value": "Сайт", "enum_id": 222}
      ]
    }
  ],
  "_embedded": {
    "tags": [],
    "contacts": [],
    "companies": [],
    "catalog_elements": []
  }
}
```

### Contact (Контакт)

```json
{
  "id": 123,
  "name": "Иван Иванов",
  "first_name": "Иван",
  "last_name": "Иванов",
  "responsible_user_id": 456,
  "group_id": 0,
  "created_by": 456,
  "updated_by": 456,
  "created_at": 1609459200,
  "updated_at": 1609545600,
  "is_deleted": false,
  "closest_task_at": null,
  "custom_fields_values": [
    {
      "field_id": 111,
      "field_name": "Телефон",
      "field_code": "PHONE",
      "field_type": "multitext",
      "values": [
        {"value": "+79001234567", "enum_code": "WORK"}
      ]
    }
  ],
  "_embedded": {
    "tags": [],
    "leads": [],
    "companies": []
  }
}
```

### Company (Компания)

```json
{
  "id": 123,
  "name": "ООО Компания",
  "responsible_user_id": 456,
  "group_id": 0,
  "created_by": 456,
  "updated_by": 456,
  "created_at": 1609459200,
  "updated_at": 1609545600,
  "is_deleted": false,
  "closest_task_at": null,
  "custom_fields_values": [],
  "_embedded": {
    "tags": [],
    "leads": [],
    "contacts": []
  }
}
```

### Task (Задача)

```json
{
  "id": 123,
  "created_by": 456,
  "updated_by": 456,
  "created_at": 1609459200,
  "updated_at": 1609545600,
  "responsible_user_id": 456,
  "group_id": 0,
  "entity_id": 789,
  "entity_type": "leads",
  "is_completed": false,
  "task_type_id": 1,
  "text": "Позвонить клиенту",
  "duration": 0,
  "complete_till": 1609632000,
  "result": null
}
```

### Pipeline (Воронка)

```json
{
  "id": 123,
  "name": "Основная воронка",
  "sort": 1,
  "is_main": true,
  "is_unsorted_on": true,
  "is_archive": false,
  "_embedded": {
    "statuses": [
      {
        "id": 456,
        "name": "Первичный контакт",
        "sort": 10,
        "is_editable": true,
        "pipeline_id": 123,
        "color": "#fffeb2",
        "type": 0
      }
    ]
  }
}
```

---

## Пагинация

Все списочные методы поддерживают пагинацию:

```
GET /api/v4/leads?page=1&limit=50
```

Ответ содержит:
```json
{
  "_page": 1,
  "_links": {
    "self": {"href": "..."},
    "next": {"href": "..."}
  },
  "_embedded": {
    "leads": [...]
  }
}
```

---

## Источники документации

- https://developers.kommo.com/reference/kommo-api-reference
- https://developers.kommo.com/docs/oauth-20
- https://developers.kommo.com/docs/limitations
- https://developers.kommo.com/docs/webhooks-general
