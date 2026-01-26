"""Analytics Engine - Core analytics functionality."""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kommo_mcp.analytics.models import (
    ActivityReport,
    FunnelAnalysis,
    FunnelStage,
    ManagerPerformance,
    PipelineSummary,
    RevenuePeriod,
    SalesForecast,
    StageForecast,
    StageSummary,
)
from kommo_mcp.db.models import (
    CompanyDB,
    ContactDB,
    LeadDB,
    NoteDB,
    PipelineDB,
    StageDB,
    TaskDB,
    UserDB,
)

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """
    Analytics Engine for Kommo CRM data.
    
    Performs all heavy computations in PostgreSQL, not in Python memory.
    This is critical for handling large datasets efficiently.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def pipeline_summary(
        self,
        pipeline_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> PipelineSummary | list[PipelineSummary]:
        """
        Get pipeline analytics summary.
        
        Args:
            pipeline_id: Specific pipeline ID (all pipelines if None)
            date_from: Filter leads created from this date
            date_to: Filter leads created until this date
        
        Returns:
            PipelineSummary or list of summaries for all pipelines
        """
        # Build base query
        query = select(
            LeadDB.pipeline_id,
            PipelineDB.name.label('pipeline_name'),
            func.count(LeadDB.id).label('total_leads'),
            func.sum(LeadDB.price).label('total_value'),
            func.avg(LeadDB.price).label('avg_value'),
        ).join(
            PipelineDB, LeadDB.pipeline_id == PipelineDB.id
        ).where(
            LeadDB.is_deleted == False  # noqa: E712
        ).group_by(
            LeadDB.pipeline_id, PipelineDB.name
        )

        # Apply filters
        if pipeline_id:
            query = query.where(LeadDB.pipeline_id == pipeline_id)
        if date_from:
            query = query.where(LeadDB.kommo_created_at >= date_from)
        if date_to:
            query = query.where(LeadDB.kommo_created_at <= date_to)

        result = await self.session.execute(query)
        rows = result.all()

        if not rows:
            if pipeline_id:
                # Return empty summary for specific pipeline
                pipeline = await self.session.get(PipelineDB, pipeline_id)
                return PipelineSummary(
                    pipeline_id=pipeline_id,
                    pipeline_name=pipeline.name if pipeline else 'Unknown',
                    period_start=date_from,
                    period_end=date_to,
                )
            return []

        summaries = []
        for row in rows:
            # Get won/lost/in_progress counts
            status_query = select(
                StageDB.type,
                func.count(LeadDB.id).label('count'),
                func.sum(LeadDB.price).label('value'),
            ).join(
                StageDB, LeadDB.status_id == StageDB.id
            ).where(
                LeadDB.pipeline_id == row.pipeline_id,
                LeadDB.is_deleted == False,  # noqa: E712
            ).group_by(StageDB.type)

            if date_from:
                status_query = status_query.where(LeadDB.kommo_created_at >= date_from)
            if date_to:
                status_query = status_query.where(LeadDB.kommo_created_at <= date_to)

            status_result = await self.session.execute(status_query)
            status_rows = {r.type: (r.count, r.value or 0) for r in status_result.all()}

            won_count, won_value = status_rows.get(2, (0, 0))
            lost_count, _ = status_rows.get(3, (0, 0))
            in_progress = row.total_leads - won_count - lost_count

            # Calculate conversion rate
            closed_total = won_count + lost_count
            conversion_rate = won_count / closed_total if closed_total > 0 else 0.0

            # Get average cycle time for closed deals
            cycle_query = select(
                func.avg(
                    func.extract('epoch', LeadDB.closed_at - LeadDB.kommo_created_at) / 86400
                ).label('avg_cycle')
            ).where(
                LeadDB.pipeline_id == row.pipeline_id,
                LeadDB.closed_at.isnot(None),
                LeadDB.is_deleted == False,  # noqa: E712
            )

            if date_from:
                cycle_query = cycle_query.where(LeadDB.kommo_created_at >= date_from)
            if date_to:
                cycle_query = cycle_query.where(LeadDB.kommo_created_at <= date_to)

            cycle_result = await self.session.execute(cycle_query)
            avg_cycle = cycle_result.scalar() or 0.0

            # Get stage breakdown
            stages = await self._get_stage_distribution(
                row.pipeline_id, date_from, date_to
            )

            summary = PipelineSummary(
                pipeline_id=row.pipeline_id,
                pipeline_name=row.pipeline_name,
                period_start=date_from,
                period_end=date_to,
                total_leads=row.total_leads,
                won_leads=won_count,
                lost_leads=lost_count,
                in_progress=in_progress,
                total_value=float(row.total_value or 0),
                avg_value=float(row.avg_value or 0),
                won_value=float(won_value),
                conversion_rate=conversion_rate,
                avg_cycle_days=float(avg_cycle),
                stages=stages,
            )
            summaries.append(summary)

        if pipeline_id:
            return summaries[0] if summaries else PipelineSummary(
                pipeline_id=pipeline_id,
                pipeline_name='Unknown',
            )
        return summaries

    async def _get_stage_distribution(
        self,
        pipeline_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[StageSummary]:
        """Get lead distribution across pipeline stages."""
        query = select(
            StageDB.id.label('stage_id'),
            StageDB.name.label('stage_name'),
            StageDB.type.label('stage_type'),
            StageDB.sort,
            func.count(LeadDB.id).label('leads_count'),
            func.sum(LeadDB.price).label('total_value'),
            func.avg(LeadDB.price).label('avg_value'),
        ).outerjoin(
            LeadDB,
            (LeadDB.status_id == StageDB.id) & (LeadDB.is_deleted == False)  # noqa: E712
        ).where(
            StageDB.pipeline_id == pipeline_id
        ).group_by(
            StageDB.id, StageDB.name, StageDB.type, StageDB.sort
        ).order_by(StageDB.sort)

        if date_from:
            query = query.where(
                (LeadDB.kommo_created_at >= date_from) | (LeadDB.id.is_(None))
            )
        if date_to:
            query = query.where(
                (LeadDB.kommo_created_at <= date_to) | (LeadDB.id.is_(None))
            )

        result = await self.session.execute(query)
        rows = result.all()

        stages = []
        total_leads = sum(r.leads_count or 0 for r in rows)

        for i, row in enumerate(rows):
            # Calculate conversion to next stage
            next_stages_count = sum(
                r.leads_count or 0 for r in rows[i + 1:]
            ) if i < len(rows) - 1 else 0
            
            current_count = row.leads_count or 0
            conversion = next_stages_count / current_count if current_count > 0 else 0.0

            stages.append(StageSummary(
                stage_id=row.stage_id,
                stage_name=row.stage_name,
                stage_type=row.stage_type,
                leads_count=current_count,
                total_value=float(row.total_value or 0),
                avg_value=float(row.avg_value or 0),
                conversion_to_next=conversion,
            ))

        return stages

    async def manager_performance(
        self,
        user_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        top_n: int | None = None,
    ) -> list[ManagerPerformance]:
        """
        Get manager performance metrics.
        
        Args:
            user_id: Specific user ID (all users if None)
            date_from: Filter by lead creation date
            date_to: Filter by lead creation date
            top_n: Return only top N managers by revenue
        
        Returns:
            List of ManagerPerformance objects
        """
        # Lead metrics query
        lead_query = select(
            LeadDB.responsible_user_id.label('user_id'),
            UserDB.name.label('user_name'),
            func.count(LeadDB.id).label('leads_created'),
            func.count(LeadDB.id).filter(StageDB.type == 2).label('leads_won'),
            func.count(LeadDB.id).filter(StageDB.type == 3).label('leads_lost'),
            func.count(LeadDB.id).filter(StageDB.type.notin_([2, 3])).label('leads_in_progress'),
            func.sum(LeadDB.price).filter(StageDB.type == 2).label('total_revenue'),
            func.avg(LeadDB.price).filter(StageDB.type == 2).label('avg_deal_size'),
            func.avg(
                func.extract('epoch', LeadDB.closed_at - LeadDB.kommo_created_at) / 86400
            ).filter(LeadDB.closed_at.isnot(None)).label('avg_cycle_days'),
        ).join(
            UserDB, LeadDB.responsible_user_id == UserDB.id
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).where(
            LeadDB.is_deleted == False,  # noqa: E712
            LeadDB.responsible_user_id.isnot(None),
        ).group_by(
            LeadDB.responsible_user_id, UserDB.name
        )

        if user_id:
            lead_query = lead_query.where(LeadDB.responsible_user_id == user_id)
        if date_from:
            lead_query = lead_query.where(LeadDB.kommo_created_at >= date_from)
        if date_to:
            lead_query = lead_query.where(LeadDB.kommo_created_at <= date_to)

        # Order by revenue and limit
        lead_query = lead_query.order_by(func.sum(LeadDB.price).filter(StageDB.type == 2).desc().nullslast())
        if top_n:
            lead_query = lead_query.limit(top_n)

        result = await self.session.execute(lead_query)
        lead_rows = result.all()

        performances = []
        for row in lead_rows:
            # Get task metrics for this user
            task_query = select(
                func.count(TaskDB.id).label('total_tasks'),
                func.count(TaskDB.id).filter(TaskDB.is_completed == True).label('completed'),  # noqa: E712
                func.count(TaskDB.id).filter(
                    TaskDB.is_completed == False,  # noqa: E712
                    TaskDB.complete_till < datetime.now()
                ).label('overdue'),
            ).where(
                TaskDB.responsible_user_id == row.user_id
            )

            if date_from:
                task_query = task_query.where(TaskDB.kommo_created_at >= date_from)
            if date_to:
                task_query = task_query.where(TaskDB.kommo_created_at <= date_to)

            task_result = await self.session.execute(task_query)
            task_row = task_result.one()

            # Calculate win rate
            closed = row.leads_won + row.leads_lost
            win_rate = row.leads_won / closed if closed > 0 else 0.0

            performances.append(ManagerPerformance(
                user_id=row.user_id,
                user_name=row.user_name,
                leads_created=row.leads_created,
                leads_won=row.leads_won,
                leads_lost=row.leads_lost,
                leads_in_progress=row.leads_in_progress,
                win_rate=win_rate,
                total_revenue=float(row.total_revenue or 0),
                avg_deal_size=float(row.avg_deal_size or 0),
                tasks_completed=task_row.completed or 0,
                tasks_overdue=task_row.overdue or 0,
                avg_cycle_days=float(row.avg_cycle_days or 0),
            ))

        return performances

    async def sales_forecast(
        self,
        pipeline_id: int | None = None,
        forecast_days: int = 30,
        method: str = 'weighted',
    ) -> SalesForecast:
        """
        Generate sales forecast based on current pipeline.
        
        Args:
            pipeline_id: Specific pipeline (all if None)
            forecast_days: Forecast horizon in days
            method: Forecasting method ('weighted', 'historical', 'optimistic')
        
        Returns:
            SalesForecast with projections
        """
        # Get current deals in pipeline (not closed)
        query = select(
            StageDB.id.label('stage_id'),
            StageDB.name.label('stage_name'),
            StageDB.sort,
            StageDB.type,
            func.count(LeadDB.id).label('deals_count'),
            func.sum(LeadDB.price).label('total_value'),
        ).join(
            LeadDB, LeadDB.status_id == StageDB.id
        ).where(
            LeadDB.is_deleted == False,  # noqa: E712
            StageDB.type.notin_([2, 3]),  # Not won or lost
        ).group_by(
            StageDB.id, StageDB.name, StageDB.sort, StageDB.type
        ).order_by(StageDB.sort)

        if pipeline_id:
            query = query.where(LeadDB.pipeline_id == pipeline_id)

        result = await self.session.execute(query)
        stages = result.all()

        # Get historical conversion rates (last 90 days)
        hist_query = select(
            StageDB.sort,
            func.count(LeadDB.id).filter(StageDB.type == 2).label('won'),
            func.count(LeadDB.id).label('total'),
        ).join(
            LeadDB, LeadDB.status_id == StageDB.id
        ).where(
            LeadDB.closed_at >= datetime.now() - timedelta(days=90),
            LeadDB.is_deleted == False,  # noqa: E712
        ).group_by(StageDB.sort)

        if pipeline_id:
            hist_query = hist_query.where(LeadDB.pipeline_id == pipeline_id)

        hist_result = await self.session.execute(hist_query)
        historical = {r.sort: r.won / r.total if r.total > 0 else 0.3 for r in hist_result.all()}

        # Calculate forecast
        stage_forecasts = []
        total_expected = 0.0
        total_optimistic = 0.0
        total_pessimistic = 0.0
        total_deals = 0

        max_sort = max((s.sort for s in stages), default=1)

        for stage in stages:
            # Determine probability based on method
            if method == 'weighted':
                # Higher stages = higher probability
                probability = min(0.1 + (stage.sort / max_sort) * 0.7, 0.9)
            elif method == 'historical':
                probability = historical.get(stage.sort, 0.3)
            else:  # optimistic
                probability = min(0.2 + (stage.sort / max_sort) * 0.75, 0.95)

            value = float(stage.total_value or 0)
            expected = value * probability

            stage_forecasts.append(StageForecast(
                stage_id=stage.stage_id,
                stage_name=stage.stage_name,
                deals_count=stage.deals_count,
                total_value=value,
                probability=probability,
                expected_value=expected,
            ))

            total_expected += expected
            total_optimistic += value * min(probability * 1.3, 1.0)
            total_pessimistic += value * probability * 0.7
            total_deals += stage.deals_count

        return SalesForecast(
            period=f'{forecast_days} days',
            forecast_date=datetime.now(),
            expected_revenue=total_expected,
            optimistic_revenue=total_optimistic,
            pessimistic_revenue=total_pessimistic,
            deals_in_pipeline=total_deals,
            weighted_pipeline_value=total_expected,
            by_stage=stage_forecasts,
        )

    async def revenue_by_period(
        self,
        group_by: str = 'month',
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        pipeline_id: int | None = None,
        compare_previous: bool = False,
    ) -> list[RevenuePeriod]:
        """
        Get revenue breakdown by time periods.
        
        Args:
            group_by: Grouping period ('day', 'week', 'month', 'quarter')
            date_from: Start date
            date_to: End date
            pipeline_id: Filter by pipeline
            compare_previous: Include comparison with previous period
        
        Returns:
            List of RevenuePeriod objects
        """
        # Determine date truncation
        trunc_map = {
            'day': 'day',
            'week': 'week',
            'month': 'month',
            'quarter': 'quarter',
        }
        trunc = trunc_map.get(group_by, 'month')

        # Build query
        query = select(
            func.date_trunc(trunc, LeadDB.closed_at).label('period'),
            func.count(LeadDB.id).label('leads_won'),
            func.sum(LeadDB.price).label('revenue'),
            func.avg(LeadDB.price).label('avg_deal_size'),
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).where(
            LeadDB.is_deleted == False,  # noqa: E712
            StageDB.type == 2,  # Won deals only
            LeadDB.closed_at.isnot(None),
        ).group_by(
            func.date_trunc(trunc, LeadDB.closed_at)
        ).order_by(
            func.date_trunc(trunc, LeadDB.closed_at)
        )

        if pipeline_id:
            query = query.where(LeadDB.pipeline_id == pipeline_id)
        if date_from:
            query = query.where(LeadDB.closed_at >= date_from)
        if date_to:
            query = query.where(LeadDB.closed_at <= date_to)

        result = await self.session.execute(query)
        rows = result.all()

        periods = []
        prev_revenue = None

        for row in rows:
            period_start = row.period
            
            # Calculate period end based on grouping
            if group_by == 'day':
                period_end = period_start + timedelta(days=1)
                period_str = period_start.strftime('%Y-%m-%d')
            elif group_by == 'week':
                period_end = period_start + timedelta(weeks=1)
                period_str = period_start.strftime('%Y-W%W')
            elif group_by == 'quarter':
                # Approximate quarter end
                period_end = period_start + timedelta(days=90)
                quarter = (period_start.month - 1) // 3 + 1
                period_str = f'{period_start.year}-Q{quarter}'
            else:  # month
                # Next month
                if period_start.month == 12:
                    period_end = period_start.replace(year=period_start.year + 1, month=1)
                else:
                    period_end = period_start.replace(month=period_start.month + 1)
                period_str = period_start.strftime('%Y-%m')

            revenue = float(row.revenue or 0)
            
            # Calculate change from previous period
            revenue_change = None
            revenue_change_pct = None
            if compare_previous and prev_revenue is not None:
                revenue_change = revenue - prev_revenue
                revenue_change_pct = (revenue_change / prev_revenue * 100) if prev_revenue > 0 else None

            periods.append(RevenuePeriod(
                period=period_str,
                period_start=period_start,
                period_end=period_end,
                leads_won=row.leads_won,
                revenue=revenue,
                avg_deal_size=float(row.avg_deal_size or 0),
                revenue_change=revenue_change,
                revenue_change_pct=revenue_change_pct,
            ))

            prev_revenue = revenue

        return periods

    async def activity_report(
        self,
        user_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ActivityReport:
        """
        Get activity report (tasks, calls, notes).
        
        Args:
            user_id: Filter by user
            date_from: Start date
            date_to: End date
        
        Returns:
            ActivityReport with activity metrics
        """
        # Task metrics
        task_query = select(
            func.count(TaskDB.id).label('total'),
            func.count(TaskDB.id).filter(TaskDB.is_completed == True).label('completed'),  # noqa: E712
            func.count(TaskDB.id).filter(
                TaskDB.is_completed == False,  # noqa: E712
                TaskDB.complete_till < datetime.now()
            ).label('overdue'),
            func.count(TaskDB.id).filter(TaskDB.task_type_id == 1).label('calls'),
            func.count(TaskDB.id).filter(TaskDB.task_type_id == 2).label('meetings'),
        )

        if user_id:
            task_query = task_query.where(TaskDB.responsible_user_id == user_id)
        if date_from:
            task_query = task_query.where(TaskDB.kommo_created_at >= date_from)
        if date_to:
            task_query = task_query.where(TaskDB.kommo_created_at <= date_to)

        task_result = await self.session.execute(task_query)
        task_row = task_result.one()

        # Note metrics
        note_query = select(func.count(NoteDB.id).label('notes'))

        if user_id:
            note_query = note_query.where(NoteDB.responsible_user_id == user_id)
        if date_from:
            note_query = note_query.where(NoteDB.kommo_created_at >= date_from)
        if date_to:
            note_query = note_query.where(NoteDB.kommo_created_at <= date_to)

        note_result = await self.session.execute(note_query)
        notes_count = note_result.scalar() or 0

        # By user breakdown
        by_user_query = select(
            TaskDB.responsible_user_id,
            UserDB.name,
            func.count(TaskDB.id).label('tasks'),
            func.count(TaskDB.id).filter(TaskDB.is_completed == True).label('completed'),  # noqa: E712
        ).join(
            UserDB, TaskDB.responsible_user_id == UserDB.id
        ).group_by(
            TaskDB.responsible_user_id, UserDB.name
        ).order_by(func.count(TaskDB.id).desc())

        if date_from:
            by_user_query = by_user_query.where(TaskDB.kommo_created_at >= date_from)
        if date_to:
            by_user_query = by_user_query.where(TaskDB.kommo_created_at <= date_to)

        by_user_result = await self.session.execute(by_user_query)
        by_user = [
            {
                'user_id': r.responsible_user_id,
                'user_name': r.name,
                'tasks': r.tasks,
                'completed': r.completed,
            }
            for r in by_user_result.all()
        ]

        return ActivityReport(
            period_start=date_from,
            period_end=date_to,
            total_tasks=task_row.total or 0,
            completed_tasks=task_row.completed or 0,
            overdue_tasks=task_row.overdue or 0,
            calls_made=task_row.calls or 0,
            meetings_held=task_row.meetings or 0,
            notes_added=notes_count,
            by_user=by_user,
        )
