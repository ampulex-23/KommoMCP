"""Tests for RAG-based tool retriever."""

import pytest
from kommo_mcp.telegram.tool_retriever import ToolRetriever, build_dynamic_prompt


def test_retriever_loads_tools():
    """Test that retriever loads tools from YAML files."""
    retriever = ToolRetriever()
    assert len(retriever.tools) > 0, 'Should load at least one tool'


def test_retriever_finds_analytics_tools():
    """Test that analytics queries find analytics tools."""
    retriever = ToolRetriever()
    
    results = retriever.retrieve('покажи аналитику воронки')
    tool_names = [t['name'] for t in results]
    
    assert 'kommo_pipeline_analytics' in tool_names, 'Should find pipeline analytics'


def test_retriever_finds_deal_tools():
    """Test that deal queries find deal tools."""
    retriever = ToolRetriever()
    
    results = retriever.retrieve('найди сделку Иванов')
    tool_names = [t['name'] for t in results]
    
    assert any('deal' in name or 'search' in name for name in tool_names), 'Should find deal/search tools'


def test_retriever_finds_company_tools():
    """Test that company queries find company tools."""
    retriever = ToolRetriever()
    
    results = retriever.retrieve('создай компанию ООО Рога')
    tool_names = [t['name'] for t in results]
    
    assert 'kommo_companies' in tool_names, 'Should find companies tool'


def test_retriever_finds_call_tools():
    """Test that call queries find call tools."""
    retriever = ToolRetriever()
    
    results = retriever.retrieve('статистика звонков')
    tool_names = [t['name'] for t in results]
    
    assert 'kommo_calls' in tool_names, 'Should find calls tool'


def test_dynamic_prompt_is_compact():
    """Test that dynamic prompt is smaller than static prompt."""
    retriever = ToolRetriever()
    
    # Build dynamic prompt for a specific query
    prompt = build_dynamic_prompt('покажи воронку', retriever, top_k=3)
    
    # Should be compact (less than 2000 chars for 3 tools)
    assert len(prompt) < 3000, f'Prompt should be compact, got {len(prompt)} chars'
    assert 'ДОСТУПНЫЕ ИНСТРУМЕНТЫ' in prompt, 'Should contain tools section'


def test_format_tools_for_prompt():
    """Test tool formatting for prompt."""
    retriever = ToolRetriever()
    
    tools = retriever.retrieve('аналитика', top_k=2)
    formatted = retriever.format_tools_for_prompt(tools)
    
    assert '🔧' in formatted, 'Should contain tool emoji'
    assert len(formatted) > 0, 'Should produce non-empty output'


if __name__ == '__main__':
    # Quick manual test
    retriever = ToolRetriever()
    print(f'Loaded {len(retriever.tools)} tools')
    
    test_queries = [
        'покажи аналитику воронки',
        'найди сделку Иванов',
        'создай компанию',
        'статистика звонков',
        'добавь тег VIP',
        'покажи каталоги товаров',
    ]
    
    for query in test_queries:
        results = retriever.retrieve(query, top_k=3)
        print(f'\n"{query}" -> {[t["name"] for t in results]}')
