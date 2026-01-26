# Модели данных KommoMCP

> Software Design Document — Модели данных и схема БД

## 1. Обзор

### 1.1 Стратегия хранения данных

| Источник | Назначение | Стратегия |
|----------|------------|-----------|
| **Kommo API** | Актуальные данные | Real-time запросы для малых объемов |
| **PostgreSQL** | Аналитика, Big Data | Синхронизация + локальные агрегации |

### 1.2 Принципы
- **Pydantic** для валидации и сериализации
- **SQLAlchemy 2.0** для ORM с async поддержкой
- **Soft delete** — данные не удаляются физически
- **Timestamps** — created_at, updated_at, synced_at

---

## 2. Pydantic Models (API Layer)

### 2.1 Base Models

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any

class KommoBaseModel(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class CustomFieldValue(BaseModel):
    field_id: int
    field_name: str
    field_code: str | None = None
    field_type: str
    values: list[dict[str, Any]]
```

### 2.2 Lead (Сделка)

```python
class LeadBase(BaseModel):
    name: str
    price: int = 0
    responsible_user_id: int | None = None
    pipeline_id: int
    status_id: int
    loss_reason_id: int | None = None
    custom_fields_values: list[CustomFieldValue] = []

class LeadCreate(LeadBase):
    pass

class LeadUpdate(BaseModel):
    name: str | None = None
    price: int | None = None
    responsible_user_id: int | None = None
    status_id: int | None = None
    loss_reason_id: int | None = None
    custom_fields_values: list[CustomFieldValue] | None = None

class Lead(KommoBaseModel, LeadBase):
    group_id: int = 0
    created_by: int
    updated_by: int
    closed_at: datetime | None = None
    closest_task_at: datetime | None = None
    is_deleted: bool = False
    
    # Embedded
    tags: list['Tag'] = []
    contacts: list['ContactShort'] = []
    companies: list['CompanyShort'] = []

class LeadShort(BaseModel):
    id: int
    name: str
    price: int
    status_id: int
    pipeline_id: int
```

### 2.3 Contact (Контакт)

```python
class ContactBase(BaseModel):
    name: str
    first_name: str | None = None
    last_name: str | None = None
    responsible_user_id: int | None = None
    custom_fields_values: list[CustomFieldValue] = []

class ContactCreate(ContactBase):
    pass

class ContactUpdate(BaseModel):
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    responsible_user_id: int | None = None
    custom_fields_values: list[CustomFieldValue] | None = None

class Contact(KommoBaseModel, ContactBase):
    group_id: int = 0
    created_by: int
    updated_by: int
    closest_task_at: datetime | None = None
    is_deleted: bool = False
    
    tags: list['Tag'] = []
    leads: list[LeadShort] = []
    companies: list['CompanyShort'] = []

class ContactShort(BaseModel):
    id: int
    name: str
    is_main: bool = False
```

### 2.4 Company (Компания)

```python
class CompanyBase(BaseModel):
    name: str
    responsible_user_id: int | None = None
    custom_fields_values: list[CustomFieldValue] = []

class CompanyCreate(CompanyBase):
    pass

class CompanyUpdate(BaseModel):
    name: str | None = None
    responsible_user_id: int | None = None
    custom_fields_values: list[CustomFieldValue] | None = None

class Company(KommoBaseModel, CompanyBase):
    group_id: int = 0
    created_by: int
    updated_by: int
    closest_task_at: datetime | None = None
    is_deleted: bool = False
    
    tags: list['Tag'] = []
    leads: list[LeadShort] = []
    contacts: list[ContactShort] = []

class CompanyShort(BaseModel):
    id: int
    name: str
```

### 2.5 Task (Задача)

```python
from enum import IntEnum

class TaskType(IntEnum):
    CALL = 1
    MEETING = 2
    EMAIL = 3

class TaskBase(BaseModel):
    text: str
    complete_till: datetime
    task_type_id: int = TaskType.CALL
    entity_id: int | None = None
    entity_type: str | None = None  # leads, contacts, companies
    responsible_user_id: int | None = None

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    text: str | None = None
    complete_till: datetime | None = None
    is_completed: bool | None = None
    result: str | None = None

class Task(KommoBaseModel, TaskBase):
    created_by: int
    updated_by: int
    group_id: int = 0
    is_completed: bool = False
    duration: int = 0
    result: str | None = None
```

### 2.6 Pipeline & Stage (Воронка и Этап)

```python
class StageBase(BaseModel):
    name: str
    sort: int
    color: str = '#fffeb2'

class Stage(StageBase):
    id: int
    pipeline_id: int
    is_editable: bool = True
    type: int = 0  # 0=normal, 1=incoming, 2=closed_won, 3=closed_lost

class PipelineBase(BaseModel):
    name: str
    sort: int = 1
    is_main: bool = False
    is_unsorted_on: bool = True

class Pipeline(PipelineBase):
    id: int
    is_archive: bool = False
    statuses: list[Stage] = []
```

### 2.7 User (Пользователь)

```python
class User(BaseModel):
    id: int
    name: str
    email: str
    lang: str = 'ru'
    rights: dict = {}
    
class UserShort(BaseModel):
    id: int
    name: str
```

### 2.8 Note (Примечание)

```python
class NoteType(IntEnum):
    COMMON = 4
    CALL_IN = 10
    CALL_OUT = 11
    SERVICE_MESSAGE = 25

class NoteBase(BaseModel):
    note_type: int = NoteType.COMMON
    text: str | None = None
    params: dict = {}

class NoteCreate(NoteBase):
    entity_id: int
    entity_type: str  # leads, contacts, companies

class Note(KommoBaseModel, NoteBase):
    entity_id: int
    responsible_user_id: int
    group_id: int = 0
    created_by: int
    updated_by: int
```

### 2.9 Tag (Тег)

```python
class Tag(BaseModel):
    id: int
    name: str
    color: str | None = None
```

### 2.10 Event (Событие)

```python
class Event(BaseModel):
    id: str
    type: str
    entity_id: int
    entity_type: str
    created_by: int
    created_at: datetime
    value_after: list[dict] = []
    value_before: list[dict] = []
```

---

## 3. SQLAlchemy Models (Database Layer)

### 3.1 Base

```python
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, ForeignKey, BigInteger, Numeric
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    synced_at = Column(DateTime, server_default=func.now())

class KommoMixin(TimestampMixin):
    kommo_created_at = Column(DateTime)
    kommo_updated_at = Column(DateTime)
```

### 3.2 Leads Table

```python
class LeadDB(Base, KommoMixin):
    __tablename__ = 'leads'
    
    id = Column(BigInteger, primary_key=True)  # Kommo ID
    name = Column(String(255), nullable=False)
    price = Column(Numeric(15, 2), default=0)
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    pipeline_id = Column(BigInteger, ForeignKey('pipelines.id'), nullable=False)
    status_id = Column(BigInteger, ForeignKey('stages.id'), nullable=False)
    loss_reason_id = Column(BigInteger)
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    closed_at = Column(DateTime)
    closest_task_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    custom_fields = Column(JSON, default={})
    
    # Relationships
    responsible_user = relationship('UserDB', back_populates='leads')
    pipeline = relationship('PipelineDB', back_populates='leads')
    status = relationship('StageDB')
    contacts = relationship('ContactDB', secondary='lead_contacts', back_populates='leads')
    companies = relationship('CompanyDB', secondary='lead_companies', back_populates='leads')
    tasks = relationship('TaskDB', back_populates='lead')
    notes = relationship('NoteDB', back_populates='lead')
    
    # Indexes
    __table_args__ = (
        Index('ix_leads_pipeline_status', 'pipeline_id', 'status_id'),
        Index('ix_leads_responsible', 'responsible_user_id'),
        Index('ix_leads_created', 'kommo_created_at'),
        Index('ix_leads_closed', 'closed_at'),
    )
```

### 3.3 Contacts Table

```python
class ContactDB(Base, KommoMixin):
    __tablename__ = 'contacts'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    closest_task_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    custom_fields = Column(JSON, default={})
    
    # Relationships
    responsible_user = relationship('UserDB', back_populates='contacts')
    leads = relationship('LeadDB', secondary='lead_contacts', back_populates='contacts')
    companies = relationship('CompanyDB', secondary='contact_companies', back_populates='contacts')
    
    __table_args__ = (
        Index('ix_contacts_responsible', 'responsible_user_id'),
        Index('ix_contacts_name', 'name'),
    )
```

### 3.4 Companies Table

```python
class CompanyDB(Base, KommoMixin):
    __tablename__ = 'companies'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    closest_task_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    custom_fields = Column(JSON, default={})
    
    # Relationships
    responsible_user = relationship('UserDB', back_populates='companies')
    leads = relationship('LeadDB', secondary='lead_companies', back_populates='companies')
    contacts = relationship('ContactDB', secondary='contact_companies', back_populates='companies')
    
    __table_args__ = (
        Index('ix_companies_responsible', 'responsible_user_id'),
        Index('ix_companies_name', 'name'),
    )
```

### 3.5 Tasks Table

```python
class TaskDB(Base, KommoMixin):
    __tablename__ = 'tasks'
    
    id = Column(BigInteger, primary_key=True)
    text = Column(String(1000))
    task_type_id = Column(Integer, default=1)
    entity_id = Column(BigInteger)
    entity_type = Column(String(50))
    responsible_user_id = Column(BigInteger, ForeignKey('users.id'))
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    is_completed = Column(Boolean, default=False)
    complete_till = Column(DateTime)
    duration = Column(Integer, default=0)
    result = Column(String(1000))
    
    # Relationships
    responsible_user = relationship('UserDB', back_populates='tasks')
    lead = relationship('LeadDB', back_populates='tasks',
                       primaryjoin='and_(TaskDB.entity_id==LeadDB.id, TaskDB.entity_type=="leads")',
                       foreign_keys=[entity_id])
    
    __table_args__ = (
        Index('ix_tasks_entity', 'entity_type', 'entity_id'),
        Index('ix_tasks_responsible', 'responsible_user_id'),
        Index('ix_tasks_complete_till', 'complete_till'),
        Index('ix_tasks_completed', 'is_completed'),
    )
```

### 3.6 Pipelines & Stages Tables

```python
class PipelineDB(Base):
    __tablename__ = 'pipelines'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    sort = Column(Integer, default=1)
    is_main = Column(Boolean, default=False)
    is_unsorted_on = Column(Boolean, default=True)
    is_archive = Column(Boolean, default=False)
    synced_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    stages = relationship('StageDB', back_populates='pipeline', order_by='StageDB.sort')
    leads = relationship('LeadDB', back_populates='pipeline')

class StageDB(Base):
    __tablename__ = 'stages'
    
    id = Column(BigInteger, primary_key=True)
    pipeline_id = Column(BigInteger, ForeignKey('pipelines.id'), nullable=False)
    name = Column(String(255), nullable=False)
    sort = Column(Integer, default=0)
    color = Column(String(20), default='#fffeb2')
    is_editable = Column(Boolean, default=True)
    type = Column(Integer, default=0)  # 0=normal, 1=incoming, 2=won, 3=lost
    
    # Relationships
    pipeline = relationship('PipelineDB', back_populates='stages')
    
    __table_args__ = (
        Index('ix_stages_pipeline', 'pipeline_id'),
    )
```

### 3.7 Users Table

```python
class UserDB(Base):
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    lang = Column(String(10), default='ru')
    rights = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    synced_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    leads = relationship('LeadDB', back_populates='responsible_user')
    contacts = relationship('ContactDB', back_populates='responsible_user')
    companies = relationship('CompanyDB', back_populates='responsible_user')
    tasks = relationship('TaskDB', back_populates='responsible_user')
```

### 3.8 Notes Table

```python
class NoteDB(Base, KommoMixin):
    __tablename__ = 'notes'
    
    id = Column(BigInteger, primary_key=True)
    entity_id = Column(BigInteger, nullable=False)
    entity_type = Column(String(50), nullable=False)
    note_type = Column(Integer, default=4)
    text = Column(String(10000))
    params = Column(JSON, default={})
    responsible_user_id = Column(BigInteger)
    group_id = Column(BigInteger, default=0)
    created_by = Column(BigInteger)
    updated_by = Column(BigInteger)
    
    # Relationships
    lead = relationship('LeadDB', back_populates='notes',
                       primaryjoin='and_(NoteDB.entity_id==LeadDB.id, NoteDB.entity_type=="leads")',
                       foreign_keys=[entity_id])
    
    __table_args__ = (
        Index('ix_notes_entity', 'entity_type', 'entity_id'),
    )
```

### 3.9 Association Tables

```python
lead_contacts = Table(
    'lead_contacts',
    Base.metadata,
    Column('lead_id', BigInteger, ForeignKey('leads.id'), primary_key=True),
    Column('contact_id', BigInteger, ForeignKey('contacts.id'), primary_key=True),
    Column('is_main', Boolean, default=False),
)

lead_companies = Table(
    'lead_companies',
    Base.metadata,
    Column('lead_id', BigInteger, ForeignKey('leads.id'), primary_key=True),
    Column('company_id', BigInteger, ForeignKey('companies.id'), primary_key=True),
)

contact_companies = Table(
    'contact_companies',
    Base.metadata,
    Column('contact_id', BigInteger, ForeignKey('contacts.id'), primary_key=True),
    Column('company_id', BigInteger, ForeignKey('companies.id'), primary_key=True),
)
```

### 3.10 Custom Fields Metadata

```python
class CustomFieldDB(Base):
    __tablename__ = 'custom_fields'
    
    id = Column(BigInteger, primary_key=True)
    entity_type = Column(String(50), nullable=False)  # leads, contacts, companies
    name = Column(String(255), nullable=False)
    code = Column(String(100))
    field_type = Column(String(50), nullable=False)
    sort = Column(Integer, default=0)
    is_api_only = Column(Boolean, default=False)
    enums = Column(JSON, default=[])  # для select/multiselect
    synced_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        Index('ix_custom_fields_entity', 'entity_type'),
        UniqueConstraint('entity_type', 'code', name='uq_custom_fields_code'),
    )
