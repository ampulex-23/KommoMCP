"""KommoMCP Server - Main entry point."""

import asyncio
import logging
from datetime import datetime, timedelta
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
    
    elif name == 'kommo_analytics':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        action = arguments.get('action')
        if not action:
            return {'error': 'action is required'}
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            
            if action == 'pipeline':
                date_from = _parse_date(arguments.get('date_from'))
                date_to = _parse_date(arguments.get('date_to'))
                result = await engine.pipeline_summary(
                    pipeline_id=arguments.get('pipeline_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
            elif action == 'funnel':
                date_from = _parse_date(arguments.get('date_from'))
                date_to = _parse_date(arguments.get('date_to'))
                result = await engine.funnel_analysis(
                    pipeline_id=arguments['pipeline_id'],
                    date_from=date_from,
                    date_to=date_to,
                )
            elif action == 'forecast':
                result = await engine.sales_forecast(
                    pipeline_id=arguments.get('pipeline_id'),
                    forecast_days=arguments.get('forecast_days', 30),
                )
            elif action == 'managers':
                date_from = _parse_date(arguments.get('date_from'))
                date_to = _parse_date(arguments.get('date_to'))
                result = await engine.manager_performance(
                    user_id=arguments.get('user_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
            elif action == 'revenue':
                result = await engine.revenue_trend(
                    group_by=arguments.get('group_by', 'month'),
                    pipeline_id=arguments.get('pipeline_id'),
                    periods_count=arguments.get('periods_count', 12),
                )
            elif action == 'stale':
                result = await engine.stale_deals(
                    threshold_days=arguments.get('threshold_days', 14),
                    pipeline_id=arguments.get('pipeline_id'),
                    limit=arguments.get('limit', 50),
                )
            elif action == 'sources':
                date_from = _parse_date(arguments.get('date_from'))
                date_to = _parse_date(arguments.get('date_to'))
                result = await engine.lead_sources(
                    pipeline_id=arguments.get('pipeline_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
            elif action == 'churn':
                result = await engine.churn_risk(
                    days_threshold=arguments.get('threshold_days', 90),
                    min_deals=arguments.get('min_deals', 1),
                    limit=arguments.get('limit', 50),
                )
            elif action == 'scoring':
                result = await engine.lead_score(
                    pipeline_id=arguments.get('pipeline_id'),
                    limit=arguments.get('limit', 50),
                )
            elif action == 'duplicates':
                result = await engine.find_duplicates(
                    entity_type=arguments.get('entity_type', 'contacts'),
                    limit=arguments.get('limit', 50),
                )
            else:
                return {'error': f'Unknown action: {action}'}
        
        return result.model_dump()
    
    elif name == 'kommo_entity':
        action = arguments.get('action')
        entity_type = arguments.get('entity_type')
        
        if not action or not entity_type:
            return {'error': 'action and entity_type are required'}
        
        if action == 'get':
            entity_id = arguments.get('entity_id')
            if not entity_id:
                return {'error': 'entity_id is required for get'}
            
            params = {'with': 'contacts,companies,leads,catalog_elements'}
            data = await api.get(f'{entity_type}/{entity_id}', params=params)
            return {'entity': data}
        
        elif action == 'list':
            params = {}
            filters = arguments.get('filters', {})
            
            if filters.get('pipeline_id'):
                params['filter[pipeline_id]'] = filters['pipeline_id']
            if filters.get('status_id'):
                params['filter[status_id]'] = filters['status_id']
            if filters.get('user_id'):
                params['filter[responsible_user_id]'] = filters['user_id']
            if filters.get('query'):
                params['query'] = filters['query']
            
            params['limit'] = min(arguments.get('limit', 50), 250)
            if arguments.get('offset'):
                params['page'] = (arguments['offset'] // params['limit']) + 1
            
            if arguments.get('sort_by'):
                order = arguments.get('sort_order', 'desc')
                params['order[' + arguments['sort_by'] + ']'] = order
            
            data = await api.get(entity_type, params=params)
            entities = data.get('_embedded', {}).get(entity_type, [])
            
            return {
                'count': len(entities),
                'entities': entities,
            }
        
        elif action == 'create':
            entity_data = arguments.get('data', {})
            if not entity_data:
                return {'error': 'data is required for create'}
            
            result = await api.post(entity_type, json=[entity_data])
            created = result.get('_embedded', {}).get(entity_type, [{}])[0]
            return {
                'status': 'created',
                'entity_id': created.get('id'),
                'entity': created,
            }
        
        elif action == 'update':
            entity_id = arguments.get('entity_id')
            entity_data = arguments.get('data', {})
            if not entity_id:
                return {'error': 'entity_id is required for update'}
            
            entity_data['id'] = entity_id
            result = await api.patch(entity_type, json=[entity_data])
            updated = result.get('_embedded', {}).get(entity_type, [{}])[0]
            return {
                'status': 'updated',
                'entity_id': entity_id,
                'entity': updated,
            }
        
        elif action == 'link':
            entity_id = arguments.get('entity_id')
            target_type = arguments.get('target_entity_type')
            target_id = arguments.get('target_entity_id')
            
            if not all([entity_id, target_type, target_id]):
                return {'error': 'entity_id, target_entity_type, target_entity_id required'}
            
            link_data = {'id': entity_id, '_embedded': {target_type: [{'id': target_id}]}}
            result = await api.patch(entity_type, json=[link_data])
            return {'status': 'linked', 'entity_id': entity_id, 'target_id': target_id}
        
        elif action == 'unlink':
            entity_id = arguments.get('entity_id')
            target_type = arguments.get('target_entity_type')
            target_id = arguments.get('target_entity_id')
            
            if not all([entity_id, target_type, target_id]):
                return {'error': 'entity_id, target_entity_type, target_entity_id required'}
            
            result = await api.post(f'{entity_type}/{entity_id}/unlink', json={target_type: [{'id': target_id}]})
            return {'status': 'unlinked', 'entity_id': entity_id, 'target_id': target_id}
        
        elif action == 'move':
            entity_id = arguments.get('entity_id')
            stage_id = arguments.get('stage_id')
            pipeline_id = arguments.get('pipeline_id')
            
            if not entity_id or not stage_id:
                return {'error': 'entity_id and stage_id required for move'}
            
            move_data = {'id': entity_id, 'status_id': stage_id}
            if pipeline_id:
                move_data['pipeline_id'] = pipeline_id
            
            result = await api.patch(entity_type, json=[move_data])
            return {'status': 'moved', 'entity_id': entity_id, 'stage_id': stage_id}
        
        elif action == 'history':
            entity_id = arguments.get('entity_id')
            if not entity_id:
                return {'error': 'entity_id required for history'}
            
            data = await api.get(f'{entity_type}/{entity_id}/notes', params={'limit': 50})
            notes = data.get('_embedded', {}).get('notes', [])
            return {'entity_id': entity_id, 'history': notes}
        
        else:
            return {'error': f'Unknown action: {action}'}
    
    elif name == 'kommo_bulk':
        action = arguments.get('action')
        entity_type = arguments.get('entity_type')
        
        if not action or not entity_type:
            return {'error': 'action and entity_type are required'}
        
        dry_run = arguments.get('dry_run', False)
        limit = min(arguments.get('limit', 100), 500)
        
        # Get entities by filters or IDs
        entity_ids = arguments.get('entity_ids', [])
        if not entity_ids:
            filters = arguments.get('filters', {})
            params = {'limit': limit}
            
            if filters.get('pipeline_id'):
                params['filter[pipeline_id]'] = filters['pipeline_id']
            if filters.get('stage_id'):
                params['filter[status_id]'] = filters['stage_id']
            if filters.get('user_id'):
                params['filter[responsible_user_id]'] = filters['user_id']
            
            data = await api.get(entity_type, params=params)
            entities = data.get('_embedded', {}).get(entity_type, [])
            entity_ids = [e['id'] for e in entities]
        
        if not entity_ids:
            return {'status': 'no_entities', 'count': 0}
        
        if action == 'assign':
            user_id = arguments.get('user_id')
            if not user_id:
                return {'error': 'user_id required for assign'}
            
            if dry_run:
                return {'status': 'dry_run', 'would_assign': len(entity_ids), 'to_user': user_id}
            
            updates = [{'id': eid, 'responsible_user_id': user_id} for eid in entity_ids]
            result = await api.patch(entity_type, json=updates)
            return {'status': 'assigned', 'count': len(entity_ids), 'user_id': user_id}
        
        elif action == 'move':
            stage_id = arguments.get('stage_id')
            if not stage_id:
                return {'error': 'stage_id required for move'}
            
            if dry_run:
                return {'status': 'dry_run', 'would_move': len(entity_ids), 'to_stage': stage_id}
            
            updates = [{'id': eid, 'status_id': stage_id} for eid in entity_ids]
            result = await api.patch(entity_type, json=updates)
            return {'status': 'moved', 'count': len(entity_ids), 'stage_id': stage_id}
        
        elif action == 'tag':
            tags = arguments.get('tags', [])
            tag_action = arguments.get('tag_action', 'add')
            
            if not tags:
                return {'error': 'tags required'}
            
            if dry_run:
                return {'status': 'dry_run', 'would_tag': len(entity_ids), 'tags': tags, 'action': tag_action}
            
            if tag_action == 'add':
                updates = [{'id': eid, '_embedded': {'tags': [{'name': t} for t in tags]}} for eid in entity_ids]
            else:
                # Remove tags - need to get current and filter
                return {'error': 'tag removal not yet implemented'}
            
            result = await api.patch(entity_type, json=updates)
            return {'status': 'tagged', 'count': len(entity_ids), 'tags': tags}
        
        elif action == 'create_tasks':
            task_text = arguments.get('task_text', 'Follow up')
            task_due_days = arguments.get('task_due_days', 1)
            
            if dry_run:
                return {'status': 'dry_run', 'would_create_tasks': len(entity_ids)}
            
            due_timestamp = int((datetime.now() + timedelta(days=task_due_days)).timestamp())
            tasks = [
                {
                    'text': task_text,
                    'complete_till': due_timestamp,
                    'entity_id': eid,
                    'entity_type': entity_type,
                }
                for eid in entity_ids
            ]
            
            result = await api.post('tasks', json=tasks)
            created = result.get('_embedded', {}).get('tasks', [])
            return {'status': 'tasks_created', 'count': len(created)}
        
        elif action == 'update':
            changes = arguments.get('changes', {})
            if not changes:
                return {'error': 'changes required for update'}
            
            if dry_run:
                return {'status': 'dry_run', 'would_update': len(entity_ids), 'changes': changes}
            
            updates = [{**changes, 'id': eid} for eid in entity_ids]
            result = await api.patch(entity_type, json=updates)
            return {'status': 'updated', 'count': len(entity_ids)}
        
        elif action == 'export':
            params = {'limit': limit}
            data = await api.get(entity_type, params=params)
            entities = data.get('_embedded', {}).get(entity_type, [])
            return {'status': 'exported', 'count': len(entities), 'entities': entities}
        
        else:
            return {'error': f'Unknown bulk action: {action}'}
    
    elif name == 'kommo_search':
        action = arguments.get('action')
        
        if not action:
            return {'error': 'action is required'}
        
        limit = arguments.get('limit', 20)
        
        if action == 'query':
            query = arguments.get('query', '')
            entity_types = arguments.get('entity_types', ['leads', 'contacts', 'companies'])
            
            results = {}
            for et in entity_types:
                try:
                    data = await api.get(et, params={'query': query, 'limit': limit})
                    results[et] = data.get('_embedded', {}).get(et, [])
                except Exception:
                    results[et] = []
            
            total = sum(len(v) for v in results.values())
            return {'query': query, 'total': total, 'results': results}
        
        elif action == 'related':
            entity_id = arguments.get('entity_id')
            entity_type = arguments.get('entity_type')
            
            if not entity_id or not entity_type:
                return {'error': 'entity_id and entity_type required'}
            
            data = await api.get(f'{entity_type}/{entity_id}', params={'with': 'contacts,companies,leads'})
            embedded = data.get('_embedded', {})
            
            return {
                'entity_id': entity_id,
                'entity_type': entity_type,
                'related': {
                    'contacts': embedded.get('contacts', []),
                    'companies': embedded.get('companies', []),
                    'leads': embedded.get('leads', []),
                },
            }
        
        elif action == 'recent':
            entity_types = arguments.get('entity_types', ['leads'])
            
            results = {}
            for et in entity_types:
                try:
                    data = await api.get(et, params={'order[updated_at]': 'desc', 'limit': limit})
                    results[et] = data.get('_embedded', {}).get(et, [])
                except Exception:
                    results[et] = []
            
            return {'results': results}
        
        elif action == 'similar':
            entity_id = arguments.get('entity_id')
            entity_type = arguments.get('entity_type', 'leads')
            
            if not entity_id:
                return {'error': 'entity_id required for similar'}
            
            # Get entity details
            entity = await api.get(f'{entity_type}/{entity_id}')
            
            # Search by name similarity
            name = entity.get('name', '')
            if name:
                data = await api.get(entity_type, params={'query': name.split()[0] if name else '', 'limit': limit})
                similar = [e for e in data.get('_embedded', {}).get(entity_type, []) if e['id'] != entity_id]
                return {'entity_id': entity_id, 'similar': similar[:limit]}
            
            return {'entity_id': entity_id, 'similar': []}
        
        else:
            return {'error': f'Unknown search action: {action}'}
    
    elif name == 'kommo_report':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        action = arguments.get('action')
        if not action:
            return {'error': 'action is required'}
        
        period = arguments.get('period', 'month')
        
        # Calculate date range based on period
        now = datetime.now()
        if period == 'today':
            date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = now
        elif period == 'yesterday':
            date_from = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            date_to = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            date_from = now - timedelta(days=7)
            date_to = now
        elif period == 'month':
            date_from = now - timedelta(days=30)
            date_to = now
        elif period == 'quarter':
            date_from = now - timedelta(days=90)
            date_to = now
        elif period == 'year':
            date_from = now - timedelta(days=365)
            date_to = now
        else:
            date_from = _parse_date(arguments.get('date_from'))
            date_to = _parse_date(arguments.get('date_to'))
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            
            if action == 'summary':
                # Get multiple analytics for summary
                pipeline_data = await engine.pipeline_summary(
                    pipeline_id=arguments.get('pipeline_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
                
                # Handle list or single object
                if isinstance(pipeline_data, list):
                    total_leads = sum(p.total_leads for p in pipeline_data)
                    won_leads = sum(p.won_leads for p in pipeline_data)
                    lost_leads = sum(p.lost_leads for p in pipeline_data)
                    total_value = sum(p.total_value for p in pipeline_data)
                    avg_value = total_value / won_leads if won_leads > 0 else 0
                    conversion_rate = (won_leads / total_leads * 100) if total_leads > 0 else 0
                    avg_cycle_days = sum(p.avg_cycle_days for p in pipeline_data) / len(pipeline_data) if pipeline_data else 0
                else:
                    total_leads = pipeline_data.total_leads
                    won_leads = pipeline_data.won_leads
                    lost_leads = pipeline_data.lost_leads
                    total_value = pipeline_data.total_value
                    avg_value = pipeline_data.avg_value
                    conversion_rate = pipeline_data.conversion_rate
                    avg_cycle_days = pipeline_data.avg_cycle_days
                
                return {
                    'report_type': 'summary',
                    'period': period,
                    'date_from': str(date_from) if date_from else None,
                    'date_to': str(date_to) if date_to else None,
                    'total_leads': total_leads,
                    'won_leads': won_leads,
                    'lost_leads': lost_leads,
                    'total_value': total_value,
                    'avg_value': avg_value,
                    'conversion_rate': conversion_rate,
                    'avg_cycle_days': avg_cycle_days,
                }
            
            elif action == 'comparison':
                compare_with = arguments.get('compare_with', 'previous_period')
                
                def extract_metrics(data):
                    if isinstance(data, list):
                        return {
                            'total_leads': sum(p.total_leads for p in data),
                            'total_value': sum(p.total_value for p in data),
                            'conversion_rate': (sum(p.won_leads for p in data) / sum(p.total_leads for p in data) * 100) if sum(p.total_leads for p in data) > 0 else 0,
                        }
                    return {
                        'total_leads': data.total_leads,
                        'total_value': data.total_value,
                        'conversion_rate': data.conversion_rate,
                    }
                
                # Current period
                current_data = await engine.pipeline_summary(
                    pipeline_id=arguments.get('pipeline_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
                current = extract_metrics(current_data)
                
                # Previous period
                if date_from and date_to:
                    period_length = (date_to - date_from).days
                    prev_date_to = date_from
                    prev_date_from = date_from - timedelta(days=period_length)
                else:
                    prev_date_from = now - timedelta(days=60)
                    prev_date_to = now - timedelta(days=30)
                
                previous_data = await engine.pipeline_summary(
                    pipeline_id=arguments.get('pipeline_id'),
                    date_from=prev_date_from,
                    date_to=prev_date_to,
                )
                previous = extract_metrics(previous_data)
                
                def calc_change(curr, prev):
                    if prev == 0:
                        return 100 if curr > 0 else 0
                    return round((curr - prev) / prev * 100, 1)
                
                return {
                    'report_type': 'comparison',
                    'current_period': {'from': str(date_from), 'to': str(date_to)},
                    'previous_period': {'from': str(prev_date_from), 'to': str(prev_date_to)},
                    'current': {
                        'leads': current['total_leads'],
                        'value': current['total_value'],
                        'conversion': current['conversion_rate'],
                    },
                    'previous': {
                        'leads': previous['total_leads'],
                        'value': previous['total_value'],
                        'conversion': previous['conversion_rate'],
                    },
                    'changes': {
                        'leads': calc_change(current['total_leads'], previous['total_leads']),
                        'value': calc_change(current['total_value'], previous['total_value']),
                        'conversion': calc_change(current['conversion_rate'], previous['conversion_rate']),
                    },
                }
            
            elif action == 'pipeline_health':
                stale = await engine.stale_deals(
                    threshold_days=arguments.get('threshold_days', 14),
                    pipeline_id=arguments.get('pipeline_id'),
                    limit=100,
                )
                
                pipeline_data = await engine.pipeline_summary(
                    pipeline_id=arguments.get('pipeline_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
                
                # Handle list or single object
                if isinstance(pipeline_data, list):
                    in_progress = sum(p.in_progress for p in pipeline_data)
                else:
                    in_progress = pipeline_data.in_progress
                
                return {
                    'report_type': 'pipeline_health',
                    'total_active_deals': in_progress,
                    'stale_deals_count': stale.total_stale,
                    'stale_deals_value': stale.total_value,
                    'health_score': max(0, 100 - (stale.total_stale * 5)),
                    'by_stage': stale.by_stage,
                    'recommendations': [
                        f'У вас {stale.total_stale} зависших сделок на сумму {stale.total_value}',
                        'Рекомендуется связаться с клиентами по этим сделкам',
                    ] if stale.total_stale > 0 else ['Воронка в хорошем состоянии'],
                }
            
            elif action == 'activity':
                managers = await engine.manager_performance(
                    user_id=arguments.get('user_id'),
                    date_from=date_from,
                    date_to=date_to,
                )
                
                return {
                    'report_type': 'activity',
                    'period': period,
                    'managers': [
                        {
                            'name': m.user_name,
                            'leads': m.total_leads,
                            'won': m.won_leads,
                            'revenue': m.total_revenue,
                            'win_rate': m.win_rate,
                        }
                        for m in managers.managers
                    ],
                }
            
            elif action == 'custom':
                metrics = arguments.get('metrics', ['revenue', 'deals_count'])
                group_by = arguments.get('group_by', 'month')
                
                result = {'report_type': 'custom', 'metrics': metrics, 'group_by': group_by}
                
                if 'revenue' in metrics:
                    revenue = await engine.revenue_trend(
                        group_by=group_by,
                        pipeline_id=arguments.get('pipeline_id'),
                        periods_count=12,
                    )
                    result['revenue_data'] = revenue.model_dump()
                
                return result
            
            else:
                return {'error': f'Unknown report action: {action}'}
    
    elif name == 'kommo_automate':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        action = arguments.get('action')
        if not action:
            return {'error': 'action is required'}
        
        dry_run = arguments.get('dry_run', True)
        
        if action == 'stale_followup':
            threshold_days = arguments.get('threshold_days', 14)
            task_text = arguments.get('task_text', 'Связаться с клиентом - сделка без активности')
            
            async with _get_session_factory()() as session:
                engine = AnalyticsEngine(session)
                stale = await engine.stale_deals(
                    threshold_days=threshold_days,
                    pipeline_id=arguments.get('pipeline_id'),
                    limit=arguments.get('limit', 50),
                )
            
            if dry_run:
                return {
                    'status': 'dry_run',
                    'action': 'stale_followup',
                    'would_create_tasks': stale.total_stale,
                    'deals': [{'id': d.lead_id, 'name': d.lead_name, 'days_inactive': d.days_inactive} for d in stale.deals[:10]],
                }
            
            # Create tasks for stale deals
            due_timestamp = int((datetime.now() + timedelta(days=1)).timestamp())
            tasks = [
                {
                    'text': task_text,
                    'complete_till': due_timestamp,
                    'entity_id': d.lead_id,
                    'entity_type': 'leads',
                }
                for d in stale.deals
            ]
            
            if tasks:
                result = await api.post('tasks', json=tasks)
                created = result.get('_embedded', {}).get('tasks', [])
                return {'status': 'executed', 'tasks_created': len(created)}
            
            return {'status': 'no_stale_deals', 'tasks_created': 0}
        
        elif action == 'escalation':
            threshold_days = arguments.get('threshold_days', 30)
            assign_to = arguments.get('assign_to')
            
            if not assign_to:
                return {'error': 'assign_to (user_id) is required for escalation'}
            
            async with _get_session_factory()() as session:
                engine = AnalyticsEngine(session)
                stale = await engine.stale_deals(
                    threshold_days=threshold_days,
                    pipeline_id=arguments.get('pipeline_id'),
                    limit=50,
                )
            
            if dry_run:
                return {
                    'status': 'dry_run',
                    'action': 'escalation',
                    'would_escalate': stale.total_stale,
                    'to_user': assign_to,
                    'deals': [{'id': d.lead_id, 'name': d.lead_name} for d in stale.deals[:10]],
                }
            
            # Reassign stale deals
            if stale.deals:
                updates = [{'id': d.lead_id, 'responsible_user_id': assign_to} for d in stale.deals]
                result = await api.patch('leads', json=updates)
                return {'status': 'escalated', 'count': len(updates), 'to_user': assign_to}
            
            return {'status': 'no_deals_to_escalate'}
        
        elif action == 'suggest':
            async with _get_session_factory()() as session:
                engine = AnalyticsEngine(session)
                
                stale = await engine.stale_deals(threshold_days=14, limit=10)
                churn = await engine.churn_risk(days_threshold=90, limit=10)
            
            suggestions = []
            
            if stale.total_stale > 5:
                suggestions.append({
                    'type': 'stale_followup',
                    'priority': 'high',
                    'description': f'Создать задачи для {stale.total_stale} зависших сделок',
                    'command': 'kommo_automate(action="stale_followup", threshold_days=14)',
                })
            
            if churn.high_risk_count > 3:
                suggestions.append({
                    'type': 'churn_prevention',
                    'priority': 'medium',
                    'description': f'Связаться с {churn.high_risk_count} клиентами в зоне риска оттока',
                    'command': 'kommo_analytics(action="churn")',
                })
            
            if not suggestions:
                suggestions.append({
                    'type': 'none',
                    'priority': 'low',
                    'description': 'CRM в хорошем состоянии, критических автоматизаций не требуется',
                })
            
            return {'suggestions': suggestions}
        
        elif action == 'check_rules':
            # Placeholder for rule checking
            return {
                'status': 'info',
                'message': 'Rule checking is configured via Kommo interface. Use suggest action for AI recommendations.',
            }
        
        elif action == 'welcome_sequence':
            return {
                'status': 'info',
                'message': 'Welcome sequences should be configured via Kommo Digital Pipeline or Salesbot.',
                'recommendation': 'Use kommo_bulk with create_tasks to create onboarding tasks for new leads.',
            }
        
        else:
            return {'error': f'Unknown automate action: {action}'}
    
    elif name == 'kommo_insights':
        from kommo_mcp.analytics.engine import AnalyticsEngine
        
        action = arguments.get('action')
        if not action:
            return {'error': 'action is required'}
        
        limit = arguments.get('limit', 10)
        by = arguments.get('by', 'companies')
        
        async with _get_session_factory()() as session:
            engine = AnalyticsEngine(session)
            
            if action == 'top_clients':
                date_from = _parse_date(arguments.get('date_from'))
                date_to = _parse_date(arguments.get('date_to'))
                
                result = await engine.top_clients(
                    limit=limit,
                    date_from=date_from,
                    date_to=date_to,
                    by=by,
                )
                return result.model_dump()
            
            elif action == 'rfm':
                result = await engine.rfm_analysis(
                    limit=limit,
                    by=by,
                )
                return result.model_dump()
            
            elif action == 'workload':
                result = await engine.manager_workload()
                return result.model_dump()
            
            elif action == 'opportunities':
                days_inactive = arguments.get('days_inactive', 90)
                result = await engine.find_opportunities(
                    days_inactive=days_inactive,
                    limit=limit,
                )
                return result.model_dump()
            
            elif action == 'big_deals':
                threshold = arguments.get('threshold')
                result = await engine.big_deals(
                    threshold=threshold,
                    limit=limit,
                )
                return result.model_dump()
            
            else:
                return {'error': f'Unknown insights action: {action}'}
    
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
