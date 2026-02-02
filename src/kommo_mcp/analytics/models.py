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


class TopClient(BaseModel):
    """Top client by revenue."""
    
    contact_id: int | None = None
    company_id: int | None = None
    name: str
    total_revenue: float = 0.0
    deals_count: int = 0
    won_deals: int = 0
    avg_deal_value: float = 0.0
    last_deal_date: datetime | None = None


class TopClientsReport(BaseModel):
    """Top clients report."""
    
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_revenue: float = 0.0
    clients: list[TopClient] = Field(default_factory=list)


class RFMSegment(BaseModel):
    """RFM segment with clients."""
    
    segment: str  # Champions, Loyal, At Risk, etc.
    r_score: int  # 1-5
    f_score: int  # 1-5
    m_score: int  # 1-5
    count: int = 0
    total_revenue: float = 0.0
    description: str = ''


class RFMClient(BaseModel):
    """Client with RFM scores."""
    
    contact_id: int | None = None
    company_id: int | None = None
    name: str
    recency_days: int = 0
    frequency: int = 0
    monetary: float = 0.0
    r_score: int = 1
    f_score: int = 1
    m_score: int = 1
    segment: str = ''


class RFMReport(BaseModel):
    """RFM analysis report."""
    
    total_clients: int = 0
    segments: list[RFMSegment] = Field(default_factory=list)
    clients: list[RFMClient] = Field(default_factory=list)


class ManagerWorkload(BaseModel):
    """Manager workload metrics."""
    
    user_id: int
    user_name: str
    active_deals: int = 0
    active_deals_value: float = 0.0
    overdue_tasks: int = 0
    tasks_today: int = 0
    avg_deals_per_day: float = 0.0
    capacity_score: int = 0  # 0-100, 100 = overloaded


class WorkloadReport(BaseModel):
    """Team workload report."""
    
    total_active_deals: int = 0
    avg_deals_per_manager: float = 0.0
    overloaded_managers: int = 0
    underloaded_managers: int = 0
    managers: list[ManagerWorkload] = Field(default_factory=list)


class Opportunity(BaseModel):
    """Sales opportunity."""
    
    type: str  # upsell, cross_sell, reactivation, renewal
    contact_id: int | None = None
    company_id: int | None = None
    name: str
    last_deal_value: float = 0.0
    potential_value: float = 0.0
    days_since_last_deal: int = 0
    reason: str = ''


class OpportunitiesReport(BaseModel):
    """Opportunities report."""
    
    total_opportunities: int = 0
    total_potential_value: float = 0.0
    upsell: list[Opportunity] = Field(default_factory=list)
    cross_sell: list[Opportunity] = Field(default_factory=list)
    reactivation: list[Opportunity] = Field(default_factory=list)


class BigDeal(BaseModel):
    """Big deal in pipeline."""
    
    lead_id: int
    lead_name: str
    price: float
    pipeline_name: str
    stage_name: str
    responsible_user: str | None = None
    days_in_pipeline: int = 0
    probability: float = 0.0


class BigDealsReport(BaseModel):
    """Big deals report."""
    
    threshold: float = 0.0
    total_count: int = 0
    total_value: float = 0.0
    deals: list[BigDeal] = Field(default_factory=list)


class Alert(BaseModel):
    """Single alert item."""
    
    type: str  # stale_deals, overdue_tasks, performance_drop, churn_risk, big_deal
    severity: str = 'medium'  # low, medium, high, critical
    title: str
    description: str
    entity_type: str | None = None  # leads, contacts, users
    entity_id: int | None = None
    entity_name: str | None = None
    value: float | None = None
    action_suggested: str | None = None


class AlertsReport(BaseModel):
    """Alerts report."""
    
    generated_at: datetime
    total_alerts: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    alerts: list[Alert] = Field(default_factory=list)


class DigestMetric(BaseModel):
    """Single metric for digest."""
    
    name: str
    value: float
    previous_value: float | None = None
    change_percent: float | None = None
    trend: str = 'stable'  # up, down, stable


class DailyDigest(BaseModel):
    """Daily digest report."""
    
    date: datetime
    period: str = 'day'  # day, week, month
    
    # Key metrics
    new_leads: int = 0
    won_deals: int = 0
    lost_deals: int = 0
    revenue: float = 0.0
    
    # Comparisons
    new_leads_change: float | None = None
    won_deals_change: float | None = None
    revenue_change: float | None = None
    
    # Top performers
    top_manager: str | None = None
    top_manager_revenue: float = 0.0
    
    # Alerts summary
    critical_alerts: int = 0
    pending_tasks: int = 0
    overdue_tasks: int = 0
    
    # Highlights
    highlights: list[str] = Field(default_factory=list)
    metrics: list[DigestMetric] = Field(default_factory=list)


class RankedManager(BaseModel):
    """Manager with ranking metrics."""
    
    user_id: int
    user_name: str
    rank: int = 0
    
    # Metrics
    deals_won: int = 0
    revenue: float = 0.0
    conversion_rate: float = 0.0
    avg_deal_value: float = 0.0
    avg_cycle_days: float = 0.0
    
    # Comparison to average
    revenue_vs_avg: float = 0.0  # percent above/below average
    conversion_vs_avg: float = 0.0


class ManagerRankingReport(BaseModel):
    """Manager ranking report."""
    
    period_start: datetime | None = None
    period_end: datetime | None = None
    ranking_by: str = 'revenue'  # revenue, conversion, deals_won
    
    total_managers: int = 0
    avg_revenue: float = 0.0
    avg_conversion: float = 0.0
    avg_deals: float = 0.0
    
    managers: list[RankedManager] = Field(default_factory=list)


class PeriodMetrics(BaseModel):
    """Metrics for a single period."""
    
    period_name: str  # "Текущий месяц", "Прошлый год"
    date_from: datetime
    date_to: datetime
    
    new_leads: int = 0
    won_deals: int = 0
    lost_deals: int = 0
    revenue: float = 0.0
    conversion_rate: float = 0.0
    avg_deal_value: float = 0.0
    avg_cycle_days: float = 0.0


class PeriodComparison(BaseModel):
    """Comparison between two periods."""
    
    current: PeriodMetrics
    previous: PeriodMetrics
    
    # Changes (percent)
    leads_change: float | None = None
    won_change: float | None = None
    revenue_change: float | None = None
    conversion_change: float | None = None
    avg_deal_change: float | None = None
    
    # Insights
    insights: list[str] = Field(default_factory=list)


class YoYComparison(BaseModel):
    """Year-over-year comparison."""
    
    current_year: int
    previous_year: int
    current_month: int
    
    current: PeriodMetrics
    previous: PeriodMetrics
    
    revenue_change: float | None = None
    deals_change: float | None = None
    
    insights: list[str] = Field(default_factory=list)