```

---

## 4. Analytics Models

### 4.1 Pipeline Summary

```python
class PipelineSummary(BaseModel):
    pipeline_id: int
    pipeline_name: str
    total_leads: int
    total_value: float
    avg_value: float
    stages: list['StageSummary']
    conversion_rate: float  # % от первого до закрытия
    avg_cycle_days: float  # средний цикл сделки

class StageSummary(BaseModel):
    stage_id: int
    stage_name: str
    leads_count: int
    total_value: float
    avg_value: float
    conversion_to_next: float  # % перехода на следующий этап
```

### 4.2 Manager Performance

```python
class ManagerPerformance(BaseModel):
    user_id: int
    user_name: str
    period: str  # 'day', 'week', 'month', 'quarter', 'year'
    
    # Leads
    leads_created: int
    leads_won: int
    leads_lost: int
    win_rate: float
    
    # Revenue
    total_revenue: float
    avg_deal_size: float
    
    # Activity
    tasks_completed: int
    calls_made: int
    meetings_held: int
    
    # Efficiency
    avg_response_time_hours: float
    avg_cycle_days: float
```

### 4.3 Sales Forecast

```python
class SalesForecast(BaseModel):
    period: str
    forecast_date: datetime
    
    # Прогноз
    expected_revenue: float
    optimistic_revenue: float
    pessimistic_revenue: float
    
    # На основе
    deals_in_pipeline: int
    weighted_pipeline_value: float
    historical_conversion_rate: float
    
    # По этапам
    by_stage: list['StageForecast']

