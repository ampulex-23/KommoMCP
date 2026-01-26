# Analytics Engine Specification

> Software Design Document — Аналитический движок (ключевой компонент)

## 1. Обзор

### 1.1 Назначение
Analytics Engine — центральный компонент для работы с большими объемами данных CRM. Выполняет агрегации, прогнозы и аналитику **в PostgreSQL**, не загружая миллионы записей в контекст LLM.

### 1.2 Принципы
- **Database-first** — вся тяжелая работа в PostgreSQL
- **Incremental** — инкрементальная синхронизация данных
- **Cached** — кэширование частых запросов
- **Async** — неблокирующие операции

### 1.3 Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Analytics Engine                          │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                   Query Builder                          ││
│  │  • Builds SQL from AnalyticsQuery                       ││
│  │  • Validates dimensions and metrics                     ││
│  │  • Applies filters and date ranges                      ││
│  └─────────────────────────────────────────────────────────┘│
│                            │                                 │
│  ┌─────────────────────────┴───────────────────────────────┐│
│  │                  Analytics Functions                     ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ ││
│  │  │ Pipeline │ │ Manager  │ │  Funnel  │ │  Forecast  │ ││
│  │  │ Summary  │ │  Stats   │ │ Analysis │ │   Engine   │ ││
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘ ││
│  └─────────────────────────────────────────────────────────┘│
│                            │                                 │
│  ┌─────────────────────────┴───────────────────────────────┐│
│  │                   Data Layer                             ││
│  │  • PostgreSQL async queries                             ││
│  │  • Pandas for post-processing                           ││
│  │  • Result caching                                       ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Core Components

### 2.1 AnalyticsEngine Class

```python
from datetime import datetime, timedelta
from typing import Any
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func

class AnalyticsEngine:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.cache = AnalyticsCache()
    
    # === Pipeline Analytics ===
    
    async def pipeline_summary(
        self,
        pipeline_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None
    ) -> PipelineSummary:
        '''Сводка по воронке'''
        
    async def stage_distribution(
        self,
        pipeline_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None
    ) -> list[StageSummary]:
        '''Распределение по этапам'''
    
    # === Conversion Analytics ===
    
    async def funnel_conversion(
        self,
        pipeline_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None
    ) -> FunnelAnalysis:
        '''Конверсия воронки'''
        
    async def stage_transitions(
        self,
        pipeline_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None
    ) -> list[StageTransition]:
        '''Переходы между этапами'''
    
    # === Manager Analytics ===
    
    async def manager_performance(
        self,
        user_id: int | None = None,
        period: str = 'month',
        date_from: datetime | None = None,
        date_to: datetime | None = None
    ) -> list[ManagerPerformance]:
        '''Статистика менеджеров'''
        
    async def manager_ranking(
        self,
        metric: str = 'revenue',
        period: str = 'month',
        top_n: int = 10
    ) -> list[ManagerRanking]:
        '''Рейтинг менеджеров'''
    
    # === Revenue Analytics ===
    
    async def revenue_by_period(
        self,
        group_by: str = 'month',
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        pipeline_id: int | None = None
    ) -> list[RevenuePeriod]:
        '''Выручка по периодам'''
        
    async def revenue_forecast(
        self,
        forecast_days: int = 30,
        method: str = 'weighted'
    ) -> SalesForecast:
        '''Прогноз выручки'''
    
    # === Cohort Analytics ===
    
    async def cohort_analysis(
        self,
        cohort_type: str = 'month',
        metric: str = 'conversion',
        periods: int = 6
    ) -> CohortAnalysis:
        '''Когортный анализ'''
    
    # === Custom Queries ===
    
    async def custom_aggregate(
        self,
        query: AnalyticsQuery
    ) -> AnalyticsResponse:
        '''Кастомный аналитический запрос'''
```

### 2.2 Query Builder

