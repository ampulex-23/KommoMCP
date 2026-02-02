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
    {
        'type': 'function',
        'function': {
            'name': 'kommo_mock_data',
            'description': 'Generate mock/test data for CRM. Creates realistic contacts, companies, leads, tasks.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['generate_all', 'contacts', 'companies', 'leads', 'tasks'],
                        'description': 'What to generate',
                    },
                    'count': {
                        'type': 'integer',
                        'description': 'Number of entities to create (default 10)',
                        'default': 10,
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID for leads (required for leads)',
                    },
                    'status_id': {
                        'type': 'integer',
                        'description': 'Status/stage ID for leads',
                    },
                    'responsible_user_id': {
                        'type': 'integer',
                        'description': 'Responsible user ID',
                    },
                    'locale': {
                        'type': 'string',
                        'enum': ['ru', 'en'],
                        'description': 'Language for generated names (default ru)',
                        'default': 'ru',
                    },
                },
                'required': ['action'],
            },
        },
    },
]

SYSTEM_PROMPT = """Ты - AI-ассистент для работы с CRM Kommo. Ты умеешь:
- Настраивать CRM (воронки, этапы, поля)
- Генерировать тестовые данные
- Показывать аналитику и списки

🔧 НАСТРОЙКА CRM (kommo_setup):
- create_pipeline: создать воронку
- create_stage: добавить этап (нужен pipeline_id)
- create_field: создать поле

📊 MOCK ДАННЫЕ (kommo_mock_data):
- generate_all: создать контакты + компании + сделки
- contacts: только контакты
- companies: только компании  
- leads: только сделки (нужен pipeline_id или возьмёт первую воронку)

📋 ПРОСМОТР (kommo_list_pipelines, kommo_search):
- Список воронок с этапами
- Поиск сделок, контактов

ВАЖНО:
- dry_run=false для реального создания
- Выполняй операции последовательно
- Используй pipeline_id из предыдущих операций

ФОРМАТИРОВАНИЕ ОТВЕТОВ (Telegram HTML):
- Используй <b>жирный</b> для заголовков
- Используй <i>курсив</i> для пояснений
- Используй <code>код</code> для ID и чисел
- Используй эмодзи для визуализации: ✅❌📊📈💰👤🏢📋🔧⚡
- Структурируй ответ с отступами и списками
- Делай красивые сводки с разделителями ━━━

Пример красивого ответа:
<b>📊 Сводка по воронкам</b>

<b>1. Продажи</b> <code>#10548294</code>
   ├ Новая заявка
   ├ В работе  
   └ Успешно

<b>💰 Итого:</b> 3 воронки, 12 этапов
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
        
        elif name == 'kommo_mock_data':
            return await self._handle_mock_data(session, headers, args)
        
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
    
    async def _handle_mock_data(self, session, headers, args: dict) -> dict:
        """Generate mock data for CRM testing."""
        import random
        
        action = args.get('action')
        count = args.get('count', 10)
        pipeline_id = args.get('pipeline_id')
        status_id = args.get('status_id')
        responsible_user_id = args.get('responsible_user_id')
        locale = args.get('locale', 'ru')
        
        # Russian mock data
        first_names_ru = ['Александр', 'Дмитрий', 'Максим', 'Сергей', 'Андрей', 'Алексей', 'Артём', 'Илья', 'Кирилл', 'Михаил',
                         'Анна', 'Мария', 'Елена', 'Ольга', 'Наталья', 'Екатерина', 'Татьяна', 'Ирина', 'Светлана', 'Юлия']
        last_names_ru = ['Иванов', 'Петров', 'Сидоров', 'Козлов', 'Новиков', 'Морозов', 'Волков', 'Соколов', 'Лебедев', 'Кузнецов']
        companies_ru = ['ООО "ТехноСервис"', 'ЗАО "Альфа"', 'ИП Смирнов', 'ООО "Бета Групп"', 'АО "Гамма"', 
                       'ООО "Дельта Плюс"', 'ЗАО "Омега"', 'ООО "Сигма Тех"', 'ИП Козлова', 'ООО "Прогресс"']
        deal_names_ru = ['Поставка оборудования', 'Разработка сайта', 'Консалтинг', 'Техподдержка', 'Интеграция CRM',
                        'Обучение персонала', 'Аудит системы', 'Модернизация', 'Внедрение ERP', 'Автоматизация']
        
        # English mock data
        first_names_en = ['John', 'Michael', 'David', 'James', 'Robert', 'William', 'Richard', 'Joseph', 'Thomas', 'Charles',
                         'Mary', 'Patricia', 'Jennifer', 'Linda', 'Elizabeth', 'Barbara', 'Susan', 'Jessica', 'Sarah', 'Karen']
        last_names_en = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez']
        companies_en = ['TechCorp Inc', 'Alpha Solutions', 'Beta Group LLC', 'Gamma Industries', 'Delta Services',
                       'Omega Tech', 'Sigma Partners', 'Innovation Labs', 'Digital Dynamics', 'Cloud Systems']
        deal_names_en = ['Equipment Supply', 'Website Development', 'Consulting Project', 'Tech Support', 'CRM Integration',
                        'Staff Training', 'System Audit', 'Modernization', 'ERP Implementation', 'Process Automation']
        
        # Select locale
        if locale == 'ru':
            first_names, last_names, companies, deal_names = first_names_ru, last_names_ru, companies_ru, deal_names_ru
        else:
            first_names, last_names, companies, deal_names = first_names_en, last_names_en, companies_en, deal_names_en
        
        results = {'created': [], 'errors': []}
        
        if action == 'contacts':
            url = f'{self.kommo_base_url}/api/v4/contacts'
            contacts = []
            for i in range(count):
                name = f'{random.choice(first_names)} {random.choice(last_names)}'
                phone = f'+7{random.randint(900, 999)}{random.randint(1000000, 9999999)}'
                email = f'{name.split()[0].lower()}{random.randint(1, 99)}@example.com'
                contacts.append({
                    'name': name,
                    'custom_fields_values': [
                        {'field_code': 'PHONE', 'values': [{'value': phone}]},
                        {'field_code': 'EMAIL', 'values': [{'value': email}]},
                    ]
                })
            
            async with session.post(url, headers=headers, json=contacts) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    created = data.get('_embedded', {}).get('contacts', [])
                    return {'success': True, 'created_contacts': len(created), 'contacts': [{'id': c['id'], 'name': c['name']} for c in created[:5]]}
                error = await resp.text()
                return {'error': f'Failed to create contacts: {error[:200]}'}
        
        elif action == 'companies':
            url = f'{self.kommo_base_url}/api/v4/companies'
            comps = []
            for i in range(count):
                comps.append({'name': f'{random.choice(companies)} #{random.randint(1, 999)}'})
            
            async with session.post(url, headers=headers, json=comps) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    created = data.get('_embedded', {}).get('companies', [])
                    return {'success': True, 'created_companies': len(created), 'companies': [{'id': c['id'], 'name': c['name']} for c in created[:5]]}
                error = await resp.text()
                return {'error': f'Failed to create companies: {error[:200]}'}
        
        elif action == 'leads':
            if not pipeline_id:
                # Get first pipeline
                pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
                async with session.get(pipelines_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pipelines = data.get('_embedded', {}).get('pipelines', [])
                        if pipelines:
                            pipeline_id = pipelines[0]['id']
                            statuses = pipelines[0].get('_embedded', {}).get('statuses', [])
                            if statuses and not status_id:
                                status_id = statuses[0]['id']
                    if not pipeline_id:
                        return {'error': 'No pipeline found. Create a pipeline first or specify pipeline_id'}
            
            url = f'{self.kommo_base_url}/api/v4/leads'
            leads = []
            for i in range(count):
                lead = {
                    'name': f'{random.choice(deal_names)} #{random.randint(100, 999)}',
                    'price': random.randint(10000, 500000),
                    'pipeline_id': pipeline_id,
                }
                if status_id:
                    lead['status_id'] = status_id
                if responsible_user_id:
                    lead['responsible_user_id'] = responsible_user_id
                leads.append(lead)
            
            async with session.post(url, headers=headers, json=leads) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    created = data.get('_embedded', {}).get('leads', [])
                    return {
                        'success': True, 
                        'created_leads': len(created), 
                        'pipeline_id': pipeline_id,
                        'leads': [{'id': l['id'], 'name': l['name'], 'price': l.get('price')} for l in created[:5]]
                    }
                error = await resp.text()
                return {'error': f'Failed to create leads: {error[:200]}'}
        
        elif action == 'generate_all':
            # Create contacts, companies, and leads
            results = {'contacts': 0, 'companies': 0, 'leads': 0, 'errors': []}
            
            # Contacts
            contacts_result = await self._handle_mock_data(session, headers, {'action': 'contacts', 'count': count, 'locale': locale})
            if contacts_result.get('success'):
                results['contacts'] = contacts_result.get('created_contacts', 0)
            else:
                results['errors'].append(f"Contacts: {contacts_result.get('error', 'unknown')}")
            
            # Companies
            companies_result = await self._handle_mock_data(session, headers, {'action': 'companies', 'count': count, 'locale': locale})
            if companies_result.get('success'):
                results['companies'] = companies_result.get('created_companies', 0)
            else:
                results['errors'].append(f"Companies: {companies_result.get('error', 'unknown')}")
            
            # Leads
            leads_result = await self._handle_mock_data(session, headers, {
                'action': 'leads', 'count': count, 'locale': locale,
                'pipeline_id': pipeline_id, 'status_id': status_id, 'responsible_user_id': responsible_user_id
            })
            if leads_result.get('success'):
                results['leads'] = leads_result.get('created_leads', 0)
            else:
                results['errors'].append(f"Leads: {leads_result.get('error', 'unknown')}")
            
            return {
                'success': len(results['errors']) == 0,
                'summary': f"Created: {results['contacts']} contacts, {results['companies']} companies, {results['leads']} leads",
                **results
            }
        
        return {'error': f'Unknown mock_data action: {action}'}
