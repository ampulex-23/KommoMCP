"""Tests for Analytics Engine."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from kommo_mcp.analytics.models import (
    PipelineSummary,
    StageSummary,
    ManagerPerformance,
    SalesForecast,
    RevenuePeriod,
    ActivityReport,
)


class TestAnalyticsModels:
    """Test analytics Pydantic models."""

    def test_pipeline_summary_defaults(self):
        """Test PipelineSummary with minimal data."""
        summary = PipelineSummary(
            pipeline_id=1,
            pipeline_name='Test Pipeline',
        )
        assert summary.pipeline_id == 1
        assert summary.total_leads == 0
        assert summary.conversion_rate == 0.0
        assert summary.stages == []

    def test_pipeline_summary_with_stages(self):
        """Test PipelineSummary with stages."""
        stages = [
            StageSummary(
                stage_id=101,
                stage_name='New',
                leads_count=10,
                total_value=100000,
            ),
            StageSummary(
                stage_id=102,
                stage_name='In Progress',
                leads_count=5,
                total_value=75000,
            ),
        ]
        summary = PipelineSummary(
            pipeline_id=1,
            pipeline_name='Test Pipeline',
            total_leads=15,
            total_value=175000,
            stages=stages,
        )
        assert len(summary.stages) == 2
        assert summary.total_leads == 15

    def test_manager_performance(self):
        """Test ManagerPerformance model."""
        perf = ManagerPerformance(
            user_id=1,
            user_name='Test Manager',
            leads_created=50,
            leads_won=20,
            leads_lost=10,
            win_rate=0.67,
            total_revenue=500000,
        )
        assert perf.win_rate == 0.67
        assert perf.leads_in_progress == 0  # default

    def test_sales_forecast(self):
        """Test SalesForecast model."""
        forecast = SalesForecast(
            period='30 days',
            forecast_date=datetime.now(),
            expected_revenue=1000000,
            optimistic_revenue=1300000,
            pessimistic_revenue=700000,
            deals_in_pipeline=25,
        )
        assert forecast.expected_revenue == 1000000
        assert forecast.by_stage == []

    def test_revenue_period(self):
        """Test RevenuePeriod model."""
        period = RevenuePeriod(
            period='2024-01',
            period_start=datetime(2024, 1, 1),
            period_end=datetime(2024, 2, 1),
            leads_won=15,
            revenue=750000,
            avg_deal_size=50000,
        )
        assert period.revenue == 750000
        assert period.revenue_change is None

    def test_activity_report(self):
        """Test ActivityReport model."""
        report = ActivityReport(
            total_tasks=100,
            completed_tasks=80,
            overdue_tasks=5,
            calls_made=50,
            meetings_held=20,
        )
        assert report.completed_tasks == 80
        assert report.by_user == []


class TestPipelineSummaryCalculations:
    """Test pipeline summary calculation logic."""

    def test_conversion_rate_calculation(self):
        """Test conversion rate is calculated correctly."""
        summary = PipelineSummary(
            pipeline_id=1,
            pipeline_name='Test',
            won_leads=30,
            lost_leads=70,
            conversion_rate=0.30,  # 30 / (30 + 70)
        )
        assert summary.conversion_rate == 0.30

    def test_zero_closed_leads(self):
        """Test handling of zero closed leads."""
        summary = PipelineSummary(
            pipeline_id=1,
            pipeline_name='Test',
            total_leads=50,
            won_leads=0,
            lost_leads=0,
            in_progress=50,
            conversion_rate=0.0,
        )
        assert summary.conversion_rate == 0.0


class TestModelSerialization:
    """Test model serialization."""

    def test_pipeline_summary_to_dict(self):
        """Test PipelineSummary serialization."""
        summary = PipelineSummary(
            pipeline_id=1,
            pipeline_name='Test Pipeline',
            total_leads=100,
            conversion_rate=0.25,
        )
        data = summary.model_dump()
        
        assert data['pipeline_id'] == 1
        assert data['pipeline_name'] == 'Test Pipeline'
        assert data['total_leads'] == 100
        assert data['conversion_rate'] == 0.25

    def test_sales_forecast_to_dict(self):
        """Test SalesForecast serialization."""
        forecast = SalesForecast(
            period='30 days',
            forecast_date=datetime(2024, 1, 15, 12, 0, 0),
            expected_revenue=1000000,
        )
        data = forecast.model_dump()
        
        assert data['period'] == '30 days'
        assert data['expected_revenue'] == 1000000
        assert 'forecast_date' in data
