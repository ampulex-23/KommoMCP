"""Analytics engine module."""

from kommo_mcp.analytics.engine import AnalyticsEngine
from kommo_mcp.analytics.models import (
    FunnelAnalysis,
    FunnelStage,
    ManagerPerformance,
    PipelineSummary,
    SalesForecast,
    StageForecast,
    StageSummary,
)

__all__ = [
    'AnalyticsEngine',
    'PipelineSummary',
    'StageSummary',
    'FunnelAnalysis',
    'FunnelStage',
    'ManagerPerformance',
    'SalesForecast',
    'StageForecast',
]
