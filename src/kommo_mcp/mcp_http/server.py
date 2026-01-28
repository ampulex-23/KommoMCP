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
