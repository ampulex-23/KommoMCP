"""MCP HTTP Server with SSE/Streamable transport for n8n integration."""

import json
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from kommo_mcp.config import init_settings
from kommo_mcp.webhooks.handlers import WebhookHandler

logger = logging.getLogger(__name__)

# Store for active sessions
_sessions: dict[str, dict] = {}


def create_mcp_http_app() -> FastAPI:
    """Create FastAPI application for MCP HTTP transport."""
    app = FastAPI(
        title='KommoMCP Server',
        description='MCP Server for Kommo CRM with HTTP Streamable transport',
        version='1.0.0',
    )
    
    webhook_handler = WebhookHandler()
    
    @app.get('/health')
    async def health_check():
        """Health check endpoint."""
        return {'status': 'ok', 'service': 'kommo-mcp'}
    
    @app.get('/oauth/callback')
    async def oauth_callback(code: str = None, state: str = None):
        """OAuth callback for Kommo integration verification."""
        return {'status': 'ok', 'message': 'OAuth callback received', 'code': code}
    
    @app.get('/mcp')
    async def mcp_info():
        """MCP server info."""
        return {
            'name': 'kommo-mcp',
            'version': '1.0.0',
            'protocol_version': '2024-11-05',
            'capabilities': {
                'tools': {},
                'resources': {},
            },
        }
    
    @app.post('/mcp')
    async def mcp_endpoint(request: Request):
        """
        MCP HTTP Streamable endpoint.
        Handles JSON-RPC requests for MCP protocol.
        """
        try:
            body = await request.json()
            logger.info(f'MCP request: {body.get("method")}')
            
            method = body.get('method')
            params = body.get('params', {})
            request_id = body.get('id')
            
            # Handle different MCP methods
            if method == 'initialize':
                result = await _handle_initialize(params)
            elif method == 'tools/list':
                result = await _handle_tools_list()
            elif method == 'tools/call':
                result = await _handle_tools_call(params)
            elif method == 'resources/list':
                result = await _handle_resources_list()
            elif method == 'resources/read':
                result = await _handle_resources_read(params)
            elif method == 'ping':
                result = {}
            else:
                return JSONResponse(
                    content={
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'error': {
                            'code': -32601,
                            'message': f'Method not found: {method}',
                        },
                    }
                )
            
            return JSONResponse(
                content={
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'result': result,
                }
            )
            
        except Exception as e:
            logger.exception('MCP request error')
            return JSONResponse(
                status_code=500,
                content={
                    'jsonrpc': '2.0',
                    'id': body.get('id') if 'body' in dir() else None,
                    'error': {
                        'code': -32603,
                        'message': str(e),
                    },
                },
            )
    
    # Webhook endpoints (keep existing functionality)
    @app.post('/webhook/kommo')
    async def receive_webhook(request: Request):
        """Receive webhook from Kommo."""
        try:
            form_data = await request.form()
            payload = dict(form_data)
            result = await webhook_handler.handle(payload)
            return JSONResponse(content=result)
        except Exception as e:
            logger.exception('Webhook error')
            return JSONResponse(status_code=500, content={'error': str(e)})
    
    return app


async def _handle_initialize(params: dict) -> dict:
    """Handle MCP initialize request."""
    return {
        'protocolVersion': '2024-11-05',
        'capabilities': {
            'tools': {},
            'resources': {},
        },
        'serverInfo': {
            'name': 'kommo-mcp',
            'version': '1.0.0',
        },
    }


