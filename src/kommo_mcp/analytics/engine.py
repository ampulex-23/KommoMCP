"""Analytics Engine - Core analytics functionality."""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kommo_mcp.analytics.models import (
    ActivityReport,
    ChurnRiskContact,
    ChurnRiskReport,
    DuplicateGroup,
    DuplicatesReport,
    FunnelAnalysis,
    FunnelStage,
    LeadScoreReport,
    LeadSource,
    LeadSourcesReport,
    ManagerPerformance,
    PipelineSummary,
    RevenuePeriod,
    RevenueTrendPeriod,
    RevenueTrendReport,
    SalesForecast,
    ScoredLead,
    StageForecast,
    StageSummary,
    StaleDeal,
    StaleDealsReport,
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
    contact_companies,
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

    async def funnel_analysis(
        self,
        pipeline_id: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> FunnelAnalysis:
        """
        Detailed funnel conversion analysis.
        
        Args:
            pipeline_id: Pipeline to analyze
            date_from: Filter leads created from this date
            date_to: Filter leads created until this date
        
        Returns:
            FunnelAnalysis with stage-by-stage conversion metrics
        """
        # Get pipeline info
        pipeline = await self.session.get(PipelineDB, pipeline_id)
        pipeline_name = pipeline.name if pipeline else 'Unknown'
        
        # Get all stages for this pipeline
        stages_query = select(StageDB).where(
            StageDB.pipeline_id == pipeline_id
        ).order_by(StageDB.sort)
        
        stages_result = await self.session.execute(stages_query)
        stages = stages_result.scalars().all()
        
        # Build base lead filter
        lead_filter = [
            LeadDB.pipeline_id == pipeline_id,
            LeadDB.is_deleted == False,  # noqa: E712
        ]
        if date_from:
            lead_filter.append(LeadDB.kommo_created_at >= date_from)
        if date_to:
            lead_filter.append(LeadDB.kommo_created_at <= date_to)
        
        # Get total leads that entered the funnel
        total_query = select(func.count(LeadDB.id)).where(*lead_filter)
        total_result = await self.session.execute(total_query)
        total_entered = total_result.scalar() or 0
        
        # Get won leads count
        won_query = select(func.count(LeadDB.id)).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).where(*lead_filter, StageDB.type == 2)
        won_result = await self.session.execute(won_query)
        total_won = won_result.scalar() or 0
        
        # Get lost leads count
        lost_query = select(func.count(LeadDB.id)).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).where(*lead_filter, StageDB.type == 3)
        lost_result = await self.session.execute(lost_query)
        total_lost = lost_result.scalar() or 0
        
        # Analyze each stage
        funnel_stages = []
        cumulative_entered = total_entered
        
        for i, stage in enumerate(stages):
            # Count leads currently in this stage
            current_query = select(func.count(LeadDB.id)).where(
                *lead_filter,
                LeadDB.status_id == stage.id
            )
            current_result = await self.session.execute(current_query)
            current_count = current_result.scalar() or 0
            
            # For won/lost stages, use their counts
            if stage.type == 2:  # Won
                exited_to_won = current_count
                exited_to_next = 0
                exited_to_lost = 0
            elif stage.type == 3:  # Lost
                exited_to_lost = current_count
                exited_to_next = 0
                exited_to_won = 0
            else:
                # For regular stages, calculate exits
                # Leads that moved to later stages (including won)
                later_stages = [s.id for s in stages[i+1:] if s.type not in [3]]
                if later_stages:
                    next_query = select(func.count(LeadDB.id)).where(
                        *lead_filter,
                        LeadDB.status_id.in_(later_stages)
                    )
                    next_result = await self.session.execute(next_query)
                    exited_to_next = next_result.scalar() or 0
                else:
                    exited_to_next = 0
                
                exited_to_won = total_won if stage.type != 2 else 0
                exited_to_lost = 0  # Lost from this stage specifically is hard to track
            
            # Calculate conversion rate for this stage
            if cumulative_entered > 0:
                conversion_rate = (cumulative_entered - current_count) / cumulative_entered if stage.type not in [2, 3] else current_count / total_entered
            else:
                conversion_rate = 0.0
            
            # Average time on stage (for closed deals)
            time_query = select(
                func.avg(
                    func.extract('epoch', LeadDB.kommo_updated_at - LeadDB.kommo_created_at) / 86400
                )
            ).where(
                *lead_filter,
                LeadDB.status_id == stage.id
            )
            time_result = await self.session.execute(time_query)
            avg_time = time_result.scalar() or 0.0
            
            funnel_stages.append(FunnelStage(
                stage_id=stage.id,
                stage_name=stage.name,
                sort=stage.sort,
                entered=cumulative_entered if stage.type not in [2, 3] else current_count,
                exited_to_next=exited_to_next,
                exited_to_won=exited_to_won if stage.type == 2 else 0,
                exited_to_lost=exited_to_lost if stage.type == 3 else 0,
                conversion_rate=conversion_rate,
                avg_time_on_stage_days=float(avg_time),
            ))
            
            # Update cumulative for next stage (excluding won/lost)
            if stage.type not in [2, 3]:
                cumulative_entered = cumulative_entered - current_count
        
        # Overall conversion rate
        overall_conversion = total_won / total_entered if total_entered > 0 else 0.0
        
        return FunnelAnalysis(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            period_start=date_from,
            period_end=date_to,
            stages=funnel_stages,
            overall_conversion=overall_conversion,
        )

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

    async def stale_deals(
        self,
        threshold_days: int = 14,
        pipeline_id: int | None = None,
        limit: int = 50,
    ) -> StaleDealsReport:
        """
        Find deals that have been inactive for too long.
        
        Args:
            threshold_days: Number of days without activity to consider stale
            pipeline_id: Filter by pipeline (optional)
            limit: Max number of deals to return
        
        Returns:
            StaleDealsReport with list of stale deals
        """
        threshold_date = datetime.utcnow() - timedelta(days=threshold_days)
        
        # Build query for stale deals (not in won/lost stages)
        query = select(
            LeadDB.id,
            LeadDB.name,
            LeadDB.price,
            LeadDB.kommo_updated_at,
            LeadDB.kommo_created_at,
            PipelineDB.name.label('pipeline_name'),
            StageDB.name.label('stage_name'),
            UserDB.name.label('user_name'),
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).join(
            PipelineDB, LeadDB.pipeline_id == PipelineDB.id
        ).outerjoin(
            UserDB, LeadDB.responsible_user_id == UserDB.id
        ).where(
            LeadDB.is_deleted == False,  # noqa: E712
            LeadDB.kommo_updated_at < threshold_date,
            StageDB.sort < 10000,  # Exclude won/lost stages (sort >= 10000)
        )
        
        if pipeline_id:
            query = query.where(LeadDB.pipeline_id == pipeline_id)
        
        query = query.order_by(LeadDB.kommo_updated_at.asc()).limit(limit)
        
        result = await self.session.execute(query)
        rows = result.all()
        
        deals = []
        by_stage: dict[str, int] = {}
        by_manager: dict[str, int] = {}
        total_value = 0.0
        
        for row in rows:
            days_inactive = (datetime.utcnow() - row.kommo_updated_at).days if row.kommo_updated_at else 0
            
            deals.append(StaleDeal(
                lead_id=row.id,
                lead_name=row.name or 'Без названия',
                pipeline_name=row.pipeline_name,
                stage_name=row.stage_name,
                responsible_user=row.user_name,
                price=float(row.price or 0),
                days_inactive=days_inactive,
                last_activity=row.kommo_updated_at,
                created_at=row.kommo_created_at,
            ))
            
            total_value += float(row.price or 0)
            
            # Count by stage
            stage = row.stage_name
            by_stage[stage] = by_stage.get(stage, 0) + 1
            
            # Count by manager
            manager = row.user_name or 'Не назначен'
            by_manager[manager] = by_manager.get(manager, 0) + 1
        
        return StaleDealsReport(
            threshold_days=threshold_days,
            total_stale=len(deals),
            total_value=total_value,
            deals=deals,
            by_stage=by_stage,
            by_manager=by_manager,
        )

    async def lead_sources(
        self,
        pipeline_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> LeadSourcesReport:
        """
        Analyze lead sources and their effectiveness.
        
        Groups leads by pipeline to show which funnels bring the most conversions.
        
        Args:
            pipeline_id: Filter by pipeline (optional)
            date_from: Filter leads created from this date
            date_to: Filter leads created until this date
        
        Returns:
            LeadSourcesReport with breakdown by pipeline/source
        """
        # Build base filter
        lead_filter = [LeadDB.is_deleted == False]  # noqa: E712
        if pipeline_id:
            lead_filter.append(LeadDB.pipeline_id == pipeline_id)
        if date_from:
            lead_filter.append(LeadDB.kommo_created_at >= date_from)
        if date_to:
            lead_filter.append(LeadDB.kommo_created_at <= date_to)
        
        # Query leads grouped by pipeline with stage info
        query = select(
            PipelineDB.id.label('pipeline_id'),
            PipelineDB.name.label('pipeline_name'),
            func.count(LeadDB.id).label('leads_count'),
            func.sum(LeadDB.price).label('total_value'),
            func.count(LeadDB.id).filter(StageDB.sort >= 10000, StageDB.sort < 11000).label('won_count'),
            func.count(LeadDB.id).filter(StageDB.sort >= 11000).label('lost_count'),
            func.sum(LeadDB.price).filter(StageDB.sort >= 10000, StageDB.sort < 11000).label('won_value'),
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).join(
            PipelineDB, LeadDB.pipeline_id == PipelineDB.id
        ).where(*lead_filter).group_by(PipelineDB.id, PipelineDB.name)
        
        result = await self.session.execute(query)
        rows = result.all()
        
        sources = []
        total_leads = 0
        
        for row in rows:
            leads_count = row.leads_count or 0
            won_count = row.won_count or 0
            lost_count = row.lost_count or 0
            total_value = float(row.total_value or 0)
            won_value = float(row.won_value or 0)
            
            closed = won_count + lost_count
            conversion = won_count / closed if closed > 0 else 0.0
            avg_deal = won_value / won_count if won_count > 0 else 0.0
            
            sources.append(LeadSource(
                source_name=row.pipeline_name,
                leads_count=leads_count,
                won_count=won_count,
                lost_count=lost_count,
                in_progress=leads_count - won_count - lost_count,
                total_value=total_value,
                won_value=won_value,
                conversion_rate=conversion,
                avg_deal_size=avg_deal,
            ))
            
            total_leads += leads_count
        
        # Sort by leads count descending
        sources.sort(key=lambda x: x.leads_count, reverse=True)
        
        return LeadSourcesReport(
            period_start=date_from,
            period_end=date_to,
            total_leads=total_leads,
            sources=sources,
        )

    async def revenue_trend(
        self,
        group_by: str = 'month',
        pipeline_id: int | None = None,
        periods_count: int = 12,
    ) -> RevenueTrendReport:
        """
        Get revenue trend over time periods.
        
        Args:
            group_by: Grouping period - 'day', 'week', 'month'
            pipeline_id: Filter by pipeline (optional)
            periods_count: Number of periods to return (default: 12)
        
        Returns:
            RevenueTrendReport with revenue by period
        """
        # Determine date truncation based on group_by
        if group_by == 'day':
            trunc_func = func.date_trunc('day', LeadDB.closed_at)
            period_format = '%Y-%m-%d'
        elif group_by == 'week':
            trunc_func = func.date_trunc('week', LeadDB.closed_at)
            period_format = '%Y-W%W'
        else:  # month
            trunc_func = func.date_trunc('month', LeadDB.closed_at)
            period_format = '%Y-%m'
        
        # Build filter for won deals
        lead_filter = [
            LeadDB.is_deleted == False,  # noqa: E712
            LeadDB.closed_at.isnot(None),
            StageDB.sort >= 10000,
            StageDB.sort < 11000,  # Won stage
        ]
        if pipeline_id:
            lead_filter.append(LeadDB.pipeline_id == pipeline_id)
        
        # Query revenue grouped by period
        query = select(
            trunc_func.label('period_start'),
            func.count(LeadDB.id).label('leads_won'),
            func.sum(LeadDB.price).label('revenue'),
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).where(*lead_filter).group_by(
            trunc_func
        ).order_by(trunc_func.desc()).limit(periods_count)
        
        result = await self.session.execute(query)
        rows = result.all()
        
        periods = []
        total_revenue = 0.0
        prev_revenue = None
        
        # Process in reverse to calculate change_pct correctly
        for row in reversed(rows):
            leads_won = row.leads_won or 0
            revenue = float(row.revenue or 0)
            avg_deal = revenue / leads_won if leads_won > 0 else 0.0
            
            # Calculate period end
            period_start = row.period_start
            if group_by == 'day':
                period_end = period_start + timedelta(days=1)
            elif group_by == 'week':
                period_end = period_start + timedelta(weeks=1)
            else:
                # Approximate month end
                if period_start.month == 12:
                    period_end = period_start.replace(year=period_start.year + 1, month=1)
                else:
                    period_end = period_start.replace(month=period_start.month + 1)
            
            # Calculate change vs previous period
            change_pct = None
            if prev_revenue is not None and prev_revenue > 0:
                change_pct = ((revenue - prev_revenue) / prev_revenue) * 100
            
            periods.append(RevenueTrendPeriod(
                period=period_start.strftime(period_format),
                period_start=period_start,
                period_end=period_end,
                leads_won=leads_won,
                revenue=revenue,
                avg_deal_size=avg_deal,
                change_pct=change_pct,
            ))
            
            total_revenue += revenue
            prev_revenue = revenue
        
        # Determine trend direction
        trend_direction = 'stable'
        if len(periods) >= 3:
            recent = sum(p.revenue for p in periods[-3:]) / 3
            older = sum(p.revenue for p in periods[:3]) / 3
            if recent > older * 1.1:
                trend_direction = 'up'
            elif recent < older * 0.9:
                trend_direction = 'down'
        
        avg_revenue = total_revenue / len(periods) if periods else 0.0
        
        return RevenueTrendReport(
            group_by=group_by,
            pipeline_id=pipeline_id,
            periods=periods,
            total_revenue=total_revenue,
            avg_revenue_per_period=avg_revenue,
            trend_direction=trend_direction,
        )

    async def churn_risk(
        self,
        days_threshold: int = 90,
        min_deals: int = 1,
        limit: int = 50,
    ) -> ChurnRiskReport:
        """
        Analyze churn risk for contacts based on deal history.
        
        Risk is calculated based on:
        - Days since last won deal
        - Total deal value (higher value = higher risk impact)
        - Number of past deals
        
        Args:
            days_threshold: Days without deal to consider at risk (default: 90)
            min_deals: Minimum past deals to include contact (default: 1)
            limit: Max contacts to return (default: 50)
        
        Returns:
            ChurnRiskReport with at-risk contacts
        """
        from kommo_mcp.db.models import lead_contacts
        
        # Subquery for contact deal stats
        deal_stats = select(
            lead_contacts.c.contact_id,
            func.count(LeadDB.id).label('total_deals'),
            func.sum(LeadDB.price).label('total_revenue'),
            func.max(LeadDB.closed_at).label('last_deal_date'),
        ).join(
            LeadDB, lead_contacts.c.lead_id == LeadDB.id
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).where(
            LeadDB.is_deleted == False,  # noqa: E712
            StageDB.sort >= 10000,
            StageDB.sort < 11000,  # Won deals only
        ).group_by(
            lead_contacts.c.contact_id
        ).having(
            func.count(LeadDB.id) >= min_deals
        ).subquery()
        
        # Main query with contact info
        query = select(
            ContactDB.id,
            ContactDB.name,
            CompanyDB.name.label('company_name'),
            deal_stats.c.total_deals,
            deal_stats.c.total_revenue,
            deal_stats.c.last_deal_date,
        ).join(
            deal_stats, ContactDB.id == deal_stats.c.contact_id
        ).outerjoin(
            contact_companies, ContactDB.id == contact_companies.c.contact_id
        ).outerjoin(
            CompanyDB, contact_companies.c.company_id == CompanyDB.id
        ).where(
            ContactDB.is_deleted == False,  # noqa: E712
        ).order_by(
            deal_stats.c.last_deal_date.asc()
        ).limit(limit)
        
        result = await self.session.execute(query)
        rows = result.all()
        
        contacts = []
        high_risk = 0
        medium_risk = 0
        low_risk = 0
        revenue_at_risk = 0.0
        
        now = datetime.utcnow()
        
        for row in rows:
            days_since = (now - row.last_deal_date).days if row.last_deal_date else 999
            total_revenue = float(row.total_revenue or 0)
            
            # Calculate risk score (0-100)
            # Base score from days inactive
            if days_since >= days_threshold * 2:
                risk_score = 90
            elif days_since >= days_threshold:
                risk_score = 60 + (days_since - days_threshold) * 30 // days_threshold
            elif days_since >= days_threshold // 2:
                risk_score = 30 + (days_since - days_threshold // 2) * 30 // (days_threshold // 2)
            else:
                risk_score = days_since * 30 // (days_threshold // 2)
            
            # Adjust by revenue (higher revenue = more critical)
            if total_revenue > 100000:
                risk_score = min(100, risk_score + 10)
            
            # Determine risk level
            if risk_score >= 70:
                risk_level = 'critical' if risk_score >= 85 else 'high'
                high_risk += 1
                revenue_at_risk += total_revenue
            elif risk_score >= 40:
                risk_level = 'medium'
                medium_risk += 1
                revenue_at_risk += total_revenue * 0.5
            else:
                risk_level = 'low'
                low_risk += 1
            
            contacts.append(ChurnRiskContact(
                contact_id=row.id,
                contact_name=row.name or 'Без имени',
                company_name=row.company_name,
                last_deal_date=row.last_deal_date,
                days_since_last_deal=days_since,
                total_deals=row.total_deals,
                total_revenue=total_revenue,
                risk_level=risk_level,
                risk_score=risk_score,
            ))
        
        return ChurnRiskReport(
            total_contacts=len(contacts),
            high_risk_count=high_risk,
            medium_risk_count=medium_risk,
            low_risk_count=low_risk,
            potential_revenue_at_risk=revenue_at_risk,
            contacts=contacts,
        )

    async def lead_score(
        self,
        pipeline_id: int | None = None,
        limit: int = 50,
    ) -> LeadScoreReport:
        """
        Score leads based on multiple factors to prioritize sales efforts.
        
        Scoring factors:
        - Deal value (higher = better)
        - Stage progression (closer to won = better)
        - Days in pipeline (too long = worse)
        - Has responsible user assigned
        - Has upcoming tasks
        
        Args:
            pipeline_id: Filter by pipeline (optional)
            limit: Max leads to return (default: 50)
        
        Returns:
            LeadScoreReport with scored leads
        """
        # Build filter for active leads
        lead_filter = [
            LeadDB.is_deleted == False,  # noqa: E712
            StageDB.sort < 10000,  # Not closed
        ]
        if pipeline_id:
            lead_filter.append(LeadDB.pipeline_id == pipeline_id)
        
        # Query leads with stage info
        query = select(
            LeadDB.id,
            LeadDB.name,
            LeadDB.price,
            LeadDB.kommo_created_at,
            LeadDB.closest_task_at,
            PipelineDB.name.label('pipeline_name'),
            StageDB.name.label('stage_name'),
            StageDB.sort.label('stage_sort'),
            UserDB.name.label('user_name'),
        ).join(
            StageDB, LeadDB.status_id == StageDB.id
        ).join(
            PipelineDB, LeadDB.pipeline_id == PipelineDB.id
        ).outerjoin(
            UserDB, LeadDB.responsible_user_id == UserDB.id
        ).where(*lead_filter).order_by(
            LeadDB.price.desc()
        ).limit(limit * 2)  # Get more to sort by score later
        
        result = await self.session.execute(query)
        rows = result.all()
        
        leads = []
        hot = 0
        warm = 0
        cold = 0
        now = datetime.utcnow()
        
        for row in rows:
            price = float(row.price or 0)
            days_in_pipeline = (now - row.kommo_created_at).days if row.kommo_created_at else 0
            has_task = row.closest_task_at is not None
            has_user = row.user_name is not None
            stage_sort = row.stage_sort or 0
            
            # Calculate score components
            breakdown = {}
            score = 0
            
            # Value score (0-30 points)
            if price >= 50000:
                breakdown['value'] = 30
            elif price >= 20000:
                breakdown['value'] = 25
            elif price >= 10000:
                breakdown['value'] = 20
            elif price >= 5000:
                breakdown['value'] = 15
            elif price > 0:
                breakdown['value'] = 10
            else:
                breakdown['value'] = 5
            score += breakdown['value']
            
            # Stage progression (0-25 points)
            # Higher sort = closer to closing (but not closed)
            if stage_sort >= 5000:
                breakdown['stage'] = 25
            elif stage_sort >= 3000:
                breakdown['stage'] = 20
            elif stage_sort >= 1000:
                breakdown['stage'] = 15
            else:
                breakdown['stage'] = 10
            score += breakdown['stage']
            
            # Freshness (0-20 points) - newer leads score higher
            if days_in_pipeline <= 7:
                breakdown['freshness'] = 20
            elif days_in_pipeline <= 14:
                breakdown['freshness'] = 15
            elif days_in_pipeline <= 30:
                breakdown['freshness'] = 10
            elif days_in_pipeline <= 60:
                breakdown['freshness'] = 5
            else:
                breakdown['freshness'] = 0
            score += breakdown['freshness']
            
            # Has responsible user (0-15 points)
            breakdown['assigned'] = 15 if has_user else 0
            score += breakdown['assigned']
            
            # Has upcoming task (0-10 points)
            breakdown['has_task'] = 10 if has_task else 0
            score += breakdown['has_task']
            
            # Generate recommendation
            if score >= 70:
                recommendation = 'Горячий лид - приоритетная обработка'
            elif score >= 50:
                recommendation = 'Теплый лид - требует внимания'
            elif score >= 30:
                recommendation = 'Холодный лид - нужна квалификация'
            else:
                recommendation = 'Низкий приоритет - проверить актуальность'
            
            leads.append(ScoredLead(
                lead_id=row.id,
                lead_name=row.name or 'Без названия',
                pipeline_name=row.pipeline_name,
                stage_name=row.stage_name,
                responsible_user=row.user_name,
                price=price,
                score=score,
                score_breakdown=breakdown,
                recommendation=recommendation,
            ))
            
            if score >= 70:
                hot += 1
            elif score >= 40:
                warm += 1
            else:
                cold += 1
        
        # Sort by score and limit
        leads.sort(key=lambda x: x.score, reverse=True)
        leads = leads[:limit]
        
        return LeadScoreReport(
            total_leads=len(leads),
            hot_leads=hot,
            warm_leads=warm,
            cold_leads=cold,
            leads=leads,
        )

    async def find_duplicates(
        self,
        entity_type: str = 'contacts',
        limit: int = 50,
    ) -> DuplicatesReport:
        """
        Find duplicate contacts or companies by name.
        
        Args:
            entity_type: 'contacts' or 'companies'
            limit: Max duplicate groups to return
        
        Returns:
            DuplicatesReport with groups of duplicates
        """
        if entity_type == 'companies':
            # Find companies with same name
            subq = select(
                func.lower(func.trim(CompanyDB.name)).label('normalized_name'),
                func.count(CompanyDB.id).label('cnt'),
            ).where(
                CompanyDB.is_deleted == False,  # noqa: E712
                CompanyDB.name.isnot(None),
                CompanyDB.name != '',
            ).group_by(
                func.lower(func.trim(CompanyDB.name))
            ).having(
                func.count(CompanyDB.id) > 1
            ).subquery()
            
            query = select(
                CompanyDB.id,
                CompanyDB.name,
                CompanyDB.kommo_created_at,
                func.lower(func.trim(CompanyDB.name)).label('normalized_name'),
            ).where(
                func.lower(func.trim(CompanyDB.name)).in_(
                    select(subq.c.normalized_name)
                ),
                CompanyDB.is_deleted == False,  # noqa: E712
            ).order_by(
                func.lower(func.trim(CompanyDB.name)),
                CompanyDB.kommo_created_at,
            )
            
            result = await self.session.execute(query)
            rows = result.all()
            
            # Group by normalized name
            groups_dict: dict[str, list] = {}
            for row in rows:
                key = row.normalized_name
                if key not in groups_dict:
                    groups_dict[key] = []
                groups_dict[key].append({
                    'id': row.id,
                    'name': row.name,
                    'created_at': row.kommo_created_at.isoformat() if row.kommo_created_at else None,
                })
        else:
            # Find contacts with same name
            subq = select(
                func.lower(func.trim(ContactDB.name)).label('normalized_name'),
                func.count(ContactDB.id).label('cnt'),
            ).where(
                ContactDB.is_deleted == False,  # noqa: E712
                ContactDB.name.isnot(None),
                ContactDB.name != '',
            ).group_by(
                func.lower(func.trim(ContactDB.name))
            ).having(
                func.count(ContactDB.id) > 1
            ).subquery()
            
            query = select(
                ContactDB.id,
                ContactDB.name,
                ContactDB.kommo_created_at,
                func.lower(func.trim(ContactDB.name)).label('normalized_name'),
            ).where(
                func.lower(func.trim(ContactDB.name)).in_(
                    select(subq.c.normalized_name)
                ),
                ContactDB.is_deleted == False,  # noqa: E712
            ).order_by(
                func.lower(func.trim(ContactDB.name)),
                ContactDB.kommo_created_at,
            )
            
            result = await self.session.execute(query)
            rows = result.all()
            
            # Group by normalized name
            groups_dict: dict[str, list] = {}
            for row in rows:
                key = row.normalized_name
                if key not in groups_dict:
                    groups_dict[key] = []
                groups_dict[key].append({
                    'id': row.id,
                    'name': row.name,
                    'created_at': row.kommo_created_at.isoformat() if row.kommo_created_at else None,
                })
        
        # Convert to DuplicateGroup list
        groups = []
        total_duplicates = 0
        for name, contacts in list(groups_dict.items())[:limit]:
            groups.append(DuplicateGroup(
                match_field='name',
                match_value=name,
                contacts=contacts,
            ))
            total_duplicates += len(contacts)
        
        return DuplicatesReport(
            entity_type=entity_type,
            total_groups=len(groups),
            total_duplicates=total_duplicates,
            groups=groups,
        )