class StageForecast(BaseModel):
    stage_id: int
    stage_name: str
    deals_count: int
    total_value: float
    probability: float  # вероятность закрытия
    expected_value: float  # value * probability
```

### 4.4 Funnel Analysis

```python
class FunnelAnalysis(BaseModel):
    pipeline_id: int
    pipeline_name: str
    period_start: datetime
    period_end: datetime
    
    stages: list['FunnelStage']
    overall_conversion: float
    avg_time_to_close_days: float

class FunnelStage(BaseModel):
    stage_id: int
    stage_name: str
    sort: int
    
    entered: int  # вошло на этап
    exited_to_next: int  # перешло на следующий
    exited_to_won: int  # закрыто успешно
    exited_to_lost: int  # закрыто неуспешно
    still_on_stage: int  # осталось на этапе
    
    conversion_rate: float
    avg_time_on_stage_days: float
```

### 4.5 Cohort Analysis

```python
class CohortAnalysis(BaseModel):
    cohort_type: str  # 'week', 'month'
    metric: str  # 'conversion', 'revenue', 'retention'
    
    cohorts: list['Cohort']

class Cohort(BaseModel):
    cohort_period: str  # '2024-01', '2024-W01'
    initial_count: int
    
    periods: list['CohortPeriod']

class CohortPeriod(BaseModel):
    period_number: int  # 0, 1, 2, ...
    value: float  # метрика
    percentage: float  # % от initial
