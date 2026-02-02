"""
AI Chat module - integrates OpenAI with MCP tools.
"""

import json
import logging
from typing import Optional, List, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)

# Available MCP tools for AI
MCP_TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'kommo_pipeline_analytics',
            'description': 'Get pipeline analytics: conversion rates, deal counts, revenue by stage',
            'parameters': {
                'type': 'object',
                'properties': {
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'date_from': {'type': 'string', 'description': 'Start date YYYY-MM-DD'},
                    'date_to': {'type': 'string', 'description': 'End date YYYY-MM-DD'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_manager_stats',
            'description': 'Get manager performance statistics',
            'parameters': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'Manager ID (optional)'},
                    'date_from': {'type': 'string', 'description': 'Start date'},
                    'date_to': {'type': 'string', 'description': 'End date'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_deals_ext',
            'description': 'Extended deal management: by_stage, health, velocity, at_risk, by_user',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['by_stage', 'health', 'velocity', 'at_risk', 'by_user'],
                        'description': 'Action to perform',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                    'limit': {'type': 'integer', 'description': 'Max results'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_tasks_ext',
            'description': 'Task management: overdue, stats, by_entity, today, without_responsible',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['overdue', 'stats', 'by_entity', 'today', 'without_responsible'],
                        'description': 'Action to perform',
                    },
                    'user_id': {'type': 'integer', 'description': 'User ID'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                    'limit': {'type': 'integer', 'description': 'Max results'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_contacts_ext',
            'description': 'Contact management: search, without_deals, linked, activity, by_responsible, recent',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['search', 'without_deals', 'linked', 'activity', 'by_responsible', 'recent'],
                        'description': 'Action to perform',
                    },
                    'query': {'type': 'string', 'description': 'Search query'},
                    'contact_id': {'type': 'integer', 'description': 'Contact ID'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                    'limit': {'type': 'integer', 'description': 'Max results'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_communications',
            'description': 'Communication history: history, calls, timeline, last_contact, by_user, summary, no_contact',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['history', 'calls', 'timeline', 'last_contact', 'by_user', 'summary', 'no_contact'],
                        'description': 'Action to perform',
                    },
                    'entity_type': {'type': 'string', 'enum': ['leads', 'contacts', 'companies']},
                    'entity_id': {'type': 'integer', 'description': 'Entity ID'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_insights',
            'description': 'Business insights: top_clients, rfm, workload, opportunities, big_deals, ranking, compare, yoy',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['top_clients', 'rfm', 'workload', 'opportunities', 'big_deals', 'ranking', 'compare', 'yoy'],
                        'description': 'Action to perform',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                    'limit': {'type': 'integer', 'description': 'Max results'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_search',
            'description': 'Search CRM: all, leads, contacts, query, related, recent, similar',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['all', 'leads', 'contacts', 'query', 'related', 'recent', 'similar'],
                        'description': 'Search action',
                    },
                    'query': {'type': 'string', 'description': 'Search query'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'min_price': {'type': 'number', 'description': 'Minimum price'},
                    'limit': {'type': 'integer', 'description': 'Max results'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_ltv',
            'description': 'Customer LTV analytics: by_source, by_pipeline, cohorts, segments',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['by_source', 'by_pipeline', 'cohorts', 'segments'],
                        'description': 'LTV action',
                    },
                    'days': {'type': 'integer', 'description': 'Period in days'},
                },
                'required': ['action'],
            },
        },
    },
]

SYSTEM_PROMPT = """Ты - AI-ассистент для работы с CRM Kommo. 
Ты помогаешь пользователям анализировать данные CRM, отвечать на вопросы о сделках, контактах, задачах и менеджерах.

Правила:
1. Отвечай кратко и по делу
2. Используй доступные инструменты для получения данных
3. Форматируй ответы для Telegram (HTML)
4. Если данных нет - скажи об этом
5. Не выдумывай данные

Доступные инструменты позволяют:
- Анализировать воронки и конверсии
- Смотреть статистику менеджеров
- Искать сделки, контакты, компании
- Анализировать задачи
- Смотреть историю коммуникаций
- Получать бизнес-инсайты и LTV
"""


class AIChat:
    """AI Chat with OpenAI and MCP integration."""
    
    def __init__(
        self,
        openai_api_key: str,
        mcp_url: str,
        model: str = 'gpt-4o-mini',
    ):
        self.openai_api_key = openai_api_key
        self.mcp_url = mcp_url
        self.model = model
    
    async def chat(self, message: str) -> str:
        """Process user message and return response."""
        try:
            # Initial request to OpenAI
            response = await self._openai_request(
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': message},
                ],
                tools=MCP_TOOLS,
            )
            
            # Check if tool call is needed
            if response.get('tool_calls'):
                # Execute tool calls
                tool_results = await self._execute_tool_calls(response['tool_calls'])
                
                # Send results back to OpenAI
                messages = [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': message},
                    {'role': 'assistant', 'content': None, 'tool_calls': response['tool_calls']},
                ]
                
                for tool_call, result in zip(response['tool_calls'], tool_results):
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call['id'],
                        'content': json.dumps(result, ensure_ascii=False),
                    })
                
                # Get final response
                final_response = await self._openai_request(messages=messages)
                return final_response.get('content', 'Не удалось получить ответ')
            
            return response.get('content', 'Не удалось получить ответ')
        
        except Exception as e:
            logger.error(f'Chat error: {e}')
            return f'❌ Ошибка: {e}'
    
    async def _openai_request(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Make request to OpenAI API."""
        async with aiohttp.ClientSession() as session:
            payload = {
                'model': self.model,
                'messages': messages,
            }
            
            if tools:
                payload['tools'] = tools
                payload['tool_choice'] = 'auto'
            
            headers = {
                'Authorization': f'Bearer {self.openai_api_key}',
                'Content-Type': 'application/json',
            }
            
            async with session.post(
                'https://api.openai.com/v1/chat/completions',
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise Exception(f'OpenAI API error: {error}')
                
                data = await resp.json()
                choice = data['choices'][0]['message']
                
                return {
                    'content': choice.get('content'),
                    'tool_calls': choice.get('tool_calls'),
                }
    
    async def _execute_tool_calls(self, tool_calls: List[Dict]) -> List[Dict]:
        """Execute MCP tool calls."""
        results = []
        
        async with aiohttp.ClientSession() as session:
            for tool_call in tool_calls:
                func = tool_call['function']
                name = func['name']
                args = json.loads(func['arguments'])
                
                # Call MCP
                payload = {
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'tools/call',
                    'params': {
                        'name': name,
                        'arguments': args,
                    },
                }
                
                try:
                    async with session.post(self.mcp_url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result = data.get('result', {})
                            # Extract text content
                            content = result.get('content', [])
                            if content and isinstance(content, list):
                                text = content[0].get('text', '{}')
                                results.append(json.loads(text))
                            else:
                                results.append(result)
                        else:
                            results.append({'error': f'MCP error: {resp.status}'})
                except Exception as e:
                    logger.error(f'Tool call error: {e}')
                    results.append({'error': str(e)})
        
        return results