```python
class QueryBuilder:
    '''Построитель SQL запросов для аналитики'''
    
    DIMENSIONS = {
        'pipeline': 'p.name',
        'status': 's.name',
        'responsible_user': 'u.name',
        'month': "DATE_TRUNC('month', l.kommo_created_at)",
        'week': "DATE_TRUNC('week', l.kommo_created_at)",
        'day': "DATE_TRUNC('day', l.kommo_created_at)",
        'quarter': "DATE_TRUNC('quarter', l.kommo_created_at)",
    }
    
    METRICS = {
        'count': 'COUNT(*)',
        'sum_price': 'SUM(l.price)',
        'avg_price': 'AVG(l.price)',
        'min_price': 'MIN(l.price)',
        'max_price': 'MAX(l.price)',
        'won_count': "COUNT(*) FILTER (WHERE s.type = 2)",
        'lost_count': "COUNT(*) FILTER (WHERE s.type = 3)",
        'conversion': "COUNT(*) FILTER (WHERE s.type = 2)::float / NULLIF(COUNT(*), 0)",
    }
    
    def build(self, query: AnalyticsQuery) -> str:
        '''Построить SQL запрос'''
        
        select_parts = []
        
        # Dimensions
        for dim in query.group_by:
            if dim in self.DIMENSIONS:
                select_parts.append(f'{self.DIMENSIONS[dim]} AS {dim}')
        
        # Metrics
        for metric in query.metrics:
            if metric in self.METRICS:
                select_parts.append(f'{self.METRICS[metric]} AS {metric}')
        
        # Build query
        sql = f'''
            SELECT {', '.join(select_parts)}
            FROM leads l
            JOIN pipelines p ON l.pipeline_id = p.id
            JOIN stages s ON l.status_id = s.id
            LEFT JOIN users u ON l.responsible_user_id = u.id
            WHERE 1=1
        '''
        
        # Apply filters
        sql += self._build_filters(query.filters)
        
        # Group by
        if query.group_by:
            group_cols = [self.DIMENSIONS[d] for d in query.group_by if d in self.DIMENSIONS]
            sql += f' GROUP BY {", ".join(group_cols)}'
        
        # Order
        sql += ' ORDER BY 1'
        
        return sql
    
    def _build_filters(self, filters: LeadsFilter) -> str:
        conditions = []
        
        if filters.pipeline_id:
            conditions.append(f'l.pipeline_id = {filters.pipeline_id}')
        
        if filters.status_ids:
            ids = ','.join(map(str, filters.status_ids))
            conditions.append(f'l.status_id IN ({ids})')
        
        if filters.responsible_user_ids:
            ids = ','.join(map(str, filters.responsible_user_ids))
            conditions.append(f'l.responsible_user_id IN ({ids})')
        
        if filters.created_at_from:
            conditions.append(f"l.kommo_created_at >= '{filters.created_at_from}'")
        
        if filters.created_at_to:
            conditions.append(f"l.kommo_created_at <= '{filters.created_at_to}'")
        
        if filters.is_deleted is not None:
            conditions.append(f'l.is_deleted = {filters.is_deleted}')
        
        return ' AND '.join(conditions) if conditions else ''
```

---

## 3. Analytics Functions

### 3.1 Pipeline Summary

```python
async def pipeline_summary(
    self,
    pipeline_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None
) -> PipelineSummary:
    '''
    Сводка по воронке:
    - Общее количество сделок
    - Сумма и средний чек
    - Выигранные/проигранные
    - Конверсия
    - Средний цикл сделки
    '''
    
    sql = '''
        WITH lead_stats AS (
            SELECT
                l.pipeline_id,
                p.name as pipeline_name,
                COUNT(*) as total_leads,
                SUM(l.price) as total_value,
                AVG(l.price) as avg_value,
                COUNT(*) FILTER (WHERE s.type = 2) as won_leads,
                COUNT(*) FILTER (WHERE s.type = 3) as lost_leads,
                COUNT(*) FILTER (WHERE s.type NOT IN (2, 3)) as in_progress,
                AVG(
                    EXTRACT(EPOCH FROM (l.closed_at - l.kommo_created_at)) / 86400
                ) FILTER (WHERE l.closed_at IS NOT NULL) as avg_cycle_days
            FROM leads l
            JOIN pipelines p ON l.pipeline_id = p.id
            JOIN stages s ON l.status_id = s.id
            WHERE l.is_deleted = false
            {pipeline_filter}
            {date_filter}
            GROUP BY l.pipeline_id, p.name
        )
        SELECT
            pipeline_id,
            pipeline_name,
            total_leads,
            total_value,
            avg_value,
            won_leads,
            lost_leads,
            in_progress,
            CASE 
                WHEN (won_leads + lost_leads) > 0 
                THEN won_leads::float / (won_leads + lost_leads)
                ELSE 0 
            END as conversion_rate,
            COALESCE(avg_cycle_days, 0) as avg_cycle_days
        FROM lead_stats
    '''
    
    # Apply filters
    pipeline_filter = f'AND l.pipeline_id = {pipeline_id}' if pipeline_id else ''
    date_filter = self._build_date_filter(date_from, date_to)
    
    sql = sql.format(pipeline_filter=pipeline_filter, date_filter=date_filter)
    
    result = await self.session.execute(text(sql))
    row = result.fetchone()
    
    if not row:
        raise NotFoundError('Pipeline not found')
    
    # Get stage distribution
    stages = await self.stage_distribution(pipeline_id, date_from, date_to)
    
    return PipelineSummary(
        pipeline_id=row.pipeline_id,
        pipeline_name=row.pipeline_name,
        total_leads=row.total_leads,
        total_value=float(row.total_value or 0),
        avg_value=float(row.avg_value or 0),
        won_leads=row.won_leads,
        lost_leads=row.lost_leads,
        in_progress=row.in_progress,
        conversion_rate=float(row.conversion_rate),
        avg_cycle_days=float(row.avg_cycle_days),
        stages=stages
    )
```

