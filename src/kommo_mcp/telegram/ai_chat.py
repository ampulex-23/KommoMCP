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
            'name': 'kommo_list_pipelines',
            'description': 'Get list of all pipelines (воронки) with their stages. Use this to see what pipelines exist.',
            'parameters': {
                'type': 'object',
                'properties': {},
            },
        },
    },
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
    {
        'type': 'function',
        'function': {
            'name': 'kommo_setup',
            'description': 'Setup CRM: create pipelines, stages, custom fields, sources. IMPORTANT: set dry_run=false to actually create!',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['templates', 'apply_template', 'create_pipeline', 'create_stage', 'create_field', 'create_source'],
                        'description': 'Setup action',
                    },
                    'dry_run': {
                        'type': 'boolean',
                        'description': 'If true, only preview. Set to false to actually create!',
                        'default': False,
                    },
                    'template': {'type': 'string', 'description': 'Template name for apply_template'},
                    'pipeline_name': {'type': 'string', 'description': 'Pipeline name for create_pipeline'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID for create_stage/create_source'},
                    'stage_name': {'type': 'string', 'description': 'Stage name'},
                    'stage_sort': {'type': 'integer', 'description': 'Stage sort order'},
                    'stage_color': {'type': 'string', 'description': 'Stage color hex'},
                    'field_name': {'type': 'string', 'description': 'Field name'},
                    'field_type': {
                        'type': 'string',
                        'enum': ['text', 'numeric', 'checkbox', 'select', 'multiselect', 'date', 'url', 'textarea', 'price'],
                        'description': 'Field type',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies'],
                        'description': 'Entity type for field',
                    },
                    'enums': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Options for select/multiselect fields',
                    },
                    'source_name': {'type': 'string', 'description': 'Source name'},
                },
                'required': ['action'],
            },
        },
    },
]

SYSTEM_PROMPT = """Ты - AI-ассистент для КОМПЛЕКСНОЙ НАСТРОЙКИ CRM Kommo.

ВАЖНО: Ты можешь выполнять МНОЖЕСТВЕННЫЕ операции последовательно!

АЛГОРИТМ КОМПЛЕКСНОЙ НАСТРОЙКИ:
1. Создай воронку (action=create_pipeline) → получи pipeline_id
2. Добавь этапы в воронку (action=create_stage) с полученным pipeline_id
3. Создай кастомные поля (action=create_field)
4. Повтори для каждой воронки из запроса

ПАРАМЕТРЫ:
- Воронка: action=create_pipeline, pipeline_name="Название", dry_run=false
- Этап: action=create_stage, pipeline_id=ID, stage_name="Название", stage_sort=10/20/30..., dry_run=false
- Поле: action=create_field, field_name="Название", field_type="select", entity_type="leads", enums=["A","B"], dry_run=false

ТИПЫ ПОЛЕЙ: text, numeric, checkbox, select, multiselect, date, url, textarea, price
ENTITY TYPES: leads, contacts, companies

ЦВЕТА ЭТАПОВ (только эти!): #fffeb2, #fffd7f, #fff000, #ffeab2, #ffdc7f, #ffce5a, #ffdbdb, #ffc8c8, #ff8f92, #d6eaff, #c1e0ff, #98cbff, #ebffb1, #deff81, #87f2c0, #f9deff, #f3beff, #ccc8f9

ПРАВИЛА:
- ВСЕГДА dry_run=false для реального создания
- Выполняй ВСЕ операции из запроса последовательно
- После каждой операции продолжай со следующей
- В конце выдай СВОДКУ: что создано (воронки, этапы, поля)
"""


