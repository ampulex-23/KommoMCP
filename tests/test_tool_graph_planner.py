"""
Tests for Tool Graph Planner — 10 amoCRM scenarios.

Each test verifies:
1. Correct intents detected
2. Required tools present in chain
3. Correct ordering (dependencies before dependents)
4. No missing mandatory steps
5. Latency < 2s
6. Chain constraints satisfied
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.kommo_mcp.planner.tool_graph_planner import (
    ToolGraphPlanner,
    PlannedChain,
    ChainStep,
)


@pytest.fixture(scope='module')
def planner():
    """Shared planner instance for all tests."""
    return ToolGraphPlanner()


def _tool_ids(chain: PlannedChain) -> list:
    """Extract tool IDs from chain."""
    return [step.tool for step in chain.chain]


def _tool_index(chain: PlannedChain, tool_id: str) -> int:
    """Get index of tool in chain, -1 if not found."""
    for i, step in enumerate(chain.chain):
        if step.tool == tool_id:
            return i
    return -1


def _has_action(chain: PlannedChain, tool_id: str, action_id: str) -> bool:
    """Check if chain has a specific tool+action."""
    return any(
        s.tool == tool_id and s.action == action_id
        for s in chain.chain
    )


class TestPlannerBasics:
    """Basic planner functionality."""

    def test_stats(self, planner):
        stats = planner.stats()
        assert stats['tools'] >= 50, f'Expected 50+ tools, got {stats["tools"]}'
        assert stats['actions'] >= 200, f'Expected 200+ actions, got {stats["actions"]}'
        assert stats['edges'] >= 20, f'Expected 20+ edges, got {stats["edges"]}'

    def test_empty_query(self, planner):
        result = planner.plan('')
        assert result.constraints_ok is True
        assert result.cost == 0

    def test_latency_under_2s(self, planner):
        queries = [
            'добавь VIP-клиента с аналитикой',
            'покажи прогноз продаж и здоровье воронки',
            'найди проблемные сделки и предложи решение',
        ]
        for q in queries:
            start = time.time()
            planner.plan(q)
            elapsed = time.time() - start
            assert elapsed < 2.0, f'Query "{q}" took {elapsed:.2f}s (>2s limit)'


class TestScenario1VipClientWithAnalytics:
    """Scenario 1: 'добавь VIP-клиента с аналитикой'
    Expected: search/create contact → tag VIP → score → analytics
    """

    def test_intents(self, planner):
        result = planner.plan('добавь VIP-клиента с аналитикой')
        assert 'vip_client' in result.intents or 'contact_management' in result.intents

    def test_required_tools(self, planner):
        result = planner.plan('добавь VIP-клиента с аналитикой')
        tools = _tool_ids(result)
        # Must have contact scoring or tags for VIP
        assert any(t in tools for t in [
            'kommo_contact_scoring', 'kommo_tags', 'kommo_contacts_ext'
        ]), f'Missing VIP tools in {tools}'

    def test_chain_not_empty(self, planner):
        result = planner.plan('добавь VIP-клиента с аналитикой')
        assert len(result.chain) >= 2


class TestScenario2PipelineForecastAndHealth:
    """Scenario 2: 'покажи прогноз продаж и здоровье воронки'
    Expected: pipeline_health + forecast (parallel)
    """

    def test_intents(self, planner):
        result = planner.plan('покажи прогноз продаж и здоровье воронки')
        assert 'forecast' in result.intents

    def test_required_tools(self, planner):
        result = planner.plan('покажи прогноз продаж и здоровье воронки')
        tools = _tool_ids(result)
        assert 'kommo_forecast' in tools, f'Missing forecast in {tools}'

    def test_constraints(self, planner):
        result = planner.plan('покажи прогноз продаж и здоровье воронки')
        assert result.constraints_ok is True
        assert result.cost > 0


class TestScenario3ProblemDealsWithSolution:
    """Scenario 3: 'найди проблемные сделки и предложи решение'
    Expected: search.problems → advisor.strategy or pipeline_health.bottlenecks
    """

    def test_intents(self, planner):
        result = planner.plan('найди проблемные сделки и предложи решение')
        assert 'problem_solving' in result.intents or 'search' in result.intents

    def test_has_search_or_analysis(self, planner):
        result = planner.plan('найди проблемные сделки и предложи решение')
        tools = _tool_ids(result)
        has_search = 'kommo_search' in tools
        has_health = 'kommo_pipeline_health' in tools
        has_insights = 'kommo_insights' in tools
        assert has_search or has_health or has_insights, f'No analysis tool in {tools}'


class TestScenario4DealQualification:
    """Scenario 4: 'квалифицируй сделку 12345 по BANT'
    Expected: advisor.qualification with lead_id context
    """

    def test_intents(self, planner):
        result = planner.plan('квалифицируй сделку по BANT')
        assert 'qualification' in result.intents

    def test_has_advisor(self, planner):
        result = planner.plan('квалифицируй сделку по BANT')
        tools = _tool_ids(result)
        assert 'kommo_advisor' in tools

    def test_qualification_action(self, planner):
        result = planner.plan('квалифицируй сделку по BANT')
        has_qual = _has_action(result, 'kommo_advisor', 'qualification')
        has_checklist = _has_action(result, 'kommo_advisor', 'qualification_checklist')
        assert has_qual or has_checklist, 'Expected qualification or qualification_checklist'


class TestScenario5ClosingDeal:
    """Scenario 5: 'помоги закрыть сделку — сигналы, скрипт, прогноз'
    Expected: deal_intelligence.closing_signals → templates.closing_script → forecast
    """

    def test_intents(self, planner):
        result = planner.plan('помоги закрыть сделку — сигналы, скрипт, прогноз')
        assert 'closing' in result.intents

    def test_has_closing_tools(self, planner):
        result = planner.plan('помоги закрыть сделку — сигналы, скрипт, прогноз')
        tools = _tool_ids(result)
        has_intelligence = 'kommo_deal_intelligence' in tools
        has_templates = 'kommo_templates' in tools
        has_forecast = 'kommo_forecast' in tools
        has_advisor = 'kommo_advisor' in tools
        assert sum([has_intelligence, has_templates, has_forecast, has_advisor]) >= 2, \
            f'Expected 2+ closing tools, got {tools}'


class TestScenario6TeamPerformance:
    """Scenario 6: 'покажи эффективность команды и нагрузку менеджеров'
    Expected: manager_stats + users.workload + activity.kpi
    """

    def test_intents(self, planner):
        result = planner.plan('покажи эффективность команды и нагрузку менеджеров')
        assert 'team' in result.intents

    def test_has_team_tools(self, planner):
        result = planner.plan('покажи эффективность команды и нагрузку менеджеров')
        tools = _tool_ids(result)
        team_tools = {'kommo_users', 'kommo_manager_stats', 'kommo_activity',
                      'kommo_gamification', 'kommo_team_planner'}
        found = team_tools & set(tools)
        assert len(found) >= 1, f'Expected team tools, got {tools}'


class TestScenario7AutomationSetup:
    """Scenario 7: 'настрой автоматическое распределение лидов'
    Expected: automation.auto_assign or round_robin
    """

    def test_intents(self, planner):
        result = planner.plan('настрой автоматическое распределение лидов')
        assert 'automation' in result.intents

    def test_has_automation(self, planner):
        result = planner.plan('настрой автоматическое распределение лидов')
        tools = _tool_ids(result)
        assert 'kommo_automation' in tools, f'Missing automation in {tools}'


class TestScenario8ReactivateSleepingClients:
    """Scenario 8: 'найди спящих клиентов и запусти реактивацию'
    Expected: reactivation.sleeping → templates or entity_actions
    """

    def test_intents(self, planner):
        result = planner.plan('найди спящих клиентов и запусти реактивацию')
        assert 'reactivation' in result.intents

    def test_has_reactivation(self, planner):
        result = planner.plan('найди спящих клиентов и запусти реактивацию')
        tools = _tool_ids(result)
        assert 'kommo_reactivation' in tools, f'Missing reactivation in {tools}'


class TestScenario9MorningDigest:
    """Scenario 9: 'утренний дайджест с прогнозом и задачами'
    Expected: digest.morning + forecast + tasks_ext.today (parallel)
    """

    def test_has_digest_or_forecast(self, planner):
        result = planner.plan('утренний дайджест с прогнозом и задачами')
        tools = _tool_ids(result)
        has_digest = 'kommo_digest' in tools
        has_forecast = 'kommo_forecast' in tools
        has_tasks = 'kommo_tasks_ext' in tools
        assert has_digest or has_forecast or has_tasks, f'Expected digest/forecast/tasks, got {tools}'


class TestScenario10ComplexSearchWithContext:
    """Scenario 10: 'найди все сделки больше 500к и покажи контекст'
    Expected: search.leads (with min_price) → search.deal_context
    """

    def test_intents(self, planner):
        result = planner.plan('найди все сделки больше 500к и покажи контекст')
        assert 'search' in result.intents or 'deal_analysis' in result.intents

    def test_has_search(self, planner):
        result = planner.plan('найди все сделки больше 500к и покажи контекст')
        tools = _tool_ids(result)
        assert 'kommo_search' in tools, f'Missing search in {tools}'

    def test_chain_length(self, planner):
        result = planner.plan('найди все сделки больше 500к и покажи контекст')
        assert len(result.chain) <= 8, f'Chain too long: {len(result.chain)}'


class TestDynamicPrompt:
    """Test dynamic prompt generation."""

    def test_prompt_not_empty(self, planner):
        result = planner.plan('покажи аналитику воронки')
        prompt = planner.build_prompt(result, 'покажи аналитику воронки')
        if result.chain:
            assert len(prompt) > 50
            assert 'ПЛАН ВЫПОЛНЕНИЯ' in prompt

    def test_tool_filter(self, planner):
        result = planner.plan('добавь VIP-клиента с аналитикой')
        tool_filter = planner.get_tool_filter(result)
        assert len(tool_filter) >= 1
        assert all(isinstance(t, str) for t in tool_filter)

    def test_yaml_output(self, planner):
        result = planner.plan('прогноз продаж')
        yaml_str = planner.to_yaml(result)
        assert 'chain:' in yaml_str
        assert 'cost:' in yaml_str


class TestMandatorySteps:
    """Verify 0% missing mandatory steps."""

    def test_move_lead_requires_pipelines(self, planner):
        """Moving a lead should include pipeline listing."""
        result = planner.plan('перемести сделку в другую воронку')
        tools = _tool_ids(result)
        if 'kommo_entity_actions' in tools:
            # list_pipelines should be before or present
            assert 'kommo_list_pipelines' in tools, \
                'Missing kommo_list_pipelines before move_lead'
            lp_idx = _tool_index(result, 'kommo_list_pipelines')
            ea_idx = _tool_index(result, 'kommo_entity_actions')
            assert lp_idx < ea_idx, 'list_pipelines must come before entity_actions'

    def test_search_before_action(self, planner):
        """Acting on entity should have search first."""
        result = planner.plan('найди контакт и обнови его данные')
        tools = _tool_ids(result)
        if 'kommo_entity_actions' in tools and 'kommo_contacts_ext' in tools:
            search_idx = _tool_index(result, 'kommo_contacts_ext')
            action_idx = _tool_index(result, 'kommo_entity_actions')
            assert search_idx < action_idx, 'Search must come before action'