### 3.2 Funnel Conversion

```python
async def funnel_conversion(
    self,
    pipeline_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None
) -> FunnelAnalysis:
    '''
    Анализ конверсии воронки:
    - Сколько вошло на каждый этап
    - Сколько перешло на следующий
    - Сколько закрылось успешно/неуспешно
    - Среднее время на этапе
    '''
    
    # Получаем этапы воронки
    stages_sql = '''
        SELECT id, name, sort, type
        FROM stages
        WHERE pipeline_id = :pipeline_id
        ORDER BY sort
    '''
    stages_result = await self.session.execute(
        text(stages_sql), 
        {'pipeline_id': pipeline_id}
    )
    stages = stages_result.fetchall()
    
    # Для каждого этапа считаем метрики
    # Используем events или историю изменений статусов
    funnel_sql = '''
        WITH stage_entries AS (
            -- Считаем входы на этапы через события
            SELECT
                e.entity_id as lead_id,
                (e.value_after->0->>'leads_statuses')::int as stage_id,
                e.created_at as entered_at
            FROM events e
            WHERE e.entity_type = 'leads'
            AND e.type = 'lead_status_changed'
            AND EXISTS (
                SELECT 1 FROM leads l 
                WHERE l.id = e.entity_id 
                AND l.pipeline_id = :pipeline_id
                {date_filter}
            )
        ),
        stage_stats AS (
            SELECT
                s.id as stage_id,
                s.name as stage_name,
                s.sort,
                s.type,
                COUNT(DISTINCT se.lead_id) as entered,
                AVG(
                    EXTRACT(EPOCH FROM (
                        LEAD(se.entered_at) OVER (
                            PARTITION BY se.lead_id ORDER BY se.entered_at
                        ) - se.entered_at
                    )) / 86400
                ) as avg_time_on_stage_days
            FROM stages s
            LEFT JOIN stage_entries se ON s.id = se.stage_id
            WHERE s.pipeline_id = :pipeline_id
            GROUP BY s.id, s.name, s.sort, s.type
        )
        SELECT * FROM stage_stats ORDER BY sort
    '''
    
    date_filter = self._build_date_filter(date_from, date_to, 'l.kommo_created_at')
    sql = funnel_sql.format(date_filter=date_filter)
    
    result = await self.session.execute(text(sql), {'pipeline_id': pipeline_id})
    rows = result.fetchall()
    
    funnel_stages = []
    for i, row in enumerate(rows):
        next_entered = rows[i + 1].entered if i + 1 < len(rows) else 0
        
        funnel_stages.append(FunnelStage(
            stage_id=row.stage_id,
            stage_name=row.stage_name,
            sort=row.sort,
            entered=row.entered,
            exited_to_next=next_entered,
            exited_to_won=row.entered if row.type == 2 else 0,
            exited_to_lost=row.entered if row.type == 3 else 0,
            conversion_rate=next_entered / row.entered if row.entered > 0 else 0,
            avg_time_on_stage_days=float(row.avg_time_on_stage_days or 0)
        ))
    
    # Общая конверсия
    first_stage = funnel_stages[0] if funnel_stages else None
    won_stage = next((s for s in funnel_stages if s.exited_to_won > 0), None)
    
    overall_conversion = 0
    if first_stage and won_stage and first_stage.entered > 0:
        overall_conversion = won_stage.exited_to_won / first_stage.entered
    
    return FunnelAnalysis(
        pipeline_id=pipeline_id,
        pipeline_name=stages[0].name if stages else '',
        period_start=date_from,
        period_end=date_to,
        stages=funnel_stages,
        overall_conversion=overall_conversion
    )
```

