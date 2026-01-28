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


class StaleDeal(BaseModel):
    """A deal that has been inactive for too long."""
    
    lead_id: int
    lead_name: str
    pipeline_name: str
    stage_name: str
    responsible_user: str | None = None
    price: float = 0.0
    days_inactive: int = 0
    last_activity: datetime | None = None
    created_at: datetime | None = None


class StaleDealsReport(BaseModel):
    """Report of stale/stuck deals."""
    
    threshold_days: int
    total_stale: int = 0
    total_value: float = 0.0
    deals: list[StaleDeal] = Field(default_factory=list)
    by_stage: dict[str, int] = Field(default_factory=dict)
    by_manager: dict[str, int] = Field(default_factory=dict)


class LeadSource(BaseModel):
    """Analytics for a single lead source."""
    
    source_name: str
    leads_count: int = 0
    won_count: int = 0
    lost_count: int = 0
    in_progress: int = 0
    total_value: float = 0.0
    won_value: float = 0.0
    conversion_rate: float = 0.0
    avg_deal_size: float = 0.0


class LeadSourcesReport(BaseModel):
    """Report of lead sources analytics."""
    
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_leads: int = 0
    sources: list[LeadSource] = Field(default_factory=list)


class RevenueTrendPeriod(BaseModel):
    """Revenue data for a single period."""
    
    period: str  # e.g., '2024-01', '2024-W05'
    period_start: datetime
    period_end: datetime
    leads_won: int = 0
    revenue: float = 0.0
    avg_deal_size: float = 0.0
    change_pct: float | None = None  # vs previous period


class RevenueTrendReport(BaseModel):
    """Revenue trend over time."""
    
    group_by: str  # day, week, month
    pipeline_id: int | None = None
    periods: list[RevenueTrendPeriod] = Field(default_factory=list)
    total_revenue: float = 0.0
    avg_revenue_per_period: float = 0.0
    trend_direction: str = 'stable'  # up, down, stable


class ChurnRiskContact(BaseModel):
    """Contact with churn risk assessment."""
    
    contact_id: int
    contact_name: str
    company_name: str | None = None
    last_deal_date: datetime | None = None
    days_since_last_deal: int = 0
    total_deals: int = 0
    total_revenue: float = 0.0
    risk_level: str = 'low'  # low, medium, high, critical
    risk_score: int = 0  # 0-100


class ChurnRiskReport(BaseModel):
    """Churn risk analysis report."""
    
    total_contacts: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    potential_revenue_at_risk: float = 0.0
    contacts: list[ChurnRiskContact] = Field(default_factory=list)


class ScoredLead(BaseModel):
    """Lead with calculated score."""
    
    lead_id: int
    lead_name: str
    pipeline_name: str
    stage_name: str
    responsible_user: str | None = None
    price: float = 0.0
    score: int = 0  # 0-100
    score_breakdown: dict = Field(default_factory=dict)
    recommendation: str = ''


class LeadScoreReport(BaseModel):
    """Lead scoring report."""
    
    total_leads: int = 0
    hot_leads: int = 0  # score >= 70
    warm_leads: int = 0  # score 40-69
    cold_leads: int = 0  # score < 40
    leads: list[ScoredLead] = Field(default_factory=list)


class DuplicateGroup(BaseModel):
    """Group of duplicate contacts."""
    
    match_field: str  # phone, email, name
    match_value: str
    contacts: list[dict] = Field(default_factory=list)


class DuplicatesReport(BaseModel):
    """Report of found duplicates."""
    
    entity_type: str  # contacts, companies
    total_groups: int = 0
    total_duplicates: int = 0
    groups: list[DuplicateGroup] = Field(default_factory=list)
