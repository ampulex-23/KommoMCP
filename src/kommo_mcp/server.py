"""KommoMCP Server - Main entry point."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from kommo_mcp.api.client import KommoClient, KommoAPIError
from kommo_mcp.config import init_settings
from kommo_mcp.db.session import _get_session_factory, init_db
from kommo_mcp.services.sync import SyncManager

logger = logging.getLogger(__name__)

# Settings will be initialized lazily
_settings = None


def _get_settings():
    global _settings
    if _settings is None:
        _settings = init_settings()
        logging.basicConfig(
            level=getattr(logging, _settings.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        )
    return _settings

# Create MCP server
server = Server('kommo-mcp')

# Global instances
_api_client: KommoClient | None = None


def get_api_client() -> KommoClient:
    """Get or create API client."""
    global _api_client
    if _api_client is None:
        _api_client = KommoClient()
    return _api_client


# === Tool Definitions ===

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name='kommo_ping',
            description='Check connection to Kommo API',
            inputSchema={
                'type': 'object',
                'properties': {},
                'required': [],
            },
        ),
        Tool(
            name='kommo_sync_start',
            description='Start data synchronization from Kommo API to local database',
            inputSchema={
                'type': 'object',
                'properties': {
                    'full': {
                        'type': 'boolean',
                        'description': 'Perform full sync (ignore last sync timestamp)',
                        'default': False,
                    },
                    'entities': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Entities to sync (users, pipelines, leads, contacts, companies, tasks). All if not specified.',
                    },
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_sync_status',
            description='Get synchronization status and data freshness',
            inputSchema={
                'type': 'object',
                'properties': {},
                'required': [],
            },
        ),
        Tool(
            name='kommo_pipelines_list',
            description='Get list of all pipelines with stages',
            inputSchema={
                'type': 'object',
                'properties': {},
                'required': [],
            },
        ),
        Tool(
            name='kommo_users_list',
            description='Get list of all users in the account',
            inputSchema={
                'type': 'object',
                'properties': {},
                'required': [],
            },
        ),
        Tool(
            name='kommo_leads_list',
            description='Get list of leads with filtering',
            inputSchema={
                'type': 'object',
                'properties': {
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Filter by pipeline ID',
                    },
                    'status_id': {
                        'type': 'integer',
                        'description': 'Filter by stage/status ID',
                    },
                    'responsible_user_id': {
                        'type': 'integer',
                        'description': 'Filter by responsible user ID',
                    },
                    'query': {
                        'type': 'string',
                        'description': 'Text search query',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Maximum number of leads to return (default 50, max 250)',
                        'default': 50,
                    },
                    'page': {
                        'type': 'integer',
                        'description': 'Page number for pagination',
                        'default': 1,
                    },
                    'order_by': {
                        'type': 'string',
                        'description': 'Sort field: created_at, updated_at, id (default: updated_at)',
                        'default': 'updated_at',
                    },
                    'order_dir': {
                        'type': 'string',
                        'description': 'Sort direction: asc or desc (default: desc)',
                        'default': 'desc',
                    },
                    'created_at_from': {
                        'type': 'string',
                        'description': 'Filter by created_at from date (ISO format or timestamp)',
                    },
                    'created_at_to': {
                        'type': 'string',
                        'description': 'Filter by created_at to date (ISO format or timestamp)',
                    },
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_lead_get',
            description='Get detailed information about a specific lead',
            inputSchema={
                'type': 'object',
                'properties': {
                    'lead_id': {
                        'type': 'integer',
                        'description': 'Lead ID',
                    },
                },
                'required': ['lead_id'],
            },
        ),
        Tool(
            name='kommo_leads_summary',
            description='Get quick summary of leads without loading all data. Ideal for overview.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Filter by pipeline ID',
                    },
                    'status_id': {
                        'type': 'integer',
                        'description': 'Filter by stage/status ID',
                    },
                    'responsible_user_id': {
                        'type': 'integer',
                        'description': 'Filter by responsible user ID',
                    },
                },
                'required': [],
            },
        ),
        # === Analytics Tools ===
        Tool(
            name='kommo_pipeline_analytics',
            description='Get detailed pipeline analytics: conversion rates, average deal size, cycle time, stage distribution. Requires synced data.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID (all pipelines if not specified)',
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Start date (ISO format: 2024-01-01)',
                    },
                    'date_to': {
                        'type': 'string',
                        'description': 'End date (ISO format: 2024-01-31)',
                    },
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_manager_performance',
            description='Get manager performance metrics: win rate, revenue, deals count, activity. Requires synced data.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'user_id': {
                        'type': 'integer',
                        'description': 'User ID (all managers if not specified)',
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Start date (ISO format)',
                    },
                    'date_to': {
                        'type': 'string',
                        'description': 'End date (ISO format)',
                    },
                    'top_n': {
                        'type': 'integer',
                        'description': 'Return only top N managers by revenue',
                    },
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_sales_forecast',
            description='Generate sales forecast based on current pipeline and historical data. Requires synced data.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID (all pipelines if not specified)',
                    },
                    'forecast_days': {
                        'type': 'integer',
                        'description': 'Forecast horizon in days (default: 30)',
                        'default': 30,
                    },
                    'method': {
                        'type': 'string',
                        'description': 'Forecasting method: weighted, historical, optimistic',
                        'default': 'weighted',
                    },
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_funnel_analysis',
            description='Detailed funnel conversion analysis with stage-by-stage metrics. Shows how leads flow through the pipeline stages. Requires synced data.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID to analyze',
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Start date (ISO format)',
                    },
                    'date_to': {
                        'type': 'string',
                        'description': 'End date (ISO format)',
                    },
                },
                'required': ['pipeline_id'],
            },
        ),
        Tool(
            name='kommo_revenue_report',
            description='Get revenue breakdown by time periods with optional comparison. Requires synced data.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'group_by': {
                        'type': 'string',
                        'description': 'Grouping period: day, week, month, quarter',
                        'default': 'month',
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Start date (ISO format)',
                    },
                    'date_to': {
                        'type': 'string',
                        'description': 'End date (ISO format)',
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Filter by pipeline ID',
                    },
                    'compare_previous': {
                        'type': 'boolean',
                        'description': 'Include comparison with previous period',
                        'default': False,
                    },
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_activity_report',
            description='Get activity report: tasks, calls, meetings, notes. Requires synced data.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'user_id': {
                        'type': 'integer',
                        'description': 'Filter by user ID',
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Start date (ISO format)',
                    },
                    'date_to': {
                        'type': 'string',
                        'description': 'End date (ISO format)',
                    },
                },
                'required': [],
            },
        ),
        # === CRUD Tools: Leads ===
        Tool(
            name='kommo_lead_create',
            description='Create a new lead in Kommo CRM',
            inputSchema={
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Lead name'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'status_id': {'type': 'integer', 'description': 'Stage/status ID (first stage if not specified)'},
                    'price': {'type': 'integer', 'description': 'Deal budget', 'default': 0},
                    'responsible_user_id': {'type': 'integer', 'description': 'Responsible user ID'},
                    'contact_id': {'type': 'integer', 'description': 'Contact ID to link'},
                    'company_id': {'type': 'integer', 'description': 'Company ID to link'},
                },
                'required': ['name', 'pipeline_id'],
            },
        ),
        Tool(
            name='kommo_lead_update',
            description='Update an existing lead',
            inputSchema={
                'type': 'object',
                'properties': {
                    'lead_id': {'type': 'integer', 'description': 'Lead ID'},
                    'name': {'type': 'string', 'description': 'New name'},
                    'status_id': {'type': 'integer', 'description': 'New stage/status ID'},
                    'price': {'type': 'integer', 'description': 'New budget'},
                    'responsible_user_id': {'type': 'integer', 'description': 'New responsible user'},
                    'loss_reason_id': {'type': 'integer', 'description': 'Loss reason (for closed lost)'},
                },
                'required': ['lead_id'],
            },
        ),
        # === CRUD Tools: Contacts ===
        Tool(
            name='kommo_contacts_list',
            description='Get list of contacts with filtering',
            inputSchema={
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Search query'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Filter by responsible user'},
                    'limit': {'type': 'integer', 'description': 'Max results (default 50)', 'default': 50},
                    'page': {'type': 'integer', 'description': 'Page number', 'default': 1},
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_contact_get',
            description='Get contact details',
            inputSchema={
                'type': 'object',
                'properties': {
                    'contact_id': {'type': 'integer', 'description': 'Contact ID'},
                },
                'required': ['contact_id'],
            },
        ),
        Tool(
            name='kommo_contact_create',
            description='Create a new contact',
            inputSchema={
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Contact name'},
                    'first_name': {'type': 'string', 'description': 'First name'},
                    'last_name': {'type': 'string', 'description': 'Last name'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Responsible user ID'},
                    'phone': {'type': 'string', 'description': 'Phone number'},
                    'email': {'type': 'string', 'description': 'Email address'},
                },
                'required': ['name'],
            },
        ),
        # === CRUD Tools: Companies ===
        Tool(
            name='kommo_companies_list',
            description='Get list of companies',
            inputSchema={
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'Search query'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Filter by responsible user'},
                    'limit': {'type': 'integer', 'description': 'Max results', 'default': 50},
                    'page': {'type': 'integer', 'description': 'Page number', 'default': 1},
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_company_create',
            description='Create a new company',
            inputSchema={
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Company name'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Responsible user ID'},
                },
                'required': ['name'],
            },
        ),
        # === CRUD Tools: Tasks ===
        Tool(
            name='kommo_tasks_list',
            description='Get list of tasks',
            inputSchema={
                'type': 'object',
                'properties': {
                    'responsible_user_id': {'type': 'integer', 'description': 'Filter by responsible user'},
                    'entity_type': {'type': 'string', 'description': 'Filter by entity type: leads, contacts, companies'},
                    'entity_id': {'type': 'integer', 'description': 'Filter by entity ID'},
                    'is_completed': {'type': 'boolean', 'description': 'Filter by completion status'},
                    'limit': {'type': 'integer', 'description': 'Max results', 'default': 50},
                    'page': {'type': 'integer', 'description': 'Page number', 'default': 1},
                },
                'required': [],
            },
        ),
        Tool(
            name='kommo_task_create',
            description='Create a new task',
            inputSchema={
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Task description'},
                    'complete_till': {'type': 'string', 'description': 'Due date (ISO datetime)'},
                    'entity_type': {'type': 'string', 'description': 'Entity type: leads, contacts, companies'},
                    'entity_id': {'type': 'integer', 'description': 'Entity ID to link task to'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Responsible user ID'},
                    'task_type': {'type': 'string', 'description': 'Task type: call, meeting, email', 'default': 'call'},
                },
                'required': ['text', 'complete_till'],
            },
        ),
        Tool(
            name='kommo_task_complete',
            description='Mark a task as completed',
            inputSchema={
                'type': 'object',
                'properties': {
                    'task_id': {'type': 'integer', 'description': 'Task ID'},
                    'result': {'type': 'string', 'description': 'Task result/notes'},
                },
                'required': ['task_id'],
            },
        ),
        # === Notes ===
        Tool(
            name='kommo_note_create',
            description='Add a note to an entity',
            inputSchema={
                'type': 'object',
                'properties': {
                    'entity_type': {'type': 'string', 'description': 'Entity type: leads, contacts, companies'},
                    'entity_id': {'type': 'integer', 'description': 'Entity ID'},
                    'text': {'type': 'string', 'description': 'Note text'},
                },
                'required': ['entity_type', 'entity_id', 'text'],
            },
        ),
        # === Scripts ===
        Tool(
            name='kommo_scripts_list',
            description='List available scripts for batch operations',
            inputSchema={
                'type': 'object',
                'properties': {},
                'required': [],
            },
        ),
        Tool(
            name='kommo_script_run',
            description='Run a predefined script for batch operations',
            inputSchema={
                'type': 'object',
                'properties': {
                    'script_name': {
                        'type': 'string',
                        'description': 'Script name: export_leads, bulk_update_status, find_duplicates, recalculate_analytics, cleanup_old_data',
                    },
                    'params': {
                        'type': 'object',
                        'description': 'Script parameters (varies by script)',
                    },
                    'async_mode': {
                        'type': 'boolean',
                        'description': 'Run in background (default: false)',
                        'default': False,
                    },
                },
                'required': ['script_name'],
            },
        ),
        Tool(
            name='kommo_script_status',
            description='Get status of a running or completed script job',
            inputSchema={
                'type': 'object',
                'properties': {
                    'job_id': {'type': 'string', 'description': 'Job ID returned from script_run'},
                },
                'required': ['job_id'],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    try:
        result = await _execute_tool(name, arguments)
        return [TextContent(type='text', text=str(result))]
    except KommoAPIError as e:
        return [TextContent(type='text', text=f'Kommo API Error: {e.message} (code: {e.status_code})')]
    except Exception as e:
        logger.exception(f'Error executing tool {name}')
        return [TextContent(type='text', text=f'Error: {str(e)}')]


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool and return result."""
    api = get_api_client()
    
    if name == 'kommo_ping':
        account = await api.get_account()
        return {
            'status': 'ok',
            'account': account.get('name', 'Unknown'),
            'subdomain': _get_settings().kommo_subdomain,
            'timestamp': datetime.now().isoformat(),
        }
    
    elif name == 'kommo_sync_start':
        full = arguments.get('full', False)
        async with _get_session_factory()() as session:
            sync_manager = SyncManager(api, session)
            results = await sync_manager.sync_all(full=full)
        return {
            'status': 'completed',
            'results': results,
            'timestamp': datetime.now().isoformat(),
        }
    
    elif name == 'kommo_sync_status':
        async with _get_session_factory()() as session:
            sync_manager = SyncManager(api, session)
            status = await sync_manager.get_sync_status()
        return status
    
    elif name == 'kommo_pipelines_list':
        pipelines = await api.get_pipelines()
        return {
            'count': len(pipelines),
            'pipelines': [
                {
                    'id': p['id'],
                    'name': p['name'],
                    'is_main': p.get('is_main', False),
                    'stages': [
                        {
                            'id': s['id'],
                            'name': s['name'],
                            'sort': s.get('sort', 0),
                            'type': s.get('type', 0),
                        }
                        for s in p.get('_embedded', {}).get('statuses', [])
                    ],
                }
                for p in pipelines
            ],
        }
    
    elif name == 'kommo_users_list':
        users = await api.get_users()
        return {
            'count': len(users),
            'users': [
                {
                    'id': u['id'],
                    'name': u.get('name', ''),
                    'email': u.get('email', ''),
                }
                for u in users
            ],
        }
    
    elif name == 'kommo_leads_list':
        params = {}
        if arguments.get('pipeline_id'):
            params['filter[pipeline_id]'] = arguments['pipeline_id']
        if arguments.get('status_id'):
            params['filter[statuses]'] = [arguments['status_id']]
        if arguments.get('responsible_user_id'):
            params['filter[responsible_user_id]'] = arguments['responsible_user_id']
        if arguments.get('query'):
            params['query'] = arguments['query']
        
        limit = min(arguments.get('limit', 50), 250)
        page = arguments.get('page', 1)
        params['limit'] = limit
        params['page'] = page
        
        # Sorting
        order_by = arguments.get('order_by', 'updated_at')
        order_dir = arguments.get('order_dir', 'desc')
        params[f'order[{order_by}]'] = order_dir
        
        # Date filters
        if arguments.get('created_at_from'):
            from_val = arguments['created_at_from']
            if isinstance(from_val, str) and not from_val.isdigit():
                from_val = int(datetime.fromisoformat(from_val.replace('Z', '+00:00')).timestamp())
            params['filter[created_at][from]'] = int(from_val)
        if arguments.get('created_at_to'):
            to_val = arguments['created_at_to']
            if isinstance(to_val, str) and not to_val.isdigit():
                to_val = int(datetime.fromisoformat(to_val.replace('Z', '+00:00')).timestamp())
            params['filter[created_at][to]'] = int(to_val)
        
        data = await api.get('leads', params=params)
        leads = data.get('_embedded', {}).get('leads', [])
        
        return {
            'count': len(leads),
            'page': page,
            'limit': limit,
            'leads': [
                {
                    'id': l['id'],
                    'name': l.get('name', ''),
                    'price': l.get('price', 0),
                    'pipeline_id': l.get('pipeline_id'),
                    'status_id': l.get('status_id'),
                    'responsible_user_id': l.get('responsible_user_id'),
                    'created_at': datetime.fromtimestamp(l['created_at']).isoformat() if l.get('created_at') else None,
                }
                for l in leads
            ],
        }
    
    elif name == 'kommo_lead_get':
        lead_id = arguments['lead_id']
        data = await api.get(f'leads/{lead_id}', params={'with': 'contacts,companies'})
        
        return {
            'id': data['id'],
            'name': data.get('name', ''),
            'price': data.get('price', 0),
            'pipeline_id': data.get('pipeline_id'),
            'status_id': data.get('status_id'),
            'responsible_user_id': data.get('responsible_user_id'),
            'created_at': datetime.fromtimestamp(data['created_at']).isoformat() if data.get('created_at') else None,
            'updated_at': datetime.fromtimestamp(data['updated_at']).isoformat() if data.get('updated_at') else None,
            'closed_at': datetime.fromtimestamp(data['closed_at']).isoformat() if data.get('closed_at') else None,
            'custom_fields': data.get('custom_fields_values', []),
            'contacts': data.get('_embedded', {}).get('contacts', []),
            'companies': data.get('_embedded', {}).get('companies', []),
        }
    
    elif name == 'kommo_leads_summary':
        # Get summary from local DB if synced, otherwise from API
        from sqlalchemy import func, select
        from kommo_mcp.db.models import LeadDB, StageDB
        
        async with _get_session_factory()() as session:
            query = select(
                func.count(LeadDB.id).label('total'),
                func.sum(LeadDB.price).label('total_value'),
                func.avg(LeadDB.price).label('avg_value'),
            ).where(LeadDB.is_deleted == False)
            
            if arguments.get('pipeline_id'):
                query = query.where(LeadDB.pipeline_id == arguments['pipeline_id'])
            if arguments.get('status_id'):
                query = query.where(LeadDB.status_id == arguments['status_id'])
            if arguments.get('responsible_user_id'):
                query = query.where(LeadDB.responsible_user_id == arguments['responsible_user_id'])
            
            result = await session.execute(query)
            row = result.one()
            
            # Get by status breakdown
            status_query = select(
                StageDB.id,
                StageDB.name,
                StageDB.type,
                func.count(LeadDB.id).label('count'),
                func.sum(LeadDB.price).label('value'),
            ).join(LeadDB, LeadDB.status_id == StageDB.id).where(
                LeadDB.is_deleted == False
            ).group_by(StageDB.id, StageDB.name, StageDB.type)
            
            if arguments.get('pipeline_id'):
                status_query = status_query.where(LeadDB.pipeline_id == arguments['pipeline_id'])
            
            status_result = await session.execute(status_query)
            statuses = status_result.all()
        
        return {
            'summary': {
                'total_leads': row.total or 0,
                'total_value': float(row.total_value or 0),
                'avg_value': float(row.avg_value or 0),
            },
            'by_status': [
                {
                    'status_id': s.id,
                    'status_name': s.name,
                    'type': s.type,
                    'count': s.count,
                    'value': float(s.value or 0),
                }
                for s in statuses
            ],
        }
    
    # === Analytics Tools ===
    
    elif name == 'kommo_pipeline_analytics':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        date_from = _parse_date(arguments.get('date_from'))
        date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.pipeline_summary(
                pipeline_id=arguments.get('pipeline_id'),
                date_from=date_from,
                date_to=date_to,
            )
        
        # Convert to dict
        if isinstance(result, list):
            return {
                'count': len(result),
                'pipelines': [r.model_dump() for r in result],
            }
        return result.model_dump()
    
    elif name == 'kommo_manager_performance':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        date_from = _parse_date(arguments.get('date_from'))
        date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.manager_performance(
                user_id=arguments.get('user_id'),
                date_from=date_from,
                date_to=date_to,
                top_n=arguments.get('top_n'),
            )
        
        return {
            'count': len(result),
            'managers': [r.model_dump() for r in result],
        }
    
    elif name == 'kommo_sales_forecast':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.sales_forecast(
                pipeline_id=arguments.get('pipeline_id'),
                forecast_days=arguments.get('forecast_days', 30),
                method=arguments.get('method', 'weighted'),
            )
        
        return result.model_dump()
    
    elif name == 'kommo_funnel_analysis':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        date_from = _parse_date(arguments.get('date_from'))
        date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.funnel_analysis(
                pipeline_id=arguments['pipeline_id'],
                date_from=date_from,
                date_to=date_to,
            )
        
        return result.model_dump()
    
    elif name == 'kommo_revenue_report':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        date_from = _parse_date(arguments.get('date_from'))
        date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.revenue_by_period(
                group_by=arguments.get('group_by', 'month'),
                date_from=date_from,
                date_to=date_to,
                pipeline_id=arguments.get('pipeline_id'),
                compare_previous=arguments.get('compare_previous', False),
            )
        
        return {
            'count': len(result),
            'periods': [r.model_dump() for r in result],
        }
    
    elif name == 'kommo_activity_report':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        date_from = _parse_date(arguments.get('date_from'))
        date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.activity_report(
                user_id=arguments.get('user_id'),
                date_from=date_from,
                date_to=date_to,
            )
        
        return result.model_dump()
    
    elif name == 'kommo_stale_deals':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.stale_deals(
                threshold_days=arguments.get('threshold_days', 14),
                pipeline_id=arguments.get('pipeline_id'),
                limit=arguments.get('limit', 50),
            )
        
        return result.model_dump()
    
    elif name == 'kommo_lead_sources':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        date_from = _parse_date(arguments.get('date_from'))
        date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.lead_sources(
                pipeline_id=arguments.get('pipeline_id'),
                date_from=date_from,
                date_to=date_to,
            )
        
        return result.model_dump()
    
    elif name == 'kommo_revenue_trend':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.revenue_trend(
                group_by=arguments.get('group_by', 'month'),
                pipeline_id=arguments.get('pipeline_id'),
                periods_count=arguments.get('periods_count', 12),
            )
        
        return result.model_dump()
    
    elif name == 'kommo_churn_risk':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.churn_risk(
                days_threshold=arguments.get('days_threshold', 90),
                min_deals=arguments.get('min_deals', 1),
                limit=arguments.get('limit', 50),
            )
        
        return result.model_dump()
    
    elif name == 'kommo_lead_score':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.lead_score(
                pipeline_id=arguments.get('pipeline_id'),
                limit=arguments.get('limit', 50),
            )
        
        return result.model_dump()
    
    elif name == 'kommo_duplicates_find':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            result = await engine.find_duplicates(
                entity_type=arguments.get('entity_type', 'contacts'),
                limit=arguments.get('limit', 50),
            )
        
        return result.model_dump()
    
    elif name == 'kommo_task_create':
        # Parse complete_till - can be ISO string or Unix timestamp
        complete_till = arguments['complete_till']
        if isinstance(complete_till, str):
            try:
                dt = datetime.fromisoformat(complete_till.replace('Z', '+00:00'))
                complete_till = int(dt.timestamp())
            except ValueError:
                complete_till = int(complete_till)
        
        task_data = {
            'text': arguments['text'],
            'complete_till': complete_till,
        }
        
        if arguments.get('entity_id') and arguments.get('entity_type'):
            task_data['entity_id'] = arguments['entity_id']
            task_data['entity_type'] = arguments['entity_type']
        
        if arguments.get('task_type_id'):
            task_data['task_type_id'] = arguments['task_type_id']
        
        if arguments.get('responsible_user_id'):
            task_data['responsible_user_id'] = arguments['responsible_user_id']
        
        result = await api.post('tasks', json=[task_data])
        created = result.get('_embedded', {}).get('tasks', [{}])[0]
        return {
            'status': 'created',
            'task_id': created.get('id'),
            'task': created,
        }
    
    elif name == 'kommo_note_create':
        entity_type = arguments['entity_type']
        entity_id = arguments['entity_id']
        
        note_data = {
            'note_type': 'common',
            'params': {
                'text': arguments['text'],
            },
        }
        
        result = await api.post(f'{entity_type}/{entity_id}/notes', json=[note_data])
        created = result.get('_embedded', {}).get('notes', [{}])[0]
        return {
            'status': 'created',
            'note_id': created.get('id'),
            'note': created,
        }
    
    # === CRUD: Leads ===
    
    elif name == 'kommo_lead_create':
        lead_data = {
            'name': arguments['name'],
            'pipeline_id': arguments['pipeline_id'],
        }
        if arguments.get('status_id'):
            lead_data['status_id'] = arguments['status_id']
        if arguments.get('price'):
            lead_data['price'] = arguments['price']
        if arguments.get('responsible_user_id'):
            lead_data['responsible_user_id'] = arguments['responsible_user_id']
        
        # Handle linked entities
        embedded = {}
        if arguments.get('contact_id'):
            embedded['contacts'] = [{'id': arguments['contact_id']}]
        if arguments.get('company_id'):
            embedded['companies'] = [{'id': arguments['company_id']}]
        if embedded:
            lead_data['_embedded'] = embedded
        
        result = await api.post('leads', json=[lead_data])
        created = result.get('_embedded', {}).get('leads', [{}])[0]
        return {
            'status': 'created',
            'lead_id': created.get('id'),
            'lead': created,
        }
    
    elif name == 'kommo_lead_update':
        lead_id = arguments['lead_id']
        update_data = {'id': lead_id}
        
        if arguments.get('name'):
            update_data['name'] = arguments['name']
        if arguments.get('status_id'):
            update_data['status_id'] = arguments['status_id']
        if arguments.get('price') is not None:
            update_data['price'] = arguments['price']
        if arguments.get('responsible_user_id'):
            update_data['responsible_user_id'] = arguments['responsible_user_id']
        if arguments.get('loss_reason_id'):
            update_data['loss_reason_id'] = arguments['loss_reason_id']
        
        result = await api.patch('leads', json=[update_data])
        updated = result.get('_embedded', {}).get('leads', [{}])[0]
        return {
            'status': 'updated',
            'lead_id': lead_id,
            'lead': updated,
        }
    
    # === CRUD: Contacts ===
    
    elif name == 'kommo_contacts_list':
        params = {}
        if arguments.get('query'):
            params['query'] = arguments['query']
        if arguments.get('responsible_user_id'):
            params['filter[responsible_user_id]'] = arguments['responsible_user_id']
        
        limit = min(arguments.get('limit', 50), 250)
        page = arguments.get('page', 1)
        params['limit'] = limit
        params['page'] = page
        
        data = await api.get('contacts', params=params)
        contacts = data.get('_embedded', {}).get('contacts', [])
        
        return {
            'count': len(contacts),
            'page': page,
            'contacts': [
                {
                    'id': c['id'],
                    'name': c.get('name', ''),
                    'first_name': c.get('first_name'),
                    'last_name': c.get('last_name'),
                    'responsible_user_id': c.get('responsible_user_id'),
                }
                for c in contacts
            ],
        }
    
    elif name == 'kommo_contact_get':
        contact_id = arguments['contact_id']
        data = await api.get(f'contacts/{contact_id}', params={'with': 'leads,companies'})
        
        return {
            'id': data['id'],
            'name': data.get('name', ''),
            'first_name': data.get('first_name'),
            'last_name': data.get('last_name'),
            'responsible_user_id': data.get('responsible_user_id'),
            'custom_fields': data.get('custom_fields_values', []),
            'leads': data.get('_embedded', {}).get('leads', []),
            'companies': data.get('_embedded', {}).get('companies', []),
        }
    
    elif name == 'kommo_contact_create':
        contact_data = {'name': arguments['name']}
        
        if arguments.get('first_name'):
            contact_data['first_name'] = arguments['first_name']
        if arguments.get('last_name'):
            contact_data['last_name'] = arguments['last_name']
        if arguments.get('responsible_user_id'):
            contact_data['responsible_user_id'] = arguments['responsible_user_id']
        
        # Handle phone and email as custom fields
        custom_fields = []
        if arguments.get('phone'):
            custom_fields.append({
                'field_code': 'PHONE',
                'values': [{'value': arguments['phone']}],
            })
        if arguments.get('email'):
            custom_fields.append({
                'field_code': 'EMAIL',
                'values': [{'value': arguments['email']}],
            })
        if custom_fields:
            contact_data['custom_fields_values'] = custom_fields
        
        result = await api.post('contacts', json=[contact_data])
        created = result.get('_embedded', {}).get('contacts', [{}])[0]
        return {
            'status': 'created',
            'contact_id': created.get('id'),
            'contact': created,
        }
    
    # === CRUD: Companies ===
    
    elif name == 'kommo_companies_list':
        params = {}
        if arguments.get('query'):
            params['query'] = arguments['query']
        if arguments.get('responsible_user_id'):
            params['filter[responsible_user_id]'] = arguments['responsible_user_id']
        
        limit = min(arguments.get('limit', 50), 250)
        page = arguments.get('page', 1)
        params['limit'] = limit
        params['page'] = page
        
        data = await api.get('companies', params=params)
        companies = data.get('_embedded', {}).get('companies', [])
        
        return {
            'count': len(companies),
            'page': page,
            'companies': [
                {
                    'id': c['id'],
                    'name': c.get('name', ''),
                    'responsible_user_id': c.get('responsible_user_id'),
                }
                for c in companies
            ],
        }
    
    elif name == 'kommo_company_create':
        company_data = {'name': arguments['name']}
        
        if arguments.get('responsible_user_id'):
            company_data['responsible_user_id'] = arguments['responsible_user_id']
        
        result = await api.post('companies', json=[company_data])
        created = result.get('_embedded', {}).get('companies', [{}])[0]
        return {
            'status': 'created',
            'company_id': created.get('id'),
            'company': created,
        }
    
    # === CRUD: Tasks ===
    
    elif name == 'kommo_tasks_list':
        params = {}
        if arguments.get('responsible_user_id'):
            params['filter[responsible_user_id]'] = arguments['responsible_user_id']
        if arguments.get('entity_type') and arguments.get('entity_id'):
            params['filter[entity_type]'] = arguments['entity_type']
            params['filter[entity_id]'] = arguments['entity_id']
        if arguments.get('is_completed') is not None:
            params['filter[is_completed]'] = arguments['is_completed']
        
        limit = min(arguments.get('limit', 50), 250)
        page = arguments.get('page', 1)
        params['limit'] = limit
        params['page'] = page
        
        data = await api.get('tasks', params=params)
        tasks = data.get('_embedded', {}).get('tasks', [])
        
        return {
            'count': len(tasks),
            'page': page,
            'tasks': [
                {
                    'id': t['id'],
                    'text': t.get('text', ''),
                    'is_completed': t.get('is_completed', False),
                    'complete_till': datetime.fromtimestamp(t['complete_till']).isoformat() if t.get('complete_till') else None,
                    'entity_type': t.get('entity_type'),
                    'entity_id': t.get('entity_id'),
                    'responsible_user_id': t.get('responsible_user_id'),
                }
                for t in tasks
            ],
        }
    
    elif name == 'kommo_task_create':
        # Map task type to ID
        task_type_map = {'call': 1, 'meeting': 2, 'email': 3}
        task_type_id = task_type_map.get(arguments.get('task_type', 'call'), 1)
        
        # Parse complete_till
        complete_till = _parse_date(arguments['complete_till'])
        if not complete_till:
            complete_till = datetime.now()
        
        task_data = {
            'text': arguments['text'],
            'complete_till': int(complete_till.timestamp()),
            'task_type_id': task_type_id,
        }
        
        if arguments.get('entity_type') and arguments.get('entity_id'):
            task_data['entity_type'] = arguments['entity_type']
            task_data['entity_id'] = arguments['entity_id']
        if arguments.get('responsible_user_id'):
            task_data['responsible_user_id'] = arguments['responsible_user_id']
        
        result = await api.post('tasks', json=[task_data])
        created = result.get('_embedded', {}).get('tasks', [{}])[0]
        return {
            'status': 'created',
            'task_id': created.get('id'),
            'task': created,
        }
    
    elif name == 'kommo_task_complete':
        task_id = arguments['task_id']
        update_data = {
            'id': task_id,
            'is_completed': True,
        }
        if arguments.get('result'):
            update_data['result'] = {'text': arguments['result']}
        
        result = await api.patch('tasks', json=[update_data])
        updated = result.get('_embedded', {}).get('tasks', [{}])[0]
        return {
            'status': 'completed',
            'task_id': task_id,
            'task': updated,
        }
    
    # === Notes ===
    
    elif name == 'kommo_note_create':
        entity_type = arguments['entity_type']
        entity_id = arguments['entity_id']
        
        note_data = {
            'note_type': 'common',
            'params': {'text': arguments['text']},
        }
        
        result = await api.post(f'{entity_type}/{entity_id}/notes', json=[note_data])
        created = result.get('_embedded', {}).get('notes', [{}])[0]
        return {
            'status': 'created',
            'note_id': created.get('id'),
            'note': created,
        }
    
    # === Scripts ===
    
    elif name == 'kommo_scripts_list':
        from kommo_mcp.scripts.engine import get_scripts_engine
        
        engine = get_scripts_engine()
        scripts = engine.list_scripts()
        return {
            'count': len(scripts),
            'scripts': scripts,
        }
    
    elif name == 'kommo_script_run':
        from kommo_mcp.scripts.engine import get_scripts_engine
        
        engine = get_scripts_engine()
        status = await engine.run_script(
            script_name=arguments['script_name'],
            params=arguments.get('params'),
            async_mode=arguments.get('async_mode', False),
        )
        return status.model_dump()
    
    elif name == 'kommo_script_status':
        from kommo_mcp.scripts.engine import get_scripts_engine
        
        engine = get_scripts_engine()
        status = engine.get_job_status(arguments['job_id'])
        if status:
            return status.model_dump()
        return {'error': 'Job not found', 'job_id': arguments['job_id']}
    
    else:
        raise ValueError(f'Unknown tool: {name}')


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse ISO date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return None


async def run_server() -> None:
    """Run the MCP server."""
    logger.info('Starting KommoMCP server...')
    
    # Initialize database
    await init_db()
    logger.info('Database initialized')
    
    # Run server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Main entry point."""
    asyncio.run(run_server())


if __name__ == '__main__':
    main()