### 3.3 Manager Performance

```python
async def manager_performance(
    self,
    user_id: int | None = None,
    period: str = 'month',
    date_from: datetime | None = None,
    date_to: datetime | None = None
) -> list[ManagerPerformance]:
    '''
    Статистика эффективности менеджеров:
    - Созданные/выигранные/проигранные сделки
    - Win rate
    - Выручка
    - Активность (задачи, звонки)
    '''
    
    sql = '''
        WITH manager_leads AS (
            SELECT
                l.responsible_user_id as user_id,
                u.name as user_name,
                COUNT(*) as leads_created,
                COUNT(*) FILTER (WHERE s.type = 2) as leads_won,
                COUNT(*) FILTER (WHERE s.type = 3) as leads_lost,
                SUM(l.price) FILTER (WHERE s.type = 2) as total_revenue,
                AVG(l.price) FILTER (WHERE s.type = 2) as avg_deal_size,
                AVG(
                    EXTRACT(EPOCH FROM (l.closed_at - l.kommo_created_at)) / 86400
                ) FILTER (WHERE l.closed_at IS NOT NULL) as avg_cycle_days
            FROM leads l
            JOIN stages s ON l.status_id = s.id
            JOIN users u ON l.responsible_user_id = u.id
            WHERE l.is_deleted = false
            {user_filter}
            {date_filter}
            GROUP BY l.responsible_user_id, u.name
        ),
        manager_tasks AS (
            SELECT
                t.responsible_user_id as user_id,
                COUNT(*) FILTER (WHERE t.is_completed = true) as tasks_completed,
                COUNT(*) FILTER (WHERE t.task_type_id = 1 AND t.is_completed = true) as calls_made,
                COUNT(*) FILTER (WHERE t.task_type_id = 2 AND t.is_completed = true) as meetings_held
            FROM tasks t
            WHERE 1=1
            {user_filter_tasks}
            {date_filter_tasks}
            GROUP BY t.responsible_user_id
        )
        SELECT
            ml.user_id,
            ml.user_name,
            ml.leads_created,
            ml.leads_won,
            ml.leads_lost,
            CASE 
                WHEN (ml.leads_won + ml.leads_lost) > 0 
                THEN ml.leads_won::float / (ml.leads_won + ml.leads_lost)
                ELSE 0 
            END as win_rate,
            COALESCE(ml.total_revenue, 0) as total_revenue,
            COALESCE(ml.avg_deal_size, 0) as avg_deal_size,
            COALESCE(mt.tasks_completed, 0) as tasks_completed,
            COALESCE(mt.calls_made, 0) as calls_made,
            COALESCE(mt.meetings_held, 0) as meetings_held,
            COALESCE(ml.avg_cycle_days, 0) as avg_cycle_days
        FROM manager_leads ml
        LEFT JOIN manager_tasks mt ON ml.user_id = mt.user_id
        ORDER BY ml.total_revenue DESC NULLS LAST
    '''
    
    user_filter = f'AND l.responsible_user_id = {user_id}' if user_id else ''
    user_filter_tasks = f'AND t.responsible_user_id = {user_id}' if user_id else ''
    date_filter = self._build_date_filter(date_from, date_to, 'l.kommo_created_at')
    date_filter_tasks = self._build_date_filter(date_from, date_to, 't.kommo_created_at')
    
    sql = sql.format(
        user_filter=user_filter,
        user_filter_tasks=user_filter_tasks,
        date_filter=date_filter,
        date_filter_tasks=date_filter_tasks
    )
    
    result = await self.session.execute(text(sql))
    rows = result.fetchall()
    
    return [
        ManagerPerformance(
            user_id=row.user_id,
            user_name=row.user_name,
            period=period,
            leads_created=row.leads_created,
            leads_won=row.leads_won,
            leads_lost=row.leads_lost,
            win_rate=float(row.win_rate),
            total_revenue=float(row.total_revenue),
            avg_deal_size=float(row.avg_deal_size),
            tasks_completed=row.tasks_completed,
            calls_made=row.calls_made,
            meetings_held=row.meetings_held,
            avg_cycle_days=float(row.avg_cycle_days)
        )
        for row in rows
    ]
```

