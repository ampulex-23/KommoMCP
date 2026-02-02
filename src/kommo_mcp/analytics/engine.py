"""Analytics Engine - Core analytics functionality."""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kommo_mcp.analytics.models import (
    ActivityReport,
    Alert,
    AlertsReport,
    BigDeal,
    BigDealsReport,
    ChurnRiskContact,
    ChurnRiskReport,
    DailyDigest,
    DigestMetric,
    DuplicateGroup,
    DuplicatesReport,
    FunnelAnalysis,
    FunnelStage,
    LeadScoreReport,
    LeadSource,
    LeadSourcesReport,
    ManagerPerformance,
    ManagerRankingReport,
    ManagerWorkload,
    Opportunity,
    OpportunitiesReport,
    PeriodComparison,
    PeriodMetrics,
    PipelineSummary,
    RankedManager,
    RevenuePeriod,
    RevenueTrendPeriod,
    RevenueTrendReport,
    RFMClient,
    RFMReport,
    RFMSegment,
    SalesForecast,
    ScoredLead,
    StageForecast,
    StageSummary,
    StaleDeal,
    StaleDealsReport,
    TopClient,
    TopClientsReport,
    WorkloadReport,
    YoYComparison,
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
    lead_companies,
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
        # Only consider deals created within forecast_days * 3 to be realistic
        # (deals older than that are likely stale and won't close)
        cutoff_date = datetime.now() - timedelta(days=forecast_days * 3)
        
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
            LeadDB.kommo_created_at >= cutoff_date,  # Only recent deals
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

    async def top_clients(
        self,
        limit: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        by: str = 'companies',  # companies or contacts
    ) -> TopClientsReport:
        """
        Get top clients by revenue.
        
        Args:
            limit: Number of top clients
            date_from: Start date for deals
            date_to: End date for deals
            by: Group by 'companies' or 'contacts'
        """
        if by == 'companies':
            query = select(
                CompanyDB.id.label('client_id'),
                CompanyDB.name,
                func.sum(LeadDB.price).label('total_revenue'),
                func.count(LeadDB.id).label('deals_count'),
                func.count(LeadDB.id).filter(StageDB.type == 2).label('won_deals'),
                func.max(LeadDB.closed_at).label('last_deal_date'),
            ).select_from(
                CompanyDB
            ).join(
                lead_companies, lead_companies.c.company_id == CompanyDB.id
            ).join(
                LeadDB, LeadDB.id == lead_companies.c.lead_id
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                LeadDB.is_deleted == False,  # noqa: E712
                StageDB.type == 2,  # Won deals only
            ).group_by(
                CompanyDB.id, CompanyDB.name
            ).order_by(
                func.sum(LeadDB.price).desc()
            ).limit(limit)
        else:
            query = select(
                ContactDB.id.label('client_id'),
                ContactDB.name,
                func.sum(LeadDB.price).label('total_revenue'),
                func.count(LeadDB.id).label('deals_count'),
                func.count(LeadDB.id).filter(StageDB.type == 2).label('won_deals'),
                func.max(LeadDB.closed_at).label('last_deal_date'),
            ).select_from(
                ContactDB
            ).join(
                LeadDB, LeadDB.main_contact_id == ContactDB.id
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                LeadDB.is_deleted == False,  # noqa: E712
                StageDB.type == 2,  # Won deals only
            ).group_by(
                ContactDB.id, ContactDB.name
            ).order_by(
                func.sum(LeadDB.price).desc()
            ).limit(limit)

        if date_from:
            query = query.where(LeadDB.closed_at >= date_from)
        if date_to:
            query = query.where(LeadDB.closed_at <= date_to)

        result = await self.session.execute(query)
        rows = result.all()

        total_revenue = 0.0
        clients = []
        for row in rows:
            revenue = float(row.total_revenue or 0)
            total_revenue += revenue
            avg_value = revenue / row.won_deals if row.won_deals > 0 else 0
            
            client = TopClient(
                company_id=row.client_id if by == 'companies' else None,
                contact_id=row.client_id if by == 'contacts' else None,
                name=row.name or 'Unknown',
                total_revenue=revenue,
                deals_count=row.deals_count,
                won_deals=row.won_deals,
                avg_deal_value=avg_value,
                last_deal_date=row.last_deal_date,
            )
            clients.append(client)

        return TopClientsReport(
            period_start=date_from,
            period_end=date_to,
            total_revenue=total_revenue,
            clients=clients,
        )

    async def rfm_analysis(
        self,
        limit: int = 100,
        by: str = 'companies',
    ) -> RFMReport:
        """
        RFM (Recency, Frequency, Monetary) analysis.
        
        Segments:
        - Champions (5,5,5): Best customers
        - Loyal (4-5, 4-5, 4-5): Regular high-value
        - Potential Loyalists (4-5, 2-3, 2-3): Recent but not frequent
        - At Risk (2-3, 4-5, 4-5): Were good, not recent
        - Hibernating (1-2, 1-2, 1-2): Lost customers
        """
        now = datetime.now()
        
        if by == 'companies':
            query = select(
                CompanyDB.id.label('client_id'),
                CompanyDB.name,
                func.max(LeadDB.closed_at).label('last_purchase'),
                func.count(LeadDB.id).label('frequency'),
                func.sum(LeadDB.price).label('monetary'),
            ).select_from(
                CompanyDB
            ).join(
                lead_companies, lead_companies.c.company_id == CompanyDB.id
            ).join(
                LeadDB, LeadDB.id == lead_companies.c.lead_id
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                LeadDB.is_deleted == False,  # noqa: E712
                StageDB.type == 2,  # Won deals
            ).group_by(
                CompanyDB.id, CompanyDB.name
            ).having(
                func.count(LeadDB.id) > 0
            )
        else:
            query = select(
                ContactDB.id.label('client_id'),
                ContactDB.name,
                func.max(LeadDB.closed_at).label('last_purchase'),
                func.count(LeadDB.id).label('frequency'),
                func.sum(LeadDB.price).label('monetary'),
            ).select_from(
                ContactDB
            ).join(
                LeadDB, LeadDB.main_contact_id == ContactDB.id
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                LeadDB.is_deleted == False,  # noqa: E712
                StageDB.type == 2,  # Won deals
            ).group_by(
                ContactDB.id, ContactDB.name
            ).having(
                func.count(LeadDB.id) > 0
            )

        result = await self.session.execute(query)
        rows = result.all()

        if not rows:
            return RFMReport(total_clients=0, segments=[], clients=[])

        # Calculate percentiles for scoring
        recencies = []
        frequencies = []
        monetaries = []
        
        for row in rows:
            if row.last_purchase:
                recencies.append((now - row.last_purchase).days)
            frequencies.append(row.frequency)
            monetaries.append(float(row.monetary or 0))

        def percentile_score(value: float, values: list, reverse: bool = False) -> int:
            if not values:
                return 3
            sorted_vals = sorted(values, reverse=reverse)
            n = len(sorted_vals)
            for i, v in enumerate(sorted_vals):
                if value <= v:
                    return min(5, max(1, 5 - int(i / n * 5)))
            return 1

        def get_segment(r: int, f: int, m: int) -> str:
            if r >= 4 and f >= 4 and m >= 4:
                return 'Champions'
            elif r >= 3 and f >= 3 and m >= 3:
                return 'Loyal'
            elif r >= 4 and f <= 2:
                return 'Potential Loyalists'
            elif r <= 2 and f >= 3 and m >= 3:
                return 'At Risk'
            elif r <= 2 and f <= 2:
                return 'Hibernating'
            else:
                return 'Others'

        clients = []
        segment_counts: dict[str, dict] = {}
        
        for row in rows:
            recency_days = (now - row.last_purchase).days if row.last_purchase else 999
            frequency = row.frequency
            monetary = float(row.monetary or 0)
            
            r_score = percentile_score(recency_days, recencies, reverse=True)
            f_score = percentile_score(frequency, frequencies)
            m_score = percentile_score(monetary, monetaries)
            
            segment = get_segment(r_score, f_score, m_score)
            
            if segment not in segment_counts:
                segment_counts[segment] = {'count': 0, 'revenue': 0.0, 'r': r_score, 'f': f_score, 'm': m_score}
            segment_counts[segment]['count'] += 1
            segment_counts[segment]['revenue'] += monetary
            
            if len(clients) < limit:
                clients.append(RFMClient(
                    company_id=row.client_id if by == 'companies' else None,
                    contact_id=row.client_id if by == 'contacts' else None,
                    name=row.name or 'Unknown',
                    recency_days=recency_days,
                    frequency=frequency,
                    monetary=monetary,
                    r_score=r_score,
                    f_score=f_score,
                    m_score=m_score,
                    segment=segment,
                ))

        segment_descriptions = {
            'Champions': 'Лучшие клиенты - покупают часто и много',
            'Loyal': 'Лояльные клиенты - стабильные покупки',
            'Potential Loyalists': 'Потенциально лояльные - недавно купили, но редко',
            'At Risk': 'В зоне риска - были хорошими, давно не покупали',
            'Hibernating': 'Спящие - давно не покупали',
            'Others': 'Прочие',
        }

        segments = [
            RFMSegment(
                segment=name,
                r_score=data['r'],
                f_score=data['f'],
                m_score=data['m'],
                count=data['count'],
                total_revenue=data['revenue'],
                description=segment_descriptions.get(name, ''),
            )
            for name, data in segment_counts.items()
        ]

        return RFMReport(
            total_clients=len(rows),
            segments=sorted(segments, key=lambda x: x.total_revenue, reverse=True),
            clients=clients,
        )

    async def manager_workload(self) -> WorkloadReport:
        """
        Get workload distribution across managers.
        """
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Active deals per manager
        deals_query = select(
            UserDB.id,
            UserDB.name,
            func.count(LeadDB.id).label('active_deals'),
            func.sum(LeadDB.price).label('active_value'),
        ).select_from(
            UserDB
        ).outerjoin(
            LeadDB, LeadDB.responsible_user_id == UserDB.id
        ).outerjoin(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            UserDB.is_active == True,  # noqa: E712
        ).group_by(
            UserDB.id, UserDB.name
        )

        # Filter to only active deals (not won/lost)
        deals_query = select(
            UserDB.id,
            UserDB.name,
            func.count(LeadDB.id).filter(
                StageDB.type.notin_([2, 3]),
                LeadDB.is_deleted == False,  # noqa: E712
            ).label('active_deals'),
            func.sum(LeadDB.price).filter(
                StageDB.type.notin_([2, 3]),
                LeadDB.is_deleted == False,  # noqa: E712
            ).label('active_value'),
        ).select_from(
            UserDB
        ).outerjoin(
            LeadDB, LeadDB.responsible_user_id == UserDB.id
        ).outerjoin(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            UserDB.is_active == True,  # noqa: E712
        ).group_by(
            UserDB.id, UserDB.name
        )

        deals_result = await self.session.execute(deals_query)
        deals_rows = {r.id: r for r in deals_result.all()}

        # Overdue tasks per manager
        tasks_query = select(
            TaskDB.responsible_user_id,
            func.count(TaskDB.id).filter(
                TaskDB.complete_till < now,
                TaskDB.is_completed == False,  # noqa: E712
            ).label('overdue'),
            func.count(TaskDB.id).filter(
                TaskDB.complete_till >= today_start,
                TaskDB.complete_till < today_start + timedelta(days=1),
            ).label('today'),
        ).group_by(
            TaskDB.responsible_user_id
        )

        tasks_result = await self.session.execute(tasks_query)
        tasks_rows = {r.responsible_user_id: r for r in tasks_result.all()}

        managers = []
        total_deals = 0
        overloaded = 0
        underloaded = 0

        for user_id, row in deals_rows.items():
            active = row.active_deals or 0
            total_deals += active
            
            task_row = tasks_rows.get(user_id)
            overdue = task_row.overdue if task_row else 0
            today = task_row.today if task_row else 0
            
            # Capacity score: 0-100, based on deals and overdue tasks
            # Assume optimal is 20 deals, 0 overdue
            capacity = min(100, int((active / 20) * 50 + (overdue * 10)))
            
            if capacity > 80:
                overloaded += 1
            elif capacity < 30 and active > 0:
                underloaded += 1

            managers.append(ManagerWorkload(
                user_id=user_id,
                user_name=row.name or f'User {user_id}',
                active_deals=active,
                active_deals_value=float(row.active_value or 0),
                overdue_tasks=overdue,
                tasks_today=today,
                capacity_score=capacity,
            ))

        managers.sort(key=lambda x: x.capacity_score, reverse=True)
        avg_deals = total_deals / len(managers) if managers else 0

        return WorkloadReport(
            total_active_deals=total_deals,
            avg_deals_per_manager=round(avg_deals, 1),
            overloaded_managers=overloaded,
            underloaded_managers=underloaded,
            managers=managers,
        )

    async def find_opportunities(
        self,
        days_inactive: int = 90,
        limit: int = 20,
    ) -> OpportunitiesReport:
        """
        Find sales opportunities: upsell, cross-sell, reactivation.
        """
        now = datetime.now()
        cutoff = now - timedelta(days=days_inactive)
        
        # Reactivation: clients who bought before but not recently
        reactivation_query = select(
            CompanyDB.id,
            CompanyDB.name,
            func.max(LeadDB.price).label('last_value'),
            func.max(LeadDB.closed_at).label('last_date'),
            func.count(LeadDB.id).label('total_deals'),
        ).select_from(
            CompanyDB
        ).join(
            lead_companies, lead_companies.c.company_id == CompanyDB.id
        ).join(
            LeadDB, LeadDB.id == lead_companies.c.lead_id
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            StageDB.type == 2,  # Won
            LeadDB.is_deleted == False,  # noqa: E712
        ).group_by(
            CompanyDB.id, CompanyDB.name
        ).having(
            func.max(LeadDB.closed_at) < cutoff,
            func.count(LeadDB.id) >= 1,
        ).order_by(
            func.sum(LeadDB.price).desc()
        ).limit(limit)

        react_result = await self.session.execute(reactivation_query)
        reactivations = []
        
        for row in react_result.all():
            days_since = (now - row.last_date).days if row.last_date else 999
            reactivations.append(Opportunity(
                type='reactivation',
                company_id=row.id,
                name=row.name or 'Unknown',
                last_deal_value=float(row.last_value or 0),
                potential_value=float(row.last_value or 0) * 1.2,
                days_since_last_deal=days_since,
                reason=f'Не покупали {days_since} дней, было {row.total_deals} сделок',
            ))

        # Upsell: clients with growing deal values
        upsell_query = select(
            CompanyDB.id,
            CompanyDB.name,
            func.max(LeadDB.price).label('max_value'),
            func.avg(LeadDB.price).label('avg_value'),
            func.count(LeadDB.id).label('deals_count'),
        ).select_from(
            CompanyDB
        ).join(
            lead_companies, lead_companies.c.company_id == CompanyDB.id
        ).join(
            LeadDB, LeadDB.id == lead_companies.c.lead_id
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            StageDB.type == 2,
            LeadDB.is_deleted == False,  # noqa: E712
            LeadDB.closed_at >= cutoff,
        ).group_by(
            CompanyDB.id, CompanyDB.name
        ).having(
            func.count(LeadDB.id) >= 2,
        ).order_by(
            func.max(LeadDB.price).desc()
        ).limit(limit)

        upsell_result = await self.session.execute(upsell_query)
        upsells = []
        
        for row in upsell_result.all():
            max_val = float(row.max_value or 0)
            avg_val = float(row.avg_value or 0)
            if max_val > avg_val * 1.3:  # Growing
                upsells.append(Opportunity(
                    type='upsell',
                    company_id=row.id,
                    name=row.name or 'Unknown',
                    last_deal_value=max_val,
                    potential_value=max_val * 1.5,
                    days_since_last_deal=0,
                    reason=f'Растущий клиент: макс {max_val:.0f}, средний {avg_val:.0f}',
                ))

        total_potential = sum(o.potential_value for o in reactivations + upsells)

        return OpportunitiesReport(
            total_opportunities=len(reactivations) + len(upsells),
            total_potential_value=total_potential,
            upsell=upsells[:limit],
            cross_sell=[],  # Would need product data
            reactivation=reactivations[:limit],
        )

    async def big_deals(
        self,
        threshold: float | None = None,
        limit: int = 20,
    ) -> BigDealsReport:
        """
        Get big deals currently in pipeline.
        
        Args:
            threshold: Minimum deal value (auto-calculated if None)
            limit: Max deals to return
        """
        # Auto-calculate threshold as top 10% of deals
        if threshold is None:
            avg_query = select(
                func.percentile_cont(0.9).within_group(LeadDB.price)
            ).where(
                LeadDB.is_deleted == False,  # noqa: E712
                LeadDB.price > 0,
            )
            try:
                avg_result = await self.session.execute(avg_query)
                threshold = float(avg_result.scalar() or 100000)
            except Exception:
                threshold = 100000

        query = select(
            LeadDB.id,
            LeadDB.name,
            LeadDB.price,
            LeadDB.kommo_created_at,
            PipelineDB.name.label('pipeline_name'),
            StageDB.name.label('stage_name'),
            StageDB.sort,
            UserDB.name.label('user_name'),
        ).select_from(
            LeadDB
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).join(
            PipelineDB, PipelineDB.id == LeadDB.pipeline_id
        ).outerjoin(
            UserDB, UserDB.id == LeadDB.responsible_user_id
        ).where(
            LeadDB.is_deleted == False,  # noqa: E712
            LeadDB.price >= threshold,
            StageDB.type.notin_([2, 3]),  # Not closed
        ).order_by(
            LeadDB.price.desc()
        ).limit(limit)

        result = await self.session.execute(query)
        rows = result.all()

        now = datetime.now()
        deals = []
        total_value = 0.0

        for row in rows:
            days = (now - row.kommo_created_at).days if row.kommo_created_at else 0
            # Simple probability based on stage position
            probability = min(0.9, 0.1 + (row.sort or 0) * 0.1)
            
            deals.append(BigDeal(
                lead_id=row.id,
                lead_name=row.name or f'Deal {row.id}',
                price=float(row.price or 0),
                pipeline_name=row.pipeline_name or '',
                stage_name=row.stage_name or '',
                responsible_user=row.user_name,
                days_in_pipeline=days,
                probability=probability,
            ))
            total_value += float(row.price or 0)

        return BigDealsReport(
            threshold=threshold,
            total_count=len(deals),
            total_value=total_value,
            deals=deals,
        )

    async def generate_alerts(
        self,
        include_stale: bool = True,
        include_overdue: bool = True,
        include_churn: bool = True,
        include_performance: bool = True,
        stale_threshold_days: int = 14,
        churn_threshold_days: int = 90,
    ) -> AlertsReport:
        """
        Generate alerts based on CRM data analysis.
        
        Checks for:
        - Stale deals without activity
        - Overdue tasks
        - Churn risk contacts
        - Manager performance drops
        """
        now = datetime.now()
        alerts: list[Alert] = []
        
        # 1. Stale deals alerts
        if include_stale:
            stale = await self.stale_deals(
                threshold_days=stale_threshold_days,
                limit=50,
            )
            if stale.total_stale > 0:
                severity = 'critical' if stale.total_stale > 10 else 'high' if stale.total_stale > 5 else 'medium'
                alerts.append(Alert(
                    type='stale_deals',
                    severity=severity,
                    title=f'{stale.total_stale} зависших сделок',
                    description=f'Сделки без активности более {stale_threshold_days} дней на сумму {stale.total_value:,.0f}',
                    value=stale.total_value,
                    action_suggested='kommo_automate(action="stale_followup")',
                ))
                # Add individual high-value stale deals
                for deal in stale.deals[:5]:
                    if deal.price and deal.price > 50000:
                        alerts.append(Alert(
                            type='stale_deal',
                            severity='high',
                            title=f'Зависла крупная сделка: {deal.lead_name}',
                            description=f'Без активности {deal.days_inactive} дней, сумма {deal.price:,.0f}',
                            entity_type='leads',
                            entity_id=deal.lead_id,
                            entity_name=deal.lead_name,
                            value=deal.price,
                            action_suggested=f'Связаться с клиентом по сделке {deal.lead_id}',
                        ))

        # 2. Overdue tasks alerts
        if include_overdue:
            query = select(
                TaskDB.responsible_user_id,
                UserDB.name.label('user_name'),
                func.count(TaskDB.id).label('overdue_count'),
            ).join(
                UserDB, UserDB.id == TaskDB.responsible_user_id
            ).where(
                TaskDB.complete_till < now,
                TaskDB.is_completed == False,  # noqa: E712
            ).group_by(
                TaskDB.responsible_user_id, UserDB.name
            ).having(
                func.count(TaskDB.id) > 0
            )
            
            result = await self.session.execute(query)
            for row in result.all():
                severity = 'critical' if row.overdue_count > 10 else 'high' if row.overdue_count > 5 else 'medium'
                alerts.append(Alert(
                    type='overdue_tasks',
                    severity=severity,
                    title=f'{row.overdue_count} просроченных задач у {row.user_name}',
                    description=f'Менеджер {row.user_name} имеет {row.overdue_count} просроченных задач',
                    entity_type='users',
                    entity_id=row.responsible_user_id,
                    entity_name=row.user_name,
                    value=float(row.overdue_count),
                    action_suggested='Проверить задачи менеджера',
                ))

        # 3. Churn risk alerts
        if include_churn:
            churn = await self.churn_risk(
                days_threshold=churn_threshold_days,
                limit=20,
            )
            if churn.high_risk_count > 0:
                severity = 'high' if churn.high_risk_count > 5 else 'medium'
                alerts.append(Alert(
                    type='churn_risk',
                    severity=severity,
                    title=f'{churn.high_risk_count} клиентов в зоне риска оттока',
                    description=f'Клиенты не активны более {churn_threshold_days} дней',
                    value=float(churn.high_risk_count),
                    action_suggested='kommo_analytics(action="churn")',
                ))

        # 4. Performance drop alerts
        if include_performance:
            # Compare last 7 days vs previous 7 days
            week_ago = now - timedelta(days=7)
            two_weeks_ago = now - timedelta(days=14)
            
            current_query = select(
                UserDB.id,
                UserDB.name,
                func.count(LeadDB.id).label('deals'),
            ).join(
                LeadDB, LeadDB.responsible_user_id == UserDB.id
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                StageDB.type == 2,  # Won
                LeadDB.closed_at >= week_ago,
            ).group_by(UserDB.id, UserDB.name)
            
            prev_query = select(
                UserDB.id,
                func.count(LeadDB.id).label('deals'),
            ).join(
                LeadDB, LeadDB.responsible_user_id == UserDB.id
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                StageDB.type == 2,
                LeadDB.closed_at >= two_weeks_ago,
                LeadDB.closed_at < week_ago,
            ).group_by(UserDB.id)
            
            current_result = await self.session.execute(current_query)
            current_data = {r.id: (r.name, r.deals) for r in current_result.all()}
            
            prev_result = await self.session.execute(prev_query)
            prev_data = {r.id: r.deals for r in prev_result.all()}
            
            for user_id, (name, current_deals) in current_data.items():
                prev_deals = prev_data.get(user_id, 0)
                if prev_deals > 2 and current_deals < prev_deals * 0.5:
                    drop_percent = (1 - current_deals / prev_deals) * 100
                    alerts.append(Alert(
                        type='performance_drop',
                        severity='medium',
                        title=f'Падение показателей: {name}',
                        description=f'Закрытых сделок снизилось на {drop_percent:.0f}% ({prev_deals} → {current_deals})',
                        entity_type='users',
                        entity_id=user_id,
                        entity_name=name,
                        value=drop_percent,
                        action_suggested='Провести 1-on-1 с менеджером',
                    ))

        # Count by severity
        critical = sum(1 for a in alerts if a.severity == 'critical')
        high = sum(1 for a in alerts if a.severity == 'high')
        medium = sum(1 for a in alerts if a.severity == 'medium')
        low = sum(1 for a in alerts if a.severity == 'low')
        
        # Sort by severity
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        alerts.sort(key=lambda x: severity_order.get(x.severity, 4))

        return AlertsReport(
            generated_at=now,
            total_alerts=len(alerts),
            critical=critical,
            high=high,
            medium=medium,
            low=low,
            alerts=alerts,
        )

    async def daily_digest(
        self,
        period: str = 'day',  # day, week, month
    ) -> DailyDigest:
        """
        Generate daily/weekly/monthly digest with key metrics.
        """
        now = datetime.now()
        
        if period == 'day':
            date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
            prev_from = date_from - timedelta(days=1)
            prev_to = date_from
        elif period == 'week':
            date_from = now - timedelta(days=7)
            prev_from = date_from - timedelta(days=7)
            prev_to = date_from
        else:  # month
            date_from = now - timedelta(days=30)
            prev_from = date_from - timedelta(days=30)
            prev_to = date_from

        # Current period metrics
        new_leads_query = select(func.count(LeadDB.id)).where(
            LeadDB.kommo_created_at >= date_from,
            LeadDB.is_deleted == False,  # noqa: E712
        )
        new_leads = (await self.session.execute(new_leads_query)).scalar() or 0

        won_query = select(
            func.count(LeadDB.id),
            func.sum(LeadDB.price),
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            StageDB.type == 2,
            LeadDB.closed_at >= date_from,
        )
        won_result = (await self.session.execute(won_query)).one()
        won_deals = won_result[0] or 0
        revenue = float(won_result[1] or 0)

        lost_query = select(func.count(LeadDB.id)).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            StageDB.type == 3,
            LeadDB.closed_at >= date_from,
        )
        lost_deals = (await self.session.execute(lost_query)).scalar() or 0

        # Previous period for comparison
        prev_leads_query = select(func.count(LeadDB.id)).where(
            LeadDB.kommo_created_at >= prev_from,
            LeadDB.kommo_created_at < prev_to,
            LeadDB.is_deleted == False,  # noqa: E712
        )
        prev_leads = (await self.session.execute(prev_leads_query)).scalar() or 0

        prev_won_query = select(
            func.count(LeadDB.id),
            func.sum(LeadDB.price),
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            StageDB.type == 2,
            LeadDB.closed_at >= prev_from,
            LeadDB.closed_at < prev_to,
        )
        prev_won_result = (await self.session.execute(prev_won_query)).one()
        prev_won = prev_won_result[0] or 0
        prev_revenue = float(prev_won_result[1] or 0)

        # Calculate changes
        def calc_change(current: float, previous: float) -> float | None:
            if previous == 0:
                return 100.0 if current > 0 else None
            return round((current - previous) / previous * 100, 1)

        new_leads_change = calc_change(new_leads, prev_leads)
        won_deals_change = calc_change(won_deals, prev_won)
        revenue_change = calc_change(revenue, prev_revenue)

        # Top manager
        top_manager_query = select(
            UserDB.name,
            func.sum(LeadDB.price).label('revenue'),
        ).join(
            LeadDB, LeadDB.responsible_user_id == UserDB.id
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            StageDB.type == 2,
            LeadDB.closed_at >= date_from,
        ).group_by(
            UserDB.name
        ).order_by(
            func.sum(LeadDB.price).desc()
        ).limit(1)
        
        top_result = (await self.session.execute(top_manager_query)).first()
        top_manager = top_result[0] if top_result else None
        top_manager_revenue = float(top_result[1]) if top_result else 0

        # Tasks stats
        overdue_query = select(func.count(TaskDB.id)).where(
            TaskDB.complete_till < now,
            TaskDB.is_completed == False,  # noqa: E712
        )
        overdue_tasks = (await self.session.execute(overdue_query)).scalar() or 0

        pending_query = select(func.count(TaskDB.id)).where(
            TaskDB.is_completed == False,  # noqa: E712
        )
        pending_tasks = (await self.session.execute(pending_query)).scalar() or 0

        # Generate highlights
        highlights = []
        if revenue > 0:
            highlights.append(f'Выручка: {revenue:,.0f} руб.')
        if won_deals > 0:
            highlights.append(f'Закрыто {won_deals} сделок')
        if new_leads > 0:
            highlights.append(f'Новых лидов: {new_leads}')
        if top_manager:
            highlights.append(f'Лучший менеджер: {top_manager} ({top_manager_revenue:,.0f} руб.)')
        if overdue_tasks > 0:
            highlights.append(f'⚠️ Просроченных задач: {overdue_tasks}')

        # Build metrics list
        metrics = [
            DigestMetric(
                name='Новые лиды',
                value=float(new_leads),
                previous_value=float(prev_leads),
                change_percent=new_leads_change,
                trend='up' if (new_leads_change or 0) > 0 else 'down' if (new_leads_change or 0) < 0 else 'stable',
            ),
            DigestMetric(
                name='Закрытые сделки',
                value=float(won_deals),
                previous_value=float(prev_won),
                change_percent=won_deals_change,
                trend='up' if (won_deals_change or 0) > 0 else 'down' if (won_deals_change or 0) < 0 else 'stable',
            ),
            DigestMetric(
                name='Выручка',
                value=revenue,
                previous_value=prev_revenue,
                change_percent=revenue_change,
                trend='up' if (revenue_change or 0) > 0 else 'down' if (revenue_change or 0) < 0 else 'stable',
            ),
        ]

        # Get alerts count
        alerts = await self.generate_alerts(
            include_stale=True,
            include_overdue=False,  # Already counted
            include_churn=True,
            include_performance=True,
        )

        return DailyDigest(
            date=now,
            period=period,
            new_leads=new_leads,
            won_deals=won_deals,
            lost_deals=lost_deals,
            revenue=revenue,
            new_leads_change=new_leads_change,
            won_deals_change=won_deals_change,
            revenue_change=revenue_change,
            top_manager=top_manager,
            top_manager_revenue=top_manager_revenue,
            critical_alerts=alerts.critical,
            pending_tasks=pending_tasks,
            overdue_tasks=overdue_tasks,
            highlights=highlights,
            metrics=metrics,
        )

    async def manager_ranking(
        self,
        ranking_by: str = 'revenue',  # revenue, conversion, deals_won
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ManagerRankingReport:
        """
        Rank managers by various metrics.
        """
        now = datetime.now()
        if not date_from:
            date_from = now - timedelta(days=30)
        if not date_to:
            date_to = now

        query = select(
            UserDB.id,
            UserDB.name,
            func.count(LeadDB.id).filter(StageDB.type == 2).label('won'),
            func.count(LeadDB.id).label('total'),
            func.sum(LeadDB.price).filter(StageDB.type == 2).label('revenue'),
            func.avg(
                func.extract('epoch', LeadDB.closed_at) - func.extract('epoch', LeadDB.kommo_created_at)
            ).filter(StageDB.type == 2).label('avg_cycle_seconds'),
        ).select_from(
            UserDB
        ).join(
            LeadDB, LeadDB.responsible_user_id == UserDB.id
        ).join(
            StageDB, StageDB.id == LeadDB.status_id
        ).where(
            UserDB.is_active == True,  # noqa: E712
            LeadDB.kommo_created_at >= date_from,
            LeadDB.kommo_created_at <= date_to,
            LeadDB.is_deleted == False,  # noqa: E712
        ).group_by(
            UserDB.id, UserDB.name
        ).having(
            func.count(LeadDB.id) > 0
        )

        result = await self.session.execute(query)
        rows = result.all()

        if not rows:
            return ManagerRankingReport(
                period_start=date_from,
                period_end=date_to,
                ranking_by=ranking_by,
            )

        managers_data = []
        total_revenue = 0.0
        total_conversion = 0.0
        total_deals = 0

        for row in rows:
            won = row.won or 0
            total = row.total or 0
            revenue = float(row.revenue or 0)
            conversion = (won / total * 100) if total > 0 else 0
            avg_value = revenue / won if won > 0 else 0
            avg_cycle = (row.avg_cycle_seconds or 0) / 86400  # to days

            managers_data.append({
                'user_id': row.id,
                'user_name': row.name or f'User {row.id}',
                'deals_won': won,
                'revenue': revenue,
                'conversion_rate': conversion,
                'avg_deal_value': avg_value,
                'avg_cycle_days': avg_cycle,
            })

            total_revenue += revenue
            total_conversion += conversion
            total_deals += won

        n = len(managers_data)
        avg_revenue = total_revenue / n if n > 0 else 0
        avg_conversion = total_conversion / n if n > 0 else 0
        avg_deals = total_deals / n if n > 0 else 0

        # Sort by ranking criteria
        if ranking_by == 'revenue':
            managers_data.sort(key=lambda x: x['revenue'], reverse=True)
        elif ranking_by == 'conversion':
            managers_data.sort(key=lambda x: x['conversion_rate'], reverse=True)
        else:  # deals_won
            managers_data.sort(key=lambda x: x['deals_won'], reverse=True)

        # Build ranked managers
        managers = []
        for i, m in enumerate(managers_data):
            revenue_vs_avg = ((m['revenue'] - avg_revenue) / avg_revenue * 100) if avg_revenue > 0 else 0
            conversion_vs_avg = ((m['conversion_rate'] - avg_conversion) / avg_conversion * 100) if avg_conversion > 0 else 0

            managers.append(RankedManager(
                user_id=m['user_id'],
                user_name=m['user_name'],
                rank=i + 1,
                deals_won=m['deals_won'],
                revenue=m['revenue'],
                conversion_rate=round(m['conversion_rate'], 1),
                avg_deal_value=round(m['avg_deal_value'], 0),
                avg_cycle_days=round(m['avg_cycle_days'], 1),
                revenue_vs_avg=round(revenue_vs_avg, 1),
                conversion_vs_avg=round(conversion_vs_avg, 1),
            ))

        return ManagerRankingReport(
            period_start=date_from,
            period_end=date_to,
            ranking_by=ranking_by,
            total_managers=n,
            avg_revenue=round(avg_revenue, 0),
            avg_conversion=round(avg_conversion, 1),
            avg_deals=round(avg_deals, 1),
            managers=managers,
        )

    async def period_comparison(
        self,
        period: str = 'month',  # month, quarter, year
        compare_with: str = 'previous',  # previous, yoy (year-over-year)
    ) -> PeriodComparison:
        """
        Compare current period with previous period or same period last year.
        """
        now = datetime.now()

        # Define current period
        if period == 'month':
            current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if current_start.month == 1:
                prev_start = current_start.replace(year=current_start.year - 1, month=12)
            else:
                prev_start = current_start.replace(month=current_start.month - 1)
            period_name = 'Текущий месяц'
            prev_name = 'Прошлый месяц'
        elif period == 'quarter':
            quarter = (now.month - 1) // 3
            current_start = now.replace(month=quarter * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            if quarter == 0:
                prev_start = current_start.replace(year=current_start.year - 1, month=10)
            else:
                prev_start = current_start.replace(month=(quarter - 1) * 3 + 1)
            period_name = 'Текущий квартал'
            prev_name = 'Прошлый квартал'
        else:  # year
            current_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_start = current_start.replace(year=current_start.year - 1)
            period_name = 'Текущий год'
            prev_name = 'Прошлый год'

        current_end = now
        prev_end = current_start

        # For YoY comparison
        if compare_with == 'yoy':
            prev_start = current_start.replace(year=current_start.year - 1)
            prev_end = current_end.replace(year=current_end.year - 1)
            prev_name = f'Тот же период {current_start.year - 1}'

        async def get_period_metrics(start: datetime, end: datetime, name: str) -> PeriodMetrics:
            leads_q = select(func.count(LeadDB.id)).where(
                LeadDB.kommo_created_at >= start,
                LeadDB.kommo_created_at <= end,
                LeadDB.is_deleted == False,  # noqa: E712
            )
            new_leads = (await self.session.execute(leads_q)).scalar() or 0

            won_q = select(
                func.count(LeadDB.id),
                func.sum(LeadDB.price),
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                StageDB.type == 2,
                LeadDB.closed_at >= start,
                LeadDB.closed_at <= end,
            )
            won_result = (await self.session.execute(won_q)).one()
            won_deals = won_result[0] or 0
            revenue = float(won_result[1] or 0)

            lost_q = select(func.count(LeadDB.id)).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                StageDB.type == 3,
                LeadDB.closed_at >= start,
                LeadDB.closed_at <= end,
            )
            lost_deals = (await self.session.execute(lost_q)).scalar() or 0

            total_closed = won_deals + lost_deals
            conversion = (won_deals / total_closed * 100) if total_closed > 0 else 0
            avg_value = revenue / won_deals if won_deals > 0 else 0

            return PeriodMetrics(
                period_name=name,
                date_from=start,
                date_to=end,
                new_leads=new_leads,
                won_deals=won_deals,
                lost_deals=lost_deals,
                revenue=revenue,
                conversion_rate=round(conversion, 1),
                avg_deal_value=round(avg_value, 0),
            )

        current = await get_period_metrics(current_start, current_end, period_name)
        previous = await get_period_metrics(prev_start, prev_end, prev_name)

        def calc_change(curr: float, prev: float) -> float | None:
            if prev == 0:
                return 100.0 if curr > 0 else None
            return round((curr - prev) / prev * 100, 1)

        leads_change = calc_change(current.new_leads, previous.new_leads)
        won_change = calc_change(current.won_deals, previous.won_deals)
        revenue_change = calc_change(current.revenue, previous.revenue)
        conversion_change = calc_change(current.conversion_rate, previous.conversion_rate)
        avg_deal_change = calc_change(current.avg_deal_value, previous.avg_deal_value)

        # Generate insights
        insights = []
        if revenue_change is not None:
            if revenue_change > 10:
                insights.append(f'📈 Выручка выросла на {revenue_change:.0f}%')
            elif revenue_change < -10:
                insights.append(f'📉 Выручка упала на {abs(revenue_change):.0f}%')

        if leads_change is not None:
            if leads_change > 20:
                insights.append(f'🚀 Лидов стало больше на {leads_change:.0f}%')
            elif leads_change < -20:
                insights.append(f'⚠️ Лидов стало меньше на {abs(leads_change):.0f}%')

        if conversion_change is not None and abs(conversion_change) > 5:
            if conversion_change > 0:
                insights.append(f'✅ Конверсия улучшилась на {conversion_change:.0f}%')
            else:
                insights.append(f'❌ Конверсия снизилась на {abs(conversion_change):.0f}%')

        if not insights:
            insights.append('📊 Показатели стабильны')

        return PeriodComparison(
            current=current,
            previous=previous,
            leads_change=leads_change,
            won_change=won_change,
            revenue_change=revenue_change,
            conversion_change=conversion_change,
            avg_deal_change=avg_deal_change,
            insights=insights,
        )

    async def yoy_comparison(
        self,
        month: int | None = None,
    ) -> YoYComparison:
        """
        Year-over-year comparison for a specific month.
        """
        now = datetime.now()
        target_month = month or now.month
        current_year = now.year
        previous_year = current_year - 1

        # Current year period
        current_start = datetime(current_year, target_month, 1)
        if target_month == 12:
            current_end = datetime(current_year + 1, 1, 1) - timedelta(seconds=1)
        else:
            current_end = datetime(current_year, target_month + 1, 1) - timedelta(seconds=1)

        # If we're comparing future month, adjust
        if current_start > now:
            current_end = now

        # Previous year same month
        prev_start = datetime(previous_year, target_month, 1)
        if target_month == 12:
            prev_end = datetime(previous_year + 1, 1, 1) - timedelta(seconds=1)
        else:
            prev_end = datetime(previous_year, target_month + 1, 1) - timedelta(seconds=1)

        async def get_metrics(start: datetime, end: datetime, name: str) -> PeriodMetrics:
            won_q = select(
                func.count(LeadDB.id),
                func.sum(LeadDB.price),
            ).join(
                StageDB, StageDB.id == LeadDB.status_id
            ).where(
                StageDB.type == 2,
                LeadDB.closed_at >= start,
                LeadDB.closed_at <= end,
            )
            result = (await self.session.execute(won_q)).one()
            won = result[0] or 0
            revenue = float(result[1] or 0)

            leads_q = select(func.count(LeadDB.id)).where(
                LeadDB.kommo_created_at >= start,
                LeadDB.kommo_created_at <= end,
                LeadDB.is_deleted == False,  # noqa: E712
            )
            leads = (await self.session.execute(leads_q)).scalar() or 0

            return PeriodMetrics(
                period_name=name,
                date_from=start,
                date_to=end,
                new_leads=leads,
                won_deals=won,
                revenue=revenue,
            )

        current = await get_metrics(current_start, current_end, f'{target_month:02d}.{current_year}')
        previous = await get_metrics(prev_start, prev_end, f'{target_month:02d}.{previous_year}')

        def calc_change(curr: float, prev: float) -> float | None:
            if prev == 0:
                return 100.0 if curr > 0 else None
            return round((curr - prev) / prev * 100, 1)

        revenue_change = calc_change(current.revenue, previous.revenue)
        deals_change = calc_change(current.won_deals, previous.won_deals)

        insights = []
        if revenue_change is not None:
            if revenue_change > 0:
                insights.append(f'📈 Выручка выросла на {revenue_change:.0f}% по сравнению с прошлым годом')
            else:
                insights.append(f'📉 Выручка упала на {abs(revenue_change):.0f}% по сравнению с прошлым годом')

        return YoYComparison(
            current_year=current_year,
            previous_year=previous_year,
            current_month=target_month,
            current=current,
            previous=previous,
            revenue_change=revenue_change,
            deals_change=deals_change,
            insights=insights,
        )