```

---

## 5. Query Models

### 5.1 Filter Models

```python
class LeadsFilter(BaseModel):
    ids: list[int] | None = None
    query: str | None = None  # текстовый поиск
    pipeline_id: int | None = None
    status_ids: list[int] | None = None
    responsible_user_ids: list[int] | None = None
    created_at_from: datetime | None = None
    created_at_to: datetime | None = None
    updated_at_from: datetime | None = None
    updated_at_to: datetime | None = None
    closed_at_from: datetime | None = None
    closed_at_to: datetime | None = None
    price_from: float | None = None
    price_to: float | None = None
    is_deleted: bool = False

class Pagination(BaseModel):
    page: int = 1
    limit: int = 50
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit

class SortOrder(BaseModel):
    field: str = 'created_at'
    direction: str = 'desc'  # 'asc' or 'desc'
```

### 5.2 Analytics Query

```python
class AnalyticsQuery(BaseModel):
    entity_type: str = 'leads'
    
    # Dimensions (GROUP BY)
    group_by: list[str] = []  # 'pipeline', 'status', 'responsible_user', 'month', 'week'
    
    # Metrics (SELECT)
    metrics: list[str] = ['count']  # 'count', 'sum_price', 'avg_price', 'conversion'
    
    # Filters
    filters: LeadsFilter = LeadsFilter()
    
    # Period
    period_start: datetime | None = None
    period_end: datetime | None = None