### 3.4 Sales Forecast

```python
async def revenue_forecast(
    self,
    pipeline_id: int | None = None,
    forecast_days: int = 30,
    method: str = 'weighted'
) -> SalesForecast:
    '''
    Прогноз продаж:
    - weighted: взвешенный по вероятности этапов
    - historical: на основе исторической конверсии
    - optimistic: оптимистичный сценарий
    '''
    
    # Получаем текущие сделки в работе
    pipeline_sql = '''
        SELECT
            s.id as stage_id,
            s.name as stage_name,
            s.sort,
            COUNT(*) as deals_count,
            SUM(l.price) as total_value
        FROM leads l
        JOIN stages s ON l.status_id = s.id
        WHERE l.is_deleted = false
        AND s.type NOT IN (2, 3)  -- не закрытые
        {pipeline_filter}
        GROUP BY s.id, s.name, s.sort
        ORDER BY s.sort
    '''
    
    pipeline_filter = f'AND l.pipeline_id = {pipeline_id}' if pipeline_id else ''
    sql = pipeline_sql.format(pipeline_filter=pipeline_filter)
    
    result = await self.session.execute(text(sql))
    stages = result.fetchall()
    
    # Получаем историческую конверсию по этапам
    conversion_sql = '''
        SELECT
            s.id as stage_id,
            COUNT(*) FILTER (WHERE final_s.type = 2)::float / 
                NULLIF(COUNT(*), 0) as historical_conversion
        FROM leads l
        JOIN stages s ON l.status_id = s.id
        JOIN stages final_s ON l.status_id = final_s.id
        WHERE l.closed_at IS NOT NULL
        AND l.closed_at >= NOW() - INTERVAL '90 days'
        {pipeline_filter}
        GROUP BY s.id
    '''
    
    conv_result = await self.session.execute(
        text(conversion_sql.format(pipeline_filter=pipeline_filter))
    )
    conversions = {row.stage_id: row.historical_conversion for row in conv_result.fetchall()}
    
    # Рассчитываем прогноз
    stage_forecasts = []
    total_expected = 0
    total_optimistic = 0
    total_pessimistic = 0
    
    for stage in stages:
        # Вероятность зависит от этапа (чем дальше, тем выше)
        if method == 'weighted':
            probability = min(0.1 + (stage.sort * 0.15), 0.9)
        elif method == 'historical':
            probability = conversions.get(stage.stage_id, 0.3)
        else:  # optimistic
            probability = min(0.3 + (stage.sort * 0.2), 0.95)
        
        expected = float(stage.total_value or 0) * probability
        total_expected += expected
        total_optimistic += float(stage.total_value or 0) * min(probability * 1.3, 1.0)
        total_pessimistic += float(stage.total_value or 0) * probability * 0.7
        
        stage_forecasts.append(StageForecast(
            stage_id=stage.stage_id,
            stage_name=stage.stage_name,
            deals_count=stage.deals_count,
            total_value=float(stage.total_value or 0),
            probability=probability,
            expected_value=expected
        ))
    
    return SalesForecast(
        period=f'{forecast_days} days',
        forecast_date=datetime.now(),
        expected_revenue=total_expected,
        optimistic_revenue=total_optimistic,
        pessimistic_revenue=total_pessimistic,
        deals_in_pipeline=sum(s.deals_count for s in stages),
        weighted_pipeline_value=total_expected,
        by_stage=stage_forecasts
    )
```

### 3.5 Cohort Analysis