class AIChat:
    """AI Chat with OpenAI and direct Kommo API integration."""
    
    def __init__(
        self,
        openai_api_key: str,
        kommo_domain: str,
        kommo_token: str,
        model: str = 'gpt-4o-mini',
    ):
        self.openai_api_key = openai_api_key
        self.kommo_domain = kommo_domain
        self.kommo_token = kommo_token
        self.model = model
        self.kommo_base_url = f'https://{kommo_domain}'
    
    async def chat(self, message: str) -> str:
        """Process user message with iterative tool calls for complex setup."""
        try:
            messages = [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': message},
            ]
            
            max_iterations = 20  # Limit iterations for safety
            all_results = []
            
            for iteration in range(max_iterations):
                response = await self._openai_request(messages=messages, tools=MCP_TOOLS)
                
                # If no tool calls, we're done
                if not response.get('tool_calls'):
                    return response.get('content', 'Не удалось получить ответ')
                
                # Execute all tool calls
                tool_results = await self._execute_tool_calls(response['tool_calls'])
                all_results.extend(tool_results)
                
                # Add assistant message with tool calls
                messages.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': response['tool_calls'],
                })
                
                # Add tool results
                for tool_call, result in zip(response['tool_calls'], tool_results):
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call['id'],
                        'content': json.dumps(result, ensure_ascii=False),
                    })
                
                logger.info(f'Iteration {iteration + 1}: executed {len(response["tool_calls"])} tool calls')
            
            # If we hit max iterations, get final summary
            final_response = await self._openai_request(messages=messages)
            return final_response.get('content', 'Настройка завершена')
        
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
        """Execute Kommo API calls directly."""
        results = []
        
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {self.kommo_token}',
                'Content-Type': 'application/json',
            }
            
            for tool_call in tool_calls:
                func = tool_call['function']
                name = func['name']
                args = json.loads(func['arguments'])
                
                try:
                    result = await self._execute_kommo_tool(session, headers, name, args)
                    results.append(result)
                except Exception as e:
                    logger.error(f'Tool call error: {e}')
                    results.append({'error': str(e)})
        
        return results
    
    async def _execute_kommo_tool(self, session, headers, name: str, args: dict) -> dict:
        """Execute a single Kommo API tool."""
        logger.info(f'Executing tool: {name} with args: {args}')
        
        if name == 'kommo_setup':
            return await self._handle_setup(session, headers, args)
        
        elif name == 'kommo_list_pipelines':
            # Get all pipelines
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            logger.info(f'Getting pipelines from {url}')
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pipelines = data.get('_embedded', {}).get('pipelines', [])
                    result = []
                    for p in pipelines:
                        statuses = p.get('_embedded', {}).get('statuses', [])
                        result.append({
                            'id': p.get('id'),
                            'name': p.get('name'),
                            'is_main': p.get('is_main'),
                            'stages_count': len(statuses),
                            'stages': [s.get('name') for s in statuses[:5]]  # First 5 stages
                        })
                    return {'pipelines': result, 'total': len(result)}
                error = await resp.text()
                return {'error': f'API error {resp.status}', 'details': error[:200]}
        
        elif name == 'kommo_pipeline_analytics':
            # Get pipelines info
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            logger.info(f'Getting pipelines from {url}')
            async with session.get(url, headers=headers) as resp:
                logger.info(f'Pipelines response status: {resp.status}')
                if resp.status == 200:
                    data = await resp.json()
                    pipelines = data.get('_embedded', {}).get('pipelines', [])
                    # Simplify response for AI
                    result = []
                    for p in pipelines:
                        result.append({
                            'id': p.get('id'),
                            'name': p.get('name'),
                            'is_main': p.get('is_main'),
                            'statuses': [{'id': s.get('id'), 'name': s.get('name')} for s in p.get('_embedded', {}).get('statuses', [])]
                        })
                    logger.info(f'Found {len(result)} pipelines')
                    return {'pipelines': result, 'count': len(result)}
                error = await resp.text()
                logger.error(f'Pipelines error: {error}')
                return {'error': f'API error: {resp.status}', 'details': error[:200]}
        
        elif name == 'kommo_search':
            action = args.get('action', 'all')
            query = args.get('query', '')
            limit = args.get('limit', 10)
            
            if action in ['all', 'leads']:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': limit}
                if query:
                    params['query'] = query
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {'leads': data.get('_embedded', {}).get('leads', [])}
                    return {'error': f'API error: {resp.status}'}
            
            elif action == 'contacts':
                url = f'{self.kommo_base_url}/api/v4/contacts'
                params = {'limit': limit}
                if query:
                    params['query'] = query
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {'contacts': data.get('_embedded', {}).get('contacts', [])}
                    return {'error': f'API error: {resp.status}'}
        
        # Default - return info about available tools
        return {'message': f'Tool {name} not fully implemented yet', 'args': args}
    
    async def _handle_setup(self, session, headers, args: dict) -> dict:
        """Handle kommo_setup tool calls."""
        action = args.get('action')
        dry_run = args.get('dry_run', True)
        
        if action == 'create_pipeline':
            pipeline_name = args.get('pipeline_name')
            if not pipeline_name:
                return {'error': 'pipeline_name is required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would create pipeline: {pipeline_name}'}
            
            # Create pipeline - Kommo API requires array format
            # Valid colors: #fffeb2, #fffd7f, #fff000, #ffeab2, #ffdc7f, #ffce5a, #ffdbdb, #ffc8c8, #ff8f92, 
            #              #d6eaff, #c1e0ff, #98cbff, #ebffb1, #deff81, #87f2c0, #f9deff, #f3beff, #ccc8f9, #eb93ff
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            payload = [{
                'name': pipeline_name,
                'is_main': False,
                'is_unsorted_on': True,
                'sort': 100,
                '_embedded': {
                    'statuses': [
                        {'name': 'Первичный контакт', 'sort': 10, 'color': '#fffeb2'},
                        {'name': 'В работе', 'sort': 20, 'color': '#ffdc7f'},
                    ]
                }
            }]
            
            logger.info(f'Creating pipeline: {url} payload: {payload}')
            
            async with session.post(url, headers=headers, json=payload) as resp:
                response_text = await resp.text()
                logger.info(f'Pipeline response: {resp.status} - {response_text[:500]}')
                
                if resp.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                        pipelines = data.get('_embedded', {}).get('pipelines', [])
                        if pipelines:
                            return {
                                'success': True,
                                'pipeline_id': pipelines[0].get('id'),
                                'pipeline_name': pipelines[0].get('name'),
                            }
                    except:
                        pass
                return {'error': f'Failed to create pipeline (status {resp.status}): {response_text[:200]}'}
        
        elif action == 'create_stage':
            pipeline_id = args.get('pipeline_id')
            stage_name = args.get('stage_name')
            stage_sort = args.get('stage_sort', 100)
            stage_color = args.get('stage_color', '#fffeb2')
            
            if not pipeline_id or not stage_name:
                return {'error': 'pipeline_id and stage_name are required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would create stage: {stage_name}'}
            
            # Create stage
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses'
            payload = [{'name': stage_name, 'sort': stage_sort, 'color': stage_color}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    statuses = data.get('_embedded', {}).get('statuses', [])
                    if statuses:
                        return {
                            'success': True,
                            'stage_id': statuses[0].get('id'),
                            'stage_name': statuses[0].get('name'),
                        }
                error = await resp.text()
                return {'error': f'Failed to create stage: {error}'}
        
        elif action == 'create_field':
            field_name = args.get('field_name')
            field_type = args.get('field_type', 'text')
            entity_type = args.get('entity_type', 'leads')
            enums = args.get('enums', [])
            
            if not field_name:
                return {'error': 'field_name is required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would create field: {field_name}'}
            
            # Map field types
            type_map = {
                'text': 'text',
                'numeric': 'numeric',
                'checkbox': 'checkbox',
                'select': 'select',
                'multiselect': 'multiselect',
                'date': 'date',
                'url': 'url',
                'textarea': 'textarea',
                'price': 'price',
            }
            
            # Create field
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields'
            payload = [{
                'name': field_name,
                'type': type_map.get(field_type, 'text'),
            }]
            
            if enums and field_type in ['select', 'multiselect']:
                payload[0]['enums'] = [{'value': e} for e in enums]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    fields = data.get('_embedded', {}).get('custom_fields', [])
                    if fields:
                        return {
                            'success': True,
                            'field_id': fields[0].get('id'),
                            'field_name': fields[0].get('name'),
                        }
                error = await resp.text()
                return {'error': f'Failed to create field: {error}'}
        
        return {'error': f'Unknown setup action: {action}'}