async def _handle_tools_list() -> dict:
    """Return list of available MCP tools."""
    tools = [
        {
            'name': 'kommo_ping',
            'description': 'Check connection to Kommo API',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'required': [],
            },
        },
        {
            'name': 'kommo_leads_list',
            'description': 'Get list of leads with optional filters',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'limit': {'type': 'integer', 'description': 'Max results (default 50)'},
                    'page': {'type': 'integer', 'description': 'Page number'},
                    'query': {'type': 'string', 'description': 'Search query'},
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline'},
                    'status_id': {'type': 'integer', 'description': 'Filter by status'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_lead_get',
            'description': 'Get lead details by ID',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'lead_id': {'type': 'integer', 'description': 'Lead ID'},
                },
                'required': ['lead_id'],
            },
        },
        {
            'name': 'kommo_lead_create',
            'description': 'Create a new lead',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Lead name'},
                    'price': {'type': 'number', 'description': 'Lead price/value'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'status_id': {'type': 'integer', 'description': 'Status ID'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Responsible user ID'},
                },
                'required': ['name'],
            },
        },
        {
            'name': 'kommo_contacts_list',
            'description': 'Get list of contacts',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'limit': {'type': 'integer', 'description': 'Max results'},
                    'query': {'type': 'string', 'description': 'Search query'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_contact_create',
            'description': 'Create a new contact',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Contact name'},
                    'first_name': {'type': 'string', 'description': 'First name'},
                    'last_name': {'type': 'string', 'description': 'Last name'},
                },
                'required': ['name'],
            },
        },
        {
            'name': 'kommo_pipelines_list',
            'description': 'Get list of pipelines and stages',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'required': [],
            },
        },
        {
            'name': 'kommo_users_list',
            'description': 'Get list of users',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'required': [],
            },
        },
        {
            'name': 'kommo_pipeline_analytics',
            'description': 'Get pipeline analytics with conversion rates',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'date_from': {'type': 'string', 'description': 'Start date (ISO format)'},
                    'date_to': {'type': 'string', 'description': 'End date (ISO format)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_manager_performance',
            'description': 'Get manager performance statistics',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'description': 'User ID (optional)'},
                    'date_from': {'type': 'string', 'description': 'Start date'},
                    'date_to': {'type': 'string', 'description': 'End date'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_sales_forecast',
            'description': 'Generate sales forecast based on current pipeline. Returns expected, optimistic and pessimistic revenue projections.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (all pipelines if not specified)'},
                    'forecast_days': {'type': 'integer', 'description': 'Forecast horizon in days (default: 30)'},
                    'method': {'type': 'string', 'description': 'Forecasting method: weighted, historical, optimistic'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_funnel_analysis',
            'description': 'Detailed funnel conversion analysis. Shows how leads flow through pipeline stages with conversion rates.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID to analyze'},
                    'date_from': {'type': 'string', 'description': 'Start date (ISO format)'},
                    'date_to': {'type': 'string', 'description': 'End date (ISO format)'},
                },
                'required': ['pipeline_id'],
            },
        },
        {
            'name': 'kommo_sync_start',
            'description': 'Start data synchronization from Kommo to local database',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'full': {'type': 'boolean', 'description': 'Full sync (true) or incremental (false)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_sync_status',
            'description': 'Get current synchronization status',
            'inputSchema': {
                'type': 'object',
                'properties': {},
                'required': [],
            },
        },
        {
            'name': 'kommo_stale_deals',
            'description': 'Find deals that have been inactive for too long. Shows stuck deals that need attention.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'threshold_days': {'type': 'integer', 'description': 'Days without activity to consider stale (default: 14)'},
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline ID'},
                    'limit': {'type': 'integer', 'description': 'Max deals to return (default: 50)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_lead_sources',
            'description': 'Analyze lead sources effectiveness. Shows which channels bring the most leads and conversions.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline ID'},
                    'date_from': {'type': 'string', 'description': 'Start date (ISO format)'},
                    'date_to': {'type': 'string', 'description': 'End date (ISO format)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_revenue_trend',
            'description': 'Get revenue trend over time. Shows how revenue changes by day/week/month with growth indicators.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'group_by': {'type': 'string', 'description': 'Grouping: day, week, month (default: month)'},
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline ID'},
                    'periods_count': {'type': 'integer', 'description': 'Number of periods (default: 12)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_churn_risk',
            'description': 'Analyze churn risk for contacts. Identifies customers who may stop buying based on deal history.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'days_threshold': {'type': 'integer', 'description': 'Days without deal to consider at risk (default: 90)'},
                    'min_deals': {'type': 'integer', 'description': 'Min past deals to include (default: 1)'},
                    'limit': {'type': 'integer', 'description': 'Max contacts to return (default: 50)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_lead_score',
            'description': 'Score leads to prioritize sales efforts. Calculates score based on value, stage, freshness, and activity.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline ID'},
                    'limit': {'type': 'integer', 'description': 'Max leads to return (default: 50)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_duplicates_find',
            'description': 'Find duplicate contacts or companies by name. Helps clean up the database.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'entity_type': {'type': 'string', 'description': 'Entity type: contacts or companies (default: contacts)'},
                    'limit': {'type': 'integer', 'description': 'Max duplicate groups to return (default: 50)'},
                },
                'required': [],
            },
        },
        {
            'name': 'kommo_task_create',
            'description': 'Create a new task in Kommo CRM. Can be linked to lead, contact, or company.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Task description/text'},
                    'complete_till': {'type': 'string', 'description': 'Due date/time (ISO format or Unix timestamp)'},
                    'entity_id': {'type': 'integer', 'description': 'ID of linked entity (lead, contact, company)'},
                    'entity_type': {'type': 'string', 'description': 'Entity type: leads, contacts, companies'},
                    'task_type_id': {'type': 'integer', 'description': 'Task type ID (1=call, 2=meeting, 3=email)'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Responsible user ID'},
                },
                'required': ['text', 'complete_till'],
            },
        },
        {
            'name': 'kommo_note_create',
            'description': 'Add a note to a lead, contact, or company in Kommo CRM.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Note text content'},
                    'entity_id': {'type': 'integer', 'description': 'ID of entity to add note to'},
                    'entity_type': {'type': 'string', 'description': 'Entity type: leads, contacts, companies'},
                },
                'required': ['text', 'entity_id', 'entity_type'],
            },
        },
        {
            'name': 'kommo_analytics',
            'description': '''Universal analytics tool. Combines all analytics functions in one.

Actions:
- pipeline: Pipeline performance (conversion, avg check, cycle time)
- funnel: Funnel conversion analysis by stage
- forecast: Sales predictions (expected, optimistic, pessimistic)
- managers: Manager performance comparison
- revenue: Revenue trend by day/week/month
- stale: Find stuck deals without activity
- sources: Lead sources effectiveness
- churn: Customers at risk of churn
- scoring: Score leads to prioritize
- duplicates: Find duplicate contacts/companies''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['pipeline', 'funnel', 'forecast', 'managers', 'revenue', 'stale', 'sources', 'churn', 'scoring', 'duplicates'],
                        'description': 'Analytics action to perform',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (for pipeline, funnel, forecast, revenue, stale, sources, scoring)'},
                    'user_id': {'type': 'integer', 'description': 'User ID (for managers)'},
                    'date_from': {'type': 'string', 'description': 'Start date ISO (for pipeline, funnel, sources)'},
                    'date_to': {'type': 'string', 'description': 'End date ISO (for pipeline, funnel, sources)'},
                    'forecast_days': {'type': 'integer', 'description': 'Forecast horizon days (for forecast, default: 30)'},
                    'group_by': {'type': 'string', 'description': 'Grouping: day/week/month (for revenue, default: month)'},
                    'periods_count': {'type': 'integer', 'description': 'Number of periods (for revenue, default: 12)'},
                    'threshold_days': {'type': 'integer', 'description': 'Days threshold (for stale: 14, churn: 90)'},
                    'limit': {'type': 'integer', 'description': 'Max results (for stale, churn, scoring, duplicates, default: 50)'},
                    'entity_type': {'type': 'string', 'description': 'Entity type: contacts/companies (for duplicates)'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_entity',
            'description': '''Universal entity management tool. Create, read, update entities in CRM.

Actions:
- get: Get entity by ID with full details and related entities
- list: List entities with filters, sorting, pagination
- create: Create new entity (lead, contact, company)
- update: Update entity fields
- link: Link entities together (contact to lead, company to contact)
- unlink: Remove link between entities
- move: Move lead to another stage/pipeline
- history: Get entity change history''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['get', 'list', 'create', 'update', 'link', 'unlink', 'move', 'history'],
                        'description': 'Action to perform',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies', 'tasks', 'notes'],
                        'description': 'Entity type',
                    },
                    'entity_id': {'type': 'integer', 'description': 'Entity ID (for get, update, link, move, history)'},
                    'data': {'type': 'object', 'description': 'Entity data (for create, update)'},
                    'filters': {'type': 'object', 'description': 'Filters for list (pipeline_id, status_id, user_id, query, tags)'},
                    'target_entity_type': {'type': 'string', 'description': 'Target entity type (for link/unlink)'},
                    'target_entity_id': {'type': 'integer', 'description': 'Target entity ID (for link/unlink)'},
                    'stage_id': {'type': 'integer', 'description': 'Stage ID (for move)'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (for move, list)'},
                    'limit': {'type': 'integer', 'description': 'Max results (default: 50)'},
                    'offset': {'type': 'integer', 'description': 'Offset for pagination'},
                    'sort_by': {'type': 'string', 'description': 'Sort field (created_at, updated_at, price)'},
                    'sort_order': {'type': 'string', 'enum': ['asc', 'desc'], 'description': 'Sort order'},
                },
                'required': ['action', 'entity_type'],
            },
        },
        {
            'name': 'kommo_bulk',
            'description': '''Bulk operations on multiple entities. Mass updates, assignments, tagging.

Actions:
- update: Update multiple entities matching criteria
- assign: Reassign entities to another user
- tag: Add/remove tags from entities
- move: Move multiple leads to stage
- create_tasks: Create tasks for multiple entities
- delete: Delete multiple entities (careful!)
- export: Export entities to structured format''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['update', 'assign', 'tag', 'move', 'create_tasks', 'delete', 'export'],
                        'description': 'Bulk action to perform',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies', 'tasks'],
                        'description': 'Entity type to operate on',
                    },
                    'filters': {
                        'type': 'object',
                        'description': 'Criteria to select entities (pipeline_id, stage_id, user_id, tags, date_from, date_to, stale_days)',
                    },
                    'entity_ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Specific entity IDs (alternative to filters)',
                    },
                    'changes': {'type': 'object', 'description': 'Changes to apply (for update)'},
                    'user_id': {'type': 'integer', 'description': 'Target user ID (for assign)'},
                    'tags': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Tags to add/remove'},
                    'tag_action': {'type': 'string', 'enum': ['add', 'remove'], 'description': 'Tag action'},
                    'stage_id': {'type': 'integer', 'description': 'Target stage (for move)'},
                    'task_text': {'type': 'string', 'description': 'Task text (for create_tasks)'},
                    'task_due_days': {'type': 'integer', 'description': 'Days until task due (for create_tasks)'},
                    'dry_run': {'type': 'boolean', 'description': 'Preview changes without applying (default: false)'},
                    'limit': {'type': 'integer', 'description': 'Max entities to process (default: 100)'},
                },
                'required': ['action', 'entity_type'],
            },
        },
        {
            'name': 'kommo_search',
            'description': '''Smart search across CRM data. Natural language queries, fuzzy matching, related entities.

Actions:
- query: Natural language search ("крупные сделки в работе", "контакты без email")
- similar: Find similar entities to given one
- related: Find all related entities (contacts of company, deals of contact)
- recent: Recently viewed/modified entities
- saved: Execute saved search/filter''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['query', 'similar', 'related', 'recent', 'saved'],
                        'description': 'Search action',
                    },
                    'query': {'type': 'string', 'description': 'Search query (natural language or keywords)'},
                    'entity_types': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Entity types to search (leads, contacts, companies, tasks, notes)',
                    },
                    'entity_id': {'type': 'integer', 'description': 'Entity ID (for similar, related)'},
                    'entity_type': {'type': 'string', 'description': 'Entity type (for similar, related)'},
                    'include_related': {'type': 'boolean', 'description': 'Include related entities in results'},
                    'date_from': {'type': 'string', 'description': 'Filter by date from'},
                    'date_to': {'type': 'string', 'description': 'Filter by date to'},
                    'limit': {'type': 'integer', 'description': 'Max results (default: 20)'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_report',
            'description': '''Generate formatted reports from CRM data. Summaries, comparisons, exports.

Actions:
- summary: Daily/weekly/monthly summary (deals, revenue, tasks)
- comparison: Compare periods or managers
- pipeline_health: Pipeline status overview
- activity: Activity report (calls, meetings, tasks)
- custom: Custom report with specified metrics''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['summary', 'comparison', 'pipeline_health', 'activity', 'custom'],
                        'description': 'Report type',
                    },
                    'period': {
                        'type': 'string',
                        'enum': ['today', 'yesterday', 'week', 'month', 'quarter', 'year', 'custom'],
                        'description': 'Report period',
                    },
                    'date_from': {'type': 'string', 'description': 'Start date for custom period'},
                    'date_to': {'type': 'string', 'description': 'End date for custom period'},
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline'},
                    'user_id': {'type': 'integer', 'description': 'Filter by user'},
                    'compare_with': {'type': 'string', 'description': 'Period to compare: previous_period, previous_year'},
                    'metrics': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Metrics for custom report: revenue, deals_count, conversion, avg_check, cycle_time',
                    },
                    'group_by': {'type': 'string', 'description': 'Group by: day, week, month, manager, pipeline, stage'},
                    'format': {'type': 'string', 'enum': ['text', 'table', 'json'], 'description': 'Output format'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_automate',
            'description': '''Automation rules and triggers. Set up automatic actions based on conditions.

Actions:
- check_rules: Check which automation rules would trigger for given conditions
- suggest: Get AI suggestions for automations based on CRM patterns
- stale_followup: Auto-create tasks for stale deals
- welcome_sequence: Set up welcome actions for new leads
- escalation: Escalate deals based on criteria''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['check_rules', 'suggest', 'stale_followup', 'welcome_sequence', 'escalation'],
                        'description': 'Automation action',
                    },
                    'trigger_type': {'type': 'string', 'description': 'Trigger: deal_created, deal_moved, deal_stale, contact_created'},
                    'conditions': {'type': 'object', 'description': 'Conditions to check'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline for automation'},
                    'threshold_days': {'type': 'integer', 'description': 'Days threshold for stale/escalation'},
                    'task_text': {'type': 'string', 'description': 'Task text for auto-created tasks'},
                    'assign_to': {'type': 'integer', 'description': 'User ID to assign'},
                    'dry_run': {'type': 'boolean', 'description': 'Preview without executing'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_insights',
            'description': '''Business insights and opportunities tool. Actions:
- top_clients: Top clients by revenue
- rfm: RFM segmentation analysis (Recency, Frequency, Monetary)
- workload: Manager workload distribution
- opportunities: Find upsell/cross-sell/reactivation opportunities
- big_deals: Large deals in pipeline
- ranking: Manager ranking by revenue/conversion/deals
- compare: Period comparison (month/quarter/year vs previous or YoY)
- yoy: Year-over-year comparison for specific month''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['top_clients', 'rfm', 'workload', 'opportunities', 'big_deals', 'ranking', 'compare', 'yoy'],
                        'description': 'Insight action',
                    },
                    'limit': {'type': 'integer', 'description': 'Number of results (default 10)'},
                    'by': {'type': 'string', 'enum': ['companies', 'contacts'], 'description': 'Group by companies or contacts'},
                    'date_from': {'type': 'string', 'description': 'Start date (ISO format)'},
                    'date_to': {'type': 'string', 'description': 'End date (ISO format)'},
                    'days_inactive': {'type': 'integer', 'description': 'Days of inactivity for opportunities'},
                    'threshold': {'type': 'number', 'description': 'Value threshold for big deals'},
                    'ranking_by': {'type': 'string', 'enum': ['revenue', 'conversion', 'deals_won'], 'description': 'Ranking criteria'},
                    'period': {'type': 'string', 'enum': ['month', 'quarter', 'year'], 'description': 'Period for comparison'},
                    'compare_with': {'type': 'string', 'enum': ['previous', 'yoy'], 'description': 'Compare with previous period or YoY'},
                    'month': {'type': 'integer', 'description': 'Month number (1-12) for YoY comparison'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_search',
            'description': '''Advanced search across CRM. Actions:
- query: Search by text query (API)
- all: Search across leads, contacts, companies (DB)
- leads: Advanced lead search with filters (DB)
- contacts: Contact search (DB)
- related: Get related entities
- recent: Get recently updated entities
- similar: Find similar entities''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['query', 'all', 'leads', 'contacts', 'related', 'recent', 'similar'],
                        'description': 'Search action',
                    },
                    'query': {'type': 'string', 'description': 'Search query'},
                    'entity_types': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Entity types for all search'},
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline'},
                    'status_id': {'type': 'integer', 'description': 'Filter by status'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Filter by responsible user'},
                    'price_min': {'type': 'integer', 'description': 'Minimum price'},
                    'price_max': {'type': 'integer', 'description': 'Maximum price'},
                    'is_open': {'type': 'boolean', 'description': 'Filter open/closed deals'},
                    'days': {'type': 'integer', 'description': 'Created in last N days'},
                    'limit': {'type': 'integer', 'description': 'Max items to return'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_deals_ext',
            'description': '''Extended deal management and analytics. Actions:
- by_stage: Deals grouped by stage with counts and values
- health: Deal health analysis (stale, no tasks, no responsible)
- velocity: Deal velocity metrics (win rate, cycle time)
- at_risk: Find deals at risk of being lost
- by_user: Deals grouped by responsible user''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['by_stage', 'health', 'velocity', 'at_risk', 'by_user'],
                        'description': 'Deal action',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Filter by pipeline'},
                    'user_id': {'type': 'integer', 'description': 'Filter by user'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                    'stale_days': {'type': 'integer', 'description': 'Days threshold for stale deals'},
                    'include_closed': {'type': 'boolean', 'description': 'Include closed deals'},
                    'limit': {'type': 'integer', 'description': 'Max items to return'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_ltv',
            'description': '''Customer Lifetime Value analytics. Actions:
- by_source: LTV by lead source
- by_pipeline: LTV by pipeline
- cohorts: Cohort analysis by first purchase month
- segments: Customer segmentation (VIP, Regular, Low)''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['by_source', 'by_pipeline', 'cohorts', 'segments'],
                        'description': 'LTV action',
                    },
                    'months': {'type': 'integer', 'description': 'Period in months for cohort analysis'},
                    'limit': {'type': 'integer', 'description': 'Max items to return'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_tasks_ext',
            'description': '''Extended task management. Actions:
- overdue: Get overdue tasks
- stats: Task statistics (completion rate, by user)
- today: Tasks due today
- by_entity: Tasks for specific entity
- without_responsible: Tasks without assigned user''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['overdue', 'stats', 'today', 'by_entity', 'without_responsible'],
                        'description': 'Task action',
                    },
                    'user_id': {'type': 'integer', 'description': 'Filter by user ID'},
                    'entity_type': {'type': 'string', 'enum': ['leads', 'contacts', 'companies'], 'description': 'Entity type for by_entity'},
                    'entity_id': {'type': 'integer', 'description': 'Entity ID for by_entity'},
                    'days': {'type': 'integer', 'description': 'Period in days for stats'},
                    'include_completed': {'type': 'boolean', 'description': 'Include completed tasks'},
                    'limit': {'type': 'integer', 'description': 'Max items to return'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_contacts_ext',
            'description': '''Extended contact management. Actions:
- search: Smart contact search with filters
- without_deals: Find contacts without any deals
- linked: Get all linked entities (deals, companies, tasks)
- duplicates: Find duplicate contacts
- merge_preview: Preview merge of contacts
- activity: Contact activity summary (calls, emails, deals)
- by_responsible: Contacts grouped by responsible user
- recent: Recently created contacts''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['search', 'without_deals', 'linked', 'duplicates', 'merge_preview', 'activity', 'by_responsible', 'recent'],
                        'description': 'Contact action',
                    },
                    'query': {'type': 'string', 'description': 'Search query for name'},
                    'contact_id': {'type': 'integer', 'description': 'Contact ID for linked action'},
                    'contact_ids': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'Contact IDs for merge_preview'},
                    'has_deals': {'type': 'boolean', 'description': 'Filter: has deals or not'},
                    'responsible_user_id': {'type': 'integer', 'description': 'Filter by responsible user'},
                    'days': {'type': 'integer', 'description': 'Period in days'},
                    'limit': {'type': 'integer', 'description': 'Max items to return'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_communications',
            'description': '''Communication history and activity tracking. Actions:
- history: Full communication history for entity (calls, emails, notes)
- calls: Call statistics (incoming/outgoing, duration, by user)
- timeline: Activity timeline for period
- last_contact: When was last contact with entity
- by_user: Communication stats by user
- summary: Overall communication summary
- no_contact: Clients with no recent contact''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['history', 'calls', 'timeline', 'last_contact', 'by_user', 'summary', 'no_contact'],
                        'description': 'Communication action',
                    },
                    'entity_type': {'type': 'string', 'enum': ['leads', 'contacts', 'companies'], 'description': 'Entity type'},
                    'entity_id': {'type': 'integer', 'description': 'Entity ID'},
                    'user_id': {'type': 'integer', 'description': 'Filter by user ID'},
                    'days': {'type': 'integer', 'description': 'Period in days (default 30)'},
                    'limit': {'type': 'integer', 'description': 'Max items to return'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_setup',
            'description': '''CRM setup and configuration tool. Actions:
- templates: List available pipeline templates
- create_pipeline: Create a new pipeline with stages
- create_stage: Add a stage to existing pipeline
- create_field: Create a custom field
- apply_template: Apply a template to create pipeline with stages and fields
- create_source: Add a lead source to pipeline''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['templates', 'create_pipeline', 'create_stage', 'create_field', 'apply_template', 'create_source'],
                        'description': 'Setup action',
                    },
                    'template': {'type': 'string', 'description': 'Template name: sales, services, rental, realestate, education, ecommerce'},
                    'pipeline_name': {'type': 'string', 'description': 'Pipeline name'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID for adding stages/sources'},
                    'stage_name': {'type': 'string', 'description': 'Stage name'},
                    'stage_sort': {'type': 'integer', 'description': 'Stage sort order (10, 20, 30...)'},
                    'stage_color': {'type': 'string', 'description': 'Stage color hex (#fffeb2)'},
                    'field_name': {'type': 'string', 'description': 'Custom field name'},
                    'field_type': {'type': 'string', 'enum': ['text', 'numeric', 'checkbox', 'select', 'multiselect', 'date', 'url', 'textarea'], 'description': 'Field type'},
                    'entity_type': {'type': 'string', 'enum': ['leads', 'contacts', 'companies'], 'description': 'Entity type for custom field'},
                    'source_name': {'type': 'string', 'description': 'Lead source name'},
                    'dry_run': {'type': 'boolean', 'description': 'Preview without creating (default true)'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_data_quality',
            'description': '''Data quality analysis tool. Actions:
- report: Full data quality report with scores and recommendations
- deals: Check deal/lead quality (missing fields, zero prices)
- duplicates: Find duplicate contacts/companies
- validate: Validate data completeness''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['report', 'deals', 'duplicates', 'validate'],
                        'description': 'Quality check action',
                    },
                    'entity_type': {'type': 'string', 'enum': ['contacts', 'companies'], 'description': 'Entity type for duplicates'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID for deal quality check'},
                },
                'required': ['action'],
            },
        },
        {
            'name': 'kommo_alerts',
            'description': '''Smart alerts and notifications tool. Actions:
- check: Generate all alerts (stale deals, overdue tasks, churn risk, performance drops)
- digest: Daily/weekly/monthly digest with key metrics and comparisons
- stale: Alerts for stale deals only
- overdue: Alerts for overdue tasks only
- performance: Alerts for manager performance drops''',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['check', 'digest', 'stale', 'overdue', 'performance'],
                        'description': 'Alert action',
                    },
                    'period': {'type': 'string', 'enum': ['day', 'week', 'month'], 'description': 'Period for digest'},
                    'stale_threshold_days': {'type': 'integer', 'description': 'Days threshold for stale deals (default 14)'},
                    'churn_threshold_days': {'type': 'integer', 'description': 'Days threshold for churn risk (default 90)'},
                },
                'required': ['action'],
            },
        },
    ]
    
    return {'tools': tools}


async def _handle_tools_call(params: dict) -> dict:
    """Execute an MCP tool."""
    tool_name = params.get('name')
    arguments = params.get('arguments', {})
    
    logger.info(f'Calling tool: {tool_name} with args: {arguments}')
    
    # Import and execute tool
    from kommo_mcp.server import _execute_tool
    
    try:
        result = await _execute_tool(tool_name, arguments)
        return {
            'content': [
                {
                    'type': 'text',
                    'text': json.dumps(result, ensure_ascii=False, default=str),
                }
            ],
        }
    except Exception as e:
        logger.exception(f'Tool execution error: {tool_name}')
        return {
            'content': [
                {
                    'type': 'text',
                    'text': f'Error: {str(e)}',
                }
            ],
            'isError': True,
        }


async def _handle_resources_list() -> dict:
    """Return list of available resources."""
    return {'resources': []}


async def _handle_resources_read(params: dict) -> dict:
    """Read a resource."""
    return {'contents': []}


def run_mcp_http_server():
    """Run MCP HTTP server standalone."""
    import uvicorn
    
    settings = init_settings()
    app = create_mcp_http_app()
    
    uvicorn.run(
        app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == '__main__':
    run_mcp_http_server()