```python
async def cohort_analysis(
    self,
    cohort_type: str = 'month',
    metric: str = 'conversion',
    periods: int = 6
) -> CohortAnalysis:
    '''
    Когортный анализ:
    - Группировка по месяцу/неделе создания
    - Отслеживание метрики во времени
    '''
    
    date_trunc = 'month' if cohort_type == 'month' else 'week'
    
    sql = f'''
        WITH cohorts AS (
            SELECT
                DATE_TRUNC('{date_trunc}', l.kommo_created_at) as cohort_period,
                l.id as lead_id,
                l.kommo_created_at,
                l.closed_at,
                s.type as final_status
            FROM leads l
            JOIN stages s ON l.status_id = s.id
            WHERE l.kommo_created_at >= NOW() - INTERVAL '{periods} {cohort_type}s'
        ),
        cohort_metrics AS (
            SELECT
                cohort_period,
                COUNT(*) as initial_count,
                COUNT(*) FILTER (WHERE final_status = 2) as won_count,
                -- Метрики по периодам после создания
                COUNT(*) FILTER (
                    WHERE closed_at IS NOT NULL 
                    AND closed_at < cohort_period + INTERVAL '1 {cohort_type}'
                ) as period_0,
                COUNT(*) FILTER (
                    WHERE closed_at IS NOT NULL 
                    AND closed_at >= cohort_period + INTERVAL '1 {cohort_type}'
                    AND closed_at < cohort_period + INTERVAL '2 {cohort_type}s'
                ) as period_1,
                COUNT(*) FILTER (
                    WHERE closed_at IS NOT NULL 
                    AND closed_at >= cohort_period + INTERVAL '2 {cohort_type}s'
                    AND closed_at < cohort_period + INTERVAL '3 {cohort_type}s'
                ) as period_2
            FROM cohorts
            GROUP BY cohort_period
            ORDER BY cohort_period
        )
        SELECT * FROM cohort_metrics
    '''
    
    result = await self.session.execute(text(sql))
    rows = result.fetchall()
    
    cohorts = []
    for row in rows:
        periods_data = []
        for i, period_count in enumerate([row.period_0, row.period_1, row.period_2]):
            if metric == 'conversion':
                value = period_count / row.initial_count if row.initial_count > 0 else 0
            else:
                value = period_count
            
            periods_data.append(CohortPeriod(
                period_number=i,
                value=value,
                percentage=value * 100 if metric == 'conversion' else 
                          (period_count / row.initial_count * 100 if row.initial_count > 0 else 0)
            ))
        
        cohorts.append(Cohort(
            cohort_period=row.cohort_period.strftime('%Y-%m' if cohort_type == 'month' else '%Y-W%W'),
            initial_count=row.initial_count,
            periods=periods_data
        ))
    
    return CohortAnalysis(
        cohort_type=cohort_type,
        metric=metric,
        cohorts=cohorts
    )
```

---

## 4. Data Synchronization

### 4.1 Sync Manager

```python
class SyncManager:
    '''Управление синхронизацией данных из Kommo API в PostgreSQL'''
    
    def __init__(
        self,
        api_client: KommoClient,
        session: AsyncSession
    ):
        self.api = api_client
        self.session = session
    
    async def sync_all(self, full: bool = False) -> SyncResult:
        '''Синхронизировать все сущности'''
        results = {}
        
        # Порядок важен из-за зависимостей
        for entity in ['users', 'pipelines', 'leads', 'contacts', 'companies', 'tasks']:
            results[entity] = await self.sync_entity(entity, full)
        
        return SyncResult(entities=results)
    
    async def sync_entity(
        self,
        entity: str,
        full: bool = False
    ) -> EntitySyncResult:
        '''Синхронизировать конкретную сущность'''
        
        # Получаем время последней синхронизации
        last_sync = await self._get_last_sync(entity)
        
        # Определяем фильтр
        if full or not last_sync:
            updated_at_from = None
        else:
            updated_at_from = last_sync
        
        # Получаем данные из API с пагинацией
        total_synced = 0
        async for batch in self.api.iterate_entity(entity, updated_at_from=updated_at_from):
            await self._upsert_batch(entity, batch)
            total_synced += len(batch)
        
        # Обновляем время синхронизации
        await self._update_last_sync(entity)
        
        return EntitySyncResult(
            entity=entity,
            synced_count=total_synced,
            last_sync=datetime.now()
        )
    
    async def _upsert_batch(self, entity: str, batch: list[dict]):
        '''Upsert пакета записей'''
        
        table = self._get_table(entity)
        
        stmt = insert(table).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=['id'],
            set_={
                col.name: col
                for col in stmt.excluded
                if col.name != 'id'
            }
        )
        
        await self.session.execute(stmt)
        await self.session.commit()
```

### 4.2 Incremental Sync Strategy