```

---

## 6. Response Models

### 6.1 Paginated Response

```python
class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    limit: int
    pages: int
    
    @classmethod
    def create(cls, items: list[T], total: int, pagination: Pagination):
        return cls(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            pages=(total + pagination.limit - 1) // pagination.limit
        )
```

### 6.2 Analytics Response

```python
class AnalyticsResponse(BaseModel):
    query: AnalyticsQuery
    executed_at: datetime
    execution_time_ms: int
    
    # Results
    summary: dict[str, float]  # общие метрики
    data: list[dict]  # детальные данные по группам
    
    # Metadata
    total_records_analyzed: int
    data_freshness: datetime  # когда данные были синхронизированы
```

---

## 7. Webhook Models

```python
class WebhookPayload(BaseModel):
    account_id: int
    event: str  # 'lead_added', 'lead_status_changed', etc.
    timestamp: datetime
    
class LeadWebhook(WebhookPayload):
    lead: dict  # raw lead data from Kommo

class ContactWebhook(WebhookPayload):
    contact: dict

class TaskWebhook(WebhookPayload):
    task: dict
```

---

## 8. Миграции (Alembic)

### 8.1 Initial Migration

```python
# migrations/versions/001_initial.py

def upgrade():
    # Users
    op.create_table('users', ...)
    
    # Pipelines & Stages
    op.create_table('pipelines', ...)
    op.create_table('stages', ...)
    
    # Main entities
    op.create_table('leads', ...)
    op.create_table('contacts', ...)
    op.create_table('companies', ...)
    op.create_table('tasks', ...)
    op.create_table('notes', ...)
    
    # Association tables
    op.create_table('lead_contacts', ...)
    op.create_table('lead_companies', ...)
    op.create_table('contact_companies', ...)
    
    # Custom fields metadata
    op.create_table('custom_fields', ...)
    
    # Indexes
    ...

def downgrade():
    op.drop_table('custom_fields')
    op.drop_table('contact_companies')
    op.drop_table('lead_companies')
    op.drop_table('lead_contacts')
    op.drop_table('notes')
    op.drop_table('tasks')
    op.drop_table('companies')
    op.drop_table('contacts')
    op.drop_table('leads')
    op.drop_table('stages')
    op.drop_table('pipelines')
    op.drop_table('users')
```

---

## 9. Индексы для аналитики

```sql
-- Составные индексы для частых аналитических запросов

-- Аналитика по воронке за период
CREATE INDEX ix_leads_pipeline_created ON leads(pipeline_id, kommo_created_at);

-- Аналитика по менеджерам
CREATE INDEX ix_leads_responsible_closed ON leads(responsible_user_id, closed_at) 
WHERE closed_at IS NOT NULL;

-- Конверсия по этапам
CREATE INDEX ix_leads_status_updated ON leads(status_id, kommo_updated_at);

-- Поиск по кастомным полям (GIN для JSON)
CREATE INDEX ix_leads_custom_fields ON leads USING GIN (custom_fields);
CREATE INDEX ix_contacts_custom_fields ON contacts USING GIN (custom_fields);
```
