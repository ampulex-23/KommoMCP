"""Analytics data models."""

from datetime import datetime
from pydantic import BaseModel, Field


class StageSummary(BaseModel):
    """Summary for a single pipeline stage."""
    
    stage_id: int
    stage_name: str
    stage_type: int = 0  # 0=normal, 1=incoming, 2=won, 3=lost
    leads_count: int = 0
    total_value: float = 0.0
    avg_value: float = 0.0
    conversion_to_next: float = 0.0


class PipelineSummary(BaseModel):
    """Pipeline analytics summary."""
    
    pipeline_id: int
    pipeline_name: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    
    # Counts
    total_leads: int = 0
    won_leads: int = 0
    lost_leads: int = 0
    in_progress: int = 0
    
    # Values
    total_value: float = 0.0
    avg_value: float = 0.0
    won_value: float = 0.0
    
    # Metrics
    conversion_rate: float = 0.0
    avg_cycle_days: float = 0.0
    
    # Stage breakdown
    stages: list[StageSummary] = Field(default_factory=list)


class FunnelStage(BaseModel):
    """Funnel stage with conversion metrics."""
    
    stage_id: int
    stage_name: str
    sort: int = 0
    entered: int = 0
    exited_to_next: int = 0
    exited_to_won: int = 0
    exited_to_lost: int = 0
    conversion_rate: float = 0.0
    avg_time_on_stage_days: float = 0.0


class FunnelAnalysis(BaseModel):
    """Detailed funnel conversion analysis."""
    
    pipeline_id: int
    pipeline_name: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    stages: list[FunnelStage] = Field(default_factory=list)
    overall_conversion: float = 0.0


class ManagerPerformance(BaseModel):
    """Manager performance metrics."""
    
    user_id: int
    user_name: str
    period: str = 'month'
    
    # Lead metrics
    leads_created: int = 0
    leads_won: int = 0
    leads_lost: int = 0
    leads_in_progress: int = 0
    win_rate: float = 0.0
    
    # Revenue metrics
    total_revenue: float = 0.0
    avg_deal_size: float = 0.0
    
    # Activity metrics
    tasks_completed: int = 0
    tasks_overdue: int = 0
    calls_made: int = 0
    meetings_held: int = 0
    
    # Efficiency
    avg_cycle_days: float = 0.0


class StageForecast(BaseModel):
    """Forecast for a single stage."""
    
    stage_id: int
    stage_name: str
    deals_count: int = 0
    total_value: float = 0.0
    probability: float = 0.0
    expected_value: float = 0.0


class SalesForecast(BaseModel):
    """Sales forecast based on pipeline analysis."""
    
    period: str
    forecast_date: datetime
    
    # Revenue projections
    expected_revenue: float = 0.0
    optimistic_revenue: float = 0.0
    pessimistic_revenue: float = 0.0
    
    # Pipeline metrics
    deals_in_pipeline: int = 0
    weighted_pipeline_value: float = 0.0
    
    # By stage breakdown
    by_stage: list[StageForecast] = Field(default_factory=list)


class RevenuePeriod(BaseModel):
    """Revenue for a specific period."""
    
    period: str  # e.g., '2024-01', '2024-W05'
    period_start: datetime
    period_end: datetime
    
    leads_won: int = 0
    revenue: float = 0.0
    avg_deal_size: float = 0.0
    
    # Comparison with previous period
    revenue_change: float | None = None
    revenue_change_pct: float | None = None


class ActivityReport(BaseModel):
    """Activity report for a period."""
    
    period_start: datetime | None = None
    period_end: datetime | None = None
    
    total_tasks: int = 0
    completed_tasks: int = 0
    overdue_tasks: int = 0
    
    calls_made: int = 0
    meetings_held: int = 0
    emails_sent: int = 0
    notes_added: int = 0
    
    # By user breakdown
    by_user: list[dict] = Field(default_factory=list)