```python
class IncrementalSyncStrategy:
    '''
    Стратегия инкрементальной синхронизации:
    1. Синхронизируем только измененные записи (updated_at > last_sync)
    2. Используем webhooks для real-time обновлений
    3. Периодическая полная синхронизация для consistency
    '''
    
    SYNC_INTERVALS = {
        'leads': timedelta(minutes=5),      # Часто меняются
        'contacts': timedelta(minutes=15),   # Реже
        'companies': timedelta(minutes=30),  # Еще реже
        'tasks': timedelta(minutes=5),       # Важно для активности
        'pipelines': timedelta(hours=1),     # Редко меняются
        'users': timedelta(hours=6),         # Очень редко
    }
    
    FULL_SYNC_INTERVAL = timedelta(days=1)  # Полная синхронизация раз в день
```

---

## 5. Caching

### 5.1 Analytics Cache

```python
class AnalyticsCache:
    '''Кэширование результатов аналитики'''
    
    # TTL для разных типов запросов
    TTL = {
        'pipeline_summary': 300,      # 5 минут
        'manager_performance': 600,   # 10 минут
        'funnel_analysis': 900,       # 15 минут
        'revenue_forecast': 1800,     # 30 минут
        'cohort_analysis': 3600,      # 1 час
    }
    
    def __init__(self):
        self._cache: dict[str, tuple[Any, datetime]] = {}
    
    def get(self, key: str) -> Any | None:
        if key in self._cache:
            value, expires_at = self._cache[key]
            if datetime.now() < expires_at:
                return value
            del self._cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl_type: str):
        ttl = self.TTL.get(ttl_type, 300)
        expires_at = datetime.now() + timedelta(seconds=ttl)
        self._cache[key] = (value, expires_at)
    
    def invalidate(self, pattern: str = '*'):
        '''Инвалидация кэша по паттерну'''
        if pattern == '*':
            self._cache.clear()
        else:
            keys_to_delete = [k for k in self._cache if pattern in k]
            for k in keys_to_delete:
                del self._cache[k]
```

---

## 6. Performance Optimizations

### 6.1 Materialized Views

```sql
-- Материализованное представление для быстрой аналитики по воронкам
CREATE MATERIALIZED VIEW mv_pipeline_daily_stats AS
SELECT
    DATE_TRUNC('day', l.kommo_created_at) as date,
    l.pipeline_id,
    l.status_id,
    l.responsible_user_id,
    COUNT(*) as leads_count,
    SUM(l.price) as total_value,
    AVG(l.price) as avg_value
FROM leads l
WHERE l.is_deleted = false
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX ON mv_pipeline_daily_stats (date, pipeline_id, status_id, responsible_user_id);

-- Обновление (запускать по расписанию)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_pipeline_daily_stats;
```

### 6.2 Partitioning

```sql
-- Партиционирование таблицы leads по дате создания
CREATE TABLE leads (
    id BIGINT NOT NULL,
    kommo_created_at TIMESTAMP NOT NULL,
    ...
) PARTITION BY RANGE (kommo_created_at);

-- Партиции по месяцам
CREATE TABLE leads_2024_01 PARTITION OF leads
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE leads_2024_02 PARTITION OF leads
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
```

### 6.3 Query Optimization Tips

```python
# Используем EXPLAIN ANALYZE для оптимизации
async def analyze_query(self, sql: str) -> dict:
    result = await self.session.execute(text(f'EXPLAIN ANALYZE {sql}'))
    return {'plan': [row[0] for row in result.fetchall()]}

# Batch processing для больших объемов
async def process_large_dataset(self, query: str, batch_size: int = 10000):
    offset = 0
    while True:
        batch_sql = f'{query} LIMIT {batch_size} OFFSET {offset}'
        result = await self.session.execute(text(batch_sql))
        rows = result.fetchall()
        
        if not rows:
            break
        
        yield rows
        offset += batch_size
```

---

## 7. Error Handling

```python
class AnalyticsError(Exception):
    '''Базовая ошибка аналитики'''
    pass

class SyncRequiredError(AnalyticsError):
    '''Требуется синхронизация данных'''
    pass

class InsufficientDataError(AnalyticsError):
    '''Недостаточно данных для анализа'''
    pass

class QueryTimeoutError(AnalyticsError):
    '''Превышено время выполнения запроса'''
    pass
```
