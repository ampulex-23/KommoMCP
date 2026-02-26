"""
AI Chat module - integrates OpenAI with MCP tools.
Uses RAG-based tool retrieval for dynamic prompt generation.
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional, List, Dict, Any

import aiohttp

from kommo_mcp.telegram.tool_retriever import get_retriever, build_dynamic_prompt
from kommo_mcp.telegram.interaction_logger import get_interaction_logger
from kommo_mcp.planner.tool_graph_planner import ToolGraphPlanner

logger = logging.getLogger(__name__)


def _md_to_html(text: str) -> str:
    """Convert Markdown formatting to Telegram HTML."""
    if not text:
        return text
    # Bold: **text** or __text__ -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Italic: *text* or _text_ (but not inside words)
    text = re.sub(r'(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)', r'<i>\1</i>', text)
    # Code: `text` -> <code>text</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Headers: ### text -> <b>text</b>
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    # Markdown list dashes at start of line -> •
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    return text

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
            'description': 'Task management: overdue, stats, by_entity, today, without_responsible, prioritize, reassign, postpone, plan_day',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['overdue', 'stats', 'by_entity', 'today', 'without_responsible', 'prioritize', 'reassign', 'postpone', 'plan_day', 'delegate', 'dependencies', 'mass_create', 'smart_reminders', 'meeting_briefing', 'meeting_prep'],
                        'description': 'Action to perform',
                    },
                    'task_id': {'type': 'integer', 'description': 'Task ID (for reassign/postpone)'},
                    'user_id': {'type': 'integer', 'description': 'User ID'},
                    'days': {'type': 'integer', 'description': 'Period in days / days to postpone'},
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
            'description': 'Contact management: search, without_deals, linked, activity, by_responsible, recent, inactive',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['search', 'without_deals', 'linked', 'activity', 'by_responsible', 'recent', 'inactive'],
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
                        'enum': ['top_clients', 'rfm', 'workload', 'opportunities', 'big_deals', 'ranking', 'compare', 'yoy', 'actionable', 'root_cause', 'stale_analysis', 'campaign_roi'],
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
            'description': 'Search CRM: all, leads, contacts, query, related, recent, similar, top_deals',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['all', 'leads', 'contacts', 'query', 'related', 'recent', 'similar', 'top_deals', 'deal_context', 'timeline', 'graph', 'nl_query', 'problems', 'bottlenecks', 'rejection_reasons', 'payment_status', 'audit_trail'],
                        'description': 'Search action',
                    },
                    'query': {'type': 'string', 'description': 'Search query'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'min_price': {'type': 'number', 'description': 'Minimum price'},
                    'max_price': {'type': 'number', 'description': 'Maximum price'},
                    'created_from': {'type': 'string', 'description': 'Created after (YYYY-MM-DD or unix timestamp)'},
                    'created_to': {'type': 'string', 'description': 'Created before (YYYY-MM-DD or unix timestamp)'},
                    'sort_by': {'type': 'string', 'enum': ['price', 'created_at', 'updated_at'], 'description': 'Sort field'},
                    'sort_order': {'type': 'string', 'enum': ['asc', 'desc'], 'description': 'Sort direction (default desc)'},
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
            'description': 'Full CRM management: create/update/delete pipelines, stages, fields. IMPORTANT: set dry_run=false to actually execute!',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'create_pipeline', 'update_pipeline', 'delete_pipeline',
                            'create_stage', 'update_stage', 'delete_stage', 'reorder_stages',
                            'create_field', 'update_field', 'delete_field',
                            'create_source', 'templates', 'apply_template'
                        ],
                        'description': 'Action to perform',
                    },
                    'dry_run': {
                        'type': 'boolean',
                        'description': 'If true, only preview. Set to false to actually create!',
                        'default': False,
                    },
                    'template': {'type': 'string', 'description': 'Template name for apply_template'},
                    'pipeline_name': {'type': 'string', 'description': 'Pipeline name (for create/update)'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (required for most operations)'},
                    'stage_id': {'type': 'integer', 'description': 'Stage/status ID (for update/delete stage)'},
                    'stage_name': {'type': 'string', 'description': 'Stage name (for create/update)'},
                    'stage_sort': {'type': 'integer', 'description': 'Stage sort order (10, 20, 30...)'},
                    'stage_color': {
                        'type': 'string',
                        'enum': ['#fffeb2', '#fffd7f', '#fff000', '#ffeab2', '#ffdc7f', '#ffce5a', '#ffdbdb', '#ffc8c8', '#ff8f92', '#d6eaff', '#c1e0ff', '#98cbff', '#ebffb1', '#deff81', '#87f2c0', '#f9deff', '#f3beff', '#ccc8f9', '#eb93ff', '#f2f3f4', '#e6e8ea'],
                        'description': 'Stage color (use only these exact values)',
                    },
                    'stages_order': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Array of stage IDs in desired order (for reorder_stages)',
                    },
                    'field_id': {'type': 'integer', 'description': 'Field ID (for update/delete field)'},
                    'field_name': {'type': 'string', 'description': 'Field name'},
                    'field_type': {
                        'type': 'string',
                        'enum': ['text', 'numeric', 'checkbox', 'select', 'multiselect', 'date', 'url', 'textarea', 'birthday', 'legal_entity', 'date_time', 'streetaddress', 'smart_address', 'tracking_data'],
                        'description': 'Field type. Use "numeric" for budget/price fields.',
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
    {
        'type': 'function',
        'function': {
            'name': 'kommo_entity_actions',
            'description': 'Work with leads, contacts, companies: add notes, create tasks, view history, update fields',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'add_note', 'get_notes', 'get_history',
                            'create_task', 'get_tasks', 'complete_task',
                            'update_lead', 'update_contact', 'move_lead',
                            'link_contact', 'unlink_contact',
                            'reactivate_lead', 'clone_lead'
                        ],
                        'description': 'Action to perform',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies'],
                        'description': 'Entity type',
                    },
                    'entity_id': {
                        'type': 'integer',
                        'description': 'Entity ID (lead_id, contact_id, company_id)',
                    },
                    'note_text': {
                        'type': 'string',
                        'description': 'Note text for add_note',
                    },
                    'task_text': {
                        'type': 'string',
                        'description': 'Task description for create_task',
                    },
                    'task_type_id': {
                        'type': 'integer',
                        'description': 'Task type: 1=call, 2=meeting, 3=email (default 1)',
                    },
                    'complete_till': {
                        'type': 'string',
                        'description': 'Task deadline (YYYY-MM-DD or +1d, +3h)',
                    },
                    'task_id': {
                        'type': 'integer',
                        'description': 'Task ID for complete_task',
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID for move_lead',
                    },
                    'status_id': {
                        'type': 'integer',
                        'description': 'Status ID for move_lead',
                    },
                    'contact_id': {
                        'type': 'integer',
                        'description': 'Contact ID for link/unlink',
                    },
                    'fields': {
                        'type': 'object',
                        'description': 'Fields to update {field_id: value}',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_bulk_actions',
            'description': 'Bulk operations on multiple entities',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['mass_update', 'mass_move', 'mass_tag', 'mass_assign', 'mass_delete'],
                        'description': 'Bulk action',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies'],
                        'description': 'Entity type',
                    },
                    'entity_ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Array of entity IDs',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Target pipeline for mass_move'},
                    'status_id': {'type': 'integer', 'description': 'Target status for mass_move'},
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Tags to add for mass_tag',
                    },
                    'responsible_user_id': {'type': 'integer', 'description': 'User ID for mass_assign'},
                    'fields': {'type': 'object', 'description': 'Fields to update for mass_update'},
                },
                'required': ['action', 'entity_ids'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_users',
            'description': 'Get CRM users, their roles, and workload statistics',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'get', 'workload', 'activity'],
                        'description': 'Action: list all users, get user details, workload stats, activity log',
                    },
                    'user_id': {
                        'type': 'integer',
                        'description': 'User ID for get/workload/activity',
                    },
                    'days': {
                        'type': 'integer',
                        'description': 'Period in days for activity (default 7)',
                        'default': 7,
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_reports',
            'description': 'Generate various CRM reports and export data',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'sales_summary', 'pipeline_report', 'manager_report',
                            'leads_by_source', 'conversion_funnel', 'tasks_report',
                            'overdue_tasks', 'stale_deals', 'top_deals'
                        ],
                        'description': 'Report type',
                    },
                    'date_from': {
                        'type': 'string',
                        'description': 'Start date YYYY-MM-DD (default: 30 days ago)',
                    },
                    'date_to': {
                        'type': 'string',
                        'description': 'End date YYYY-MM-DD (default: today)',
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Filter by pipeline ID',
                    },
                    'user_id': {
                        'type': 'integer',
                        'description': 'Filter by user/manager ID',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Limit results (default 20)',
                        'default': 20,
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_webhooks',
            'description': 'Manage webhooks for CRM events',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'create', 'delete'],
                        'description': 'Webhook action',
                    },
                    'webhook_id': {
                        'type': 'integer',
                        'description': 'Webhook ID for delete',
                    },
                    'destination': {
                        'type': 'string',
                        'description': 'Webhook URL for create',
                    },
                    'events': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Events to subscribe: add_lead, update_lead, delete_lead, add_contact, etc',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_tags',
            'description': 'Manage tags for leads, contacts, companies',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'add', 'remove', 'search_by_tag'],
                        'description': 'Tag action',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies'],
                        'description': 'Entity type',
                    },
                    'entity_id': {
                        'type': 'integer',
                        'description': 'Entity ID for add/remove',
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Tag names to add/remove',
                    },
                    'tag_name': {
                        'type': 'string',
                        'description': 'Tag name for search_by_tag',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_custom_fields',
            'description': 'Manage and view custom fields for entities',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'get_values', 'set_value'],
                        'description': 'Action: list fields, get values, set value',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies'],
                        'description': 'Entity type',
                    },
                    'entity_id': {
                        'type': 'integer',
                        'description': 'Entity ID for get/set values',
                    },
                    'field_id': {
                        'type': 'integer',
                        'description': 'Field ID for set_value',
                    },
                    'value': {
                        'type': 'string',
                        'description': 'Value to set',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_sources',
            'description': 'Manage lead sources and analyze source performance',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'create', 'analytics'],
                        'description': 'Action: list sources, create source, analytics by source',
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID',
                    },
                    'source_name': {
                        'type': 'string',
                        'description': 'Source name for create',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_companies',
            'description': 'Manage companies: list, get details, create, update, link to contacts/leads',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'get', 'create', 'update', 'get_contacts', 'get_leads', 'link_contact'],
                        'description': 'Action to perform',
                    },
                    'company_id': {
                        'type': 'integer',
                        'description': 'Company ID for get/update/get_contacts/get_leads',
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Company name for create/search',
                    },
                    'contact_id': {
                        'type': 'integer',
                        'description': 'Contact ID for link_contact',
                    },
                    'query': {
                        'type': 'string',
                        'description': 'Search query for list',
                    },
                    'fields': {
                        'type': 'object',
                        'description': 'Fields to update',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Limit results (default 20)',
                        'default': 20,
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_duplicates',
            'description': 'Find and manage duplicate contacts/companies',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['find_contacts', 'find_companies', 'merge_contacts'],
                        'description': 'Action: find duplicates or merge',
                    },
                    'threshold': {
                        'type': 'number',
                        'description': 'Similarity threshold 0-1 (default 0.8)',
                        'default': 0.8,
                    },
                    'primary_id': {
                        'type': 'integer',
                        'description': 'Primary contact ID for merge (keeps this one)',
                    },
                    'duplicate_id': {
                        'type': 'integer',
                        'description': 'Duplicate contact ID for merge (will be deleted)',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_links',
            'description': 'Manage links between entities (leads, contacts, companies)',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['get', 'link', 'unlink'],
                        'description': 'Action: get links, create link, remove link',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies'],
                        'description': 'Source entity type',
                    },
                    'entity_id': {
                        'type': 'integer',
                        'description': 'Source entity ID',
                    },
                    'to_entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts', 'companies', 'catalog_elements'],
                        'description': 'Target entity type',
                    },
                    'to_entity_id': {
                        'type': 'integer',
                        'description': 'Target entity ID',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_catalogs',
            'description': 'Manage product catalogs and catalog elements (products, services)',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list_catalogs', 'get_catalog', 'list_elements', 'get_element', 'create_element', 'link_to_lead'],
                        'description': 'Action to perform',
                    },
                    'catalog_id': {
                        'type': 'integer',
                        'description': 'Catalog ID',
                    },
                    'element_id': {
                        'type': 'integer',
                        'description': 'Catalog element ID',
                    },
                    'lead_id': {
                        'type': 'integer',
                        'description': 'Lead ID for link_to_lead',
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Element name for create',
                    },
                    'price': {
                        'type': 'number',
                        'description': 'Element price',
                    },
                    'quantity': {
                        'type': 'integer',
                        'description': 'Quantity for link_to_lead',
                        'default': 1,
                    },
                    'query': {
                        'type': 'string',
                        'description': 'Search query for list_elements',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_events',
            'description': 'View and analyze CRM events (entity changes, notes, calls, etc)',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'by_entity', 'by_type', 'stats'],
                        'description': 'Action: list all, by entity, by type, or stats',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['lead', 'contact', 'company', 'customer', 'task'],
                        'description': 'Entity type for by_entity',
                    },
                    'entity_id': {
                        'type': 'integer',
                        'description': 'Entity ID for by_entity',
                    },
                    'event_type': {
                        'type': 'string',
                        'description': 'Event type filter (lead_added, lead_status_changed, note_added, etc)',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Limit results (default 50)',
                        'default': 50,
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_calls',
            'description': 'Manage call records and telephony integration',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'log_call', 'stats'],
                        'description': 'Action: list calls, log a call, or get stats',
                    },
                    'entity_type': {
                        'type': 'string',
                        'enum': ['leads', 'contacts'],
                        'description': 'Entity type for log_call',
                    },
                    'entity_id': {
                        'type': 'integer',
                        'description': 'Entity ID for log_call',
                    },
                    'phone': {
                        'type': 'string',
                        'description': 'Phone number',
                    },
                    'duration': {
                        'type': 'integer',
                        'description': 'Call duration in seconds',
                    },
                    'direction': {
                        'type': 'string',
                        'enum': ['inbound', 'outbound'],
                        'description': 'Call direction',
                    },
                    'result': {
                        'type': 'string',
                        'description': 'Call result/notes',
                    },
                    'days': {
                        'type': 'integer',
                        'description': 'Days for stats (default 30)',
                        'default': 30,
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_cleanup',
            'description': 'Clean up CRM data: delete leads, contacts, companies, or reset to default state',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['delete_leads', 'delete_contacts', 'delete_companies', 'delete_all', 'reset_pipelines', 'full_reset', 'preview'],
                        'description': 'Action: delete specific entities, delete all data, reset pipelines, or full reset',
                    },
                    'confirm': {
                        'type': 'boolean',
                        'description': 'Must be true to execute destructive actions',
                        'default': False,
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID - for delete_leads deletes only leads in this pipeline, for reset_pipelines resets specific pipeline',
                    },
                },
                'required': ['action', 'confirm'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_export',
            'description': 'Export CRM data as CSV/text. Returns formatted data for download.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['leads_csv', 'contacts_csv', 'analytics'],
                        'description': 'What to export: leads_csv, contacts_csv, or analytics summary',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Filter leads by pipeline'},
                    'status_id': {'type': 'integer', 'description': 'Filter leads by status'},
                    'limit': {'type': 'integer', 'description': 'Max rows (default 100)', 'default': 100},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_digest',
            'description': 'Generate CRM digest/summary: morning briefing, weekly report, or personal tasks',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['morning', 'weekly', 'my_tasks'],
                        'description': 'Digest type: morning (today overview), weekly (week summary), my_tasks (tasks for today)',
                    },
                    'user_id': {'type': 'integer', 'description': 'CRM user ID (for my_tasks)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_advisor',
            'description': 'AI-powered CRM advisor: recommendations, tips, analysis based on CRM data',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['next_action', 'pipeline_tips', 'loss_analysis', 'closing_tips', 'objections', 'next_best', 'funnel_optimize', 'strategy', 'qualification', 'qualification_checklist', 'negotiation', 'communication_style', 'product_recommendations', 'talking_points'],
                        'description': 'Advice type',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for deal-specific advice'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID for pipeline analysis'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_pipeline_health',
            'description': 'Deep pipeline health analysis: bottlenecks, velocity, win/loss ratio, stage conversion',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['check', 'velocity', 'bottlenecks', 'win_loss', 'optimize', 'hygiene', 'balance', 'coverage'],
                        'description': 'Analysis type: check (overall health), velocity (speed), bottlenecks (stuck stages), win_loss (ratio analysis)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional, analyzes all if omitted)'},
                    'days': {'type': 'integer', 'description': 'Analysis period in days (default 30)', 'default': 30},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_forecast',
            'description': 'Sales forecasting: pipeline forecast, revenue prediction, deal probability, trend analysis',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['pipeline', 'revenue', 'deal_probability', 'trends', 'cashflow', 'whatif', 'revenue_model', 'plan_fact', 'closing_forecast'],
                        'description': 'Forecast type: pipeline, revenue, deal_probability, trends, cashflow (expected payments), whatif (scenario modeling)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'days': {'type': 'integer', 'description': 'Forecast horizon in days (default 30)', 'default': 30},
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for deal_probability'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_alerts',
            'description': 'Proactive CRM alerts: health check, risk warnings, performance alerts, opportunity detection',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['check', 'risks', 'performance', 'opportunities', 'trends', 'early_warning', 'team'],
                        'description': 'Alert type: check, risks, performance, opportunities, trends, early_warning (predictive), team (per-user alerts)',
                    },
                    'days': {'type': 'integer', 'description': 'Analysis period in days (default 7)', 'default': 7},
                    'user_id': {'type': 'integer', 'description': 'Filter by user ID'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_compare',
            'description': 'Compare and analyze CRM data: period comparison, trend detection, pattern analysis, correlations',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['periods', 'trends', 'patterns', 'correlations'],
                        'description': 'Comparison type: periods (this vs last period), trends (metric over time), patterns (recurring patterns), correlations (metric relationships)',
                    },
                    'metric': {
                        'type': 'string',
                        'enum': ['deals', 'revenue', 'conversion', 'tasks', 'velocity'],
                        'description': 'Metric to analyze (default deals)',
                    },
                    'days': {'type': 'integer', 'description': 'Period length in days (default 30)', 'default': 30},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_automation',
            'description': 'Smart automation: auto-assign leads, round-robin distribution, auto follow-up task creation',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['auto_assign', 'round_robin', 'auto_followup', 'auto_archive', 'auto_followup_smart'],
                        'description': 'Automation type: auto_assign, round_robin, auto_followup, auto_archive (archive old closed deals)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID'},
                    'lead_ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Lead IDs to assign (optional, uses unassigned if omitted)',
                    },
                    'user_ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'User IDs to distribute among (optional, uses all active)',
                    },
                    'days_after': {'type': 'integer', 'description': 'Days after last activity for auto_followup (default 3)', 'default': 3},
                    'dry_run': {'type': 'boolean', 'description': 'Preview only, no changes (default true)', 'default': True},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_my',
            'description': 'Personal CRM view: my pipeline, my workload summary',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['pipeline', 'workload', 'team', 'insights'],
                        'description': 'View type: pipeline (my deals), workload (my load), team (team overview), insights (pipeline insights)',
                    },
                    'days': {'type': 'integer', 'description': 'Period in days (default 7)', 'default': 7},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_gamification',
            'description': 'Team gamification: leaderboards, achievements, challenges, points tracking',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['leaderboard', 'achievements', 'challenges', 'points', 'onboarding', 'badges', 'daily_quests', 'streaks'],
                        'description': 'Gamification type: leaderboard, achievements, challenges, points, onboarding (new hire ramp-up tracking)',
                    },
                    'days': {'type': 'integer', 'description': 'Period in days (default 30)', 'default': 30},
                    'metric': {
                        'type': 'string',
                        'enum': ['deals_won', 'revenue', 'tasks_completed', 'calls', 'conversion'],
                        'description': 'Metric for leaderboard (default deals_won)',
                    },
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_loss_analysis',
            'description': 'Deep analysis of lost deals: reasons, patterns, manager comparison',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['reasons', 'patterns', 'by_manager'],
                        'description': 'Analysis type: reasons (why deals lost), patterns (timing/stage patterns), by_manager (loss comparison)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'days': {'type': 'integer', 'description': 'Period in days (default 90)', 'default': 90},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_smart_time',
            'description': 'Smart timing analysis: best time to call, customer journey mapping',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['best_call_time', 'customer_journey', 'time_to_purchase', 'lead_response'],
                        'description': 'Analysis type: best_call_time (optimal contact hours), customer_journey (touch-to-purchase path)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'days': {'type': 'integer', 'description': 'Period in days (default 90)', 'default': 90},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_team_planner',
            'description': 'Team capacity planning and workload forecasting',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['capacity', 'forecast'],
                        'description': 'Planning type: capacity (current workload), forecast (predicted load based on pipeline)',
                    },
                    'days': {'type': 'integer', 'description': 'Planning horizon in days (default 14)', 'default': 14},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_segments',
            'description': 'Customer segmentation: by volume, lookalike, best manager match, basket analysis',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['by_volume', 'lookalike', 'best_manager', 'basket', 'by_behavior', 'retention'],
                        'description': 'Segment type: by_volume, lookalike, best_manager, basket, by_behavior (activity patterns), retention (manager retention rates)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for lookalike'},
                    'days': {'type': 'integer', 'description': 'Period in days (default 90)', 'default': 90},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_escalation',
            'description': 'Deal escalation: detect problematic deals, SLA violations, send notifications',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['check', 'notify', 'sla', 'support'],
                        'description': 'Escalation type: check (find deals needing escalation), notify (alert about critical deals), sla (SLA violation check)',
                    },
                    'days': {'type': 'integer', 'description': 'Threshold in days (default 7)', 'default': 7},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_reactivation',
            'description': 'Client reactivation: sleeping clients, lost deal nurture, churn prevention',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['sleeping', 'lost_nurture', 'churn_prevention', 'prevent', 'win_back'],
                        'description': 'Reactivation type: sleeping (inactive clients), lost_nurture (lost deals worth retrying), churn_prevention (at-risk active deals)',
                    },
                    'days': {'type': 'integer', 'description': 'Inactivity threshold in days (default 30)', 'default': 30},
                    'min_value': {'type': 'integer', 'description': 'Minimum deal value filter'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_contact_enrichment',
            'description': 'Contact data enrichment: analyze completeness, find duplicates, suggest enrichment',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['analyze', 'merge_duplicates', 'enrich', 'profile', 'social'],
                        'description': 'Enrichment type: analyze (data quality score), merge_duplicates (find mergeable contacts), enrich (suggest missing data)',
                    },
                    'limit': {'type': 'integer', 'description': 'Max contacts to analyze (default 50)', 'default': 50},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_templates',
            'description': 'Message templates: list, generate, personalize, sales scripts',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['list', 'generate', 'apply', 'personalize', 'sales_script', 'follow_up', 'closing_script'],
                        'description': 'Template type: list (saved templates), generate (AI template), apply (fill template), personalize (customize for lead), sales_script (stage-specific script)',
                    },
                    'template_type': {
                        'type': 'string',
                        'enum': ['welcome', 'followup', 'proposal', 'closing', 'reactivation', 'custom'],
                        'description': 'Template category',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for personalization'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID for sales scripts'},
                    'stage_name': {'type': 'string', 'description': 'Stage name for sales script'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_anomaly',
            'description': 'Anomaly detection: unusual patterns in deals, sales, activity',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['detect', 'sales'],
                        'description': 'Detection type: detect (general anomalies), sales (sales-specific anomalies)',
                    },
                    'days': {'type': 'integer', 'description': 'Analysis period in days (default 30)', 'default': 30},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_objections',
            'description': 'Objection handling: scripts, library of common objections, prediction',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['handle', 'library', 'predict', 'best_practices'],
                        'description': 'Action: handle (get response script), library (browse objections), predict (anticipate objections for deal)',
                    },
                    'objection': {'type': 'string', 'description': 'The objection text to handle'},
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for predict action'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_deal_intelligence',
            'description': 'Deal intelligence: enterprise deal analysis, stakeholder mapping, deal reviews',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['enterprise', 'stakeholders', 'review', 'pipeline_review', 'closing_signals'],
                        'description': 'Action: enterprise (complex deal analysis), stakeholders (contact mapping), review (deal health review)',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for analysis'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                    'min_value': {'type': 'integer', 'description': 'Min deal value filter (default 100000)', 'default': 100000},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_contact_scoring',
            'description': 'Contact scoring and value segmentation based on deal history',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['score', 'value_segments', 'by_value', 'company_scoring', 'relationship_strength', 'account_scoring'],
                        'description': 'Action: score (score contacts by engagement), value_segments (segment by lifetime value)',
                    },
                    'limit': {'type': 'integer', 'description': 'Max contacts (default 50)', 'default': 50},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_ai_coach',
            'description': 'AI sales coaching: deal review, skill assessment, skill gaps, role-play scenarios',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['review_deal', 'skill_assessment', 'skill_gaps', 'roleplay', 'best_practices', 'micro_learning'],
                        'description': 'Coaching type: review_deal, skill_assessment, skill_gaps, roleplay',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for deal review'},
                    'user_id': {'type': 'integer', 'description': 'User ID for skill assessment'},
                    'days': {'type': 'integer', 'description': 'Analysis period (default 30)', 'default': 30},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_smart_reply',
            'description': 'Smart reply suggestions: contextual responses, objection handling, communication context',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['suggest', 'objection_response', 'context', 'auto_reply'],
                        'description': 'Action: suggest (reply suggestions), objection_response (handle objection in context), context (communication history context)',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for context'},
                    'message': {'type': 'string', 'description': 'Client message to respond to'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_communication_analytics',
            'description': 'Communication analytics: conversation summaries, quality monitoring',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['summary', 'quality', 'sentiment', 'patterns', 'insights'],
                        'description': 'Action: summary (conversation summary for deal), quality (communication quality metrics)',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for summary'},
                    'user_id': {'type': 'integer', 'description': 'User ID for quality analysis'},
                    'days': {'type': 'integer', 'description': 'Period in days (default 30)', 'default': 30},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_doc_generator',
            'description': 'Document generation: presentations, proposals, case studies based on CRM data',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['presentation', 'proposal', 'case_study', 'commercial_offer', 'report', 'partner_report', 'exportable_report'],
                        'description': 'Document type: presentation (client deck), proposal (commercial proposal), case_study (success story)',
                    },
                    'lead_id': {'type': 'integer', 'description': 'Lead ID for personalization'},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_activity',
            'description': 'Activity analytics: team feed, productivity analysis, KPI tracking, recommendations, correlations',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['feed', 'productivity', 'kpi', 'recommendations', 'correlations'],
                        'description': 'Activity analysis type: feed (team activity stream), productivity (output analysis), kpi (activity KPIs), recommendations (improvement tips), correlations (activity-result links)',
                    },
                    'user_id': {'type': 'integer', 'description': 'User ID (optional, for specific user)'},
                    'days': {'type': 'integer', 'description': 'Period in days (default 30)', 'default': 30},
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional)'},
                },
                'required': ['action'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'kommo_lead_gen',
            'description': 'B2B lead generation: search companies by OKVED/region via DaData, search HoReCa via 2GIS, enrich contacts, import into CRM as leads/contacts/companies',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['search_companies', 'search_horeca', 'preview', 'import_to_crm', 'enrich'],
                        'description': 'Action: search_companies (by OKVED/region via DaData), search_horeca (restaurants/hotels via 2GIS), preview (show what will be found), import_to_crm (create leads in AmoCRM), enrich (get full details by INN)',
                    },
                    'okved': {
                        'type': 'string',
                        'description': 'OKVED code to search (e.g. 46.37 for tea/coffee wholesale, 56.10 for restaurants, 47.29.3 for tea shops)',
                    },
                    'query': {
                        'type': 'string',
                        'description': 'Search query for companies (e.g. "чай", "кофе оптом")',
                    },
                    'region': {
                        'type': 'string',
                        'description': 'Region filter (e.g. "Москва", "Краснодарский край", "Санкт-Петербург")',
                    },
                    'city': {
                        'type': 'string',
                        'description': 'City for HoReCa search via 2GIS (e.g. "Сочи", "Москва")',
                    },
                    'rubric': {
                        'type': 'string',
                        'description': 'Rubric for 2GIS search (e.g. "рестораны", "кафе", "гостиницы", "санатории")',
                    },
                    'inn': {
                        'type': 'string',
                        'description': 'INN for enrich action - get full company details',
                    },
                    'pipeline_id': {
                        'type': 'integer',
                        'description': 'Pipeline ID for import_to_crm',
                    },
                    'status_id': {
                        'type': 'integer',
                        'description': 'Status/stage ID for import_to_crm',
                    },
                    'tag': {
                        'type': 'string',
                        'description': 'Tag to assign to imported leads (e.g. "оптовики_чай", "horeca_сочи")',
                    },
                    'responsible_user_id': {
                        'type': 'integer',
                        'description': 'Responsible user ID for imported leads',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max results to return/import (default 20, max 100)',
                        'default': 20,
                    },
                },
                'required': ['action'],
            },
        },
    },
]

# Index MCP_TOOLS by function name for fast filtering
_MCP_TOOLS_INDEX: Dict[str, Dict] = {
    tool['function']['name']: tool for tool in MCP_TOOLS
}

# Planner singleton
_planner_instance: Optional[ToolGraphPlanner] = None


def get_planner() -> ToolGraphPlanner:
    """Get or create singleton ToolGraphPlanner instance."""
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = ToolGraphPlanner()
    return _planner_instance


def _filter_tools_by_plan(tool_names: List[str]) -> List[Dict]:
    """Filter MCP_TOOLS to only include tools from the plan.
    
    Falls back to full MCP_TOOLS if no tools match.
    """
    filtered = [_MCP_TOOLS_INDEX[name] for name in tool_names if name in _MCP_TOOLS_INDEX]
    return filtered if filtered else MCP_TOOLS


SYSTEM_PROMPT = """Ты - AI-ассистент для ПОЛНОГО управления CRM Kommo.

⚡ ПЛАНИРОВАНИЕ СЛОЖНЫХ ЗАДАЧ:
Если действие требует предварительных шагов - ВЫПОЛНИ ИХ АВТОМАТИЧЕСКИ:
- Удаление воронки → сначала удали все сделки в ней (kommo_cleanup delete_leads pipeline_id=X)
- Удаление контакта → сначала отвяжи от сделок (kommo_links unlink)
- Удаление компании → сначала отвяжи контакты и сделки
НЕ ПРОСИ пользователя делать это вручную! Выполни сам последовательно.

⚠️ ВАЖНО ПРИ СОЗДАНИИ ВОРОНКИ:
1. Сначала вызови create_pipeline и ДОЖДИСЬ ответа с pipeline_id
2. Только ПОТОМ создавай стадии с полученным pipeline_id
3. НЕ вызывай create_stage параллельно с create_pipeline!

🔧 СТРУКТУРА: kommo_setup (pipelines, stages, fields)
✏️ СУЩНОСТИ: kommo_entity_actions (notes, tasks, move, link)
📦 МАССОВЫЕ: kommo_bulk_actions (mass_move/tag/assign/update)
👥 ПОЛЬЗОВАТЕЛИ: kommo_users (list, workload, activity)
📊 ОТЧЁТЫ: kommo_reports (sales, pipeline, manager, tasks, stale_deals, top_deals)
🏷️ ТЕГИ: kommo_tags (list, add, remove, search_by_tag)
📝 ПОЛЯ: kommo_custom_fields (list, get_values, set_value)
🎯 ИСТОЧНИКИ: kommo_sources (list, create, analytics)
🏢 КОМПАНИИ: kommo_companies (list, get, create, update, get_contacts, get_leads, link_contact)
🔍 ДУБЛИКАТЫ: kommo_duplicates (find_contacts, find_companies, merge_contacts)
🔗 СВЯЗИ: kommo_links (get, link, unlink)

📦 КАТАЛОГИ (kommo_catalogs):
- list_catalogs: список каталогов
- get_catalog: детали каталога (catalog_id)
- list_elements: элементы каталога (catalog_id, query)
- get_element: детали элемента (catalog_id, element_id)
- create_element: создать элемент (catalog_id, name, price)
- link_to_lead: привязать к сделке (lead_id, catalog_id, element_id, quantity)

📅 СОБЫТИЯ (kommo_events):
- list: последние события (limit)
- by_entity: события сущности (entity_type, entity_id)
- by_type: события по типу (event_type)
- stats: статистика событий

📞 ЗВОНКИ (kommo_calls):
- list: список звонков
- log_call: записать звонок (entity_type, entity_id, phone, duration, direction, result)
- stats: статистика звонков (days)

🗑️ ЗАЧИСТКА (kommo_cleanup):
- preview: показать что будет удалено (без confirm)
- delete_leads: удалить сделки (confirm=true, pipeline_id=X для конкретной воронки)
- delete_contacts: удалить все контакты (confirm=true)
- delete_companies: удалить все компании (confirm=true)
- delete_all: удалить сделки+контакты+компании (confirm=true)
- reset_pipelines: сбросить воронки к дефолту (confirm=true)
- full_reset: полная зачистка + сброс воронок (confirm=true)

⚠️ УДАЛЕНИЕ ВОРОНКИ: сначала вызови kommo_cleanup delete_leads pipeline_id=X confirm=true, затем kommo_setup delete_pipeline

ФОРМАТИРОВАНИЕ ОТВЕТОВ (СТРОГО):
- Используй ТОЛЬКО HTML-теги для Telegram: <b>жирный</b>, <i>курсив</i>, <code>код/ID</code>
- НИКОГДА не используй Markdown: НЕ используй **, ##, ###, *, ```, - для списков
- Для списков используй эмодзи или цифры с точкой: "1. текст" или "• текст"
- Для заголовков используй <b>ЗАГОЛОВОК</b> с эмодзи
- Эмодзи: ✅❌📊📈💰👤🏢📋🔧⚡🏷️🔗📦📞🗑️🔄⏱️
- Пример правильного ответа:
  ✅ CRM настроена для воронки "<b>Продажи</b>":

  <b>📋 Воронка продаж:</b>
  1. Получение заявки
  2. Квалификация
  3. Коммерческое предложение
"""


class AIChat:
    """AI Chat with OpenAI and direct Kommo API integration."""
    
    # Conversation history per user (user_id -> list of messages)
    _conversation_history: Dict[str, List[Dict]] = {}
    _max_history_messages = 20  # Keep last N messages per user
    
    def __init__(
        self,
        openai_api_key: str,
        kommo_domain: str,
        kommo_token: str,
        model: str = 'gpt-5-mini',
        llm_base_url: str = None,
    ):
        self.openai_api_key = openai_api_key
        self.kommo_domain = kommo_domain
        self.kommo_token = kommo_token
        self.model = model
        self.llm_base_url = llm_base_url or os.getenv('LLM_BASE_URL', 'https://api.polza.ai/v1')
        self.kommo_base_url = f'https://{kommo_domain}'
    
    def _get_history(self, user_id: str) -> List[Dict]:
        """Get conversation history for user."""
        if user_id not in self._conversation_history:
            self._conversation_history[user_id] = []
        return self._conversation_history[user_id]
    
    def _add_to_history(self, user_id: str, role: str, content: str):
        """Add message to user's conversation history."""
        history = self._get_history(user_id)
        history.append({'role': role, 'content': content})
        # Trim old messages
        if len(history) > self._max_history_messages:
            self._conversation_history[user_id] = history[-self._max_history_messages:]
    
    def clear_history(self, user_id: str):
        """Clear conversation history for user."""
        if user_id in self._conversation_history:
            del self._conversation_history[user_id]
    
    async def chat(self, message: str, use_rag: bool = True, user_id: str = 'default') -> str:
        """Process user message with iterative tool calls for complex setup.
        
        Args:
            message: User message
            use_rag: If True, use RAG-based dynamic prompt. If False, use full static prompt.
            user_id: User identifier for conversation history
        """
        # Initialize interaction logger
        ilog = get_interaction_logger()
        session_id = ilog.start_session(user_id, message)
        
        try:
            # Step 1: Run Tool Graph Planner for deterministic chain planning
            planner = get_planner()
            planned_chain = planner.plan(message)
            planned_tool_names = planner.get_tool_filter(planned_chain)
            planner_prompt = ''

            if planned_chain.chain:
                # Filter MCP_TOOLS to only planned tools
                active_tools = _filter_tools_by_plan(planned_tool_names)
                planner_prompt = planner.build_prompt(planned_chain, message)
                logger.info(
                    f'Planner: {len(planned_chain.chain)} steps, '
                    f'cost={planned_chain.cost}, '
                    f'tools=[{", ".join(planned_tool_names)}], '
                    f'{planned_chain.latency_ms}ms'
                )
            else:
                # Fallback: no plan → use all tools
                active_tools = MCP_TOOLS
                logger.info('Planner: no chain found, using full tool set')

            # Step 2: Build dynamic prompt (RAG + planner)
            if use_rag:
                retriever = get_retriever()
                dynamic_prompt = build_dynamic_prompt(message, retriever, top_k=5)
                logger.info(f'RAG: retrieved tools for query, prompt size: {len(dynamic_prompt)} chars')
            else:
                dynamic_prompt = SYSTEM_PROMPT

            # Inject planner prompt into system prompt
            if planner_prompt:
                dynamic_prompt = dynamic_prompt + '\n\n' + planner_prompt
            
            # Log prompts
            ilog.log_prompt(SYSTEM_PROMPT, dynamic_prompt)
            
            # Get conversation history and build messages
            history = self._get_history(user_id)
            messages = [
                {'role': 'system', 'content': dynamic_prompt},
            ]
            # Add recent history (only user/assistant messages, not tool calls)
            for msg in history[-10:]:  # Last 10 messages for context
                messages.append(msg)
            # Add current message
            messages.append({'role': 'user', 'content': message})
            
            max_iterations = 10  # Limit iterations for safety
            all_results = []
            
            for iteration in range(max_iterations):
                response = await self._openai_request(messages=messages, tools=active_tools)
                
                # If no tool calls, we're done
                if not response.get('tool_calls'):
                    assistant_response = _md_to_html(response.get('content', 'Не удалось получить ответ'))
                    # Save to history
                    self._add_to_history(user_id, 'user', message)
                    self._add_to_history(user_id, 'assistant', assistant_response)
                    # End session logging
                    ilog.end_session(assistant_response)
                    return assistant_response
                
                # Execute all tool calls
                tool_results = await self._execute_tool_calls(response['tool_calls'])
                all_results.extend(tool_results)
                
                # Log iteration
                ilog.log_iteration(iteration + 1, response['tool_calls'], tool_results)
                
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
            assistant_response = _md_to_html(final_response.get('content', 'Настройка завершена'))
            # Save to history
            self._add_to_history(user_id, 'user', message)
            self._add_to_history(user_id, 'assistant', assistant_response)
            # End session logging
            ilog.end_session(assistant_response)
            return assistant_response
        
        except Exception as e:
            logger.error(f'Chat error: {e}')
            # Log error
            ilog.log_error('chat_error', str(e))
            ilog.end_session(f'❌ Ошибка: {e}')
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
                f'{self.llm_base_url}/chat/completions',
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
        ilog = get_interaction_logger()
        
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
                    ilog.log_error('tool_call_error', str(e), {'tool': name, 'args': args})
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
            # Get pipelines with deal counts per stage
            pipeline_id = args.get('pipeline_id')
            
            # First get pipelines structure
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Failed to get pipelines: {resp.status}'}
                pipelines_data = await resp.json()
                pipelines = pipelines_data.get('_embedded', {}).get('pipelines', [])
            
            # Filter by pipeline_id if specified
            if pipeline_id:
                pipelines = [p for p in pipelines if p.get('id') == pipeline_id]
            
            result = []
            total_deals = 0
            total_revenue = 0
            
            for p in pipelines:
                p_id = p.get('id')
                statuses = p.get('_embedded', {}).get('statuses', [])
                
                # Get deals for this pipeline
                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': p_id, 'limit': 250}
                
                async with session.get(leads_url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        leads_data = await resp.json()
                        leads = leads_data.get('_embedded', {}).get('leads', [])
                    else:
                        leads = []
                
                # Count deals per status
                status_counts = {}
                status_revenue = {}
                for lead in leads:
                    status_id = lead.get('status_id')
                    price = lead.get('price', 0) or 0
                    status_counts[status_id] = status_counts.get(status_id, 0) + 1
                    status_revenue[status_id] = status_revenue.get(status_id, 0) + price
                    total_deals += 1
                    total_revenue += price
                
                # Build stages with counts
                stages_with_counts = []
                for s in statuses:
                    s_id = s.get('id')
                    stages_with_counts.append({
                        'name': s.get('name'),
                        'deals': status_counts.get(s_id, 0),
                        'revenue': status_revenue.get(s_id, 0),
                    })
                
                pipeline_deals = sum(status_counts.values())
                pipeline_revenue = sum(status_revenue.values())
                
                result.append({
                    'id': p_id,
                    'name': p.get('name'),
                    'total_deals': pipeline_deals,
                    'total_revenue': pipeline_revenue,
                    'stages': stages_with_counts,
                })
            
            return {
                'pipelines': result,
                'summary': {
                    'total_pipelines': len(result),
                    'total_deals': total_deals,
                    'total_revenue': total_revenue,
                }
            }
        
        elif name == 'kommo_search':
            import time as _time
            action = args.get('action', 'all')
            query = args.get('query', '')
            limit = args.get('limit', 10)
            pipeline_id = args.get('pipeline_id')
            min_price = args.get('min_price')
            max_price = args.get('max_price')
            created_from = args.get('created_from')
            created_to = args.get('created_to')
            sort_by = args.get('sort_by')
            sort_order = args.get('sort_order', 'desc')
            
            def _parse_date(val):
                if not val:
                    return None
                if isinstance(val, (int, float)):
                    return int(val)
                try:
                    from datetime import datetime
                    return int(datetime.strptime(val, '%Y-%m-%d').timestamp())
                except Exception:
                    return None
            
            if action in ['all', 'leads', 'top_deals']:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': min(limit, 250)}
                if query:
                    params['query'] = query
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                ts_from = _parse_date(created_from)
                ts_to = _parse_date(created_to)
                if ts_from:
                    params['filter[created_at][from]'] = ts_from
                if ts_to:
                    params['filter[created_at][to]'] = ts_to
                
                all_leads = []
                page = 1
                fetch_limit = 250 if (min_price or max_price or sort_by or action == 'top_deals') else limit
                while len(all_leads) < fetch_limit:
                    params['page'] = page
                    async with session.get(url, headers=headers, params=params) as resp:
                        if resp.status != 200:
                            if not all_leads:
                                return {'error': f'API error: {resp.status}'}
                            break
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])
                        if not leads:
                            break
                        all_leads.extend(leads)
                        page += 1
                        if len(leads) < 250:
                            break
                
                if min_price is not None:
                    all_leads = [l for l in all_leads if (l.get('price', 0) or 0) >= min_price]
                if max_price is not None:
                    all_leads = [l for l in all_leads if (l.get('price', 0) or 0) <= max_price]
                
                if sort_by or action == 'top_deals':
                    sort_key = sort_by or 'price'
                    reverse = sort_order != 'asc' if sort_by else True
                    all_leads.sort(key=lambda l: l.get(sort_key, 0) or 0, reverse=reverse)
                
                all_leads = all_leads[:limit]
                result_leads = [{
                    'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0),
                    'status_id': l.get('status_id'), 'pipeline_id': l.get('pipeline_id'),
                    'responsible_user_id': l.get('responsible_user_id'),
                } for l in all_leads]
                return {'leads': result_leads, 'total': len(result_leads)}
            
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

            elif action == 'deal_context':
                lead_id = args.get('lead_id') or (int(query) if query and query.isdigit() else None)
                if not lead_id:
                    return {'error': 'Provide lead_id or numeric query for deal_context'}
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 50}) as resp:
                    notes = []
                    if resp.status == 200:
                        ndata = await resp.json()
                        notes = ndata.get('_embedded', {}).get('notes', [])
                turl = f'{self.kommo_base_url}/api/v4/tasks'
                async with session.get(turl, headers=headers, params={'filter[entity_id]': lead_id, 'filter[entity_type]': 'leads'}) as resp:
                    tasks = []
                    if resp.status == 200:
                        tdata = await resp.json()
                        tasks = tdata.get('_embedded', {}).get('tasks', [])
                contacts = lead.get('_embedded', {}).get('contacts', [])
                now = int(_time.time())
                return {
                    'lead': {'id': lead.get('id'), 'name': lead.get('name'), 'price': lead.get('price'), 'status_id': lead.get('status_id'), 'pipeline_id': lead.get('pipeline_id'), 'created_at': lead.get('created_at'), 'updated_at': lead.get('updated_at')},
                    'contacts': [{'id': c.get('id')} for c in contacts],
                    'notes_count': len(notes),
                    'recent_notes': [{'type': n.get('note_type'), 'text': (n.get('params', {}).get('text', '') or '')[:100], 'created': n.get('created_at')} for n in notes[:10]],
                    'tasks': [{'id': t.get('id'), 'text': t.get('text', '')[:80], 'due': t.get('complete_till'), 'done': t.get('is_completed')} for t in tasks[:10]],
                    'age_days': round((now - lead.get('created_at', now)) / 86400),
                    'hint': 'Present full deal context: lead info, contacts, recent notes, tasks. Help user understand the full picture.',
                }

            elif action == 'timeline':
                lead_id = args.get('lead_id') or (int(query) if query and query.isdigit() else None)
                if not lead_id:
                    return {'error': 'Provide lead_id or numeric query for timeline'}
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                eurl = f'{self.kommo_base_url}/api/v4/events'
                eparams = {'filter[entity]': 'lead', 'filter[entity_id]': lead_id, 'limit': 100}
                async with session.get(eurl, headers=headers, params=eparams) as resp:
                    events = []
                    if resp.status == 200:
                        edata = await resp.json()
                        events = edata.get('_embedded', {}).get('events', [])
                nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 50}) as resp:
                    notes = []
                    if resp.status == 200:
                        ndata = await resp.json()
                        notes = ndata.get('_embedded', {}).get('notes', [])
                timeline = []
                for e in events:
                    timeline.append({'ts': e.get('created_at'), 'type': 'event', 'event_type': e.get('type'), 'value_after': str(e.get('value_after', [{}])[0].get('value', ''))[:80] if e.get('value_after') else ''})
                for n in notes:
                    timeline.append({'ts': n.get('created_at'), 'type': 'note', 'note_type': n.get('note_type'), 'text': (n.get('params', {}).get('text', '') or '')[:80]})
                timeline.sort(key=lambda x: x.get('ts', 0))
                return {
                    'lead': lead.get('name'),
                    'timeline': timeline[-30:],
                    'total_events': len(events),
                    'total_notes': len(notes),
                    'hint': 'Present timeline chronologically. Show key milestones: creation, stage changes, notes, calls. Help user see deal progression.',
                }

            elif action == 'graph':
                lead_id = args.get('lead_id') or (int(query) if query and query.isdigit() else None)
                if not lead_id:
                    url = f'{self.kommo_base_url}/api/v4/leads'
                    params = {'limit': 1, 'with': 'contacts'}
                    if query:
                        params['query'] = query
                    async with session.get(url, headers=headers, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            leads = data.get('_embedded', {}).get('leads', [])
                            if leads:
                                lead_id = leads[0].get('id')
                    if not lead_id:
                        return {'error': 'Provide lead_id or query to build relationship graph'}
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                contacts = lead.get('_embedded', {}).get('contacts', [])
                nodes = [{'type': 'lead', 'id': lead.get('id'), 'name': lead.get('name'), 'price': lead.get('price')}]
                edges = []
                for c in contacts:
                    curl = f'{self.kommo_base_url}/api/v4/contacts/{c["id"]}'
                    async with session.get(curl, headers=headers, params={'with': 'leads'}) as cresp:
                        if cresp.status == 200:
                            cdata = await cresp.json()
                            nodes.append({'type': 'contact', 'id': cdata.get('id'), 'name': cdata.get('name'), 'company_id': cdata.get('company_id')})
                            edges.append({'from': lead.get('id'), 'to': cdata.get('id'), 'relation': 'has_contact'})
                            other_leads = cdata.get('_embedded', {}).get('leads', [])
                            for ol in other_leads:
                                if ol.get('id') != lead_id:
                                    nodes.append({'type': 'lead', 'id': ol.get('id')})
                                    edges.append({'from': cdata.get('id'), 'to': ol.get('id'), 'relation': 'also_in'})
                            if cdata.get('company_id'):
                                nodes.append({'type': 'company', 'id': cdata.get('company_id')})
                                edges.append({'from': cdata.get('id'), 'to': cdata.get('company_id'), 'relation': 'works_at'})
                unique_nodes = {(n['type'], n['id']): n for n in nodes}
                return {
                    'nodes': list(unique_nodes.values()),
                    'edges': edges,
                    'total_nodes': len(unique_nodes),
                    'total_edges': len(edges),
                    'hint': 'Present as relationship graph. Show connections between leads, contacts, companies. Highlight shared contacts across deals.',
                }

            elif action == 'nl_query':
                if not query:
                    return {'error': 'query required for nl_query'}
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250, 'query': query}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    all_leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])
                if min_price is not None:
                    all_leads = [l for l in all_leads if (l.get('price', 0) or 0) >= min_price]
                if max_price is not None:
                    all_leads = [l for l in all_leads if (l.get('price', 0) or 0) <= max_price]
                result = [{
                    'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0),
                    'status_id': l.get('status_id'), 'pipeline_id': l.get('pipeline_id'),
                    'responsible_user_id': l.get('responsible_user_id'),
                    'created_at': l.get('created_at'), 'updated_at': l.get('updated_at'),
                } for l in all_leads[:limit]]
                return {
                    'results': result, 'total': len(result),
                    'query': query,
                    'hint': 'Results from natural language query. Present as structured list. Offer to drill down into specific deals.',
                }

            elif action == 'problems':
                now = int(_time.time())
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    all_leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])
                active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
                problems = []
                for l in active:
                    issues = []
                    days_stale = (now - (l.get('updated_at') or now)) / 86400
                    price = l.get('price', 0) or 0
                    if days_stale > 30:
                        issues.append(f'Stale {round(days_stale)}d')
                    if not price:
                        issues.append('No price set')
                    if not l.get('responsible_user_id'):
                        issues.append('No responsible user')
                    if issues:
                        problems.append({
                            'id': l.get('id'), 'name': l.get('name'), 'price': price,
                            'issues': issues, 'severity': 'high' if days_stale > 30 else 'medium',
                            'days_stale': round(days_stale),
                        })
                problems.sort(key=lambda x: x['days_stale'], reverse=True)
                return {
                    'problem_deals': problems[:20],
                    'total_problems': len(problems),
                    'hint': 'Present problem deals sorted by severity. Each has specific issues. Help user prioritize fixes.',
                }

            elif action == 'bottlenecks':
                now = int(_time.time())
                purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
                async with session.get(purl, headers=headers) as resp:
                    pipelines = []
                    if resp.status == 200:
                        pdata = await resp.json()
                        pipelines = pdata.get('_embedded', {}).get('pipelines', [])
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    all_leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])
                active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
                stage_map = {}
                for p in pipelines:
                    for s in p.get('_embedded', {}).get('statuses', []):
                        stage_map[s.get('id')] = {'name': s.get('name'), 'pipeline': p.get('name')}
                by_stage = {}
                for l in active:
                    sid = l.get('status_id')
                    if sid not in by_stage:
                        info = stage_map.get(sid, {'name': f'Stage {sid}', 'pipeline': 'Unknown'})
                        by_stage[sid] = {'stage': info['name'], 'pipeline': info['pipeline'], 'count': 0, 'total_value': 0, 'avg_age': 0, 'ages': []}
                    by_stage[sid]['count'] += 1
                    by_stage[sid]['total_value'] += l.get('price', 0) or 0
                    by_stage[sid]['ages'].append((now - l.get('created_at', now)) / 86400)
                bottlenecks = []
                for sid, s in by_stage.items():
                    avg_age = sum(s['ages']) / max(len(s['ages']), 1)
                    bottlenecks.append({
                        'stage': s['stage'], 'pipeline': s['pipeline'],
                        'deals': s['count'], 'value': s['total_value'],
                        'avg_age_days': round(avg_age),
                        'is_bottleneck': s['count'] > 5 or avg_age > 30,
                    })
                bottlenecks.sort(key=lambda x: x['deals'], reverse=True)
                return {
                    'bottlenecks': [b for b in bottlenecks if b['is_bottleneck']],
                    'all_stages': bottlenecks,
                    'hint': 'Present bottleneck stages — high deal count or long avg age. Suggest actions to unclog pipeline.',
                }

            elif action == 'rejection_reasons':
                now = int(_time.time())
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250, 'filter[statuses][0][status_id]': 143}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    lost = []
                    if resp.status == 200:
                        data = await resp.json()
                        lost = data.get('_embedded', {}).get('leads', [])
                reasons = {}
                for l in lost[:50]:
                    nurl = f'{self.kommo_base_url}/api/v4/leads/{l["id"]}/notes'
                    async with session.get(nurl, headers=headers, params={'limit': 5}) as resp:
                        if resp.status == 200:
                            ndata = await resp.json()
                            for n in ndata.get('_embedded', {}).get('notes', []):
                                text = (n.get('params', {}).get('text', '') or '').lower()
                                if 'цена' in text or 'дорого' in text or 'бюджет' in text:
                                    reasons['price'] = reasons.get('price', 0) + 1
                                elif 'конкурент' in text or 'другой' in text or 'альтернатив' in text:
                                    reasons['competitor'] = reasons.get('competitor', 0) + 1
                                elif 'срок' in text or 'долго' in text or 'время' in text:
                                    reasons['timing'] = reasons.get('timing', 0) + 1
                                elif 'не нужно' in text or 'отказ' in text or 'передумал' in text:
                                    reasons['no_need'] = reasons.get('no_need', 0) + 1
                reason_list = [{'reason': k, 'count': v} for k, v in sorted(reasons.items(), key=lambda x: x[1], reverse=True)]
                if not reason_list:
                    reason_list.append({'reason': 'unknown', 'count': len(lost), 'note': 'No clear reasons found in notes — consider adding loss reason tracking'})
                return {
                    'rejection_reasons': reason_list,
                    'total_lost_analyzed': min(len(lost), 50),
                    'hint': 'Present rejection reasons ranked by frequency. Suggest process improvements for top reasons.',
                }

            elif action == 'payment_status':
                lead_id = args.get('lead_id')
                if lead_id:
                    lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                    async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                        if resp.status != 200:
                            return {'error': f'Lead {lead_id} not found'}
                        lead = await resp.json()
                    nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
                    async with session.get(nurl, headers=headers, params={'limit': 20}) as resp:
                        notes = []
                        if resp.status == 200:
                            ndata = await resp.json()
                            notes = ndata.get('_embedded', {}).get('notes', [])
                    all_text = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
                    price = lead.get('price', 0) or 0
                    paid = 'оплат' in all_text or 'оплач' in all_text or 'счёт оплач' in all_text
                    invoiced = 'счёт' in all_text or 'счет' in all_text or 'инвойс' in all_text
                    status = 'paid' if paid else ('invoiced' if invoiced else 'no_payment_info')
                    return {
                        'payment_status': {
                            'lead': lead.get('name'), 'lead_id': lead_id, 'price': price,
                            'status': status,
                            'status_label': 'Оплачено' if paid else ('Счёт выставлен' if invoiced else 'Нет данных об оплате'),
                        },
                        'hint': 'Present payment status for the deal. If no info, suggest checking with accounting.',
                    }
                else:
                    url = f'{self.kommo_base_url}/api/v4/leads'
                    params = {'limit': 250, 'filter[statuses][0][status_id]': 142}
                    async with session.get(url, headers=headers, params=params) as resp:
                        won_leads = []
                        if resp.status == 200:
                            data = await resp.json()
                            won_leads = data.get('_embedded', {}).get('leads', [])
                    results = []
                    for l in won_leads[:20]:
                        price = l.get('price', 0) or 0
                        results.append({
                            'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                            'status': 'won_no_payment_check',
                        })
                    return {
                        'won_deals_payment': results,
                        'hint': 'Present won deals that may need payment verification. Suggest checking each with accounting.',
                    }

            elif action == 'audit_trail':
                lead_id = args.get('lead_id')
                if not lead_id:
                    return {'error': 'lead_id required for audit_trail'}
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 50}) as resp:
                    notes = []
                    if resp.status == 200:
                        ndata = await resp.json()
                        notes = ndata.get('_embedded', {}).get('notes', [])
                events = []
                events.append({
                    'timestamp': lead.get('created_at'), 'type': 'created',
                    'detail': f'Deal created: {lead.get("name")}',
                })
                for n in sorted(notes, key=lambda x: x.get('created_at', 0)):
                    ntype = n.get('note_type', '')
                    text = (n.get('params', {}).get('text', '') or '')[:150]
                    events.append({
                        'timestamp': n.get('created_at'), 'type': ntype,
                        'detail': text or f'Note type: {ntype}',
                        'created_by': n.get('created_by'),
                    })
                if lead.get('updated_at') != lead.get('created_at'):
                    events.append({
                        'timestamp': lead.get('updated_at'), 'type': 'last_update',
                        'detail': f'Last updated (status_id: {lead.get("status_id")})',
                    })
                events.sort(key=lambda x: x.get('timestamp', 0))
                return {
                    'audit_trail': {
                        'lead': lead.get('name'), 'lead_id': lead_id,
                        'events': events, 'total_events': len(events),
                    },
                    'hint': 'Present audit trail chronologically. Show who did what and when. Useful for compliance and deal review.',
                }

            return {'error': f'Unknown search action: {action}'}
        
        elif name == 'kommo_mock_data':
            return await self._handle_mock_data(session, headers, args)
        
        elif name == 'kommo_entity_actions':
            return await self._handle_entity_actions(session, headers, args)
        
        elif name == 'kommo_bulk_actions':
            return await self._handle_bulk_actions(session, headers, args)
        
        elif name == 'kommo_users':
            return await self._handle_users(session, headers, args)
        
        elif name == 'kommo_reports':
            return await self._handle_reports(session, headers, args)
        
        elif name == 'kommo_webhooks':
            return await self._handle_webhooks(session, headers, args)
        
        elif name == 'kommo_tags':
            return await self._handle_tags(session, headers, args)
        
        elif name == 'kommo_custom_fields':
            return await self._handle_custom_fields(session, headers, args)
        
        elif name == 'kommo_sources':
            return await self._handle_sources(session, headers, args)
        
        elif name == 'kommo_companies':
            return await self._handle_companies(session, headers, args)
        
        elif name == 'kommo_duplicates':
            return await self._handle_duplicates(session, headers, args)
        
        elif name == 'kommo_links':
            return await self._handle_links(session, headers, args)
        
        elif name == 'kommo_catalogs':
            return await self._handle_catalogs(session, headers, args)
        
        elif name == 'kommo_events':
            return await self._handle_events(session, headers, args)
        
        elif name == 'kommo_calls':
            return await self._handle_calls(session, headers, args)
        
        elif name == 'kommo_cleanup':
            return await self._handle_cleanup(session, headers, args)
        
        elif name == 'kommo_export':
            return await self._handle_export(session, headers, args)
        
        elif name == 'kommo_digest':
            return await self._handle_digest(session, headers, args)
        
        elif name == 'kommo_advisor':
            return await self._handle_advisor(session, headers, args)
        
        elif name == 'kommo_pipeline_health':
            return await self._handle_pipeline_health(session, headers, args)
        
        elif name == 'kommo_tasks_ext':
            return await self._handle_tasks_ext(session, headers, args)
        
        elif name == 'kommo_contacts_ext':
            return await self._handle_contacts_ext(session, headers, args)
        
        elif name == 'kommo_forecast':
            return await self._handle_forecast(session, headers, args)
        
        elif name == 'kommo_alerts':
            return await self._handle_alerts(session, headers, args)
        
        elif name == 'kommo_compare':
            return await self._handle_compare(session, headers, args)
        
        elif name == 'kommo_automation':
            return await self._handle_automation(session, headers, args)
        
        elif name == 'kommo_my':
            return await self._handle_my(session, headers, args)
        
        elif name == 'kommo_gamification':
            return await self._handle_gamification(session, headers, args)
        
        elif name == 'kommo_loss_analysis':
            return await self._handle_loss_analysis(session, headers, args)
        
        elif name == 'kommo_smart_time':
            return await self._handle_smart_time(session, headers, args)
        
        elif name == 'kommo_team_planner':
            return await self._handle_team_planner(session, headers, args)
        
        elif name == 'kommo_segments':
            return await self._handle_segments(session, headers, args)
        
        elif name == 'kommo_escalation':
            return await self._handle_escalation(session, headers, args)
        
        elif name == 'kommo_reactivation':
            return await self._handle_reactivation(session, headers, args)
        
        elif name == 'kommo_contact_enrichment':
            return await self._handle_contact_enrichment(session, headers, args)
        
        elif name == 'kommo_templates':
            return await self._handle_templates(session, headers, args)
        
        elif name == 'kommo_anomaly':
            return await self._handle_anomaly(session, headers, args)
        
        elif name == 'kommo_objections':
            return await self._handle_objections(session, headers, args)
        
        elif name == 'kommo_deal_intelligence':
            return await self._handle_deal_intelligence(session, headers, args)
        
        elif name == 'kommo_contact_scoring':
            return await self._handle_contact_scoring(session, headers, args)
        
        elif name == 'kommo_ai_coach':
            return await self._handle_ai_coach(session, headers, args)
        
        elif name == 'kommo_smart_reply':
            return await self._handle_smart_reply(session, headers, args)
        
        elif name == 'kommo_communication_analytics':
            return await self._handle_communication_analytics(session, headers, args)
        
        elif name == 'kommo_doc_generator':
            return await self._handle_doc_generator(session, headers, args)
        
        elif name == 'kommo_activity':
            return await self._handle_activity(session, headers, args)
        
        elif name == 'kommo_insights':
            return await self._handle_insights(session, headers, args)
        
        elif name == 'kommo_manager_stats':
            return await self._handle_manager_stats(session, headers, args)
        
        elif name == 'kommo_deals_ext':
            return await self._handle_deals_ext(session, headers, args)
        
        elif name == 'kommo_communications':
            return await self._handle_communications(session, headers, args)
        
        elif name == 'kommo_ltv':
            return await self._handle_ltv(session, headers, args)
        
        elif name == 'kommo_lead_gen':
            return await self._handle_lead_gen(session, headers, args)
        
        # Default - return info about available tools
        return {'message': f'Tool {name} not fully implemented yet', 'args': args}
    
    async def _handle_setup(self, session, headers, args: dict) -> dict:
        """Handle kommo_setup tool calls."""
        action = args.get('action')
        dry_run = args.get('dry_run', False)
        
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
                            pipeline_id = pipelines[0].get('id')
                            stages = pipelines[0].get('_embedded', {}).get('statuses', [])
                            
                            # Delete default stages (keep only system ones: 142/143 win/lose)
                            for stage in stages:
                                stage_id = stage.get('id')
                                # System stages (win/lose) cannot be deleted, skip them
                                if stage_id and stage_id not in [142, 143]:
                                    del_url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses/{stage_id}'
                                    async with session.delete(del_url, headers=headers) as del_resp:
                                        logger.info(f'Deleted default stage {stage.get("name")} ({stage_id}): {del_resp.status}')
                            
                            return {
                                'success': True,
                                'pipeline_id': pipeline_id,
                                'pipeline_name': pipelines[0].get('name'),
                                'stages': [],
                                'hint': f'Pipeline created empty. Use pipeline_id={pipeline_id} for create_stage calls. Stages start from sort=10.',
                            }
                    except:
                        pass
                return {'error': f'Failed to create pipeline (status {resp.status}): {response_text[:200]}'}
        
        elif action == 'create_stage':
            pipeline_id = args.get('pipeline_id')
            stage_name = args.get('stage_name')
            stage_sort = args.get('stage_sort', 100)
            stage_color = args.get('stage_color', '#fffeb2')
            
            # Validate color - Kommo only accepts specific colors
            valid_colors = ['#fffeb2', '#fffd7f', '#fff000', '#ffeab2', '#ffdc7f', '#ffce5a', '#ffdbdb', '#ffc8c8', '#ff8f92', '#d6eaff', '#c1e0ff', '#98cbff', '#ebffb1', '#deff81', '#87f2c0', '#f9deff', '#f3beff', '#ccc8f9', '#eb93ff', '#f2f3f4', '#e6e8ea']
            if stage_color not in valid_colors:
                # Pick a color based on sort order for variety
                color_idx = (stage_sort // 10) % len(valid_colors)
                stage_color = valid_colors[color_idx]
            
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
            
            # Map field types - Kommo API valid types
            # Note: 'price' is NOT valid, use 'numeric' for budget/price fields
            type_map = {
                'text': 'text',
                'numeric': 'numeric',
                'checkbox': 'checkbox',
                'select': 'select',
                'multiselect': 'multiselect',
                'date': 'date',
                'url': 'url',
                'textarea': 'textarea',
                'birthday': 'birthday',
                'legal_entity': 'legal_entity',
                'date_time': 'date_time',
                'streetaddress': 'streetaddress',
                'smart_address': 'smart_address',
                'tracking_data': 'tracking_data',
                # Aliases for common mistakes
                'price': 'numeric',
                'money': 'numeric',
                'budget': 'numeric',
                'number': 'numeric',
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
        
        elif action == 'update_pipeline':
            pipeline_id = args.get('pipeline_id')
            pipeline_name = args.get('pipeline_name')
            
            if not pipeline_id:
                return {'error': 'pipeline_id is required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would update pipeline {pipeline_id}'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}'
            payload = {}
            if pipeline_name:
                payload['name'] = pipeline_name
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'success': True, 'pipeline_id': pipeline_id, 'name': data.get('name')}
                error = await resp.text()
                return {'error': f'Failed to update pipeline: {error[:200]}'}
        
        elif action == 'delete_pipeline':
            pipeline_id = args.get('pipeline_id')
            
            if not pipeline_id:
                return {'error': 'pipeline_id is required'}
            
            pipeline_id = int(pipeline_id)
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would DELETE pipeline {pipeline_id}. This is irreversible!'}
            
            # Step 1: Find the main pipeline to move leads there
            main_pipeline_id = None
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for p in data.get('_embedded', {}).get('pipelines', []):
                        if p.get('is_main'):
                            main_pipeline_id = p['id']
                            break
                        if p['id'] != pipeline_id and main_pipeline_id is None:
                            main_pipeline_id = p['id']
            
            if not main_pipeline_id:
                return {'error': 'Cannot find another pipeline to move leads to before deletion'}
            
            # Step 2: Move all leads from target pipeline to main pipeline (status 143 = lost)
            leads_moved = 0
            leads_found = 0
            page = 1
            
            while True:
                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id][]': pipeline_id, 'limit': 250, 'page': page}
                logger.info(f'Fetching leads from pipeline {pipeline_id}, page {page}')
                async with session.get(leads_url, headers=headers, params=params) as leads_resp:
                    if leads_resp.status != 200:
                        break
                    data = await leads_resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    leads_found += len(leads)
                    if not leads:
                        break
                    
                    # Move each lead to main pipeline's lost status
                    for lead in leads:
                        lead_id = lead['id']
                        move_url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                        move_payload = {
                            'pipeline_id': main_pipeline_id,
                            'status_id': 143,
                        }
                        async with session.patch(move_url, headers=headers, json=move_payload) as move_resp:
                            if move_resp.status in [200, 204]:
                                leads_moved += 1
                            else:
                                resp_text = await move_resp.text()
                                logger.warning(f'Failed to move lead {lead_id}: {move_resp.status} {resp_text[:100]}')
                    
                    page += 1
                    if len(leads) < 250:
                        break
            
            logger.info(f'Pipeline {pipeline_id}: found {leads_found} leads, moved {leads_moved} to pipeline {main_pipeline_id}')
            
            # Step 3: Delete the now-empty pipeline
            del_url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}'
            async with session.delete(del_url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    result = {'success': True, 'deleted_pipeline_id': pipeline_id}
                    if leads_moved > 0:
                        result['leads_moved'] = leads_moved
                        result['moved_to_pipeline'] = main_pipeline_id
                        result['message'] = f'Moved {leads_moved} leads to main pipeline before deletion'
                    return result
                error_text = await resp.text()
                return {'error': f'Failed to delete pipeline (moved {leads_moved} leads): {error_text[:300]}'}
        
        elif action == 'update_stage':
            pipeline_id = args.get('pipeline_id')
            stage_id = args.get('stage_id')
            stage_name = args.get('stage_name')
            stage_sort = args.get('stage_sort')
            stage_color = args.get('stage_color')
            
            if not pipeline_id or not stage_id:
                return {'error': 'pipeline_id and stage_id are required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would update stage {stage_id} in pipeline {pipeline_id}'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses/{stage_id}'
            payload = {}
            if stage_name:
                payload['name'] = stage_name
            if stage_sort is not None:
                payload['sort'] = stage_sort
            if stage_color:
                payload['color'] = stage_color
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'success': True, 'stage_id': stage_id, 'name': data.get('name'), 'sort': data.get('sort')}
                error = await resp.text()
                return {'error': f'Failed to update stage: {error[:200]}'}
        
        elif action == 'delete_stage':
            pipeline_id = args.get('pipeline_id')
            stage_id = args.get('stage_id')
            
            if not pipeline_id or not stage_id:
                return {'error': 'pipeline_id and stage_id are required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would DELETE stage {stage_id}. Deals will be moved to first stage!'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses/{stage_id}'
            
            async with session.delete(url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    return {'success': True, 'deleted_stage_id': stage_id}
                error = await resp.text()
                return {'error': f'Failed to delete stage: {error[:200]}'}
        
        elif action == 'reorder_stages':
            pipeline_id = args.get('pipeline_id')
            stages_order = args.get('stages_order', [])
            
            if not pipeline_id or not stages_order:
                return {'error': 'pipeline_id and stages_order (array of stage IDs) are required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would reorder stages in pipeline {pipeline_id}: {stages_order}'}
            
            # Update sort for each stage
            results = []
            for i, stage_id in enumerate(stages_order):
                sort_value = (i + 1) * 10  # 10, 20, 30...
                url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses/{stage_id}'
                payload = {'sort': sort_value}
                
                async with session.patch(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        results.append({'stage_id': stage_id, 'sort': sort_value, 'success': True})
                    else:
                        error = await resp.text()
                        results.append({'stage_id': stage_id, 'error': error[:100]})
            
            return {'success': True, 'reordered': results}
        
        elif action == 'update_field':
            field_id = args.get('field_id')
            field_name = args.get('field_name')
            entity_type = args.get('entity_type', 'leads')
            enums = args.get('enums', [])
            
            if not field_id:
                return {'error': 'field_id is required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would update field {field_id}'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields/{field_id}'
            payload = {}
            if field_name:
                payload['name'] = field_name
            if enums:
                payload['enums'] = [{'value': e} for e in enums]
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'success': True, 'field_id': field_id, 'name': data.get('name')}
                error = await resp.text()
                return {'error': f'Failed to update field: {error[:200]}'}
        
        elif action == 'delete_field':
            field_id = args.get('field_id')
            entity_type = args.get('entity_type', 'leads')
            
            if not field_id:
                return {'error': 'field_id is required'}
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would DELETE field {field_id}. Data in this field will be lost!'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields/{field_id}'
            
            async with session.delete(url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    return {'success': True, 'deleted_field_id': field_id}
                error = await resp.text()
                return {'error': f'Failed to delete field: {error[:200]}'}
        
        elif action == 'templates':
            templates = [
                {
                    'code': 'capture',
                    'name': 'Захват и первичная обработка',
                    'description': 'Воронка для входящих лидов: от первого контакта до квалификации',
                    'stages': ['Новая заявка', 'Первичный контакт', 'Квалификация', 'Передано в работу'],
                    'fields': ['Источник лида', 'UTM-метка', 'Телефон подтверждён'],
                },
                {
                    'code': 'qualification',
                    'name': 'Квалификация лида',
                    'description': 'Глубокая квалификация: выявление потребности, бюджета, сроков',
                    'stages': ['Выявление потребности', 'Оценка бюджета', 'Определение сроков', 'Квалифицирован', 'Не целевой'],
                    'fields': ['Бюджет', 'Срок принятия решения', 'ЛПР'],
                },
                {
                    'code': 'followup',
                    'name': 'Follow-up / напоминания',
                    'description': 'Воронка дожима: повторные касания, напоминания, реактивация',
                    'stages': ['Ожидает ответа', 'Повторный контакт', 'Назначена встреча', 'Реактивация'],
                    'fields': ['Дата следующего контакта', 'Причина паузы'],
                },
                {
                    'code': 'demo',
                    'name': 'Демонстрация / встреча',
                    'description': 'Воронка для проведения демо и встреч с клиентами',
                    'stages': ['Запрос на демо', 'Демо назначено', 'Демо проведено', 'Обратная связь', 'Решение'],
                    'fields': ['Дата демо', 'Участники', 'Формат встречи'],
                },
                {
                    'code': 'proposal',
                    'name': 'КП / согласование',
                    'description': 'Воронка для подготовки и согласования коммерческих предложений',
                    'stages': ['Подготовка КП', 'КП отправлено', 'На рассмотрении', 'Корректировка', 'Согласовано', 'Отклонено'],
                    'fields': ['Сумма КП', 'Срок действия КП', 'Версия КП'],
                },
                {
                    'code': 'autoservice',
                    'name': 'Автосервис',
                    'description': 'Воронка для автосервиса: от заявки до выдачи авто',
                    'stages': ['Заявка', 'Диагностика', 'Согласование работ', 'В ремонте', 'Готово к выдаче', 'Выдано'],
                    'fields': ['Марка авто', 'Гос. номер', 'Вид работ', 'Стоимость запчастей'],
                },
                {
                    'code': 'realestate',
                    'name': 'Недвижимость',
                    'description': 'Воронка для агентства недвижимости: от заявки до сделки',
                    'stages': ['Новая заявка', 'Выявление потребности', 'Подбор объектов', 'Показ', 'Переговоры', 'Бронь', 'Сделка'],
                    'fields': ['Тип недвижимости', 'Бюджет', 'Район', 'Площадь'],
                },
                {
                    'code': 'education',
                    'name': 'Онлайн-школа',
                    'description': 'Воронка для онлайн-школы: от лида до оплаты курса',
                    'stages': ['Заявка на курс', 'Консультация', 'Пробный урок', 'Выбор тарифа', 'Оплата', 'Обучение'],
                    'fields': ['Курс', 'Тариф', 'Промокод', 'Источник'],
                },
                {
                    'code': 'ecommerce',
                    'name': 'Интернет-магазин',
                    'description': 'Воронка для e-commerce: от заказа до доставки',
                    'stages': ['Новый заказ', 'Подтверждение', 'Комплектация', 'Отправлено', 'Доставлено', 'Возврат'],
                    'fields': ['Номер заказа', 'Способ доставки', 'Трек-номер'],
                },
                {
                    'code': 'b2b_sales',
                    'name': 'B2B продажи',
                    'description': 'Воронка для B2B: длинный цикл сделки с несколькими ЛПР',
                    'stages': ['Лид', 'Квалификация', 'Выявление ЛПР', 'Презентация', 'Пилот/Тест', 'КП', 'Согласование', 'Контракт'],
                    'fields': ['Компания', 'ЛПР', 'Бюджет', 'Срок принятия решения', 'Конкуренты'],
                },
            ]
            return {'templates': templates, 'hint': 'Use apply_template with template code to create pipeline from template'}

        elif action == 'apply_template':
            template_code = args.get('template')
            if not template_code:
                return {'error': 'template parameter is required (e.g. capture, qualification, followup, demo, proposal)'}

            templates_map = {
                'capture': {
                    'name': 'Захват и первичная обработка',
                    'stages': [
                        ('Новая заявка', '#d6eaff', 10),
                        ('Первичный контакт', '#c1e0ff', 20),
                        ('Квалификация', '#ffdc7f', 30),
                        ('Передано в работу', '#87f2c0', 40),
                    ],
                },
                'qualification': {
                    'name': 'Квалификация лида',
                    'stages': [
                        ('Выявление потребности', '#d6eaff', 10),
                        ('Оценка бюджета', '#ffeab2', 20),
                        ('Определение сроков', '#ffdc7f', 30),
                        ('Квалифицирован', '#87f2c0', 40),
                        ('Не целевой', '#ff8f92', 50),
                    ],
                },
                'followup': {
                    'name': 'Follow-up / напоминания',
                    'stages': [
                        ('Ожидает ответа', '#ffeab2', 10),
                        ('Повторный контакт', '#ffdc7f', 20),
                        ('Назначена встреча', '#c1e0ff', 30),
                        ('Реактивация', '#f9deff', 40),
                    ],
                },
                'demo': {
                    'name': 'Демонстрация / встреча',
                    'stages': [
                        ('Запрос на демо', '#d6eaff', 10),
                        ('Демо назначено', '#c1e0ff', 20),
                        ('Демо проведено', '#ffdc7f', 30),
                        ('Обратная связь', '#ffeab2', 40),
                        ('Решение', '#87f2c0', 50),
                    ],
                },
                'proposal': {
                    'name': 'КП / согласование',
                    'stages': [
                        ('Подготовка КП', '#d6eaff', 10),
                        ('КП отправлено', '#c1e0ff', 20),
                        ('На рассмотрении', '#ffeab2', 30),
                        ('Корректировка', '#ffdc7f', 40),
                        ('Согласовано', '#87f2c0', 50),
                        ('Отклонено', '#ff8f92', 60),
                    ],
                },
                'autoservice': {
                    'name': 'Автосервис',
                    'stages': [
                        ('Заявка', '#d6eaff', 10),
                        ('Диагностика', '#c1e0ff', 20),
                        ('Согласование работ', '#ffeab2', 30),
                        ('В ремонте', '#ffdc7f', 40),
                        ('Готово к выдаче', '#87f2c0', 50),
                        ('Выдано', '#ebffb1', 60),
                    ],
                },
                'realestate': {
                    'name': 'Недвижимость',
                    'stages': [
                        ('Новая заявка', '#d6eaff', 10),
                        ('Выявление потребности', '#c1e0ff', 20),
                        ('Подбор объектов', '#ffeab2', 30),
                        ('Показ', '#ffdc7f', 40),
                        ('Переговоры', '#f9deff', 50),
                        ('Бронь', '#ccc8f9', 60),
                        ('Сделка', '#87f2c0', 70),
                    ],
                },
                'education': {
                    'name': 'Онлайн-школа',
                    'stages': [
                        ('Заявка на курс', '#d6eaff', 10),
                        ('Консультация', '#c1e0ff', 20),
                        ('Пробный урок', '#ffeab2', 30),
                        ('Выбор тарифа', '#ffdc7f', 40),
                        ('Оплата', '#87f2c0', 50),
                        ('Обучение', '#ebffb1', 60),
                    ],
                },
                'ecommerce': {
                    'name': 'Интернет-магазин',
                    'stages': [
                        ('Новый заказ', '#d6eaff', 10),
                        ('Подтверждение', '#c1e0ff', 20),
                        ('Комплектация', '#ffeab2', 30),
                        ('Отправлено', '#ffdc7f', 40),
                        ('Доставлено', '#87f2c0', 50),
                        ('Возврат', '#ff8f92', 60),
                    ],
                },
                'b2b_sales': {
                    'name': 'B2B продажи',
                    'stages': [
                        ('Лид', '#d6eaff', 10),
                        ('Квалификация', '#c1e0ff', 20),
                        ('Выявление ЛПР', '#98cbff', 30),
                        ('Презентация', '#ffeab2', 40),
                        ('Пилот/Тест', '#ffdc7f', 50),
                        ('КП', '#f9deff', 60),
                        ('Согласование', '#ccc8f9', 70),
                        ('Контракт', '#87f2c0', 80),
                    ],
                },
            }

            tpl = templates_map.get(template_code)
            if not tpl:
                return {'error': f'Unknown template: {template_code}. Available: {", ".join(templates_map.keys())}'}

            if dry_run:
                return {'dry_run': True, 'template': template_code, 'pipeline_name': tpl['name'], 'stages': [s[0] for s in tpl['stages']]}

            # 1. Create pipeline
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            payload = [{'name': tpl['name'], 'is_main': False, 'is_unsorted_on': True, 'sort': 100, '_embedded': {'statuses': [{'name': tpl['stages'][0][0], 'sort': 10, 'color': tpl['stages'][0][1]}]}}]

            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status not in [200, 201]:
                    error = await resp.text()
                    return {'error': f'Failed to create pipeline: {error[:200]}'}
                data = await resp.json()
                pipelines = data.get('_embedded', {}).get('pipelines', [])
                if not pipelines:
                    return {'error': 'Pipeline created but no data returned'}
                pipeline_id = pipelines[0].get('id')

                # Delete default stages
                default_stages = pipelines[0].get('_embedded', {}).get('statuses', [])
                for stage in default_stages:
                    sid = stage.get('id')
                    if sid and sid not in [142, 143]:
                        del_url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses/{sid}'
                        async with session.delete(del_url, headers=headers) as del_resp:
                            logger.info(f'Deleted default stage {sid}: {del_resp.status}')

            # 2. Create template stages
            created_stages = []
            for stage_name, stage_color, stage_sort in tpl['stages']:
                stage_url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/statuses'
                stage_payload = [{'name': stage_name, 'sort': stage_sort, 'color': stage_color}]
                async with session.post(stage_url, headers=headers, json=stage_payload) as resp:
                    if resp.status in [200, 201]:
                        sdata = await resp.json()
                        statuses = sdata.get('_embedded', {}).get('statuses', [])
                        if statuses:
                            created_stages.append({'id': statuses[0].get('id'), 'name': stage_name, 'sort': stage_sort})
                    else:
                        logger.warning(f'Failed to create stage {stage_name}: {resp.status}')

            return {
                'success': True,
                'template': template_code,
                'pipeline_id': pipeline_id,
                'pipeline_name': tpl['name'],
                'stages_created': created_stages,
            }

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
            
            logger.info(f'Creating {len(contacts)} contacts')
            async with session.post(url, headers=headers, json=contacts) as resp:
                response_text = await resp.text()
                logger.info(f'Contacts response: {resp.status} - {response_text[:300]}')
                if resp.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                        created = data.get('_embedded', {}).get('contacts', [])
                        return {
                            'success': True, 
                            'created_contacts': len(created), 
                            'contacts': [{'id': c.get('id'), 'name': c.get('name', 'N/A')} for c in created[:5]]
                        }
                    except Exception as e:
                        return {'error': f'Parse error: {e}'}
                return {'error': f'API error {resp.status}: {response_text[:200]}'}
        
        elif action == 'companies':
            url = f'{self.kommo_base_url}/api/v4/companies'
            comps = []
            for i in range(count):
                comps.append({'name': f'{random.choice(companies)} #{random.randint(1, 999)}'})
            
            logger.info(f'Creating {len(comps)} companies')
            async with session.post(url, headers=headers, json=comps) as resp:
                response_text = await resp.text()
                logger.info(f'Companies response: {resp.status} - {response_text[:300]}')
                if resp.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                        created = data.get('_embedded', {}).get('companies', [])
                        return {
                            'success': True, 
                            'created_companies': len(created), 
                            'companies': [{'id': c.get('id'), 'name': c.get('name', 'N/A')} for c in created[:5]]
                        }
                    except Exception as e:
                        return {'error': f'Parse error: {e}'}
                return {'error': f'API error {resp.status}: {response_text[:200]}'}
        
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
            
            logger.info(f'Creating {len(leads)} leads in pipeline {pipeline_id}')
            async with session.post(url, headers=headers, json=leads) as resp:
                response_text = await resp.text()
                logger.info(f'Leads response: {resp.status} - {response_text[:300]}')
                if resp.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                        created = data.get('_embedded', {}).get('leads', [])
                        return {
                            'success': True, 
                            'created_leads': len(created), 
                            'pipeline_id': pipeline_id,
                            'leads': [{'id': l.get('id'), 'name': l.get('name', 'N/A'), 'price': l.get('price')} for l in created[:5]]
                        }
                    except Exception as e:
                        return {'error': f'Parse error: {e}'}
                return {'error': f'API error {resp.status}: {response_text[:200]}'}
        
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
    
    async def _handle_entity_actions(self, session, headers, args: dict) -> dict:
        """Handle entity actions: notes, tasks, history, updates."""
        import time
        from datetime import datetime, timedelta
        
        action = args.get('action')
        entity_type = args.get('entity_type', 'leads')
        entity_id = args.get('entity_id')
        
        if action == 'add_note':
            note_text = args.get('note_text')
            if not entity_id or not note_text:
                return {'error': 'entity_id and note_text are required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/notes'
            payload = [{'note_type': 'common', 'params': {'text': note_text}}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])
                    if notes:
                        return {'success': True, 'note_id': notes[0].get('id'), 'text': note_text[:50]}
                error = await resp.text()
                return {'error': f'Failed to add note: {error[:200]}'}
        
        elif action == 'get_notes':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/notes'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 204:
                    return {'notes': []}
                if resp.status == 200:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])
                    return {
                        'notes': [
                            {'id': n.get('id'), 'type': n.get('note_type'), 
                             'text': n.get('params', {}).get('text', '')[:100],
                             'created_at': n.get('created_at')}
                            for n in notes[:20]
                        ]
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'get_history':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/notes'
            params = {'limit': 50}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 204:
                    return {'history': [], 'message': 'No history for this entity'}
                if resp.status == 200:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])
                    history = []
                    for n in notes:
                        note_type = n.get('note_type')
                        params_data = n.get('params', {})
                        text = params_data.get('text', '') if isinstance(params_data, dict) else ''
                        history.append({
                            'type': note_type,
                            'text': text[:100] if text else note_type,
                            'created_at': n.get('created_at'),
                        })
                    return {'history': history}
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'create_task':
            task_text = args.get('task_text')
            if not entity_id or not task_text:
                return {'error': 'entity_id and task_text are required'}
            
            task_type_id = args.get('task_type_id', 1)  # 1=call, 2=meeting, 3=email
            complete_till = args.get('complete_till', '+1d')
            
            # Parse deadline
            if complete_till.startswith('+'):
                now = datetime.now()
                if 'd' in complete_till:
                    days = int(complete_till.replace('+', '').replace('d', ''))
                    deadline = now + timedelta(days=days)
                elif 'h' in complete_till:
                    hours = int(complete_till.replace('+', '').replace('h', ''))
                    deadline = now + timedelta(hours=hours)
                elif 'm' in complete_till:
                    minutes = int(complete_till.replace('+', '').replace('m', ''))
                    deadline = now + timedelta(minutes=minutes)
                else:
                    deadline = now + timedelta(days=1)
                complete_till_ts = int(deadline.timestamp())
            else:
                try:
                    deadline = datetime.strptime(complete_till, '%Y-%m-%d')
                    complete_till_ts = int(deadline.timestamp())
                except:
                    complete_till_ts = int(time.time()) + 86400
            
            url = f'{self.kommo_base_url}/api/v4/tasks'
            payload = [{
                'text': task_text,
                'complete_till': complete_till_ts,
                'task_type_id': task_type_id,
                'entity_id': entity_id,
                'entity_type': entity_type,
            }]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
                    if tasks:
                        return {'success': True, 'task_id': tasks[0].get('id'), 'text': task_text[:50]}
                error = await resp.text()
                return {'error': f'Failed to create task: {error[:200]}'}
        
        elif action == 'get_tasks':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'filter[entity_id]': entity_id, 'filter[entity_type]': entity_type}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
                    return {
                        'tasks': [
                            {'id': t.get('id'), 'text': t.get('text', '')[:50], 
                             'is_completed': t.get('is_completed'),
                             'complete_till': t.get('complete_till')}
                            for t in tasks[:20]
                        ]
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'complete_task':
            task_id = args.get('task_id')
            if not task_id:
                return {'error': 'task_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/tasks/{task_id}'
            payload = {'is_completed': True, 'result': {'text': 'Completed via AI assistant'}}
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'task_id': task_id, 'completed': True}
                error = await resp.text()
                return {'error': f'Failed to complete task: {error[:200]}'}
        
        elif action == 'update_lead':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            fields = args.get('fields', {})
            url = f'{self.kommo_base_url}/api/v4/leads/{entity_id}'
            
            async with session.patch(url, headers=headers, json=fields) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'success': True, 'lead_id': entity_id, 'updated': list(fields.keys())}
                error = await resp.text()
                return {'error': f'Failed to update lead: {error[:200]}'}
        
        elif action == 'move_lead':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            pipeline_id = args.get('pipeline_id')
            status_id = args.get('status_id')
            
            if not pipeline_id and not status_id:
                return {'error': 'pipeline_id or status_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/{entity_id}'
            payload = {}
            if pipeline_id:
                payload['pipeline_id'] = pipeline_id
            if status_id:
                payload['status_id'] = status_id
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'lead_id': entity_id, 'moved_to': payload}
                error = await resp.text()
                return {'error': f'Failed to move lead: {error[:200]}'}
        
        elif action == 'link_contact':
            if not entity_id:
                return {'error': 'entity_id (lead_id) is required'}
            
            contact_id = args.get('contact_id')
            if not contact_id:
                return {'error': 'contact_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/{entity_id}/link'
            payload = [{'to_entity_id': contact_id, 'to_entity_type': 'contacts'}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    return {'success': True, 'lead_id': entity_id, 'linked_contact': contact_id}
                error = await resp.text()
                return {'error': f'Failed to link contact: {error[:200]}'}
        
        elif action == 'unlink_contact':
            if not entity_id:
                return {'error': 'entity_id (lead_id) is required'}
            
            contact_id = args.get('contact_id')
            if not contact_id:
                return {'error': 'contact_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/{entity_id}/unlink'
            payload = [{'to_entity_id': contact_id, 'to_entity_type': 'contacts'}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201, 204]:
                    return {'success': True, 'lead_id': entity_id, 'unlinked_contact': contact_id}
                error = await resp.text()
                return {'error': f'Failed to unlink contact: {error[:200]}'}
        
        elif action == 'reactivate_lead':
            if not entity_id:
                return {'error': 'entity_id (lead_id) is required'}
            
            pipeline_id = args.get('pipeline_id')
            status_id = args.get('status_id')
            
            if not pipeline_id:
                pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
                async with session.get(pipelines_url, headers=headers) as resp:
                    if resp.status == 200:
                        pdata = await resp.json()
                        pipelines = pdata.get('_embedded', {}).get('pipelines', [])
                        if pipelines:
                            main = [p for p in pipelines if p.get('is_main')]
                            target_p = main[0] if main else pipelines[0]
                            pipeline_id = target_p.get('id')
                            statuses = target_p.get('_embedded', {}).get('statuses', [])
                            active_statuses = [s for s in statuses if s.get('id') not in [142, 143]]
                            if active_statuses:
                                status_id = active_statuses[0].get('id')
            
            if not pipeline_id or not status_id:
                return {'error': 'Could not determine target pipeline/status. Provide pipeline_id and status_id.'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/{entity_id}'
            payload = {'pipeline_id': pipeline_id, 'status_id': status_id}
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'lead_id': entity_id, 'reactivated_to': {'pipeline_id': pipeline_id, 'status_id': status_id}}
                error = await resp.text()
                return {'error': f'Failed to reactivate: {error[:200]}'}
        
        elif action == 'clone_lead':
            if not entity_id:
                return {'error': 'entity_id (lead_id) is required'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/{entity_id}'
            params = {'with': 'contacts'}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return {'error': f'Lead not found: {resp.status}'}
                lead = await resp.json()
            
            new_lead = {
                'name': f'{lead.get("name", "")} (копия)',
                'price': lead.get('price', 0),
                'pipeline_id': lead.get('pipeline_id'),
                'status_id': lead.get('status_id'),
                'responsible_user_id': lead.get('responsible_user_id'),
            }
            
            cf_values = lead.get('custom_fields_values')
            if cf_values:
                new_lead['custom_fields_values'] = cf_values
            
            create_url = f'{self.kommo_base_url}/api/v4/leads'
            async with session.post(create_url, headers=headers, json=[new_lead]) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    created = data.get('_embedded', {}).get('leads', [])
                    if created:
                        new_id = created[0].get('id')
                        contacts = lead.get('_embedded', {}).get('contacts', [])
                        for c in contacts:
                            link_url = f'{self.kommo_base_url}/api/v4/leads/{new_id}/link'
                            link_payload = [{'to_entity_id': c.get('id'), 'to_entity_type': 'contacts'}]
                            async with session.post(link_url, headers=headers, json=link_payload) as link_resp:
                                pass
                        return {'success': True, 'original_id': entity_id, 'cloned_id': new_id, 'name': new_lead['name']}
                error = await resp.text()
                return {'error': f'Failed to clone lead: {error[:200]}'}
        
        return {'error': f'Unknown entity action: {action}'}
    
    async def _handle_bulk_actions(self, session, headers, args: dict) -> dict:
        """Handle bulk operations on multiple entities."""
        action = args.get('action')
        entity_type = args.get('entity_type', 'leads')
        entity_ids = args.get('entity_ids', [])
        
        if not entity_ids:
            return {'error': 'entity_ids array is required'}
        
        if action == 'mass_move':
            pipeline_id = args.get('pipeline_id')
            status_id = args.get('status_id')
            
            if not status_id:
                return {'error': 'status_id is required for mass_move'}
            
            url = f'{self.kommo_base_url}/api/v4/leads'
            payload = []
            for eid in entity_ids:
                item = {'id': eid, 'status_id': status_id}
                if pipeline_id:
                    item['pipeline_id'] = pipeline_id
                payload.append(item)
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'moved': len(entity_ids), 'to_status': status_id}
                error = await resp.text()
                return {'error': f'Failed to mass move: {error[:200]}'}
        
        elif action == 'mass_tag':
            tags = args.get('tags', [])
            if not tags:
                return {'error': 'tags array is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}'
            payload = []
            for eid in entity_ids:
                payload.append({
                    'id': eid,
                    '_embedded': {'tags': [{'name': t} for t in tags]}
                })
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'tagged': len(entity_ids), 'tags': tags}
                error = await resp.text()
                return {'error': f'Failed to mass tag: {error[:200]}'}
        
        elif action == 'mass_assign':
            responsible_user_id = args.get('responsible_user_id')
            if not responsible_user_id:
                return {'error': 'responsible_user_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}'
            payload = [{'id': eid, 'responsible_user_id': responsible_user_id} for eid in entity_ids]
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'assigned': len(entity_ids), 'to_user': responsible_user_id}
                error = await resp.text()
                return {'error': f'Failed to mass assign: {error[:200]}'}
        
        elif action == 'mass_update':
            fields = args.get('fields', {})
            if not fields:
                return {'error': 'fields object is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}'
            payload = [{**{'id': eid}, **fields} for eid in entity_ids]
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'updated': len(entity_ids), 'fields': list(fields.keys())}
                error = await resp.text()
                return {'error': f'Failed to mass update: {error[:200]}'}
        
        elif action == 'mass_delete':
            # Delete entities one by one (Kommo API limitation)
            deleted = 0
            errors = []
            for eid in entity_ids:
                url = f'{self.kommo_base_url}/api/v4/{entity_type}/{eid}'
                async with session.delete(url, headers=headers) as resp:
                    if resp.status in [200, 204]:
                        deleted += 1
                    else:
                        errors.append(eid)
            
            return {'success': deleted > 0, 'deleted': deleted, 'failed': errors}
        
        return {'error': f'Unknown bulk action: {action}'}
    
    async def _handle_users(self, session, headers, args: dict) -> dict:
        """Handle users management and statistics."""
        action = args.get('action')
        user_id = args.get('user_id')
        days = args.get('days', 7)
        
        if action == 'list':
            url = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    users = data.get('_embedded', {}).get('users', [])
                    return {
                        'users': [
                            {
                                'id': u.get('id'),
                                'name': u.get('name'),
                                'email': u.get('email'),
                                'role': u.get('rights', {}).get('is_admin') and 'admin' or 'user',
                            }
                            for u in users
                        ],
                        'total': len(users),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'get':
            if not user_id:
                return {'error': 'user_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/users/{user_id}'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    user = await resp.json()
                    return {
                        'id': user.get('id'),
                        'name': user.get('name'),
                        'email': user.get('email'),
                        'lang': user.get('lang'),
                        'rights': user.get('rights'),
                    }
                return {'error': f'User not found: {resp.status}'}
        
        elif action == 'workload':
            if not user_id:
                return {'error': 'user_id is required'}
            
            # Get leads count
            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[responsible_user_id]': user_id, 'limit': 250}
            
            async with session.get(leads_url, headers=headers, params=params) as resp:
                leads_count = 0
                leads_sum = 0
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    leads_count = len(leads)
                    leads_sum = sum(l.get('price', 0) or 0 for l in leads)
            
            # Get tasks count
            tasks_url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'filter[responsible_user_id]': user_id, 'filter[is_completed]': 0}
            
            async with session.get(tasks_url, headers=headers, params=params) as resp:
                tasks_count = 0
                overdue_count = 0
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
                    tasks_count = len(tasks)
                    import time
                    now = int(time.time())
                    overdue_count = sum(1 for t in tasks if t.get('complete_till', 0) < now)
            
            return {
                'user_id': user_id,
                'leads': leads_count,
                'leads_sum': leads_sum,
                'open_tasks': tasks_count,
                'overdue_tasks': overdue_count,
            }
        
        elif action == 'activity':
            if not user_id:
                return {'error': 'user_id is required'}
            
            # Get recent events for user
            import time
            from datetime import datetime, timedelta
            
            date_from = int((datetime.now() - timedelta(days=days)).timestamp())
            
            events_url = f'{self.kommo_base_url}/api/v4/events'
            params = {
                'filter[created_by]': user_id,
                'filter[created_at][from]': date_from,
                'limit': 100,
            }
            
            async with session.get(events_url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    
                    # Count by type
                    event_counts = {}
                    for e in events:
                        etype = e.get('type', 'unknown')
                        event_counts[etype] = event_counts.get(etype, 0) + 1
                    
                    return {
                        'user_id': user_id,
                        'period_days': days,
                        'total_events': len(events),
                        'by_type': event_counts,
                    }
                return {'error': f'API error: {resp.status}'}
        
        return {'error': f'Unknown users action: {action}'}
    
    async def _handle_reports(self, session, headers, args: dict) -> dict:
        """Generate various CRM reports."""
        import time
        from datetime import datetime, timedelta
        
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        user_id = args.get('user_id')
        limit = args.get('limit', 20)
        
        # Parse dates
        date_from_str = args.get('date_from')
        date_to_str = args.get('date_to')
        
        if date_from_str:
            try:
                date_from = int(datetime.strptime(date_from_str, '%Y-%m-%d').timestamp())
            except:
                date_from = int((datetime.now() - timedelta(days=30)).timestamp())
        else:
            date_from = int((datetime.now() - timedelta(days=30)).timestamp())
        
        if date_to_str:
            try:
                date_to = int(datetime.strptime(date_to_str, '%Y-%m-%d').timestamp())
            except:
                date_to = int(time.time())
        else:
            date_to = int(time.time())
        
        if action == 'sales_summary':
            # Get all leads
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'filter[created_at][from]': date_from, 'filter[created_at][to]': date_to}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    
                    total = len(leads)
                    total_sum = sum(l.get('price', 0) or 0 for l in leads)
                    won = [l for l in leads if l.get('status_id') == 142]  # Won status
                    lost = [l for l in leads if l.get('status_id') == 143]  # Lost status
                    
                    return {
                        'period': f'{date_from_str or "30d ago"} - {date_to_str or "today"}',
                        'total_leads': total,
                        'total_value': total_sum,
                        'won': len(won),
                        'won_value': sum(l.get('price', 0) or 0 for l in won),
                        'lost': len(lost),
                        'avg_deal': total_sum // total if total > 0 else 0,
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'pipeline_report':
            # Get pipelines with stats
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                data = await resp.json()
                pipelines = data.get('_embedded', {}).get('pipelines', [])
            
            if pipeline_id:
                pipelines = [p for p in pipelines if p.get('id') == pipeline_id]
            
            result = []
            for p in pipelines:
                p_id = p.get('id')
                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': p_id, 'limit': 250}
                
                async with session.get(leads_url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        leads_data = await resp.json()
                        leads = leads_data.get('_embedded', {}).get('leads', [])
                        
                        statuses = p.get('_embedded', {}).get('statuses', [])
                        status_map = {s['id']: s['name'] for s in statuses}
                        
                        by_status = {}
                        for lead in leads:
                            sid = lead.get('status_id')
                            sname = status_map.get(sid, str(sid))
                            if sname not in by_status:
                                by_status[sname] = {'count': 0, 'sum': 0}
                            by_status[sname]['count'] += 1
                            by_status[sname]['sum'] += lead.get('price', 0) or 0
                        
                        result.append({
                            'pipeline': p.get('name'),
                            'pipeline_id': p_id,
                            'total_leads': len(leads),
                            'total_value': sum(l.get('price', 0) or 0 for l in leads),
                            'by_stage': by_status,
                        })
            
            return {'pipelines': result}
        
        elif action == 'manager_report':
            # Get users first
            users_url = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(users_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                users_data = await resp.json()
                users = users_data.get('_embedded', {}).get('users', [])
            
            if user_id:
                users = [u for u in users if u.get('id') == user_id]
            
            result = []
            for user in users[:10]:  # Limit to 10 users
                uid = user.get('id')
                
                # Get leads for user
                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[responsible_user_id]': uid, 'limit': 250}
                
                async with session.get(leads_url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        leads_data = await resp.json()
                        leads = leads_data.get('_embedded', {}).get('leads', [])
                        
                        result.append({
                            'user': user.get('name'),
                            'user_id': uid,
                            'leads': len(leads),
                            'total_value': sum(l.get('price', 0) or 0 for l in leads),
                            'avg_deal': sum(l.get('price', 0) or 0 for l in leads) // len(leads) if leads else 0,
                        })
            
            return {'managers': sorted(result, key=lambda x: x['total_value'], reverse=True)}
        
        elif action == 'overdue_tasks':
            url = f'{self.kommo_base_url}/api/v4/tasks'
            now = int(time.time())
            params = {'filter[is_completed]': 0, 'limit': limit}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
                    
                    overdue = [t for t in tasks if t.get('complete_till', 0) < now]
                    
                    return {
                        'overdue_tasks': [
                            {
                                'id': t.get('id'),
                                'text': t.get('text', '')[:50],
                                'entity_id': t.get('entity_id'),
                                'responsible_user_id': t.get('responsible_user_id'),
                                'overdue_days': (now - t.get('complete_till', now)) // 86400,
                            }
                            for t in overdue[:limit]
                        ],
                        'total_overdue': len(overdue),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'stale_deals':
            url = f'{self.kommo_base_url}/api/v4/leads'
            stale_days = 14
            stale_threshold = int(time.time()) - (stale_days * 86400)
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    
                    # Filter stale (not updated for stale_days)
                    stale = [l for l in leads if l.get('updated_at', 0) < stale_threshold 
                             and l.get('status_id') not in [142, 143]]  # Not won/lost
                    
                    return {
                        'stale_deals': [
                            {
                                'id': l.get('id'),
                                'name': l.get('name'),
                                'price': l.get('price'),
                                'days_stale': (int(time.time()) - l.get('updated_at', 0)) // 86400,
                            }
                            for l in sorted(stale, key=lambda x: x.get('updated_at', 0))[:limit]
                        ],
                        'total_stale': len(stale),
                        'threshold_days': stale_days,
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'top_deals':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    
                    # Sort by price
                    top = sorted(leads, key=lambda x: x.get('price', 0) or 0, reverse=True)[:limit]
                    
                    return {
                        'top_deals': [
                            {
                                'id': l.get('id'),
                                'name': l.get('name'),
                                'price': l.get('price'),
                                'status_id': l.get('status_id'),
                                'responsible_user_id': l.get('responsible_user_id'),
                            }
                            for l in top
                        ],
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'tasks_report':
            url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'limit': 250}
            if user_id:
                params['filter[responsible_user_id]'] = user_id
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
                    
                    now = int(time.time())
                    completed = [t for t in tasks if t.get('is_completed')]
                    pending = [t for t in tasks if not t.get('is_completed')]
                    overdue = [t for t in pending if t.get('complete_till', 0) < now]
                    
                    # By type
                    by_type = {}
                    for t in tasks:
                        ttype = t.get('task_type_id', 0)
                        type_name = {1: 'call', 2: 'meeting', 3: 'email'}.get(ttype, 'other')
                        by_type[type_name] = by_type.get(type_name, 0) + 1
                    
                    return {
                        'total': len(tasks),
                        'completed': len(completed),
                        'pending': len(pending),
                        'overdue': len(overdue),
                        'by_type': by_type,
                    }
                return {'error': f'API error: {resp.status}'}
        
        return {'error': f'Unknown report action: {action}'}
    
    async def _handle_webhooks(self, session, headers, args: dict) -> dict:
        """Manage webhooks."""
        action = args.get('action')
        
        if action == 'list':
            url = f'{self.kommo_base_url}/api/v4/webhooks'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    webhooks = data.get('_embedded', {}).get('webhooks', [])
                    return {
                        'webhooks': [
                            {
                                'id': w.get('id'),
                                'destination': w.get('destination'),
                                'settings': w.get('settings', []),
                            }
                            for w in webhooks
                        ],
                        'total': len(webhooks),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'create':
            destination = args.get('destination')
            events = args.get('events', ['add_lead', 'update_lead'])
            
            if not destination:
                return {'error': 'destination URL is required'}
            
            url = f'{self.kommo_base_url}/api/v4/webhooks'
            payload = {
                'destination': destination,
                'settings': events,
            }
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    return {'success': True, 'webhook': data}
                error = await resp.text()
                return {'error': f'Failed to create webhook: {error[:200]}'}
        
        elif action == 'delete':
            webhook_id = args.get('webhook_id')
            if not webhook_id:
                return {'error': 'webhook_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/webhooks/{webhook_id}'
            async with session.delete(url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    return {'success': True, 'deleted_webhook_id': webhook_id}
                error = await resp.text()
                return {'error': f'Failed to delete webhook: {error[:200]}'} 
        
        return {'error': f'Unknown webhooks action: {action}'}
    
    async def _handle_tags(self, session, headers, args: dict) -> dict:
        """Handle tags management."""
        action = args.get('action')
        entity_type = args.get('entity_type', 'leads')
        entity_id = args.get('entity_id')
        tags = args.get('tags', [])
        tag_name = args.get('tag_name')
        
        if action == 'list':
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/tags'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tags_list = data.get('_embedded', {}).get('tags', [])
                    return {
                        'tags': [{'id': t.get('id'), 'name': t.get('name'), 'color': t.get('color')} for t in tags_list],
                        'total': len(tags_list),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'add':
            if not entity_id or not tags:
                return {'error': 'entity_id and tags array are required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
            
            # First get current tags
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Entity not found: {resp.status}'}
                entity_data = await resp.json()
                current_tags = entity_data.get('_embedded', {}).get('tags', [])
            
            # Add new tags
            all_tags = [{'name': t.get('name')} for t in current_tags]
            for tag in tags:
                if tag not in [t['name'] for t in all_tags]:
                    all_tags.append({'name': tag})
            
            payload = {'_embedded': {'tags': all_tags}}
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'entity_id': entity_id, 'added_tags': tags}
                error = await resp.text()
                return {'error': f'Failed to add tags: {error[:200]}'}
        
        elif action == 'remove':
            if not entity_id or not tags:
                return {'error': 'entity_id and tags array are required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
            
            # First get current tags
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Entity not found: {resp.status}'}
                entity_data = await resp.json()
                current_tags = entity_data.get('_embedded', {}).get('tags', [])
            
            # Remove specified tags
            remaining_tags = [{'name': t.get('name')} for t in current_tags if t.get('name') not in tags]
            
            payload = {'_embedded': {'tags': remaining_tags}}
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'entity_id': entity_id, 'removed_tags': tags}
                error = await resp.text()
                return {'error': f'Failed to remove tags: {error[:200]}'}
        
        elif action == 'search_by_tag':
            if not tag_name:
                return {'error': 'tag_name is required'}
            
            # First get tag ID
            tags_url = f'{self.kommo_base_url}/api/v4/{entity_type}/tags'
            async with session.get(tags_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                data = await resp.json()
                tags_list = data.get('_embedded', {}).get('tags', [])
                tag_id = None
                for t in tags_list:
                    if t.get('name', '').lower() == tag_name.lower():
                        tag_id = t.get('id')
                        break
                if not tag_id:
                    return {'error': f'Tag "{tag_name}" not found', 'available_tags': [t.get('name') for t in tags_list[:10]]}
            
            # Search entities with this tag
            url = f'{self.kommo_base_url}/api/v4/{entity_type}'
            params = {'filter[tags]': tag_id, 'limit': 50}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    entities = data.get('_embedded', {}).get(entity_type, [])
                    return {
                        'tag': tag_name,
                        'entities': [{'id': e.get('id'), 'name': e.get('name')} for e in entities],
                        'total': len(entities),
                    }
                return {'error': f'API error: {resp.status}'}
        
        return {'error': f'Unknown tags action: {action}'}
    
    async def _handle_custom_fields(self, session, headers, args: dict) -> dict:
        """Handle custom fields management — full CRUD + mass operations."""
        action = args.get('action')
        entity_type = args.get('entity_type', 'leads')
        entity_id = args.get('entity_id')
        field_id = args.get('field_id')
        value = args.get('value')
        
        # Valid entity types for custom fields
        valid_entities = ['leads', 'contacts', 'companies', 'customers', 'segments']
        if entity_type not in valid_entities:
            return {'error': f'Invalid entity_type: {entity_type}. Valid: {valid_entities}'}
        
        if action == 'list':
            # List all custom fields for entity type, optionally for all entity types
            all_types = args.get('all_types', False)
            
            if all_types:
                # Get fields for leads, contacts, companies
                all_fields = {}
                for et in ['leads', 'contacts', 'companies']:
                    url = f'{self.kommo_base_url}/api/v4/{et}/custom_fields'
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            fields = data.get('_embedded', {}).get('custom_fields', [])
                            all_fields[et] = [
                                {
                                    'id': f.get('id'),
                                    'name': f.get('name'),
                                    'type': f.get('type'),
                                    'is_api_only': f.get('is_api_only', False),
                                    'group_id': f.get('group_id'),
                                    'required_statuses': f.get('required_statuses', []),
                                    'enums': [{'id': e.get('id'), 'value': e.get('value')} for e in f.get('enums', [])] if f.get('enums') else None,
                                }
                                for f in fields
                            ]
                        else:
                            all_fields[et] = []
                total = sum(len(v) for v in all_fields.values())
                return {'fields_by_entity': all_fields, 'total': total}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    fields = data.get('_embedded', {}).get('custom_fields', [])
                    return {
                        'entity_type': entity_type,
                        'fields': [
                            {
                                'id': f.get('id'),
                                'name': f.get('name'),
                                'type': f.get('type'),
                                'is_api_only': f.get('is_api_only', False),
                                'group_id': f.get('group_id'),
                                'required_statuses': f.get('required_statuses', []),
                                'enums': [{'id': e.get('id'), 'value': e.get('value')} for e in f.get('enums', [])] if f.get('enums') else None,
                            }
                            for f in fields
                        ],
                        'total': len(fields),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'create':
            field_name = args.get('field_name')
            field_type = args.get('field_type', 'text')
            enums = args.get('enums', [])
            group_id = args.get('group_id')
            is_api_only = args.get('is_api_only', False)
            required_statuses = args.get('required_statuses', [])
            
            if not field_name:
                return {'error': 'field_name is required'}
            
            # Map common aliases to valid Kommo field types
            type_map = {
                'text': 'text', 'numeric': 'numeric', 'checkbox': 'checkbox',
                'select': 'select', 'multiselect': 'multiselect', 'date': 'date',
                'url': 'url', 'textarea': 'textarea', 'radiobutton': 'radiobutton',
                'streetaddress': 'streetaddress', 'smart_address': 'smart_address',
                'birthday': 'birthday', 'legal_entity': 'legal_entity',
                'date_time': 'date_time', 'tracking_data': 'tracking_data',
                'linked_entity': 'linked_entity', 'items': 'items',
                'org_legal_name': 'org_legal_name',
                # Aliases
                'price': 'numeric', 'money': 'numeric', 'budget': 'numeric',
                'number': 'numeric', 'switch': 'radiobutton', 'list': 'select',
                'multilist': 'multiselect', 'address': 'streetaddress',
            }
            
            mapped_type = type_map.get(field_type, 'text')
            
            payload = [{'name': field_name, 'type': mapped_type}]
            
            if enums and mapped_type in ['select', 'multiselect', 'radiobutton']:
                payload[0]['enums'] = [{'value': e, 'sort': i * 10} for i, e in enumerate(enums)]
            
            if group_id:
                payload[0]['group_id'] = group_id
            
            if is_api_only:
                payload[0]['is_api_only'] = True
            
            if required_statuses:
                payload[0]['required_statuses'] = [{'pipeline_id': rs.get('pipeline_id'), 'status_id': rs.get('status_id')} for rs in required_statuses]
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields'
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    fields = data.get('_embedded', {}).get('custom_fields', [])
                    if fields:
                        f = fields[0]
                        return {
                            'success': True,
                            'field_id': f.get('id'),
                            'field_name': f.get('name'),
                            'field_type': f.get('type'),
                            'entity_type': entity_type,
                        }
                error = await resp.text()
                return {'error': f'Failed to create field: {error[:300]}'}
        
        elif action == 'update':
            if not field_id:
                return {'error': 'field_id is required'}
            
            field_name = args.get('field_name')
            enums = args.get('enums', [])
            required_statuses = args.get('required_statuses')
            
            payload = {}
            if field_name:
                payload['name'] = field_name
            if enums:
                payload['enums'] = [{'value': e, 'sort': i * 10} for i, e in enumerate(enums)]
            if required_statuses is not None:
                payload['required_statuses'] = required_statuses
            
            if not payload:
                return {'error': 'Nothing to update. Provide field_name, enums, or required_statuses.'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields/{field_id}'
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        'success': True,
                        'field_id': field_id,
                        'name': data.get('name'),
                        'type': data.get('type'),
                    }
                error = await resp.text()
                return {'error': f'Failed to update field: {error[:300]}'}
        
        elif action == 'delete':
            if not field_id:
                return {'error': 'field_id is required'}
            
            field_id = int(field_id)
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields/{field_id}'
            async with session.delete(url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    return {'success': True, 'deleted_field_id': field_id, 'entity_type': entity_type}
                error = await resp.text()
                return {'error': f'Failed to delete field {field_id}: {error[:300]}'}
        
        elif action == 'delete_all':
            # Delete ALL custom fields for given entity type(s)
            # System fields (tracking_data, multitext like Phone/Email) cannot be deleted via API
            SYSTEM_FIELD_TYPES = {'tracking_data'}
            SYSTEM_FIELD_CODES = {'PHONE', 'EMAIL', 'IM', 'POSITION', 'WEB', 'ADDRESS'}
            
            confirm = args.get('confirm', False)
            all_types = args.get('all_types', False)
            
            target_types = ['leads', 'contacts', 'companies'] if all_types else [entity_type]
            
            if not confirm:
                # Preview mode - show what would be deleted vs system fields
                preview = {}
                for et in target_types:
                    url = f'{self.kommo_base_url}/api/v4/{et}/custom_fields'
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            fields = data.get('_embedded', {}).get('custom_fields', [])
                            deletable = []
                            system = []
                            for f in fields:
                                info = {'id': f.get('id'), 'name': f.get('name'), 'type': f.get('type')}
                                code = f.get('code', '')
                                if f.get('type') in SYSTEM_FIELD_TYPES or code in SYSTEM_FIELD_CODES:
                                    system.append(info)
                                else:
                                    deletable.append(info)
                            preview[et] = {'deletable': deletable, 'system_undeletable': system}
                        else:
                            preview[et] = {'deletable': [], 'system_undeletable': []}
                total_deletable = sum(len(v['deletable']) for v in preview.values())
                total_system = sum(len(v['system_undeletable']) for v in preview.values())
                return {
                    'preview': True,
                    'fields_to_delete': preview,
                    'total_deletable': total_deletable,
                    'total_system_undeletable': total_system,
                    'warning': f'{total_deletable} fields can be deleted, {total_system} are system fields that CANNOT be deleted. Set confirm=true to proceed.',
                }
            
            results = {}
            for et in target_types:
                url = f'{self.kommo_base_url}/api/v4/{et}/custom_fields'
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        results[et] = {'error': f'Failed to list fields: {resp.status}'}
                        continue
                    data = await resp.json()
                    fields = data.get('_embedded', {}).get('custom_fields', [])
                
                deleted = 0
                deleted_names = []
                skipped_system = []
                failed = []
                for f in fields:
                    fid = f.get('id')
                    fname = f.get('name')
                    ftype = f.get('type')
                    code = f.get('code', '')
                    # Skip system fields — they cannot be deleted
                    if ftype in SYSTEM_FIELD_TYPES or code in SYSTEM_FIELD_CODES:
                        skipped_system.append({'id': fid, 'name': fname, 'type': ftype, 'reason': 'system field'})
                        continue
                    del_url = f'{self.kommo_base_url}/api/v4/{et}/custom_fields/{fid}'
                    async with session.delete(del_url, headers=headers) as del_resp:
                        if del_resp.status in [200, 204]:
                            deleted += 1
                            deleted_names.append(fname)
                        else:
                            failed.append({'id': fid, 'name': fname, 'status': del_resp.status})
                
                results[et] = {
                    'total_fields': len(fields),
                    'deleted': deleted,
                    'deleted_names': deleted_names,
                    'skipped_system': skipped_system,
                    'failed': failed,
                }
            
            return {'action': 'delete_all', 'results': results}
        
        elif action == 'get_values':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    custom_fields = data.get('custom_fields_values', [])
                    
                    # Get field names
                    fields_url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields'
                    async with session.get(fields_url, headers=headers) as fields_resp:
                        field_names = {}
                        if fields_resp.status == 200:
                            fields_data = await fields_resp.json()
                            for f in fields_data.get('_embedded', {}).get('custom_fields', []):
                                field_names[f.get('id')] = f.get('name')
                    
                    return {
                        'entity_id': entity_id,
                        'fields': [
                            {
                                'field_id': cf.get('field_id'),
                                'field_name': field_names.get(cf.get('field_id'), 'Unknown'),
                                'values': [v.get('value') for v in cf.get('values', [])],
                            }
                            for cf in custom_fields
                        ],
                    }
                return {'error': f'Entity not found: {resp.status}'}
        
        elif action == 'set_value':
            if not entity_id or not field_id:
                return {'error': 'entity_id and field_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
            payload = {
                'custom_fields_values': [
                    {'field_id': int(field_id), 'values': [{'value': value}]}
                ]
            }
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'entity_id': entity_id, 'field_id': field_id, 'value': value}
                error = await resp.text()
                return {'error': f'Failed to set field value: {error[:200]}'}
        
        elif action == 'set_values_bulk':
            # Set multiple field values on one entity at once
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            fields_values = args.get('fields_values', [])
            if not fields_values:
                return {'error': 'fields_values is required (array of {field_id, value})'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
            payload = {
                'custom_fields_values': [
                    {'field_id': int(fv.get('field_id')), 'values': [{'value': fv.get('value')}]}
                    for fv in fields_values
                ]
            }
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'entity_id': entity_id, 'fields_updated': len(fields_values)}
                error = await resp.text()
                return {'error': f'Failed to set field values: {error[:200]}'}
        
        return {'error': f'Unknown custom_fields action: {action}. Available: list, create, update, delete, delete_all, get_values, set_value, set_values_bulk'}
    
    async def _handle_sources(self, session, headers, args: dict) -> dict:
        """Handle lead sources management and analytics."""
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        source_name = args.get('source_name')
        
        if action == 'list':
            # Get pipelines first to find sources
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                data = await resp.json()
                pipelines = data.get('_embedded', {}).get('pipelines', [])
            
            if pipeline_id:
                pipelines = [p for p in pipelines if p.get('id') == pipeline_id]
            
            result = []
            for p in pipelines:
                # Get sources for this pipeline
                sources_url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{p.get("id")}/sources'
                async with session.get(sources_url, headers=headers) as resp:
                    if resp.status == 200:
                        sources_data = await resp.json()
                        sources = sources_data.get('_embedded', {}).get('sources', [])
                        result.append({
                            'pipeline': p.get('name'),
                            'pipeline_id': p.get('id'),
                            'sources': [{'id': s.get('id'), 'name': s.get('name')} for s in sources],
                        })
            
            return {'pipelines': result}
        
        elif action == 'create':
            if not pipeline_id or not source_name:
                return {'error': 'pipeline_id and source_name are required'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}/sources'
            payload = [{'name': source_name}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    sources = data.get('_embedded', {}).get('sources', [])
                    if sources:
                        return {'success': True, 'source_id': sources[0].get('id'), 'source_name': source_name}
                error = await resp.text()
                return {'error': f'Failed to create source: {error[:200]}'}
        
        elif action == 'analytics':
            # Get leads and analyze by source
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'with': 'source_id'}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    
                    # Group by source
                    by_source = {}
                    for lead in leads:
                        source_id = lead.get('source_id') or 'unknown'
                        if source_id not in by_source:
                            by_source[source_id] = {'count': 0, 'sum': 0}
                        by_source[source_id]['count'] += 1
                        by_source[source_id]['sum'] += lead.get('price', 0) or 0
                    
                    return {
                        'total_leads': len(leads),
                        'by_source': by_source,
                    }
                return {'error': f'API error: {resp.status}'}
        
        return {'error': f'Unknown sources action: {action}'}
    
    async def _handle_companies(self, session, headers, args: dict) -> dict:
        """Handle companies management."""
        action = args.get('action')
        company_id = args.get('company_id')
        name = args.get('name')
        query = args.get('query')
        fields = args.get('fields', {})
        limit = args.get('limit', 20)
        contact_id = args.get('contact_id')
        
        if action == 'list':
            url = f'{self.kommo_base_url}/api/v4/companies'
            params = {'limit': limit}
            if query:
                params['query'] = query
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    companies = data.get('_embedded', {}).get('companies', [])
                    return {
                        'companies': [
                            {'id': c.get('id'), 'name': c.get('name')}
                            for c in companies
                        ],
                        'total': len(companies),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'get':
            if not company_id:
                return {'error': 'company_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/companies/{company_id}'
            params = {'with': 'contacts,leads'}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    company = await resp.json()
                    return {
                        'id': company.get('id'),
                        'name': company.get('name'),
                        'responsible_user_id': company.get('responsible_user_id'),
                        'contacts_count': len(company.get('_embedded', {}).get('contacts', [])),
                        'leads_count': len(company.get('_embedded', {}).get('leads', [])),
                        'custom_fields': company.get('custom_fields_values', []),
                    }
                return {'error': f'Company not found: {resp.status}'}
        
        elif action == 'create':
            if not name:
                return {'error': 'name is required'}
            
            url = f'{self.kommo_base_url}/api/v4/companies'
            payload = [{'name': name}]
            if fields:
                payload[0].update(fields)
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    companies = data.get('_embedded', {}).get('companies', [])
                    if companies:
                        return {'success': True, 'company_id': companies[0].get('id'), 'name': name}
                error = await resp.text()
                return {'error': f'Failed to create company: {error[:200]}'}
        
        elif action == 'update':
            if not company_id:
                return {'error': 'company_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/companies/{company_id}'
            payload = fields if fields else {}
            if name:
                payload['name'] = name
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'company_id': company_id, 'updated': list(payload.keys())}
                error = await resp.text()
                return {'error': f'Failed to update company: {error[:200]}'}
        
        elif action == 'get_contacts':
            if not company_id:
                return {'error': 'company_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/companies/{company_id}/contacts'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    contacts = data.get('_embedded', {}).get('contacts', [])
                    return {
                        'company_id': company_id,
                        'contacts': [{'id': c.get('id'), 'name': c.get('name')} for c in contacts],
                        'total': len(contacts),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'get_leads':
            if not company_id:
                return {'error': 'company_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/companies/{company_id}/leads'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    return {
                        'company_id': company_id,
                        'leads': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price')} for l in leads],
                        'total': len(leads),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'link_contact':
            if not company_id or not contact_id:
                return {'error': 'company_id and contact_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/companies/{company_id}/link'
            payload = [{'to_entity_id': contact_id, 'to_entity_type': 'contacts'}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    return {'success': True, 'company_id': company_id, 'linked_contact': contact_id}
                error = await resp.text()
                return {'error': f'Failed to link contact: {error[:200]}'}
        
        return {'error': f'Unknown companies action: {action}'}
    
    async def _handle_duplicates(self, session, headers, args: dict) -> dict:
        """Handle duplicate detection and merging."""
        action = args.get('action')
        threshold = args.get('threshold', 0.8)
        primary_id = args.get('primary_id')
        duplicate_id = args.get('duplicate_id')
        
        def similarity(s1, s2):
            """Simple similarity check."""
            if not s1 or not s2:
                return 0
            s1, s2 = s1.lower().strip(), s2.lower().strip()
            if s1 == s2:
                return 1.0
            # Check if one contains the other
            if s1 in s2 or s2 in s1:
                return 0.9
            # Simple word overlap
            words1 = set(s1.split())
            words2 = set(s2.split())
            if not words1 or not words2:
                return 0
            overlap = len(words1 & words2)
            return overlap / max(len(words1), len(words2))
        
        if action == 'find_contacts':
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'limit': 250}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                data = await resp.json()
                contacts = data.get('_embedded', {}).get('contacts', [])
            
            # Find duplicates by name similarity
            duplicates = []
            checked = set()
            for i, c1 in enumerate(contacts):
                if c1.get('id') in checked:
                    continue
                for c2 in contacts[i+1:]:
                    if c2.get('id') in checked:
                        continue
                    sim = similarity(c1.get('name', ''), c2.get('name', ''))
                    if sim >= threshold:
                        duplicates.append({
                            'contact1': {'id': c1.get('id'), 'name': c1.get('name')},
                            'contact2': {'id': c2.get('id'), 'name': c2.get('name')},
                            'similarity': round(sim, 2),
                        })
                        checked.add(c2.get('id'))
            
            return {
                'duplicates': duplicates[:20],
                'total_found': len(duplicates),
                'threshold': threshold,
            }
        
        elif action == 'find_companies':
            url = f'{self.kommo_base_url}/api/v4/companies'
            params = {'limit': 250}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                data = await resp.json()
                companies = data.get('_embedded', {}).get('companies', [])
            
            # Find duplicates by name similarity
            duplicates = []
            checked = set()
            for i, c1 in enumerate(companies):
                if c1.get('id') in checked:
                    continue
                for c2 in companies[i+1:]:
                    if c2.get('id') in checked:
                        continue
                    sim = similarity(c1.get('name', ''), c2.get('name', ''))
                    if sim >= threshold:
                        duplicates.append({
                            'company1': {'id': c1.get('id'), 'name': c1.get('name')},
                            'company2': {'id': c2.get('id'), 'name': c2.get('name')},
                            'similarity': round(sim, 2),
                        })
                        checked.add(c2.get('id'))
            
            return {
                'duplicates': duplicates[:20],
                'total_found': len(duplicates),
                'threshold': threshold,
            }
        
        elif action == 'merge_contacts':
            if not primary_id or not duplicate_id:
                return {'error': 'primary_id and duplicate_id are required'}
            
            # Get duplicate contact data
            dup_url = f'{self.kommo_base_url}/api/v4/contacts/{duplicate_id}'
            async with session.get(dup_url, headers=headers, params={'with': 'leads'}) as resp:
                if resp.status != 200:
                    return {'error': f'Duplicate contact not found: {resp.status}'}
                dup_data = await resp.json()
            
            # Move leads from duplicate to primary
            dup_leads = dup_data.get('_embedded', {}).get('leads', [])
            moved_leads = 0
            for lead in dup_leads:
                lead_url = f'{self.kommo_base_url}/api/v4/leads/{lead.get("id")}/link'
                payload = [{'to_entity_id': primary_id, 'to_entity_type': 'contacts'}]
                async with session.post(lead_url, headers=headers, json=payload) as resp:
                    if resp.status in [200, 201]:
                        moved_leads += 1
            
            # Delete duplicate contact
            del_url = f'{self.kommo_base_url}/api/v4/contacts/{duplicate_id}'
            async with session.delete(del_url, headers=headers) as resp:
                deleted = resp.status in [200, 204]
            
            return {
                'success': True,
                'primary_id': primary_id,
                'duplicate_id': duplicate_id,
                'moved_leads': moved_leads,
                'duplicate_deleted': deleted,
            }
        
        return {'error': f'Unknown duplicates action: {action}'}
    
    async def _handle_links(self, session, headers, args: dict) -> dict:
        """Handle entity links management."""
        action = args.get('action')
        entity_type = args.get('entity_type', 'leads')
        entity_id = args.get('entity_id')
        to_entity_type = args.get('to_entity_type')
        to_entity_id = args.get('to_entity_id')
        
        if action == 'get':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/links'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    links = data.get('_embedded', {}).get('links', [])
                    return {
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'links': [
                            {
                                'to_entity_type': l.get('to_entity_type'),
                                'to_entity_id': l.get('to_entity_id'),
                            }
                            for l in links
                        ],
                        'total': len(links),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'link':
            if not entity_id or not to_entity_type or not to_entity_id:
                return {'error': 'entity_id, to_entity_type, and to_entity_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/link'
            payload = [{'to_entity_id': to_entity_id, 'to_entity_type': to_entity_type}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    return {
                        'success': True,
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'linked_to': {'type': to_entity_type, 'id': to_entity_id},
                    }
                error = await resp.text()
                return {'error': f'Failed to create link: {error[:200]}'}
        
        elif action == 'unlink':
            if not entity_id or not to_entity_type or not to_entity_id:
                return {'error': 'entity_id, to_entity_type, and to_entity_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/unlink'
            payload = [{'to_entity_id': to_entity_id, 'to_entity_type': to_entity_type}]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201, 204]:
                    return {
                        'success': True,
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'unlinked_from': {'type': to_entity_type, 'id': to_entity_id},
                    }
                error = await resp.text()
                return {'error': f'Failed to remove link: {error[:200]}'}
        
        return {'error': f'Unknown links action: {action}'}
    
    async def _handle_catalogs(self, session, headers, args: dict) -> dict:
        """Handle product catalogs management."""
        action = args.get('action')
        catalog_id = args.get('catalog_id')
        element_id = args.get('element_id')
        lead_id = args.get('lead_id')
        name = args.get('name')
        price = args.get('price')
        quantity = args.get('quantity', 1)
        query = args.get('query')
        
        if action == 'list_catalogs':
            url = f'{self.kommo_base_url}/api/v4/catalogs'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    catalogs = data.get('_embedded', {}).get('catalogs', [])
                    return {
                        'catalogs': [
                            {'id': c.get('id'), 'name': c.get('name'), 'type': c.get('type')}
                            for c in catalogs
                        ],
                        'total': len(catalogs),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'get_catalog':
            if not catalog_id:
                return {'error': 'catalog_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/catalogs/{catalog_id}'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    catalog = await resp.json()
                    return {
                        'id': catalog.get('id'),
                        'name': catalog.get('name'),
                        'type': catalog.get('type'),
                        'can_add_elements': catalog.get('can_add_elements'),
                    }
                return {'error': f'Catalog not found: {resp.status}'}
        
        elif action == 'list_elements':
            if not catalog_id:
                return {'error': 'catalog_id is required'}
            
            url = f'{self.kommo_base_url}/api/v4/catalogs/{catalog_id}/elements'
            params = {'limit': 50}
            if query:
                params['query'] = query
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    elements = data.get('_embedded', {}).get('elements', [])
                    return {
                        'catalog_id': catalog_id,
                        'elements': [
                            {
                                'id': e.get('id'),
                                'name': e.get('name'),
                                'custom_fields': e.get('custom_fields_values', []),
                            }
                            for e in elements
                        ],
                        'total': len(elements),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'get_element':
            if not catalog_id or not element_id:
                return {'error': 'catalog_id and element_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/catalogs/{catalog_id}/elements/{element_id}'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    element = await resp.json()
                    return {
                        'id': element.get('id'),
                        'name': element.get('name'),
                        'custom_fields': element.get('custom_fields_values', []),
                    }
                return {'error': f'Element not found: {resp.status}'}
        
        elif action == 'create_element':
            if not catalog_id or not name:
                return {'error': 'catalog_id and name are required'}
            
            url = f'{self.kommo_base_url}/api/v4/catalogs/{catalog_id}/elements'
            payload = [{'name': name}]
            if price:
                payload[0]['custom_fields_values'] = [
                    {'field_code': 'PRICE', 'values': [{'value': price}]}
                ]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    elements = data.get('_embedded', {}).get('elements', [])
                    if elements:
                        return {'success': True, 'element_id': elements[0].get('id'), 'name': name}
                error = await resp.text()
                return {'error': f'Failed to create element: {error[:200]}'}
        
        elif action == 'link_to_lead':
            if not lead_id or not catalog_id or not element_id:
                return {'error': 'lead_id, catalog_id, and element_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/link'
            payload = [{
                'to_entity_id': element_id,
                'to_entity_type': 'catalog_elements',
                'metadata': {'catalog_id': catalog_id, 'quantity': quantity},
            }]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    return {'success': True, 'lead_id': lead_id, 'element_id': element_id, 'quantity': quantity}
                error = await resp.text()
                return {'error': f'Failed to link element: {error[:200]}'}
        
        return {'error': f'Unknown catalogs action: {action}'}
    
    async def _handle_events(self, session, headers, args: dict) -> dict:
        """Handle CRM events."""
        action = args.get('action')
        entity_type = args.get('entity_type')
        entity_id = args.get('entity_id')
        event_type = args.get('event_type')
        limit = args.get('limit', 50)
        
        if action == 'list':
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {'limit': limit}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    return {
                        'events': [
                            {
                                'id': e.get('id'),
                                'type': e.get('type'),
                                'entity_type': e.get('entity_type'),
                                'entity_id': e.get('entity_id'),
                                'created_by': e.get('created_by'),
                                'created_at': e.get('created_at'),
                            }
                            for e in events
                        ],
                        'total': len(events),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'by_entity':
            if not entity_type or not entity_id:
                return {'error': 'entity_type and entity_id are required'}
            
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {
                'limit': limit,
                'filter[entity]': entity_type,
                'filter[entity_id]': entity_id,
            }
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    return {
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'events': [
                            {'id': e.get('id'), 'type': e.get('type'), 'created_at': e.get('created_at')}
                            for e in events
                        ],
                        'total': len(events),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'by_type':
            if not event_type:
                return {'error': 'event_type is required'}
            
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {'limit': limit, 'filter[type]': event_type}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    return {
                        'event_type': event_type,
                        'events': [
                            {
                                'id': e.get('id'),
                                'entity_type': e.get('entity_type'),
                                'entity_id': e.get('entity_id'),
                                'created_at': e.get('created_at'),
                            }
                            for e in events
                        ],
                        'total': len(events),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'stats':
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {'limit': 250}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    
                    # Count by type
                    by_type = {}
                    for e in events:
                        t = e.get('type', 'unknown')
                        by_type[t] = by_type.get(t, 0) + 1
                    
                    return {
                        'total_events': len(events),
                        'by_type': by_type,
                    }
                return {'error': f'API error: {resp.status}'}
        
        return {'error': f'Unknown events action: {action}'}
    
    async def _handle_calls(self, session, headers, args: dict) -> dict:
        """Handle call records."""
        action = args.get('action')
        entity_type = args.get('entity_type', 'contacts')
        entity_id = args.get('entity_id')
        phone = args.get('phone')
        duration = args.get('duration', 0)
        direction = args.get('direction', 'outbound')
        result = args.get('result', '')
        days = args.get('days', 30)
        
        if action == 'list':
            # Get recent call events
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {'limit': 50, 'filter[type]': 'outgoing_call,incoming_call'}
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    return {
                        'calls': [
                            {
                                'id': e.get('id'),
                                'type': e.get('type'),
                                'entity_type': e.get('entity_type'),
                                'entity_id': e.get('entity_id'),
                                'created_at': e.get('created_at'),
                            }
                            for e in events
                        ],
                        'total': len(events),
                    }
                return {'error': f'API error: {resp.status}'}
        
        elif action == 'log_call':
            if not entity_id:
                return {'error': 'entity_id is required'}
            
            # Log call as a note with call type
            import time
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/notes'
            note_type = 'call_in' if direction == 'inbound' else 'call_out'
            payload = [{
                'note_type': note_type,
                'params': {
                    'uniq': str(int(time.time())),
                    'duration': duration,
                    'source': 'telegram_bot',
                    'phone': phone or '',
                },
                'text': result,
            }]
            
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])
                    if notes:
                        return {
                            'success': True,
                            'note_id': notes[0].get('id'),
                            'entity_id': entity_id,
                            'direction': direction,
                            'duration': duration,
                        }
                error = await resp.text()
                return {'error': f'Failed to log call: {error[:200]}'}
        
        elif action == 'stats':
            import time
            # Get call events for stats
            url = f'{self.kommo_base_url}/api/v4/events'
            since = int(time.time()) - (days * 86400)
            params = {
                'limit': 250,
                'filter[type]': 'outgoing_call,incoming_call',
                'filter[created_at][from]': since,
            }
            
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    
                    incoming = sum(1 for e in events if 'incoming' in e.get('type', ''))
                    outgoing = sum(1 for e in events if 'outgoing' in e.get('type', ''))
                    
                    return {
                        'period_days': days,
                        'total_calls': len(events),
                        'incoming': incoming,
                        'outgoing': outgoing,
                    }
                return {'error': f'API error: {resp.status}'}
        
        return {'error': f'Unknown calls action: {action}'}
    
    async def _handle_cleanup(self, session, headers, args: dict) -> dict:
        """Handle kommo_cleanup tool calls - delete data and reset CRM.
        
        Smart deletion: first unlinks all relationships, then deletes entities.
        """
        action = args.get('action')
        confirm = args.get('confirm', False)
        pipeline_id = args.get('pipeline_id')
        
        async def get_all_entities(entity_type: str, filter_pipeline_id: int = None) -> list:
            """Get all entities with their data for deletion.
            
            Args:
                entity_type: 'leads', 'contacts', or 'companies'
                filter_pipeline_id: If set, only return leads from this pipeline
            """
            entities = []
            page = 1
            while True:
                url = f'{self.kommo_base_url}/api/v4/{entity_type}'
                params = {'limit': 250, 'page': page, 'with': 'contacts,companies,leads'}
                if filter_pipeline_id and entity_type == 'leads':
                    params['filter[pipeline_id]'] = filter_pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    items = data.get('_embedded', {}).get(entity_type, [])
                    if not items:
                        break
                    entities.extend(items)
                    page += 1
                    if len(items) < 250:
                        break
            return entities
        
        async def get_entity_links(entity_type: str, entity_id: int) -> list:
            """Get all links for an entity."""
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/links'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('_embedded', {}).get('links', [])
            return []
        
        async def unlink_entity(entity_type: str, entity_id: int, links: list) -> int:
            """Remove all links from an entity."""
            if not links:
                return 0
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/unlink'
            unlinked = 0
            for link in links:
                payload = [{
                    'to_entity_type': link.get('to_entity_type'),
                    'to_entity_id': link.get('to_entity_id'),
                }]
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status in [200, 204]:
                        unlinked += 1
            return unlinked
        
        async def delete_entity(entity_type: str, entity_id: int) -> bool:
            """Delete a single entity. For leads, move to 'lost' status since DELETE is not supported."""
            if entity_type == 'leads':
                # Kommo doesn't support DELETE for leads, use PATCH to move to lost status (143)
                url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
                payload = {'status_id': 143}  # 143 = Closed and not realized (lost)
                async with session.patch(url, headers=headers, json=payload) as resp:
                    return resp.status in [200, 204]
            else:
                url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}'
                async with session.delete(url, headers=headers) as resp:
                    return resp.status in [200, 204]
        
        async def smart_delete_all(entity_type: str, entities: list) -> dict:
            """Smart delete: unlink first, then delete, retry failed ones."""
            total = len(entities)
            unlinked_total = 0
            deleted = 0
            failed_ids = []
            
            # Phase 1: Unlink all entities
            for entity in entities:
                entity_id = entity['id']
                links = await get_entity_links(entity_type, entity_id)
                if links:
                    unlinked_total += await unlink_entity(entity_type, entity_id, links)
            
            # Phase 2: Delete all entities
            for entity in entities:
                entity_id = entity['id']
                if await delete_entity(entity_type, entity_id):
                    deleted += 1
                else:
                    failed_ids.append(entity_id)
            
            # Phase 3: Retry failed deletions (links might be cleared now)
            if failed_ids:
                retry_deleted = 0
                still_failed = []
                for entity_id in failed_ids:
                    # Try to unlink again
                    links = await get_entity_links(entity_type, entity_id)
                    if links:
                        await unlink_entity(entity_type, entity_id, links)
                    # Try delete again
                    if await delete_entity(entity_type, entity_id):
                        retry_deleted += 1
                    else:
                        still_failed.append(entity_id)
                deleted += retry_deleted
                failed_ids = still_failed
            
            return {
                'found': total,
                'unlinked': unlinked_total,
                'deleted': deleted,
                'errors': len(failed_ids),
                'failed_ids': failed_ids[:10] if failed_ids else [],  # Show first 10
            }
        
        async def get_pipelines() -> list:
            """Get all pipelines."""
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('_embedded', {}).get('pipelines', [])
            return []
        
        async def move_leads_out(pipeline_id: int, target_pipeline_id: int) -> int:
            """Move all leads from pipeline to target pipeline (status 143=lost). Returns count moved."""
            moved = 0
            page = 1
            while True:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id][]': pipeline_id, 'limit': 250, 'page': page}
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    if not leads:
                        break
                    for lead in leads:
                        move_url = f'{self.kommo_base_url}/api/v4/leads/{lead["id"]}'
                        payload = {'pipeline_id': target_pipeline_id, 'status_id': 143}
                        async with session.patch(move_url, headers=headers, json=payload) as mr:
                            if mr.status in [200, 204]:
                                moved += 1
                    page += 1
                    if len(leads) < 250:
                        break
            return moved
        
        async def delete_pipeline_safe(pipeline_id: int, main_pipeline_id: int) -> dict:
            """Safely delete a pipeline by moving leads out first."""
            moved = await move_leads_out(pipeline_id, main_pipeline_id)
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}'
            async with session.delete(url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    return {'success': True, 'pipeline_id': pipeline_id, 'leads_moved': moved}
                error = await resp.text()
                return {'error': f'Failed to delete pipeline {pipeline_id}: {error[:200]}', 'leads_moved': moved}
        
        async def get_all_custom_fields() -> dict:
            """Get all custom fields grouped by entity type."""
            all_fields = {}
            for et in ['leads', 'contacts', 'companies']:
                url = f'{self.kommo_base_url}/api/v4/{et}/custom_fields'
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        all_fields[et] = data.get('_embedded', {}).get('custom_fields', [])
                    else:
                        all_fields[et] = []
            return all_fields
        
        async def delete_all_custom_fields() -> dict:
            """Delete all custom fields for leads, contacts, companies.
            Skips system fields (tracking_data, Phone, Email, etc.) that cannot be deleted."""
            SYSTEM_FIELD_TYPES = {'tracking_data'}
            SYSTEM_FIELD_CODES = {'PHONE', 'EMAIL', 'IM', 'POSITION', 'WEB', 'ADDRESS'}
            all_fields = await get_all_custom_fields()
            results = {}
            for et, fields in all_fields.items():
                deleted = 0
                deleted_names = []
                skipped_system = []
                failed = []
                for f in fields:
                    fid = f.get('id')
                    fname = f.get('name')
                    ftype = f.get('type')
                    code = f.get('code', '')
                    if ftype in SYSTEM_FIELD_TYPES or code in SYSTEM_FIELD_CODES:
                        skipped_system.append({'id': fid, 'name': fname, 'type': ftype})
                        continue
                    del_url = f'{self.kommo_base_url}/api/v4/{et}/custom_fields/{fid}'
                    async with session.delete(del_url, headers=headers) as resp:
                        if resp.status in [200, 204]:
                            deleted += 1
                            deleted_names.append(fname)
                        else:
                            failed.append({'id': fid, 'name': fname})
                results[et] = {
                    'total': len(fields),
                    'deleted': deleted,
                    'deleted_names': deleted_names,
                    'skipped_system': len(skipped_system),
                    'failed': failed,
                }
            return results
        
        if action == 'preview':
            leads = await get_all_entities('leads')
            contacts = await get_all_entities('contacts')
            companies = await get_all_entities('companies')
            pipelines = await get_pipelines()
            custom_fields = await get_all_custom_fields()
            fields_count = {et: len(fs) for et, fs in custom_fields.items()}
            fields_list = {et: [{'id': f.get('id'), 'name': f.get('name'), 'type': f.get('type')} for f in fs] for et, fs in custom_fields.items()}
            
            return {
                'preview': True,
                'leads_count': len(leads),
                'contacts_count': len(contacts),
                'companies_count': len(companies),
                'pipelines_count': len(pipelines),
                'pipelines': [{'id': p['id'], 'name': p['name']} for p in pipelines],
                'custom_fields_count': fields_count,
                'custom_fields': fields_list,
                'warning': 'Use confirm=true to execute deletion',
            }
        
        if not confirm:
            return {
                'error': 'Destructive action requires confirm=true',
                'action': action,
                'hint': 'Set confirm=true to proceed with deletion',
            }
        
        if action == 'delete_leads':
            entities = await get_all_entities('leads', filter_pipeline_id=pipeline_id)
            result = await smart_delete_all('leads', entities)
            if pipeline_id:
                return {'action': 'delete_leads', 'pipeline_id': pipeline_id, **result}
            return {'action': 'delete_leads', **result}
        
        elif action == 'delete_contacts':
            entities = await get_all_entities('contacts')
            result = await smart_delete_all('contacts', entities)
            return {'action': 'delete_contacts', **result}
        
        elif action == 'delete_companies':
            entities = await get_all_entities('companies')
            result = await smart_delete_all('companies', entities)
            return {'action': 'delete_companies', **result}
        
        elif action == 'delete_all':
            results = {}
            
            # Order matters: leads -> contacts -> companies
            # Each step unlinks and deletes
            
            # 1. Delete leads (they link to contacts/companies)
            leads = await get_all_entities('leads')
            results['leads'] = await smart_delete_all('leads', leads)
            
            # 2. Delete contacts (may link to companies)
            contacts = await get_all_entities('contacts')
            results['contacts'] = await smart_delete_all('contacts', contacts)
            
            # 3. Delete companies
            companies = await get_all_entities('companies')
            results['companies'] = await smart_delete_all('companies', companies)
            
            return {'action': 'delete_all', **results}
        
        elif action == 'delete_fields':
            # Delete all custom fields across leads, contacts, companies
            results = await delete_all_custom_fields()
            total_deleted = sum(r.get('deleted', 0) for r in results.values())
            total_found = sum(r.get('found', 0) for r in results.values())
            return {
                'action': 'delete_fields',
                'total_found': total_found,
                'total_deleted': total_deleted,
                'details': results,
            }
        
        elif action == 'reset_pipelines':
            pipelines = await get_pipelines()
            main_pipeline_id = None
            for p in pipelines:
                if p.get('is_main'):
                    main_pipeline_id = p['id']
                    break
            if not main_pipeline_id and pipelines:
                main_pipeline_id = pipelines[0]['id']
            
            deleted_pipelines = 0
            total_leads_moved = 0
            pipeline_results = []
            
            for pipeline in pipelines:
                if pipeline['id'] == main_pipeline_id:
                    continue
                result = await delete_pipeline_safe(pipeline['id'], main_pipeline_id)
                pipeline_results.append(result)
                if result.get('success'):
                    deleted_pipelines += 1
                total_leads_moved += result.get('leads_moved', 0)
            
            return {
                'action': 'reset_pipelines',
                'pipelines_found': len(pipelines),
                'pipelines_deleted': deleted_pipelines,
                'leads_moved': total_leads_moved,
                'details': pipeline_results,
                'note': 'Main pipeline preserved, leads moved to main pipeline before deletion',
            }
        
        elif action == 'full_reset':
            results = {}
            
            # 1. Get main pipeline for moving leads
            pipelines = await get_pipelines()
            main_pipeline_id = None
            for p in pipelines:
                if p.get('is_main'):
                    main_pipeline_id = p['id']
                    break
            if not main_pipeline_id and pipelines:
                main_pipeline_id = pipelines[0]['id']
            
            # 2. Move all leads from non-main pipelines to main, then delete pipelines
            deleted_pipelines = 0
            total_leads_moved = 0
            for pipeline in pipelines:
                if pipeline['id'] == main_pipeline_id:
                    continue
                result = await delete_pipeline_safe(pipeline['id'], main_pipeline_id)
                if result.get('success'):
                    deleted_pipelines += 1
                total_leads_moved += result.get('leads_moved', 0)
            
            results['pipelines'] = {
                'found': len(pipelines),
                'deleted': deleted_pipelines,
                'leads_moved': total_leads_moved,
            }
            
            # 3. Smart delete all remaining leads (in main pipeline)
            leads = await get_all_entities('leads')
            results['leads'] = await smart_delete_all('leads', leads)
            
            # 4. Smart delete contacts
            contacts = await get_all_entities('contacts')
            results['contacts'] = await smart_delete_all('contacts', contacts)
            
            # 5. Smart delete companies
            companies = await get_all_entities('companies')
            results['companies'] = await smart_delete_all('companies', companies)
            
            # 6. Delete all custom fields
            results['custom_fields'] = await delete_all_custom_fields()
            
            return {'action': 'full_reset', 'success': True, **results}
        
        return {'error': f'Unknown cleanup action: {action}'}

    async def _handle_export(self, session, headers, args: dict) -> dict:
        """Export CRM data as CSV-formatted text."""
        import time
        action = args.get('action')
        limit = min(args.get('limit', 100), 500)
        pipeline_id = args.get('pipeline_id')

        if action == 'leads_csv':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': limit, 'with': 'contacts'}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id

            all_leads = []
            page = 1
            while len(all_leads) < limit:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    if not leads:
                        break
                    all_leads.extend(leads)
                    page += 1
                    if len(leads) < 250:
                        break

            all_leads = all_leads[:limit]
            csv_lines = ['ID;Название;Бюджет;Статус;Воронка;Ответственный;Создано']
            for lead in all_leads:
                created = time.strftime('%Y-%m-%d', time.localtime(lead.get('created_at', 0)))
                csv_lines.append(f'{lead.get("id")};{lead.get("name", "")};{lead.get("price", 0)};{lead.get("status_id", "")};{lead.get("pipeline_id", "")};{lead.get("responsible_user_id", "")};{created}')

            return {
                'format': 'csv',
                'rows': len(all_leads),
                'csv_data': '\n'.join(csv_lines),
                'hint': 'Present this data as a formatted table to the user',
            }

        elif action == 'contacts_csv':
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'limit': limit}

            all_contacts = []
            page = 1
            while len(all_contacts) < limit:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    contacts = data.get('_embedded', {}).get('contacts', [])
                    if not contacts:
                        break
                    all_contacts.extend(contacts)
                    page += 1
                    if len(contacts) < 250:
                        break

            all_contacts = all_contacts[:limit]
            csv_lines = ['ID;Имя;Телефон;Email;Ответственный;Создано']
            for c in all_contacts:
                created = time.strftime('%Y-%m-%d', time.localtime(c.get('created_at', 0)))
                phone = ''
                email = ''
                for cf in c.get('custom_fields_values', []) or []:
                    code = cf.get('field_code', '')
                    vals = cf.get('values', [])
                    if code == 'PHONE' and vals:
                        phone = vals[0].get('value', '')
                    elif code == 'EMAIL' and vals:
                        email = vals[0].get('value', '')
                name = c.get('name', '')
                csv_lines.append(f'{c.get("id")};{name};{phone};{email};{c.get("responsible_user_id", "")};{created}')

            return {
                'format': 'csv',
                'rows': len(all_contacts),
                'csv_data': '\n'.join(csv_lines),
                'hint': 'Present this data as a formatted table to the user',
            }

        elif action == 'analytics':
            # Collect summary analytics across all pipelines
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Failed to get pipelines: {resp.status}'}
                pipelines_data = await resp.json()
                pipelines = pipelines_data.get('_embedded', {}).get('pipelines', [])

            summary = []
            grand_total_deals = 0
            grand_total_revenue = 0

            for p in pipelines:
                p_id = p.get('id')
                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': p_id, 'limit': 250}
                async with session.get(leads_url, headers=headers, params=params) as resp:
                    leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])

                total_deals = len(leads)
                total_revenue = sum((l.get('price', 0) or 0) for l in leads)
                grand_total_deals += total_deals
                grand_total_revenue += total_revenue

                summary.append({
                    'pipeline': p.get('name'),
                    'deals': total_deals,
                    'revenue': total_revenue,
                    'avg_check': round(total_revenue / total_deals) if total_deals else 0,
                })

            return {
                'pipelines': summary,
                'totals': {
                    'deals': grand_total_deals,
                    'revenue': grand_total_revenue,
                    'avg_check': round(grand_total_revenue / grand_total_deals) if grand_total_deals else 0,
                    'pipelines_count': len(pipelines),
                },
            }

        return {'error': f'Unknown export action: {action}'}

    async def _handle_digest(self, session, headers, args: dict) -> dict:
        """Generate CRM digest: morning briefing, weekly summary, personal tasks."""
        import time
        from datetime import datetime, timedelta

        action = args.get('action')
        user_id = args.get('user_id')

        if action == 'morning':
            now = int(time.time())
            today_start = now - (now % 86400)

            # 1. Active deals count
            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(leads_url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])

            active_deals = len(leads)
            total_revenue = sum((l.get('price', 0) or 0) for l in leads)
            new_today = sum(1 for l in leads if (l.get('created_at', 0) or 0) >= today_start)

            # 2. Overdue tasks
            tasks_url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'filter[is_completed]': 0, 'limit': 250}
            async with session.get(tasks_url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])

            overdue_tasks = [t for t in tasks if (t.get('complete_till', 0) or 0) < now and not t.get('is_completed')]
            today_tasks = [t for t in tasks if today_start <= (t.get('complete_till', 0) or 0) < today_start + 86400]

            # 3. Stale deals (no activity > 7 days)
            stale_threshold = now - 7 * 86400
            stale_deals = [l for l in leads if (l.get('updated_at', 0) or 0) < stale_threshold]

            return {
                'digest_type': 'morning',
                'date': datetime.now().strftime('%d.%m.%Y'),
                'active_deals': active_deals,
                'total_pipeline_value': total_revenue,
                'new_deals_today': new_today,
                'tasks_today': len(today_tasks),
                'overdue_tasks': len(overdue_tasks),
                'stale_deals': len(stale_deals),
                'hint': 'Format this as a morning briefing for the user. Use emoji and clear structure.',
            }

        elif action == 'weekly':
            now = int(time.time())
            week_ago = now - 7 * 86400

            # Deals created this week
            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'filter[created_at][from]': week_ago}
            async with session.get(leads_url, headers=headers, params=params) as resp:
                new_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    new_leads = data.get('_embedded', {}).get('leads', [])

            # Won deals (status 142)
            params_won = {'limit': 250, 'filter[statuses][0][status_id]': 142}
            async with session.get(leads_url, headers=headers, params=params_won) as resp:
                won_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])

            won_this_week = [l for l in won_leads if (l.get('closed_at', 0) or 0) >= week_ago]
            won_revenue = sum((l.get('price', 0) or 0) for l in won_this_week)

            # Lost deals (status 143)
            params_lost = {'limit': 250, 'filter[statuses][0][status_id]': 143}
            async with session.get(leads_url, headers=headers, params=params_lost) as resp:
                lost_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    lost_leads = data.get('_embedded', {}).get('leads', [])

            lost_this_week = [l for l in lost_leads if (l.get('closed_at', 0) or 0) >= week_ago]

            # Completed tasks
            tasks_url = f'{self.kommo_base_url}/api/v4/tasks'
            params_tasks = {'filter[is_completed]': 1, 'limit': 250}
            async with session.get(tasks_url, headers=headers, params=params_tasks) as resp:
                completed_tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    completed_tasks = data.get('_embedded', {}).get('tasks', [])

            return {
                'digest_type': 'weekly',
                'period': f'{datetime.fromtimestamp(week_ago).strftime("%d.%m")} - {datetime.now().strftime("%d.%m.%Y")}',
                'new_deals': len(new_leads),
                'new_deals_value': sum((l.get('price', 0) or 0) for l in new_leads),
                'won_deals': len(won_this_week),
                'won_revenue': won_revenue,
                'lost_deals': len(lost_this_week),
                'tasks_completed': len(completed_tasks),
                'conversion': f'{round(len(won_this_week) / max(len(new_leads), 1) * 100)}%',
                'hint': 'Format this as a weekly summary report. Use emoji and clear structure.',
            }

        elif action == 'my_tasks':
            now = int(time.time())
            today_end = now - (now % 86400) + 86400

            tasks_url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'filter[is_completed]': 0, 'limit': 100}
            if user_id:
                params['filter[responsible_user_id]'] = user_id

            async with session.get(tasks_url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])

            overdue = []
            today = []
            upcoming = []
            for t in tasks:
                deadline = t.get('complete_till', 0) or 0
                task_info = {
                    'id': t.get('id'),
                    'text': t.get('text', '')[:80],
                    'type': t.get('task_type_id'),
                    'deadline': time.strftime('%d.%m %H:%M', time.localtime(deadline)) if deadline else 'нет',
                    'entity_id': t.get('entity_id'),
                    'entity_type': t.get('entity_type'),
                }
                if deadline < now:
                    overdue.append(task_info)
                elif deadline < today_end:
                    today.append(task_info)
                else:
                    upcoming.append(task_info)

            return {
                'digest_type': 'my_tasks',
                'overdue': overdue,
                'today': today,
                'upcoming': upcoming[:10],
                'total_pending': len(tasks),
                'hint': 'Format as a task list grouped by urgency. Overdue first (with warning), then today, then upcoming.',
            }

        return {'error': f'Unknown digest action: {action}'}

    async def _handle_advisor(self, session, headers, args: dict) -> dict:
        """AI-powered CRM advisor: recommendations based on actual CRM data."""
        import time
        action = args.get('action')
        lead_id = args.get('lead_id')
        pipeline_id = args.get('pipeline_id')

        if action == 'next_action':
            if not lead_id:
                return {'error': 'lead_id is required for next_action advice'}

            url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            params = {'with': 'contacts,catalog_elements'}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return {'error': f'Lead not found: {resp.status}'}
                lead = await resp.json()

            # Get tasks for this lead
            tasks_url = f'{self.kommo_base_url}/api/v4/tasks'
            tasks_params = {'filter[entity_id]': lead_id, 'filter[entity_type]': 'leads', 'filter[is_completed]': 0}
            async with session.get(tasks_url, headers=headers, params=tasks_params) as resp:
                pending_tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    pending_tasks = data.get('_embedded', {}).get('tasks', [])

            # Get notes/history
            notes_url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(notes_url, headers=headers, params={'limit': 10}) as resp:
                notes = []
                if resp.status == 200:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])

            now = int(time.time())
            days_since_update = (now - (lead.get('updated_at', now) or now)) // 86400
            days_since_creation = (now - (lead.get('created_at', now) or now)) // 86400
            price = lead.get('price', 0) or 0
            has_contacts = bool(lead.get('_embedded', {}).get('contacts'))

            return {
                'lead': {
                    'name': lead.get('name'),
                    'price': price,
                    'status_id': lead.get('status_id'),
                    'pipeline_id': lead.get('pipeline_id'),
                    'days_in_pipeline': days_since_creation,
                    'days_since_update': days_since_update,
                    'has_contacts': has_contacts,
                    'pending_tasks': len(pending_tasks),
                    'notes_count': len(notes),
                },
                'analysis': {
                    'is_stale': days_since_update > 7,
                    'no_tasks': len(pending_tasks) == 0,
                    'no_contacts': not has_contacts,
                    'no_price': price == 0,
                    'long_cycle': days_since_creation > 30,
                },
                'hint': 'Based on this data, provide specific actionable recommendations: what to do next with this deal, what risks exist, and what actions to take. Be specific and practical.',
            }

        elif action == 'pipeline_tips':
            # Analyze pipeline health and give recommendations
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Failed to get pipelines: {resp.status}'}
                pipelines_data = await resp.json()
                pipelines = pipelines_data.get('_embedded', {}).get('pipelines', [])

            if pipeline_id:
                pipelines = [p for p in pipelines if p.get('id') == pipeline_id]

            now = int(time.time())
            results = []

            for p in pipelines:
                p_id = p.get('id')
                statuses = p.get('_embedded', {}).get('statuses', [])

                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': p_id, 'limit': 250}
                async with session.get(leads_url, headers=headers, params=params) as resp:
                    leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])

                stage_counts = {}
                stale_by_stage = {}
                revenue_by_stage = {}
                for lead in leads:
                    sid = lead.get('status_id')
                    stage_counts[sid] = stage_counts.get(sid, 0) + 1
                    revenue_by_stage[sid] = revenue_by_stage.get(sid, 0) + (lead.get('price', 0) or 0)
                    if (now - (lead.get('updated_at', now) or now)) > 7 * 86400:
                        stale_by_stage[sid] = stale_by_stage.get(sid, 0) + 1

                stages_analysis = []
                for s in statuses:
                    sid = s.get('id')
                    if sid in [142, 143]:
                        continue
                    count = stage_counts.get(sid, 0)
                    stale = stale_by_stage.get(sid, 0)
                    stages_analysis.append({
                        'name': s.get('name'),
                        'deals': count,
                        'stale': stale,
                        'stale_pct': f'{round(stale / max(count, 1) * 100)}%',
                        'revenue': revenue_by_stage.get(sid, 0),
                    })

                bottleneck = max(stages_analysis, key=lambda x: x['deals']) if stages_analysis else None

                results.append({
                    'pipeline': p.get('name'),
                    'total_deals': len(leads),
                    'total_revenue': sum((l.get('price', 0) or 0) for l in leads),
                    'stages': stages_analysis,
                    'bottleneck': bottleneck['name'] if bottleneck else None,
                })

            return {
                'pipelines': results,
                'hint': 'Analyze this pipeline data and provide specific recommendations: where are bottlenecks, which stages have too many stale deals, what can be improved. Be actionable.',
            }

        elif action == 'loss_analysis':
            # Analyze lost deals
            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[statuses][0][status_id]': 143, 'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id

            async with session.get(leads_url, headers=headers, params=params) as resp:
                lost_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    lost_leads = data.get('_embedded', {}).get('leads', [])

            now = int(time.time())
            total_lost = len(lost_leads)
            total_lost_value = sum((l.get('price', 0) or 0) for l in lost_leads)

            # Analyze by pipeline
            by_pipeline = {}
            cycle_times = []
            for l in lost_leads:
                pid = l.get('pipeline_id')
                by_pipeline[pid] = by_pipeline.get(pid, 0) + 1
                created = l.get('created_at', 0) or 0
                closed = l.get('closed_at', 0) or 0
                if created and closed:
                    cycle_times.append((closed - created) // 86400)

            avg_cycle = round(sum(cycle_times) / max(len(cycle_times), 1)) if cycle_times else 0

            # Recent losses (last 30 days)
            month_ago = now - 30 * 86400
            recent_losses = [l for l in lost_leads if (l.get('closed_at', 0) or 0) >= month_ago]

            return {
                'total_lost': total_lost,
                'total_lost_value': total_lost_value,
                'recent_losses_30d': len(recent_losses),
                'recent_lost_value': sum((l.get('price', 0) or 0) for l in recent_losses),
                'avg_cycle_days': avg_cycle,
                'by_pipeline': by_pipeline,
                'hint': 'Analyze loss patterns and provide insights: why deals are being lost, what patterns exist, and specific recommendations to reduce losses.',
            }

        elif action == 'closing_tips':
            if not lead_id:
                return {'error': 'lead_id is required for closing_tips'}

            url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            params = {'with': 'contacts'}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return {'error': f'Lead not found: {resp.status}'}
                lead = await resp.json()

            now = int(time.time())
            price = lead.get('price', 0) or 0
            days_in_pipeline = (now - (lead.get('created_at', now) or now)) // 86400
            has_contacts = bool(lead.get('_embedded', {}).get('contacts'))

            return {
                'lead': {
                    'name': lead.get('name'),
                    'price': price,
                    'days_in_pipeline': days_in_pipeline,
                    'has_contacts': has_contacts,
                    'status_id': lead.get('status_id'),
                },
                'hint': 'Based on this deal data, provide specific closing tips: what objections to expect at this price point, how to accelerate the decision, what closing techniques to use. Be practical and specific to this deal.',
            }

        elif action == 'objections':
            # Get pipeline context for objection handling
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                pipelines = []
                if resp.status == 200:
                    data = await resp.json()
                    pipelines = data.get('_embedded', {}).get('pipelines', [])

            pipeline_names = [p.get('name', '') for p in pipelines]

            # Get lost deals for pattern analysis
            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[statuses][0][status_id]': 143, 'limit': 50}
            async with session.get(leads_url, headers=headers, params=params) as resp:
                lost_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    lost_leads = data.get('_embedded', {}).get('leads', [])

            # Get notes from lost deals for objection patterns
            loss_reasons = []
            for l in lost_leads[:10]:
                notes_url = f'{self.kommo_base_url}/api/v4/leads/{l["id"]}/notes'
                async with session.get(notes_url, headers=headers, params={'limit': 5}) as resp:
                    if resp.status == 200:
                        ndata = await resp.json()
                        for n in ndata.get('_embedded', {}).get('notes', []):
                            text = n.get('params', {}).get('text', '') if isinstance(n.get('params'), dict) else ''
                            if text:
                                loss_reasons.append(text[:100])

            return {
                'business_context': {
                    'pipelines': pipeline_names,
                    'lost_deals_count': len(lost_leads),
                    'avg_deal_value': round(sum((l.get('price', 0) or 0) for l in lost_leads) / max(len(lost_leads), 1)),
                },
                'loss_notes_sample': loss_reasons[:5],
                'hint': 'Based on this CRM context and loss patterns, generate a practical objection handling guide: top 5-7 common objections for this type of business, with specific response scripts for each. Make it actionable.',
            }

        elif action == 'next_best':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'with': 'contacts'}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            now_ts = int(time.time())

            scored = []
            for lead in active:
                score = 0
                reasons = []
                price = lead.get('price', 0) or 0
                last_activity = (now_ts - (lead.get('updated_at') or now_ts)) / 86400
                age = (now_ts - lead.get('created_at', now_ts)) / 86400
                has_contacts = bool(lead.get('_embedded', {}).get('contacts'))

                if price > 100000:
                    score += 30
                    reasons.append('High value deal')
                elif price > 50000:
                    score += 20
                    reasons.append('Medium-high value')

                if 3 < last_activity < 14:
                    score += 25
                    reasons.append(f'Needs follow-up ({last_activity:.0f}d inactive)')
                elif last_activity >= 14:
                    score += 15
                    reasons.append(f'At risk — {last_activity:.0f}d without activity')

                if age < 7:
                    score += 20
                    reasons.append('Fresh deal — momentum matters')
                elif age < 14:
                    score += 10

                if has_contacts:
                    score += 5

                scored.append({
                    'lead_id': lead.get('id'),
                    'name': lead.get('name'),
                    'price': price,
                    'priority_score': score,
                    'reasons': reasons,
                    'suggested_action': 'Call/follow-up' if last_activity > 3 else ('Advance to next stage' if age > 3 else 'Qualify and set price'),
                })

            scored.sort(key=lambda x: x['priority_score'], reverse=True)
            return {
                'next_best_actions': scored[:10],
                'total_active': len(active),
                'hint': 'Present as prioritized action list. For each deal, explain WHY it should be the next focus and WHAT specific action to take.',
            }

        elif action == 'funnel_optimize':
            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                pipelines = []
                if resp.status == 200:
                    pdata = await resp.json()
                    pipelines = pdata.get('_embedded', {}).get('pipelines', [])
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if args.get('pipeline_id'):
                params['filter[pipeline_id]'] = args['pipeline_id']
            all_leads = []
            page = 1
            while page <= 4:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])
                        all_leads.extend(leads)
                        if len(leads) < 250:
                            break
                        page += 1
                    else:
                        break
            now = int(time.time())
            recommendations = []
            for p in pipelines:
                if args.get('pipeline_id') and p.get('id') != args['pipeline_id']:
                    continue
                statuses = [s for s in p.get('_embedded', {}).get('statuses', []) if s.get('id') not in (142, 143)]
                p_leads = [l for l in all_leads if l.get('pipeline_id') == p.get('id')]
                active = [l for l in p_leads if l.get('status_id') not in (142, 143)]
                won = [l for l in p_leads if l.get('status_id') == 142]
                lost = [l for l in p_leads if l.get('status_id') == 143]
                stage_analysis = []
                prev_count = len(active) + len(won) + len(lost)
                for s in statuses:
                    s_leads = [l for l in active if l.get('status_id') == s.get('id')]
                    avg_time = 0
                    if s_leads:
                        avg_time = sum((now - l.get('created_at', now)) / 86400 for l in s_leads) / len(s_leads)
                    drop_rate = 1 - (len(s_leads) / max(prev_count, 1)) if prev_count > 0 else 0
                    tips = []
                    if avg_time > 14:
                        tips.append(f'Deals stay too long ({avg_time:.0f}d avg). Add automation or split stage.')
                    if drop_rate > 0.5:
                        tips.append(f'High drop-off ({drop_rate:.0%}). Review qualification criteria.')
                    if len(s_leads) == 0:
                        tips.append('Empty stage. Consider removing or merging with adjacent.')
                    stage_analysis.append({'stage': s.get('name'), 'deals': len(s_leads), 'avg_days': round(avg_time), 'drop_rate': f'{drop_rate:.0%}', 'tips': tips})
                    prev_count = len(s_leads)
                win_rate = len(won) / max(len(won) + len(lost), 1)
                recommendations.append({
                    'pipeline': p.get('name'),
                    'stages': len(statuses),
                    'win_rate': f'{win_rate:.0%}',
                    'stage_analysis': stage_analysis,
                    'overall_tips': [
                        f'Win rate {win_rate:.0%}' + (' — needs improvement' if win_rate < 0.25 else ' — good' if win_rate < 0.5 else ' — excellent'),
                        f'{len(statuses)} stages' + (' — consider consolidating' if len(statuses) > 7 else ''),
                    ],
                })
            return {
                'recommendations': recommendations,
                'hint': 'Present funnel optimization tips per pipeline. Focus on stages with high drop-off and long dwell time. Suggest specific actions.',
            }

        elif action == 'strategy':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            won = [l for l in all_leads if l.get('status_id') == 142]
            lost = [l for l in all_leads if l.get('status_id') == 143]
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            revenue = sum(l.get('price', 0) or 0 for l in won)
            pipeline_value = sum(l.get('price', 0) or 0 for l in active)
            win_rate = len(won) / max(len(won) + len(lost), 1)
            avg_deal = revenue / max(len(won), 1)
            stale = [l for l in active if (now - (l.get('updated_at') or now)) / 86400 > 14]
            recommendations = []
            if win_rate < 0.2:
                recommendations.append({'area': 'Qualification', 'priority': 'high', 'action': 'Improve lead qualification — current win rate is low. Focus on quality over quantity.'})
            if len(stale) > len(active) * 0.3:
                recommendations.append({'area': 'Pipeline hygiene', 'priority': 'high', 'action': f'{len(stale)} stale deals need attention. Set up regular pipeline review cadence.'})
            if avg_deal < 30000:
                recommendations.append({'area': 'Deal size', 'priority': 'medium', 'action': f'Average deal {avg_deal:.0f}₽ is low. Consider upselling or targeting larger accounts.'})
            if pipeline_value < revenue * 3:
                recommendations.append({'area': 'Pipeline coverage', 'priority': 'high', 'action': 'Pipeline coverage is below 3x. Increase lead generation to ensure target achievement.'})
            else:
                recommendations.append({'area': 'Pipeline coverage', 'priority': 'low', 'action': f'Good pipeline coverage: {pipeline_value/max(revenue,1):.1f}x revenue.'})
            if win_rate > 0.4:
                recommendations.append({'area': 'Growth', 'priority': 'medium', 'action': 'Strong win rate — consider increasing volume or expanding to new segments.'})
            recommendations.append({'area': 'Process', 'priority': 'medium', 'action': 'Implement weekly pipeline reviews and deal coaching sessions.'})
            return {
                'strategy': {
                    'current_state': {
                        'revenue': revenue, 'pipeline_value': pipeline_value,
                        'win_rate': f'{win_rate:.0%}', 'avg_deal': round(avg_deal),
                        'active_deals': len(active), 'stale_deals': len(stale),
                    },
                    'recommendations': recommendations,
                    'growth_levers': [
                        'Increase lead volume' if pipeline_value < revenue * 3 else 'Optimize conversion',
                        'Improve deal qualification' if win_rate < 0.3 else 'Scale winning formula',
                        'Increase average deal size' if avg_deal < 50000 else 'Maintain premium positioning',
                    ],
                },
                'hint': 'Present as strategic recommendations. Prioritize high-priority items. Suggest specific next steps for each recommendation.',
            }

        elif action == 'qualification':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for qualification advice'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 20}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            price = lead.get('price', 0) or 0
            contacts = lead.get('_embedded', {}).get('contacts', [])
            has_notes = len(notes) > 0
            score = 0
            factors = []
            if price > 0:
                score += 25
                factors.append({'factor': 'Budget identified', 'status': 'yes', 'weight': 25})
            else:
                factors.append({'factor': 'Budget identified', 'status': 'no', 'weight': 0, 'action': 'Ask about budget range'})
            if contacts:
                score += 25
                factors.append({'factor': 'Decision maker identified', 'status': 'yes', 'weight': 25})
            else:
                factors.append({'factor': 'Decision maker identified', 'status': 'no', 'weight': 0, 'action': 'Identify key stakeholders'})
            if has_notes:
                score += 25
                factors.append({'factor': 'Need confirmed', 'status': 'yes', 'weight': 25})
            else:
                factors.append({'factor': 'Need confirmed', 'status': 'no', 'weight': 0, 'action': 'Conduct discovery call'})
            age = (now - lead.get('created_at', now)) / 86400
            if age < 30:
                score += 25
                factors.append({'factor': 'Timeline active', 'status': 'yes', 'weight': 25})
            else:
                factors.append({'factor': 'Timeline active', 'status': 'no', 'weight': 0, 'action': 'Re-engage — deal is aging'})
            verdict = 'Qualified' if score >= 75 else ('Promising' if score >= 50 else ('Needs work' if score >= 25 else 'Not qualified'))
            return {
                'qualification': {
                    'lead': lead.get('name'), 'score': score, 'verdict': verdict,
                    'factors': factors,
                    'next_steps': [f['action'] for f in factors if f.get('action')],
                },
                'hint': 'Present BANT qualification analysis. Show score and missing factors. Suggest specific actions to qualify the deal.',
            }

        elif action == 'qualification_checklist':
            return {
                'checklist': {
                    'bant': [
                        {'item': 'Budget', 'questions': ['What is your budget range?', 'Is budget approved?', 'Who controls the budget?']},
                        {'item': 'Authority', 'questions': ['Who makes the final decision?', 'Who else is involved?', 'What is the approval process?']},
                        {'item': 'Need', 'questions': ['What problem are you solving?', 'What happens if you do nothing?', 'What have you tried before?']},
                        {'item': 'Timeline', 'questions': ['When do you need this by?', 'What is driving the timeline?', 'Are there any deadlines?']},
                    ],
                    'red_flags': [
                        'No clear budget or "we will figure it out later"',
                        'Cannot identify decision maker',
                        'No urgency or timeline',
                        'Vague requirements',
                        'Competitor already selected',
                    ],
                    'green_flags': [
                        'Budget approved and allocated',
                        'Direct access to decision maker',
                        'Clear pain point with measurable impact',
                        'Defined timeline with external deadline',
                        'Previous vendor experience (knows what they want)',
                    ],
                },
                'hint': 'Present as interactive checklist. Help user go through each item during qualification call.',
            }

        elif action == 'negotiation':
            lead_id = args.get('lead_id')
            lead_info = {}
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers) as resp:
                    if resp.status == 200:
                        lead_info = await resp.json()
            price = lead_info.get('price', 0) or 0
            tips = [
                {'tip': 'Anchor high', 'detail': 'Start with a higher price point to create room for negotiation', 'priority': 'high'},
                {'tip': 'Focus on value, not price', 'detail': 'Quantify ROI and business impact before discussing price', 'priority': 'high'},
                {'tip': 'Use silence', 'detail': 'After stating your price, wait. Let the client respond first.', 'priority': 'medium'},
                {'tip': 'Bundle, don\'t discount', 'detail': 'Instead of lowering price, add value — extra features, support, training', 'priority': 'high'},
                {'tip': 'Get something for something', 'detail': 'If you give a discount, ask for longer contract, upfront payment, or referral', 'priority': 'medium'},
                {'tip': 'Know your walk-away point', 'detail': f'Set minimum acceptable price before negotiation starts', 'priority': 'high'},
            ]
            if price > 100000:
                tips.append({'tip': 'Multi-stakeholder alignment', 'detail': 'For large deals, ensure all decision makers agree on value before price discussion', 'priority': 'high'})
            if price > 0 and price < 30000:
                tips.append({'tip': 'Efficiency play', 'detail': 'For smaller deals, streamline the process — quick proposals, fast closes', 'priority': 'medium'})
            return {
                'negotiation_tips': tips,
                'deal_context': {'name': lead_info.get('name'), 'price': price} if lead_info else None,
                'hint': 'Present negotiation tips prioritized by importance. If deal context available, customize advice. Help user prepare for negotiation.',
            }

        elif action == 'communication_style':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for communication_style'}
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 30}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            all_text = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
            word_count = len(all_text.split())
            formal_words = sum(1 for w in ['уважаемый', 'добрый день', 'с уважением', 'прошу', 'предоставить', 'рассмотреть'] if w in all_text)
            informal_words = sum(1 for w in ['привет', 'ок', 'круто', 'супер', 'давай', 'норм'] if w in all_text)
            style = 'formal' if formal_words > informal_words else ('informal' if informal_words > formal_words else 'neutral')
            recommendations = []
            if style == 'formal':
                recommendations = [
                    'Use professional tone and complete sentences',
                    'Address by name and patronymic if known',
                    'Provide detailed documentation and specifications',
                    'Schedule formal meetings rather than quick calls',
                ]
            elif style == 'informal':
                recommendations = [
                    'Keep messages short and friendly',
                    'Use first name, casual tone is OK',
                    'Quick voice messages or calls work well',
                    'Share visual content — screenshots, demos',
                ]
            else:
                recommendations = [
                    'Mirror the client\'s communication style',
                    'Start professional, adjust based on response',
                    'Mix formal proposals with friendly follow-ups',
                    'Offer multiple communication channels',
                ]
            return {
                'communication_style': {
                    'detected_style': style,
                    'formal_signals': formal_words, 'informal_signals': informal_words,
                    'word_volume': word_count,
                    'recommendations': recommendations,
                },
                'hint': 'Present detected communication style and recommendations. Help user adapt their approach to match client preferences.',
            }

        elif action == 'product_recommendations':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for product_recommendations'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 20}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            price = lead.get('price', 0) or 0
            all_text = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
            recs = []
            if price > 100000:
                recs.append({'type': 'upsell', 'suggestion': 'Premium package with extended support and SLA', 'reason': 'High-value client — premium positioning justified'})
            if price > 0:
                recs.append({'type': 'cross_sell', 'suggestion': 'Complementary services: training, consulting, implementation', 'reason': 'Active deal — good time to expand scope'})
            if 'обучен' in all_text or 'тренинг' in all_text:
                recs.append({'type': 'addon', 'suggestion': 'Training package', 'reason': 'Client mentioned training needs'})
            if 'поддержк' in all_text or 'сопровожд' in all_text:
                recs.append({'type': 'addon', 'suggestion': 'Extended support contract', 'reason': 'Client interested in ongoing support'})
            if 'интеграц' in all_text or 'подключ' in all_text:
                recs.append({'type': 'addon', 'suggestion': 'Integration services', 'reason': 'Client needs integration work'})
            if not recs:
                recs.append({'type': 'discovery', 'suggestion': 'Conduct needs assessment to identify product fit', 'reason': 'Not enough data for specific recommendations'})
            return {
                'product_recommendations': recs,
                'deal_context': {'name': lead.get('name'), 'price': price},
                'hint': 'Present product recommendations based on deal context. Help user identify upsell/cross-sell opportunities.',
            }

        elif action == 'talking_points':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for talking_points'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 20}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            price = lead.get('price', 0) or 0
            age = (now - lead.get('created_at', now)) / 86400
            all_text = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
            points = []
            points.append({'topic': 'Deal status', 'point': f'Deal "{lead.get("name")}" — {round(age)} days old, price {price}₽', 'priority': 'high'})
            if notes:
                last_note = notes[0]
                last_text = (last_note.get('params', {}).get('text', '') or '')[:100]
                points.append({'topic': 'Last interaction', 'point': f'Last note: {last_text}', 'priority': 'high'})
            if 'цена' in all_text or 'бюджет' in all_text:
                points.append({'topic': 'Pricing discussed', 'point': 'Client has raised pricing — be prepared with value justification', 'priority': 'high'})
            if 'конкурент' in all_text:
                points.append({'topic': 'Competition', 'point': 'Competitor mentioned — prepare differentiation points', 'priority': 'high'})
            if 'срок' in all_text or 'дедлайн' in all_text:
                points.append({'topic': 'Timeline', 'point': 'Client has timeline pressure — use urgency in closing', 'priority': 'medium'})
            if age > 30:
                points.append({'topic': 'Deal aging', 'point': f'Deal is {round(age)} days old — address any blockers directly', 'priority': 'medium'})
            points.append({'topic': 'Next step', 'point': 'Confirm next action and timeline before ending conversation', 'priority': 'medium'})
            return {
                'talking_points': points,
                'deal': lead.get('name'),
                'hint': 'Present talking points before a call or meeting. High-priority items first. Help user stay focused and prepared.',
            }

        return {'error': f'Unknown advisor action: {action}'}

    async def _handle_pipeline_health(self, session, headers, args: dict) -> dict:
        """Deep pipeline health analysis."""
        import time
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        days = args.get('days', 30)
        now = int(time.time())
        period_start = now - days * 86400

        async def get_pipelines():
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get('_embedded', {}).get('pipelines', [])

        async def get_leads(p_id, status_filter=None):
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[pipeline_id]': p_id, 'limit': 250}
            if status_filter:
                params['filter[statuses][0][status_id]'] = status_filter
            all_leads = []
            page = 1
            while True:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    if not leads:
                        break
                    all_leads.extend(leads)
                    page += 1
                    if len(leads) < 250:
                        break
            return all_leads

        pipelines = await get_pipelines()
        if pipeline_id:
            pipelines = [p for p in pipelines if p.get('id') == pipeline_id]
        if not pipelines:
            return {'error': 'No pipelines found'}

        if action == 'check':
            results = []
            for p in pipelines:
                p_id = p.get('id')
                statuses = p.get('_embedded', {}).get('statuses', [])
                leads = await get_leads(p_id)
                active = [l for l in leads if l.get('status_id') not in [142, 143]]
                won = [l for l in leads if l.get('status_id') == 142]
                lost = [l for l in leads if l.get('status_id') == 143]
                stale = [l for l in active if (now - (l.get('updated_at', now) or now)) > 7 * 86400]
                no_tasks_count = 0

                total_value = sum((l.get('price', 0) or 0) for l in active)
                won_value = sum((l.get('price', 0) or 0) for l in won)

                health_score = 100
                if len(active) > 0:
                    stale_pct = len(stale) / len(active) * 100
                    if stale_pct > 50:
                        health_score -= 30
                    elif stale_pct > 25:
                        health_score -= 15
                if len(won) + len(lost) > 0:
                    win_rate = len(won) / (len(won) + len(lost)) * 100
                    if win_rate < 20:
                        health_score -= 25
                    elif win_rate < 40:
                        health_score -= 10
                else:
                    win_rate = 0
                health_score = max(0, health_score)

                results.append({
                    'pipeline': p.get('name'),
                    'health_score': health_score,
                    'active_deals': len(active),
                    'pipeline_value': total_value,
                    'won': len(won),
                    'lost': len(lost),
                    'win_rate': f'{round(win_rate)}%',
                    'stale_deals': len(stale),
                    'stages_count': len([s for s in statuses if s.get('id') not in [142, 143]]),
                })

            return {
                'pipelines': results,
                'hint': 'Present pipeline health as a report card. Score 80+ is healthy, 50-80 needs attention, below 50 is critical. Give specific recommendations.',
            }

        elif action == 'velocity':
            results = []
            for p in pipelines:
                p_id = p.get('id')
                won_leads = await get_leads(p_id, 142)
                recent_won = [l for l in won_leads if (l.get('closed_at', 0) or 0) >= period_start]

                cycle_times = []
                for l in recent_won:
                    created = l.get('created_at', 0) or 0
                    closed = l.get('closed_at', 0) or 0
                    if created and closed and closed > created:
                        cycle_times.append((closed - created) / 86400)

                avg_cycle = round(sum(cycle_times) / max(len(cycle_times), 1), 1) if cycle_times else 0
                median_cycle = sorted(cycle_times)[len(cycle_times) // 2] if cycle_times else 0
                total_won_value = sum((l.get('price', 0) or 0) for l in recent_won)
                velocity = round(total_won_value / max(days, 1))

                results.append({
                    'pipeline': p.get('name'),
                    'deals_won': len(recent_won),
                    'avg_cycle_days': avg_cycle,
                    'median_cycle_days': round(median_cycle, 1),
                    'fastest_deal_days': round(min(cycle_times), 1) if cycle_times else 0,
                    'slowest_deal_days': round(max(cycle_times), 1) if cycle_times else 0,
                    'revenue_won': total_won_value,
                    'daily_velocity': velocity,
                    'period_days': days,
                })

            return {
                'pipelines': results,
                'hint': 'Analyze sales velocity and cycle times. Compare with benchmarks, suggest how to speed up the pipeline.',
            }

        elif action == 'bottlenecks':
            results = []
            for p in pipelines:
                p_id = p.get('id')
                statuses = p.get('_embedded', {}).get('statuses', [])
                leads = await get_leads(p_id)
                active = [l for l in leads if l.get('status_id') not in [142, 143]]

                stage_data = []
                for s in statuses:
                    sid = s.get('id')
                    if sid in [142, 143]:
                        continue
                    stage_leads = [l for l in active if l.get('status_id') == sid]
                    stale = [l for l in stage_leads if (now - (l.get('updated_at', now) or now)) > 7 * 86400]
                    avg_age = 0
                    if stage_leads:
                        ages = [(now - (l.get('updated_at', now) or now)) / 86400 for l in stage_leads]
                        avg_age = round(sum(ages) / len(ages), 1)

                    stage_data.append({
                        'name': s.get('name'),
                        'deals': len(stage_leads),
                        'stale': len(stale),
                        'avg_age_days': avg_age,
                        'value': sum((l.get('price', 0) or 0) for l in stage_leads),
                        'is_bottleneck': len(stage_leads) > len(active) * 0.4 if active else False,
                    })

                bottleneck = max(stage_data, key=lambda x: x['deals']) if stage_data else None
                results.append({
                    'pipeline': p.get('name'),
                    'total_active': len(active),
                    'stages': stage_data,
                    'main_bottleneck': bottleneck['name'] if bottleneck and bottleneck['deals'] > 0 else None,
                })

            return {
                'pipelines': results,
                'hint': 'Identify bottlenecks: stages with too many deals or high average age. Recommend specific actions to clear them.',
            }

        elif action == 'win_loss':
            results = []
            for p in pipelines:
                p_id = p.get('id')
                won = await get_leads(p_id, 142)
                lost = await get_leads(p_id, 143)
                recent_won = [l for l in won if (l.get('closed_at', 0) or 0) >= period_start]
                recent_lost = [l for l in lost if (l.get('closed_at', 0) or 0) >= period_start]

                won_value = sum((l.get('price', 0) or 0) for l in recent_won)
                lost_value = sum((l.get('price', 0) or 0) for l in recent_lost)
                total_closed = len(recent_won) + len(recent_lost)
                win_rate = round(len(recent_won) / max(total_closed, 1) * 100)

                won_cycles = []
                lost_cycles = []
                for l in recent_won:
                    c, cl = l.get('created_at', 0) or 0, l.get('closed_at', 0) or 0
                    if c and cl:
                        won_cycles.append((cl - c) / 86400)
                for l in recent_lost:
                    c, cl = l.get('created_at', 0) or 0, l.get('closed_at', 0) or 0
                    if c and cl:
                        lost_cycles.append((cl - c) / 86400)

                results.append({
                    'pipeline': p.get('name'),
                    'period_days': days,
                    'won': len(recent_won),
                    'lost': len(recent_lost),
                    'win_rate': f'{win_rate}%',
                    'won_value': won_value,
                    'lost_value': lost_value,
                    'avg_won_cycle_days': round(sum(won_cycles) / max(len(won_cycles), 1), 1),
                    'avg_lost_cycle_days': round(sum(lost_cycles) / max(len(lost_cycles), 1), 1),
                    'avg_won_check': round(won_value / max(len(recent_won), 1)),
                    'avg_lost_check': round(lost_value / max(len(recent_lost), 1)),
                })

            return {
                'pipelines': results,
                'hint': 'Analyze win/loss patterns. Compare cycle times, deal sizes. Suggest what differentiates won vs lost deals.',
            }

        elif action == 'optimize':
            results = []
            for p in pipelines:
                pid = p.get('id')
                statuses = {s['id']: s for s in p.get('_embedded', {}).get('statuses', [])}
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': pid, 'limit': 250}
                all_leads = []
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])

                stage_stats = {}
                for lead in all_leads:
                    sid = lead.get('status_id')
                    if sid in (142, 143):
                        continue
                    sname = statuses.get(sid, {}).get('name', f'#{sid}')
                    if sname not in stage_stats:
                        stage_stats[sname] = {'count': 0, 'total_value': 0, 'ages': []}
                    stage_stats[sname]['count'] += 1
                    stage_stats[sname]['total_value'] += lead.get('price', 0) or 0
                    age = (now - lead.get('created_at', now)) / 86400
                    stage_stats[sname]['ages'].append(age)

                recommendations = []
                for sname, stats in stage_stats.items():
                    avg_age = sum(stats['ages']) / max(len(stats['ages']), 1)
                    if stats['count'] > 10 and avg_age > 14:
                        recommendations.append(f'Stage "{sname}": {stats["count"]} deals, avg {avg_age:.0f} days — consider splitting or adding automation')
                    elif stats['count'] > 20:
                        recommendations.append(f'Stage "{sname}": {stats["count"]} deals congested — review capacity or criteria')
                    elif avg_age > 30:
                        recommendations.append(f'Stage "{sname}": avg age {avg_age:.0f} days — deals may be stale, consider cleanup')

                total_active = sum(s['count'] for s in stage_stats.values())
                if total_active == 0:
                    recommendations.append('Pipeline is empty — focus on lead generation')

                results.append({
                    'pipeline': p.get('name'),
                    'total_active': total_active,
                    'stages': {k: {'count': v['count'], 'avg_age_days': round(sum(v['ages']) / max(len(v['ages']), 1), 1), 'value': v['total_value']} for k, v in stage_stats.items()},
                    'recommendations': recommendations if recommendations else ['Pipeline looks healthy — no immediate optimizations needed'],
                })

            return {
                'pipelines': results,
                'hint': 'Present optimization recommendations clearly. Prioritize by impact. Suggest specific actions for each recommendation.',
            }

        elif action == 'hygiene':
            results = []
            for p in pipelines:
                pid = p.get('id')
                statuses = {s['id']: s.get('name') for s in p.get('_embedded', {}).get('statuses', []) if s.get('id') not in (142, 143)}
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': pid, 'limit': 250}
                async with session.get(url, headers=headers, params=params) as resp:
                    leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])

                issues = []
                no_price = [l for l in leads if l.get('status_id') not in (142, 143) and not (l.get('price') or 0)]
                if no_price:
                    issues.append({'type': 'no_price', 'count': len(no_price), 'message': f'{len(no_price)} active deals without price', 'sample': [l.get('name') for l in no_price[:3]]})
                stale_30 = [l for l in leads if l.get('status_id') not in (142, 143) and (now - (l.get('updated_at') or now)) > 30 * 86400]
                if stale_30:
                    issues.append({'type': 'stale_30d', 'count': len(stale_30), 'message': f'{len(stale_30)} deals inactive 30+ days — consider archiving', 'sample': [l.get('name') for l in stale_30[:3]]})
                no_responsible = [l for l in leads if l.get('status_id') not in (142, 143) and not l.get('responsible_user_id')]
                if no_responsible:
                    issues.append({'type': 'no_responsible', 'count': len(no_responsible), 'message': f'{len(no_responsible)} deals without responsible user'})
                old_won = [l for l in leads if l.get('status_id') == 142 and (now - (l.get('updated_at') or now)) > 90 * 86400]
                if old_won:
                    issues.append({'type': 'old_closed', 'count': len(old_won), 'message': f'{len(old_won)} won deals older than 90 days still in pipeline'})

                hygiene_score = max(0, 100 - len(no_price) * 2 - len(stale_30) * 3 - len(no_responsible) * 5 - len(old_won))
                results.append({'pipeline': p.get('name'), 'hygiene_score': hygiene_score, 'issues': issues, 'total_active': len([l for l in leads if l.get('status_id') not in (142, 143)])})

            return {
                'pipelines': results,
                'hint': 'Present hygiene score per pipeline. List issues by severity. Suggest cleanup actions for each issue type.',
            }

        elif action == 'balance':
            results = []
            for p in pipelines:
                if pipeline_id and p.get('id') != pipeline_id:
                    continue
                statuses = {s.get('id'): s.get('name') for s in p.get('_embedded', {}).get('statuses', []) if s.get('id') not in (142, 143)}
                leads = [l for l in all_leads if l.get('pipeline_id') == p.get('id') and l.get('status_id') not in (142, 143)]
                stage_dist = {}
                total_value = 0
                for sid, sname in statuses.items():
                    stage_leads = [l for l in leads if l.get('status_id') == sid]
                    stage_value = sum(l.get('price', 0) or 0 for l in stage_leads)
                    total_value += stage_value
                    stage_dist[sname] = {'count': len(stage_leads), 'value': stage_value}
                ideal_per_stage = len(leads) / max(len(statuses), 1)
                imbalances = []
                for sname, data in stage_dist.items():
                    if data['count'] > ideal_per_stage * 2:
                        imbalances.append(f'"{sname}" overloaded: {data["count"]} deals (ideal ~{ideal_per_stage:.0f})')
                    elif data['count'] == 0:
                        imbalances.append(f'"{sname}" is empty — check if stage is needed')
                results.append({
                    'pipeline': p.get('name'),
                    'total_deals': len(leads),
                    'total_value': total_value,
                    'stage_distribution': stage_dist,
                    'imbalances': imbalances,
                    'balance_score': max(0, 100 - len(imbalances) * 20),
                })
            return {
                'pipelines': results,
                'hint': 'Present pipeline balance. Highlight overloaded stages and empty stages. Suggest redistribution or stage consolidation.',
            }

        elif action == 'coverage':
            results = []
            for p in pipelines:
                if pipeline_id and p.get('id') != pipeline_id:
                    continue
                p_leads = [l for l in all_leads if l.get('pipeline_id') == p.get('id')]
                active = [l for l in p_leads if l.get('status_id') not in (142, 143)]
                won_period = [l for l in p_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                won_value = sum(l.get('price', 0) or 0 for l in won_period)
                active_value = sum(l.get('price', 0) or 0 for l in active)
                monthly_target = won_value * (30 / max(days, 1)) if won_value > 0 else active_value * 0.3
                coverage_ratio = active_value / max(monthly_target, 1) if monthly_target > 0 else 0
                results.append({
                    'pipeline': p.get('name'),
                    'active_deals': len(active),
                    'active_value': active_value,
                    'won_last_period': won_value,
                    'estimated_monthly_target': round(monthly_target),
                    'coverage_ratio': f'{coverage_ratio:.1f}x',
                    'status': 'healthy' if coverage_ratio >= 3 else ('adequate' if coverage_ratio >= 2 else ('low' if coverage_ratio >= 1 else 'critical')),
                })
            return {
                'pipelines': results,
                'hint': 'Present pipeline coverage. 3x+ is healthy, 2x adequate, <2x needs more leads. Suggest actions to improve coverage.',
            }

        return {'error': f'Unknown pipeline_health action: {action}'}

    async def _handle_tasks_ext(self, session, headers, args: dict) -> dict:
        """Handle extended task management actions."""
        import time
        action = args.get('action')
        now = int(time.time())

        if action == 'prioritize':
            url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'filter[is_completed]': 0, 'limit': 100}
            user_id = args.get('user_id')
            if user_id:
                params['filter[responsible_user_id]'] = user_id

            async with session.get(url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])

            scored = []
            for t in tasks:
                deadline = t.get('complete_till', 0) or 0
                score = 0
                if deadline < now:
                    score += 100 + min((now - deadline) // 3600, 100)
                elif deadline < now + 86400:
                    score += 80
                elif deadline < now + 3 * 86400:
                    score += 50
                else:
                    score += 20

                task_type = t.get('task_type_id', 0)
                if task_type == 1:
                    score += 10
                elif task_type == 2:
                    score += 15

                scored.append({
                    'id': t.get('id'),
                    'text': t.get('text', '')[:80],
                    'type': task_type,
                    'priority_score': score,
                    'deadline': time.strftime('%d.%m %H:%M', time.localtime(deadline)) if deadline else 'нет',
                    'is_overdue': deadline < now if deadline else False,
                    'entity_id': t.get('entity_id'),
                    'entity_type': t.get('entity_type'),
                })

            scored.sort(key=lambda x: x['priority_score'], reverse=True)
            return {
                'tasks': scored[:20],
                'total': len(tasks),
                'hint': 'Present as a prioritized task list. Explain why each task has its priority.',
            }

        elif action == 'reassign':
            task_id = args.get('task_id')
            user_id = args.get('user_id')
            if not task_id or not user_id:
                return {'error': 'task_id and user_id are required'}

            url = f'{self.kommo_base_url}/api/v4/tasks/{task_id}'
            payload = {'responsible_user_id': user_id}
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'task_id': task_id, 'new_responsible': user_id}
                error = await resp.text()
                return {'error': f'Failed to reassign: {error[:200]}'}

        elif action == 'postpone':
            task_id = args.get('task_id')
            postpone_days = args.get('days', 1)
            if not task_id:
                return {'error': 'task_id is required'}

            url = f'{self.kommo_base_url}/api/v4/tasks/{task_id}'
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Task not found: {resp.status}'}
                task = await resp.json()

            current_deadline = task.get('complete_till', now) or now
            new_deadline = current_deadline + postpone_days * 86400

            async with session.patch(url, headers=headers, json={'complete_till': new_deadline}) as resp:
                if resp.status == 200:
                    return {
                        'success': True,
                        'task_id': task_id,
                        'new_deadline': time.strftime('%d.%m.%Y %H:%M', time.localtime(new_deadline)),
                        'postponed_days': postpone_days,
                    }
                error = await resp.text()
                return {'error': f'Failed to postpone: {error[:200]}'}

        elif action == 'plan_day':
            today_start = now - (now % 86400)
            today_end = today_start + 86400

            url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'filter[is_completed]': 0, 'limit': 100}
            user_id = args.get('user_id')
            if user_id:
                params['filter[responsible_user_id]'] = user_id

            async with session.get(url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])

            overdue = []
            today = []
            tomorrow = []
            for t in tasks:
                deadline = t.get('complete_till', 0) or 0
                info = {
                    'id': t.get('id'),
                    'text': t.get('text', '')[:80],
                    'type': t.get('task_type_id'),
                    'deadline': time.strftime('%H:%M', time.localtime(deadline)) if deadline else '',
                    'entity_id': t.get('entity_id'),
                }
                if deadline < today_start:
                    overdue.append(info)
                elif deadline < today_end:
                    today.append(info)
                elif deadline < today_end + 86400:
                    tomorrow.append(info)

            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            leads_params = {'limit': 10, 'order[updated_at]': 'desc'}
            async with session.get(leads_url, headers=headers, params=leads_params) as resp:
                recent_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    recent_leads = data.get('_embedded', {}).get('leads', [])

            return {
                'plan': {
                    'overdue': overdue,
                    'today': today,
                    'tomorrow_preview': tomorrow[:5],
                },
                'recent_active_deals': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0)} for l in recent_leads[:5]],
                'summary': {
                    'overdue_count': len(overdue),
                    'today_count': len(today),
                    'total_pending': len(tasks),
                },
                'hint': 'Create a structured daily plan: 1) Handle overdue first, 2) Today tasks by priority, 3) Preview tomorrow. Add time estimates and recommendations.',
            }

        return await self._handle_tasks_ext_legacy(session, headers, args)

    async def _handle_tasks_ext_legacy(self, session, headers, args: dict) -> dict:
        """Handle legacy tasks_ext actions (overdue, stats, by_entity, today, without_responsible)."""
        import time
        action = args.get('action')
        now = int(time.time())
        user_id = args.get('user_id')
        days = args.get('days', 7)
        limit = args.get('limit', 20)

        url = f'{self.kommo_base_url}/api/v4/tasks'
        params = {'limit': 250}

        if action == 'overdue':
            params['filter[is_completed]'] = 0
            if user_id:
                params['filter[responsible_user_id]'] = user_id
            async with session.get(url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
            overdue = [t for t in tasks if (t.get('complete_till', 0) or 0) < now]
            overdue.sort(key=lambda t: t.get('complete_till', 0) or 0)
            return {'overdue_tasks': [{'id': t.get('id'), 'text': t.get('text', '')[:80], 'deadline': time.strftime('%d.%m', time.localtime(t.get('complete_till', 0)))} for t in overdue[:limit]], 'total': len(overdue)}

        elif action == 'today':
            today_start = now - (now % 86400)
            today_end = today_start + 86400
            params['filter[is_completed]'] = 0
            if user_id:
                params['filter[responsible_user_id]'] = user_id
            async with session.get(url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
            today_tasks = [t for t in tasks if today_start <= (t.get('complete_till', 0) or 0) < today_end]
            return {'today_tasks': [{'id': t.get('id'), 'text': t.get('text', '')[:80], 'type': t.get('task_type_id')} for t in today_tasks[:limit]], 'total': len(today_tasks)}

        elif action == 'stats':
            params_open = {'filter[is_completed]': 0, 'limit': 250}
            params_done = {'filter[is_completed]': 1, 'limit': 250}
            async with session.get(url, headers=headers, params=params_open) as resp:
                open_tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    open_tasks = data.get('_embedded', {}).get('tasks', [])
            async with session.get(url, headers=headers, params=params_done) as resp:
                done_tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    done_tasks = data.get('_embedded', {}).get('tasks', [])
            overdue = sum(1 for t in open_tasks if (t.get('complete_till', 0) or 0) < now)
            return {'open': len(open_tasks), 'completed': len(done_tasks), 'overdue': overdue}

        elif action == 'without_responsible':
            params['filter[is_completed]'] = 0
            async with session.get(url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
            unassigned = [t for t in tasks if not t.get('responsible_user_id')]
            return {'unassigned_tasks': [{'id': t.get('id'), 'text': t.get('text', '')[:80]} for t in unassigned[:limit]], 'total': len(unassigned)}

        elif action == 'delegate':
            task_id = args.get('task_id')
            user_id = args.get('user_id')
            if not task_id or not user_id:
                return {'error': 'task_id and user_id required for delegate'}
            turl = f'{self.kommo_base_url}/api/v4/tasks/{task_id}'
            async with session.get(turl, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Task {task_id} not found'}
                task = await resp.json()
            patch_data = {'responsible_user_id': user_id}
            async with session.patch(turl, headers=headers, json=patch_data) as resp:
                if resp.status == 200:
                    uurl = f'{self.kommo_base_url}/api/v4/users/{user_id}'
                    async with session.get(uurl, headers=headers) as uresp:
                        uname = 'Unknown'
                        if uresp.status == 200:
                            udata = await uresp.json()
                            uname = udata.get('name', 'Unknown')
                    return {
                        'delegated': True,
                        'task_id': task_id,
                        'new_responsible': uname,
                        'task_text': task.get('text', '')[:100],
                        'hint': 'Task delegated successfully. Suggest notifying the new assignee.',
                    }
                return {'error': f'Failed to delegate task: {resp.status}'}

        elif action == 'dependencies':
            url = f'{self.kommo_base_url}/api/v4/tasks'
            params = {'limit': 250}
            if args.get('user_id'):
                params['filter[responsible_user_id]'] = args['user_id']
            async with session.get(url, headers=headers, params=params) as resp:
                tasks = []
                if resp.status == 200:
                    data = await resp.json()
                    tasks = data.get('_embedded', {}).get('tasks', [])
            entity_tasks = {}
            for t in tasks:
                if t.get('entity_id') and t.get('entity_type') == 'leads':
                    eid = t['entity_id']
                    if eid not in entity_tasks:
                        entity_tasks[eid] = []
                    entity_tasks[eid].append(t)
            chains = []
            for eid, etasks in entity_tasks.items():
                if len(etasks) > 1:
                    sorted_tasks = sorted(etasks, key=lambda x: x.get('complete_till', 0))
                    chains.append({
                        'entity_id': eid,
                        'entity_type': 'lead',
                        'task_chain': [{'id': t.get('id'), 'text': t.get('text', '')[:60], 'due': t.get('complete_till'), 'done': t.get('is_completed', False)} for t in sorted_tasks],
                        'total_tasks': len(sorted_tasks),
                        'completed': sum(1 for t in sorted_tasks if t.get('is_completed')),
                    })
            chains.sort(key=lambda x: x['total_tasks'], reverse=True)
            return {
                'task_chains': chains[:15],
                'total_entities_with_chains': len(chains),
                'hint': 'Present task chains per deal. Show completion progress. Highlight blocked chains where earlier tasks are incomplete.',
            }

        elif action == 'mass_create':
            user_ids = args.get('user_ids', [])
            text = args.get('text', 'Follow up on deal')
            task_type = args.get('task_type', 1)
            if not user_ids:
                uurl = f'{self.kommo_base_url}/api/v4/users'
                async with session.get(uurl, headers=headers) as resp:
                    if resp.status == 200:
                        udata = await resp.json()
                        user_ids = [u.get('id') for u in udata.get('_embedded', {}).get('users', []) if u.get('rights', {}).get('is_active', True)]
            complete_till = now + (args.get('days', 1)) * 86400
            created = []
            for uid in user_ids:
                payload = [{'text': text, 'complete_till': complete_till, 'responsible_user_id': uid, 'task_type_id': task_type}]
                async with session.post(f'{self.kommo_base_url}/api/v4/tasks', headers=headers, json=payload) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        tasks = data.get('_embedded', {}).get('tasks', [])
                        created.extend(tasks)
            return {
                'created_tasks': len(created),
                'for_users': len(user_ids),
                'text': text,
                'hint': 'Tasks created for team. Confirm with user count and deadline.',
            }

        elif action == 'smart_reminders':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if args.get('pipeline_id'):
                params['filter[pipeline_id]'] = args['pipeline_id']
            async with session.get(url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
            reminders = []
            for l in leads:
                if l.get('status_id') in (142, 143):
                    continue
                last_act = (now - (l.get('updated_at') or now)) / 86400
                price = l.get('price', 0) or 0
                if last_act > 7:
                    urgency = 'high' if last_act > 14 or price > 100000 else ('medium' if last_act > 7 else 'low')
                    reminders.append({
                        'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                        'days_inactive': round(last_act), 'urgency': urgency,
                        'reminder': f'Follow up on "{l.get("name")}" — {round(last_act)}d inactive',
                        'suggested_action': 'Call' if price > 50000 else 'Message',
                    })
            reminders.sort(key=lambda x: (0 if x['urgency'] == 'high' else 1 if x['urgency'] == 'medium' else 2, -x['price']))
            return {
                'reminders': reminders[:20],
                'total': len(reminders),
                'hint': 'Present smart reminders sorted by urgency. High-value inactive deals need immediate attention.',
            }

        elif action == 'meeting_briefing':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for meeting_briefing'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 20}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            contacts = lead.get('_embedded', {}).get('contacts', [])
            contact_details = []
            for c in contacts[:5]:
                curl = f'{self.kommo_base_url}/api/v4/contacts/{c["id"]}'
                async with session.get(curl, headers=headers) as cresp:
                    if cresp.status == 200:
                        cdata = await cresp.json()
                        contact_details.append({'name': cdata.get('name'), 'id': cdata.get('id')})
            recent_texts = [(n.get('params', {}).get('text', '') or '')[:100] for n in notes if n.get('params', {}).get('text')][:5]
            return {
                'briefing': {
                    'deal': lead.get('name'), 'price': lead.get('price'),
                    'stage': lead.get('status_id'), 'pipeline': lead.get('pipeline_id'),
                    'age_days': round((now - lead.get('created_at', now)) / 86400),
                    'contacts': contact_details,
                    'recent_communications': recent_texts,
                    'talking_points': [
                        f'Deal value: {lead.get("price", 0)}₽',
                        f'In pipeline for {round((now - lead.get("created_at", now)) / 86400)} days',
                        f'{len(notes)} interactions recorded',
                    ],
                },
                'hint': 'Present as meeting briefing card. Include key contacts, deal status, recent comms, and suggested talking points.',
            }

        elif action == 'meeting_prep':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for meeting_prep'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 30}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            turl = f'{self.kommo_base_url}/api/v4/tasks'
            async with session.get(turl, headers=headers, params={'filter[entity_id]': lead_id, 'filter[entity_type]': 'leads'}) as resp:
                tasks = []
                if resp.status == 200:
                    tdata = await resp.json()
                    tasks = tdata.get('_embedded', {}).get('tasks', [])
            open_tasks = [t for t in tasks if not t.get('is_completed')]
            all_texts = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
            concerns = []
            if 'цена' in all_texts or 'бюджет' in all_texts or 'дорого' in all_texts:
                concerns.append('Price sensitivity detected in communications')
            if 'конкурент' in all_texts or 'альтернатив' in all_texts:
                concerns.append('Competitor mentions found')
            if 'срок' in all_texts or 'когда' in all_texts:
                concerns.append('Timeline concerns raised')
            age = (now - lead.get('created_at', now)) / 86400
            return {
                'preparation': {
                    'deal': lead.get('name'), 'price': lead.get('price'),
                    'age_days': round(age),
                    'open_tasks': [{'text': t.get('text', '')[:60], 'due': t.get('complete_till')} for t in open_tasks[:5]],
                    'concerns': concerns if concerns else ['No specific concerns detected'],
                    'agenda_suggestions': [
                        'Review current status and next steps',
                        'Address any open questions or concerns',
                        f'Discuss timeline and pricing' if lead.get('price') else 'Qualify budget and timeline',
                        'Define clear action items and deadlines',
                    ],
                    'preparation_checklist': [
                        'Review recent communications',
                        'Prepare answers for potential objections',
                        'Have pricing/proposal ready',
                        'Prepare case studies for reference',
                    ],
                },
                'hint': 'Present as meeting preparation guide. Include agenda, concerns to address, and checklist.',
            }

        return {'error': f'Unknown tasks_ext action: {action}'}

    async def _handle_contacts_ext(self, session, headers, args: dict) -> dict:
        """Handle extended contact analysis."""
        import time
        action = args.get('action')
        now = int(time.time())
        days = args.get('days', 30)
        limit = args.get('limit', 20)

        if action == 'inactive':
            threshold = now - days * 86400
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'limit': 250}
            all_contacts = []
            page = 1
            while len(all_contacts) < 250:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    contacts = data.get('_embedded', {}).get('contacts', [])
                    if not contacts:
                        break
                    all_contacts.extend(contacts)
                    page += 1
                    if len(contacts) < 250:
                        break

            inactive = [c for c in all_contacts if (c.get('updated_at', now) or now) < threshold]
            inactive.sort(key=lambda c: c.get('updated_at', 0) or 0)

            return {
                'inactive_contacts': [{
                    'id': c.get('id'),
                    'name': c.get('name', ''),
                    'last_activity': time.strftime('%d.%m.%Y', time.localtime(c.get('updated_at', 0) or 0)),
                    'days_inactive': (now - (c.get('updated_at', now) or now)) // 86400,
                } for c in inactive[:limit]],
                'total_inactive': len(inactive),
                'total_contacts': len(all_contacts),
                'threshold_days': days,
                'hint': 'These contacts have no activity. Recommend re-engagement or cleanup.',
            }

        elif action == 'without_deals':
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'limit': 250, 'with': 'leads'}
            all_contacts = []
            page = 1
            while len(all_contacts) < 250:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    contacts = data.get('_embedded', {}).get('contacts', [])
                    if not contacts:
                        break
                    all_contacts.extend(contacts)
                    page += 1
                    if len(contacts) < 250:
                        break

            without_deals = []
            for c in all_contacts:
                leads = c.get('_embedded', {}).get('leads', [])
                if not leads:
                    without_deals.append(c)

            return {
                'contacts_without_deals': [{
                    'id': c.get('id'),
                    'name': c.get('name', ''),
                    'created': time.strftime('%d.%m.%Y', time.localtime(c.get('created_at', 0) or 0)),
                } for c in without_deals[:limit]],
                'total_without_deals': len(without_deals),
                'total_contacts': len(all_contacts),
                'hint': 'These contacts have no linked deals. Consider creating deals or cleaning up.',
            }

        elif action == 'search':
            query = args.get('query', '')
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'limit': limit}
            if query:
                params['query'] = query
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'contacts': data.get('_embedded', {}).get('contacts', [])}
                return {'error': f'API error: {resp.status}'}

        elif action == 'recent':
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'limit': limit, 'order[updated_at]': 'desc'}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'contacts': data.get('_embedded', {}).get('contacts', [])}
                return {'error': f'API error: {resp.status}'}

        elif action == 'by_responsible':
            user_id = args.get('user_id') or args.get('contact_id')
            if not user_id:
                return {'error': 'user_id is required'}
            url = f'{self.kommo_base_url}/api/v4/contacts'
            params = {'filter[responsible_user_id]': user_id, 'limit': limit}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {'contacts': data.get('_embedded', {}).get('contacts', [])}
                return {'error': f'API error: {resp.status}'}

        return {'error': f'Unknown contacts_ext action: {action}'}

    async def _handle_forecast(self, session, headers, args: dict) -> dict:
        """Sales forecasting: pipeline forecast, revenue prediction, deal probability, trends."""
        import time
        from datetime import datetime, timedelta
        action = args.get('action')
        days = args.get('days', 30)
        pipeline_id = args.get('pipeline_id')
        now = int(time.time())
        cutoff = now - days * 86400

        if action == 'pipeline':
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'API error: {resp.status}'}
                pdata = await resp.json()
            pipelines = pdata.get('_embedded', {}).get('pipelines', [])
            if pipeline_id:
                pipelines = [p for p in pipelines if p.get('id') == pipeline_id]

            results = []
            for p in pipelines:
                pid = p.get('id')
                statuses = p.get('_embedded', {}).get('statuses', [])
                active_statuses = [s for s in statuses if s.get('id') not in (142, 143)]
                total_stages = len(active_statuses)

                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[pipeline_id]': pid, 'limit': 250}
                async with session.get(url, headers=headers, params=params) as resp:
                    leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])

                active_leads = [l for l in leads if l.get('status_id') not in (142, 143)]
                weighted_total = 0
                stage_forecast = []
                for s in active_statuses:
                    sid = s.get('id')
                    stage_leads = [l for l in active_leads if l.get('status_id') == sid]
                    stage_idx = next((i for i, st in enumerate(active_statuses) if st.get('id') == sid), 0)
                    weight = (stage_idx + 1) / max(total_stages, 1)
                    stage_value = sum(l.get('price', 0) or 0 for l in stage_leads)
                    weighted = round(stage_value * weight)
                    weighted_total += weighted
                    if stage_leads:
                        stage_forecast.append({
                            'stage': s.get('name'),
                            'deals': len(stage_leads),
                            'value': stage_value,
                            'weight': f'{weight:.0%}',
                            'weighted_value': weighted,
                        })

                results.append({
                    'pipeline': p.get('name'),
                    'total_active_deals': len(active_leads),
                    'total_pipeline_value': sum(l.get('price', 0) or 0 for l in active_leads),
                    'weighted_forecast': weighted_total,
                    'stages': stage_forecast,
                })

            return {
                'forecast': results,
                'method': 'weighted_pipeline',
                'hint': 'Present weighted forecast as the most likely outcome. Explain that deals closer to closing have higher weight. Compare total vs weighted values.',
            }

        elif action == 'revenue':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[statuses][0][status_id]': 142, 'limit': 250, 'order[closed_at]': 'desc'}
            won_leads = []
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])

            monthly = {}
            for lead in won_leads:
                closed = lead.get('closed_at') or lead.get('updated_at', now)
                dt = datetime.fromtimestamp(closed)
                key = dt.strftime('%Y-%m')
                if key not in monthly:
                    monthly[key] = {'count': 0, 'revenue': 0}
                monthly[key]['count'] += 1
                monthly[key]['revenue'] += lead.get('price', 0) or 0

            sorted_months = sorted(monthly.items(), reverse=True)[:6]
            if len(sorted_months) >= 2:
                recent_avg = sum(m[1]['revenue'] for m in sorted_months[:3]) / min(3, len(sorted_months))
                older_avg = sum(m[1]['revenue'] for m in sorted_months[3:]) / max(len(sorted_months) - 3, 1) if len(sorted_months) > 3 else recent_avg
                growth = ((recent_avg - older_avg) / max(older_avg, 1)) * 100
                next_month_est = round(recent_avg * (1 + growth / 100 * 0.5))
            else:
                recent_avg = sorted_months[0][1]['revenue'] if sorted_months else 0
                growth = 0
                next_month_est = round(recent_avg)

            return {
                'monthly_revenue': [{'month': m[0], 'deals_won': m[1]['count'], 'revenue': m[1]['revenue']} for m in sorted_months],
                'avg_monthly_revenue': round(recent_avg),
                'growth_trend': f'{growth:+.1f}%',
                'next_month_estimate': next_month_est,
                'hint': 'Present revenue trend with growth direction. Highlight if growing or declining. Give confidence level based on data volume.',
            }

        elif action == 'deal_probability':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id is required for deal_probability'}

            url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            params = {'with': 'contacts'}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return {'error': f'Lead not found: {resp.status}'}
                lead = await resp.json()

            price = lead.get('price', 0) or 0
            status_id = lead.get('status_id')
            pipeline_id_l = lead.get('pipeline_id')
            created = lead.get('created_at', now)
            age_days = (now - created) / 86400
            has_contacts = bool(lead.get('_embedded', {}).get('contacts'))

            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id_l}'
            async with session.get(purl, headers=headers) as resp:
                if resp.status == 200:
                    pdata = await resp.json()
                    statuses = pdata.get('_embedded', {}).get('statuses', [])
                    active_statuses = [s for s in statuses if s.get('id') not in (142, 143)]
                    stage_idx = next((i for i, s in enumerate(active_statuses) if s.get('id') == status_id), 0)
                    stage_progress = (stage_idx + 1) / max(len(active_statuses), 1)
                else:
                    stage_progress = 0.5

            score = 50
            score += stage_progress * 30
            if has_contacts:
                score += 5
            if price > 0:
                score += 5
            if age_days > 60:
                score -= 15
            elif age_days > 30:
                score -= 5
            if age_days < 7:
                score += 5
            score = max(5, min(95, round(score)))

            factors = []
            factors.append(f'Stage progress: {stage_progress:.0%} through pipeline (+{stage_progress * 30:.0f})')
            if age_days > 30:
                factors.append(f'Deal age: {age_days:.0f} days (negative signal)')
            if has_contacts:
                factors.append('Has linked contacts (+5)')
            if price > 0:
                factors.append(f'Has price set: {price} (+5)')

            return {
                'lead_id': lead_id,
                'name': lead.get('name'),
                'probability': f'{score}%',
                'score': score,
                'factors': factors,
                'stage_progress': f'{stage_progress:.0%}',
                'age_days': round(age_days),
                'hint': 'Present probability with key factors. Suggest actions to improve probability if below 50%.',
            }

        elif action == 'trends':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'order[created_at]': 'desc'}
            all_leads = []
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            weeks = {}
            for lead in all_leads:
                created = lead.get('created_at', now)
                if created < cutoff:
                    continue
                dt = datetime.fromtimestamp(created)
                week_start = dt - timedelta(days=dt.weekday())
                key = week_start.strftime('%Y-%m-%d')
                if key not in weeks:
                    weeks[key] = {'new': 0, 'value': 0, 'won': 0, 'lost': 0}
                weeks[key]['new'] += 1
                weeks[key]['value'] += lead.get('price', 0) or 0
                if lead.get('status_id') == 142:
                    weeks[key]['won'] += 1
                elif lead.get('status_id') == 143:
                    weeks[key]['lost'] += 1

            sorted_weeks = sorted(weeks.items())
            trend_direction = 'stable'
            if len(sorted_weeks) >= 2:
                first_half = sorted_weeks[:len(sorted_weeks)//2]
                second_half = sorted_weeks[len(sorted_weeks)//2:]
                avg_first = sum(w[1]['new'] for w in first_half) / max(len(first_half), 1)
                avg_second = sum(w[1]['new'] for w in second_half) / max(len(second_half), 1)
                if avg_second > avg_first * 1.1:
                    trend_direction = 'growing'
                elif avg_second < avg_first * 0.9:
                    trend_direction = 'declining'

            return {
                'period_days': days,
                'weekly_data': [{'week': w[0], **w[1]} for w in sorted_weeks],
                'trend': trend_direction,
                'total_new': sum(w[1]['new'] for w in sorted_weeks),
                'total_value': sum(w[1]['value'] for w in sorted_weeks),
                'hint': f'Trend is {trend_direction}. Visualize weekly data. Highlight any anomalies or significant changes.',
            }

        elif action == 'cashflow':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'order[created_at]': 'desc'}
            all_leads = []
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]

            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                pipelines_data = {}
                if resp.status == 200:
                    pdata = await resp.json()
                    for p in pdata.get('_embedded', {}).get('pipelines', []):
                        statuses = [s for s in p.get('_embedded', {}).get('statuses', []) if s.get('id') not in (142, 143)]
                        pipelines_data[p.get('id')] = {'name': p.get('name'), 'stages': len(statuses), 'statuses': {s['id']: i for i, s in enumerate(statuses)}}

            weekly_forecast = {}
            for lead in active:
                price = lead.get('price', 0) or 0
                if price == 0:
                    continue
                pid = lead.get('pipeline_id')
                sid = lead.get('status_id')
                pinfo = pipelines_data.get(pid, {})
                stage_idx = pinfo.get('statuses', {}).get(sid, 0)
                total_stages = pinfo.get('stages', 5)
                progress = (stage_idx + 1) / max(total_stages, 1)
                est_weeks = max(1, round((1 - progress) * 4))
                week_key = f'week_{est_weeks}'
                if week_key not in weekly_forecast:
                    weekly_forecast[week_key] = {'expected': 0, 'deals': 0}
                weekly_forecast[week_key]['expected'] += round(price * progress)
                weekly_forecast[week_key]['deals'] += 1

            total_expected = sum(w['expected'] for w in weekly_forecast.values())
            return {
                'cashflow_forecast': weekly_forecast,
                'total_expected': total_expected,
                'active_deals_with_price': len([l for l in active if (l.get('price') or 0) > 0]),
                'hint': 'Present as expected cash inflow by week. Explain that closer deals have higher confidence. Total is weighted by stage progress.',
            }

        elif action == 'whatif':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            won = [l for l in all_leads if l.get('status_id') == 142]
            total_active_value = sum(l.get('price', 0) or 0 for l in active)
            current_won_value = sum(l.get('price', 0) or 0 for l in won)
            current_conversion = len(won) / max(len(all_leads), 1)

            scenarios = []
            for conv_boost in [0.05, 0.10, 0.20]:
                new_conv = current_conversion + conv_boost
                additional_deals = round(len(active) * conv_boost)
                avg_deal = total_active_value / max(len(active), 1)
                additional_revenue = round(additional_deals * avg_deal)
                scenarios.append({
                    'scenario': f'+{conv_boost:.0%} conversion',
                    'new_conversion': f'{new_conv:.1%}',
                    'additional_deals_won': additional_deals,
                    'additional_revenue': additional_revenue,
                })

            for check_boost in [1.1, 1.25, 1.5]:
                avg_deal = total_active_value / max(len(active), 1)
                new_avg = round(avg_deal * check_boost)
                scenarios.append({
                    'scenario': f'Avg check x{check_boost}',
                    'new_avg_check': new_avg,
                    'revenue_impact': round((new_avg - avg_deal) * len(won)),
                })

            return {
                'current': {
                    'active_deals': len(active),
                    'pipeline_value': total_active_value,
                    'won_deals': len(won),
                    'won_value': current_won_value,
                    'conversion': f'{current_conversion:.1%}',
                    'avg_check': round(total_active_value / max(len(active), 1)),
                },
                'scenarios': scenarios,
                'hint': 'Present what-if scenarios as potential impact. Show current baseline vs each scenario. Help user understand which lever has most impact.',
            }

        elif action == 'revenue_model':
            won = [l for l in all_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            lost = [l for l in all_leads if l.get('status_id') == 143 and l.get('updated_at', 0) >= cutoff]
            current_revenue = sum(l.get('price', 0) or 0 for l in won)
            pipeline_value = sum(l.get('price', 0) or 0 for l in active)
            win_rate = len(won) / max(len(won) + len(lost), 1)
            avg_deal = current_revenue / max(len(won), 1)
            avg_cycle = sum((l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in won) / max(len(won), 1) if won else 30
            scenarios = {
                'conservative': {
                    'win_rate': win_rate * 0.8,
                    'expected_revenue': round(pipeline_value * win_rate * 0.8),
                    'deals_to_close': round(len(active) * win_rate * 0.8),
                },
                'realistic': {
                    'win_rate': win_rate,
                    'expected_revenue': round(pipeline_value * win_rate),
                    'deals_to_close': round(len(active) * win_rate),
                },
                'optimistic': {
                    'win_rate': min(win_rate * 1.2, 1.0),
                    'expected_revenue': round(pipeline_value * min(win_rate * 1.2, 1.0)),
                    'deals_to_close': round(len(active) * min(win_rate * 1.2, 1.0)),
                },
            }
            growth_needed = 0
            if current_revenue > 0:
                growth_needed = round((scenarios['realistic']['expected_revenue'] - current_revenue) / current_revenue * 100)
            return {
                'current_period': {'revenue': current_revenue, 'deals_won': len(won), 'avg_deal': round(avg_deal), 'avg_cycle_days': round(avg_cycle)},
                'pipeline': {'active_deals': len(active), 'total_value': pipeline_value, 'win_rate': f'{win_rate:.0%}'},
                'scenarios': scenarios,
                'growth_projection': f'{growth_needed:+d}%',
                'levers': [
                    f'Increase win rate by 5% → +{round(pipeline_value * 0.05)}₽',
                    f'Add 10 more deals → +{round(avg_deal * 10 * win_rate)}₽',
                    f'Increase avg deal by 20% → +{round(current_revenue * 0.2)}₽',
                ],
                'hint': 'Present 3 scenarios with revenue projections. Show growth levers with estimated impact. Help user pick strategy.',
            }

        elif action == 'plan_fact':
            won = [l for l in all_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            actual_revenue = sum(l.get('price', 0) or 0 for l in won)
            pipeline_value = sum(l.get('price', 0) or 0 for l in active)
            lost = [l for l in all_leads if l.get('status_id') == 143 and l.get('updated_at', 0) >= cutoff]
            lost_value = sum(l.get('price', 0) or 0 for l in lost)
            win_rate = len(won) / max(len(won) + len(lost), 1)
            expected_from_pipeline = round(pipeline_value * win_rate)
            projected_total = actual_revenue + expected_from_pipeline
            plan = args.get('plan_value', projected_total * 1.2) or projected_total * 1.2
            completion = actual_revenue / max(plan, 1) * 100
            days_left = max(days - (now - cutoff) / 86400, 1)
            daily_target = (plan - actual_revenue) / days_left if days_left > 0 else 0
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            by_user = {}
            for l in won:
                uid = l.get('responsible_user_id')
                if uid:
                    if uid not in by_user:
                        by_user[uid] = {'name': users.get(uid, f'User {uid}'), 'revenue': 0, 'deals': 0}
                    by_user[uid]['revenue'] += l.get('price', 0) or 0
                    by_user[uid]['deals'] += 1
            return {
                'plan': round(plan),
                'actual': actual_revenue,
                'completion': f'{completion:.1f}%',
                'projected': projected_total,
                'gap': round(plan - actual_revenue),
                'daily_target': round(daily_target),
                'days_left': round(days_left),
                'won_deals': len(won),
                'lost_deals': len(lost),
                'lost_value': lost_value,
                'win_rate': f'{win_rate:.0%}',
                'by_user': sorted(by_user.values(), key=lambda x: x['revenue'], reverse=True),
                'hint': 'Present plan vs fact with completion %. Show gap and daily target needed. Break down by user. Suggest actions to close the gap.',
            }

        elif action == 'closing_forecast':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                stages = {}
                if resp.status == 200:
                    pdata = await resp.json()
                    for p in pdata.get('_embedded', {}).get('pipelines', []):
                        total = len(p.get('_embedded', {}).get('statuses', []))
                        for i, s in enumerate(p.get('_embedded', {}).get('statuses', [])):
                            stages[s.get('id')] = {'name': s.get('name'), 'position': i, 'total': total}
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            candidates = []
            for l in active:
                sid = l.get('status_id')
                info = stages.get(sid, {'position': 0, 'total': 5})
                progress = info['position'] / max(info['total'] - 1, 1)
                price = l.get('price', 0) or 0
                activity = (now - (l.get('updated_at') or now)) / 86400
                prob = min(95, int(progress * 60 + (20 if activity < 7 else (10 if activity < 14 else 0)) + (15 if price > 0 else 0)))
                if prob >= 30:
                    candidates.append({
                        'id': l.get('id'), 'name': l.get('name'), 'price': price,
                        'stage': info.get('name', f'Stage {sid}'), 'probability': prob,
                        'expected_value': int(price * prob / 100),
                        'days_inactive': round(activity),
                    })
            candidates.sort(key=lambda x: x['expected_value'], reverse=True)
            total_expected = sum(c['expected_value'] for c in candidates)
            return {
                'closing_forecast': {
                    'candidates': candidates[:20],
                    'total_expected_revenue': total_expected,
                    'total_candidates': len(candidates),
                    'forecast_period': f'{days} days',
                },
                'hint': 'Present closing forecast ranked by expected value. Show probability and stage. Help user focus on highest-probability deals.',
            }

        return {'error': f'Unknown forecast action: {action}'}

    async def _handle_alerts(self, session, headers, args: dict) -> dict:
        """Proactive CRM alerts: risks, performance, opportunities."""
        import time
        action = args.get('action')
        days = args.get('days', 7)
        now = int(time.time())
        cutoff = now - days * 86400

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250, 'with': 'contacts'}
        all_leads = []
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                all_leads = data.get('_embedded', {}).get('leads', [])

        active_leads = [l for l in all_leads if l.get('status_id') not in (142, 143)]

        if action == 'check':
            alerts = []
            stale = [l for l in active_leads if (now - (l.get('updated_at') or now)) > 7 * 86400]
            if stale:
                alerts.append({'type': 'warning', 'category': 'stale_deals', 'message': f'{len(stale)} deals without activity for 7+ days', 'count': len(stale)})

            no_contacts = [l for l in active_leads if not l.get('_embedded', {}).get('contacts')]
            if no_contacts:
                alerts.append({'type': 'info', 'category': 'no_contacts', 'message': f'{len(no_contacts)} deals without linked contacts', 'count': len(no_contacts)})

            no_price = [l for l in active_leads if not (l.get('price') or 0)]
            if no_price:
                alerts.append({'type': 'info', 'category': 'no_price', 'message': f'{len(no_price)} deals without price set', 'count': len(no_price)})

            high_value_stale = [l for l in stale if (l.get('price') or 0) > 100000]
            if high_value_stale:
                alerts.append({'type': 'critical', 'category': 'high_value_stale', 'message': f'{len(high_value_stale)} high-value deals (>100K) are stale', 'count': len(high_value_stale)})

            turl = f'{self.kommo_base_url}/api/v4/tasks'
            tparams = {'filter[is_completed]': 0, 'limit': 250}
            async with session.get(turl, headers=headers, params=tparams) as resp:
                tasks = []
                if resp.status == 200:
                    tdata = await resp.json()
                    tasks = tdata.get('_embedded', {}).get('tasks', [])
            overdue = [t for t in tasks if (t.get('complete_till') or now) < now]
            if overdue:
                alerts.append({'type': 'warning', 'category': 'overdue_tasks', 'message': f'{len(overdue)} overdue tasks', 'count': len(overdue)})

            return {
                'alerts': alerts,
                'total_alerts': len(alerts),
                'critical': len([a for a in alerts if a['type'] == 'critical']),
                'warnings': len([a for a in alerts if a['type'] == 'warning']),
                'hint': 'Present alerts by severity: critical first, then warnings, then info. Suggest immediate actions for critical alerts.',
            }

        elif action == 'risks':
            risks = []
            for lead in active_leads:
                risk_score = 0
                risk_factors = []
                age = (now - lead.get('created_at', now)) / 86400
                last_activity = (now - (lead.get('updated_at') or now)) / 86400
                price = lead.get('price', 0) or 0

                if last_activity > 14:
                    risk_score += 40
                    risk_factors.append(f'No activity for {last_activity:.0f} days')
                elif last_activity > 7:
                    risk_score += 20
                    risk_factors.append(f'Low activity ({last_activity:.0f} days)')

                if age > 60:
                    risk_score += 30
                    risk_factors.append(f'Very old deal ({age:.0f} days)')
                elif age > 30:
                    risk_score += 15
                    risk_factors.append(f'Aging deal ({age:.0f} days)')

                if not lead.get('_embedded', {}).get('contacts'):
                    risk_score += 10
                    risk_factors.append('No linked contacts')

                if price == 0:
                    risk_score += 10
                    risk_factors.append('No price set')

                if risk_score >= 30:
                    risks.append({
                        'lead_id': lead.get('id'),
                        'name': lead.get('name'),
                        'price': price,
                        'risk_score': min(risk_score, 100),
                        'risk_level': 'high' if risk_score >= 60 else 'medium',
                        'factors': risk_factors,
                    })

            risks.sort(key=lambda x: x['risk_score'], reverse=True)
            return {
                'at_risk_deals': risks[:20],
                'total_at_risk': len(risks),
                'high_risk': len([r for r in risks if r['risk_level'] == 'high']),
                'total_risk_value': sum(r['price'] for r in risks),
                'hint': 'Present high-risk deals first. For each, suggest specific recovery actions based on risk factors.',
            }

        elif action == 'performance':
            user_id = args.get('user_id')
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = []
                if resp.status == 200:
                    udata = await resp.json()
                    users = udata.get('_embedded', {}).get('users', [])

            if user_id:
                users = [u for u in users if u.get('id') == user_id]

            perf_alerts = []
            for user in users:
                uid = user.get('id')
                user_leads = [l for l in active_leads if l.get('responsible_user_id') == uid]
                user_stale = [l for l in user_leads if (now - (l.get('updated_at') or now)) > 7 * 86400]

                if len(user_leads) > 30:
                    perf_alerts.append({'user': user.get('name'), 'user_id': uid, 'type': 'overloaded', 'message': f'{len(user_leads)} active deals — may be overloaded', 'severity': 'warning'})
                if user_stale and len(user_stale) > len(user_leads) * 0.3:
                    perf_alerts.append({'user': user.get('name'), 'user_id': uid, 'type': 'stale_ratio', 'message': f'{len(user_stale)}/{len(user_leads)} deals are stale (>{30}%)', 'severity': 'warning'})
                if len(user_leads) == 0:
                    perf_alerts.append({'user': user.get('name'), 'user_id': uid, 'type': 'no_deals', 'message': 'No active deals assigned', 'severity': 'info'})

            return {
                'performance_alerts': perf_alerts,
                'total_alerts': len(perf_alerts),
                'hint': 'Present performance alerts grouped by user. Suggest workload rebalancing if needed.',
            }

        elif action == 'opportunities':
            opps = []
            won_leads = [l for l in all_leads if l.get('status_id') == 142]
            lost_leads = [l for l in all_leads if l.get('status_id') == 143]

            recently_lost = [l for l in lost_leads if (now - (l.get('updated_at') or now)) < 30 * 86400 and (l.get('price') or 0) > 0]
            if recently_lost:
                recently_lost.sort(key=lambda x: x.get('price', 0), reverse=True)
                opps.append({
                    'type': 'reactivation',
                    'message': f'{len(recently_lost)} recently lost deals could be reactivated',
                    'total_value': sum(l.get('price', 0) or 0 for l in recently_lost),
                    'top_deals': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price')} for l in recently_lost[:5]],
                })

            big_active = [l for l in active_leads if (l.get('price') or 0) > 50000]
            stale_big = [l for l in big_active if (now - (l.get('updated_at') or now)) > 5 * 86400]
            if stale_big:
                opps.append({
                    'type': 'follow_up_needed',
                    'message': f'{len(stale_big)} high-value deals need follow-up',
                    'total_value': sum(l.get('price', 0) or 0 for l in stale_big),
                    'deals': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price')} for l in stale_big[:5]],
                })

            no_task_leads = []
            for lead in active_leads[:50]:
                lurl = f'{self.kommo_base_url}/api/v4/tasks'
                tparams = {'filter[entity_type]': 'leads', 'filter[entity_id]': lead.get('id'), 'filter[is_completed]': 0, 'limit': 1}
                async with session.get(lurl, headers=headers, params=tparams) as resp:
                    if resp.status == 204 or (resp.status == 200 and not (await resp.json()).get('_embedded', {}).get('tasks')):
                        no_task_leads.append(lead)
                if len(no_task_leads) >= 10:
                    break

            if no_task_leads:
                opps.append({
                    'type': 'no_next_step',
                    'message': f'{len(no_task_leads)}+ deals without planned next step',
                    'deals': [{'id': l.get('id'), 'name': l.get('name')} for l in no_task_leads[:5]],
                })

            return {
                'opportunities': opps,
                'total_opportunities': len(opps),
                'hint': 'Present opportunities by potential value. Suggest specific actions for each opportunity type.',
            }

        elif action == 'trends':
            from datetime import datetime, timedelta
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'order[created_at]': 'desc'}
            page = 1
            all_hist = []
            while page <= 4:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])
                        all_hist.extend(leads)
                        if len(leads) < 250:
                            break
                        page += 1
                    else:
                        break

            current_start = now - days * 86400
            prev_start = current_start - days * 86400
            current = [l for l in all_hist if l.get('created_at', 0) >= current_start]
            prev = [l for l in all_hist if prev_start <= l.get('created_at', 0) < current_start]

            trend_alerts = []
            curr_count = len(current)
            prev_count = len(prev)
            if prev_count > 0:
                deal_change = (curr_count - prev_count) / prev_count * 100
                if deal_change < -20:
                    trend_alerts.append({'type': 'warning', 'metric': 'new_deals', 'message': f'New deals down {deal_change:.0f}% vs previous period', 'change': f'{deal_change:+.0f}%'})
                elif deal_change > 30:
                    trend_alerts.append({'type': 'positive', 'metric': 'new_deals', 'message': f'New deals up {deal_change:.0f}% vs previous period', 'change': f'{deal_change:+.0f}%'})

            curr_won = len([l for l in current if l.get('status_id') == 142])
            prev_won = len([l for l in prev if l.get('status_id') == 142])
            if prev_won > 0:
                won_change = (curr_won - prev_won) / prev_won * 100
                if won_change < -20:
                    trend_alerts.append({'type': 'warning', 'metric': 'won_deals', 'message': f'Won deals down {won_change:.0f}%', 'change': f'{won_change:+.0f}%'})
                elif won_change > 30:
                    trend_alerts.append({'type': 'positive', 'metric': 'won_deals', 'message': f'Won deals up {won_change:.0f}%', 'change': f'{won_change:+.0f}%'})

            curr_rev = sum(l.get('price', 0) or 0 for l in current if l.get('status_id') == 142)
            prev_rev = sum(l.get('price', 0) or 0 for l in prev if l.get('status_id') == 142)
            if prev_rev > 0:
                rev_change = (curr_rev - prev_rev) / prev_rev * 100
                if rev_change < -20:
                    trend_alerts.append({'type': 'critical', 'metric': 'revenue', 'message': f'Revenue down {rev_change:.0f}%', 'change': f'{rev_change:+.0f}%'})
                elif rev_change > 30:
                    trend_alerts.append({'type': 'positive', 'metric': 'revenue', 'message': f'Revenue up {rev_change:.0f}%', 'change': f'{rev_change:+.0f}%'})

            if not trend_alerts:
                trend_alerts.append({'type': 'info', 'metric': 'all', 'message': 'All metrics stable — no significant changes detected'})

            return {
                'period_days': days,
                'trend_alerts': trend_alerts,
                'current': {'deals': curr_count, 'won': curr_won, 'revenue': curr_rev},
                'previous': {'deals': prev_count, 'won': prev_won, 'revenue': prev_rev},
                'hint': 'Present trend alerts with direction arrows. Critical/warning first. Suggest investigation for declining metrics.',
            }

        elif action == 'early_warning':
            warnings = []
            stale_high = [l for l in active_leads if (l.get('price') or 0) > 50000 and (now - (l.get('updated_at') or now)) > 5 * 86400]
            if stale_high:
                warnings.append({'type': 'critical', 'category': 'high_value_stalling', 'message': f'{len(stale_high)} high-value deals (>50K) stalling', 'deals': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price'), 'days_inactive': round((now - (l.get('updated_at') or now)) / 86400)} for l in stale_high[:5]]})

            new_leads = [l for l in active_leads if (now - l.get('created_at', now)) < 3 * 86400]
            old_new = [l for l in new_leads if (now - (l.get('updated_at') or now)) > 1 * 86400]
            if old_new:
                warnings.append({'type': 'warning', 'category': 'slow_first_contact', 'message': f'{len(old_new)} new leads without activity in 24h', 'count': len(old_new)})

            from collections import Counter
            user_counts = Counter(l.get('responsible_user_id') for l in active_leads if l.get('responsible_user_id'))
            if user_counts:
                avg_load = sum(user_counts.values()) / len(user_counts)
                overloaded = {uid: cnt for uid, cnt in user_counts.items() if cnt > avg_load * 1.5}
                if overloaded:
                    warnings.append({'type': 'warning', 'category': 'workload_imbalance', 'message': f'{len(overloaded)} users have 50%+ more deals than average', 'count': len(overloaded)})

            if not warnings:
                warnings.append({'type': 'info', 'category': 'all_clear', 'message': 'No early warnings detected — pipeline looks healthy'})

            return {
                'early_warnings': warnings,
                'total_warnings': len([w for w in warnings if w['type'] != 'info']),
                'hint': 'Present early warnings as predictive alerts. Critical first. Suggest immediate actions to prevent deal loss.',
            }

        elif action == 'team':
            from collections import Counter
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            team_alerts = []
            for uid, name in users.items():
                u_leads = [l for l in active_leads if l.get('responsible_user_id') == uid]
                u_stale = [l for l in u_leads if (now - (l.get('updated_at') or now)) > 7 * 86400]
                alerts = []
                if len(u_leads) > 25:
                    alerts.append(f'Overloaded: {len(u_leads)} active deals')
                if u_stale and len(u_stale) > len(u_leads) * 0.4:
                    alerts.append(f'{len(u_stale)}/{len(u_leads)} deals stale (>40%)')
                if len(u_leads) == 0:
                    alerts.append('No active deals assigned')
                no_price = len([l for l in u_leads if not (l.get('price') or 0)])
                if no_price > len(u_leads) * 0.5 and len(u_leads) > 3:
                    alerts.append(f'{no_price} deals without price (>50%)')
                if alerts:
                    team_alerts.append({'user': name, 'user_id': uid, 'active_deals': len(u_leads), 'alerts': alerts})

            return {
                'team_alerts': team_alerts,
                'total_users_with_alerts': len(team_alerts),
                'hint': 'Present per-user alerts. Group by severity. Suggest specific actions for each user.',
            }

        return {'error': f'Unknown alerts action: {action}'}

    async def _handle_compare(self, session, headers, args: dict) -> dict:
        """Compare and analyze CRM data across periods."""
        import time
        from datetime import datetime, timedelta
        action = args.get('action')
        days = args.get('days', 30)
        metric = args.get('metric', 'deals')
        pipeline_id = args.get('pipeline_id')
        now = int(time.time())

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250, 'order[created_at]': 'desc'}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        all_leads = []
        page = 1
        while page <= 4:
            params['page'] = page
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    all_leads.extend(leads)
                    if len(leads) < 250:
                        break
                    page += 1
                else:
                    break

        current_start = now - days * 86400
        prev_start = current_start - days * 86400
        current_leads = [l for l in all_leads if l.get('created_at', 0) >= current_start]
        prev_leads = [l for l in all_leads if prev_start <= l.get('created_at', 0) < current_start]

        if action == 'periods':
            def calc_metrics(leads_list):
                total = len(leads_list)
                revenue = sum(l.get('price', 0) or 0 for l in leads_list)
                won = len([l for l in leads_list if l.get('status_id') == 142])
                lost = len([l for l in leads_list if l.get('status_id') == 143])
                conversion = round(won / max(total, 1) * 100, 1)
                return {'deals': total, 'revenue': revenue, 'won': won, 'lost': lost, 'conversion': f'{conversion}%', 'avg_check': round(revenue / max(won, 1))}

            current_m = calc_metrics(current_leads)
            prev_m = calc_metrics(prev_leads)

            changes = {}
            for key in ['deals', 'revenue', 'won', 'lost']:
                curr_val = current_m[key]
                prev_val = prev_m[key]
                if prev_val > 0:
                    pct = round((curr_val - prev_val) / prev_val * 100, 1)
                    changes[key] = f'{pct:+.1f}%'
                else:
                    changes[key] = 'N/A (no prev data)'

            return {
                'period_days': days,
                'current_period': current_m,
                'previous_period': prev_m,
                'changes': changes,
                'hint': 'Compare periods side by side. Highlight significant changes (>20%). Use arrows ↑↓ for direction. Suggest reasons for changes.',
            }

        elif action == 'trends':
            weeks = {}
            for lead in all_leads:
                created = lead.get('created_at', now)
                dt = datetime.fromtimestamp(created)
                week_start = dt - timedelta(days=dt.weekday())
                key = week_start.strftime('%Y-%m-%d')
                if key not in weeks:
                    weeks[key] = {'new_deals': 0, 'revenue': 0, 'won': 0, 'lost': 0}
                weeks[key]['new_deals'] += 1
                weeks[key]['revenue'] += lead.get('price', 0) or 0
                if lead.get('status_id') == 142:
                    weeks[key]['won'] += 1
                elif lead.get('status_id') == 143:
                    weeks[key]['lost'] += 1

            sorted_weeks = sorted(weeks.items())[-12:]
            metric_key = {'deals': 'new_deals', 'revenue': 'revenue', 'conversion': 'won', 'tasks': 'new_deals', 'velocity': 'won'}.get(metric, 'new_deals')

            values = [w[1].get(metric_key, 0) for w in sorted_weeks]
            if len(values) >= 4:
                first_half_avg = sum(values[:len(values)//2]) / (len(values)//2)
                second_half_avg = sum(values[len(values)//2:]) / (len(values) - len(values)//2)
                trend = 'growing' if second_half_avg > first_half_avg * 1.1 else ('declining' if second_half_avg < first_half_avg * 0.9 else 'stable')
            else:
                trend = 'insufficient_data'

            return {
                'metric': metric,
                'weekly_data': [{'week': w[0], **w[1]} for w in sorted_weeks],
                'trend': trend,
                'hint': f'Show {metric} trend over time. Highlight the overall direction: {trend}. Note any spikes or dips.',
            }

        elif action == 'patterns':
            from collections import Counter
            dow_counts = Counter()
            hour_counts = Counter()
            for lead in all_leads:
                created = lead.get('created_at', now)
                dt = datetime.fromtimestamp(created)
                dow_counts[dt.strftime('%A')] += 1
                hour_counts[dt.hour] += 1

            best_day = dow_counts.most_common(1)[0] if dow_counts else ('N/A', 0)
            best_hours = hour_counts.most_common(3)
            worst_day = dow_counts.most_common()[-1] if dow_counts else ('N/A', 0)

            monthly_conversion = {}
            for lead in all_leads:
                dt = datetime.fromtimestamp(lead.get('created_at', now))
                month = dt.strftime('%Y-%m')
                if month not in monthly_conversion:
                    monthly_conversion[month] = {'total': 0, 'won': 0}
                monthly_conversion[month]['total'] += 1
                if lead.get('status_id') == 142:
                    monthly_conversion[month]['won'] += 1

            return {
                'patterns': {
                    'best_day_for_deals': {'day': best_day[0], 'count': best_day[1]},
                    'worst_day_for_deals': {'day': worst_day[0], 'count': worst_day[1]},
                    'peak_hours': [{'hour': h, 'count': c} for h, c in best_hours],
                    'day_distribution': dict(dow_counts),
                    'monthly_conversion': {k: f'{v["won"]}/{v["total"]} ({round(v["won"]/max(v["total"],1)*100)}%)' for k, v in sorted(monthly_conversion.items())[-6:]},
                },
                'total_analyzed': len(all_leads),
                'hint': 'Present patterns as actionable insights: best days/hours for outreach, seasonal trends in conversion.',
            }

        elif action == 'correlations':
            price_buckets = {'0': [], '1-50K': [], '50K-200K': [], '200K+': []}
            for lead in all_leads:
                price = lead.get('price', 0) or 0
                if price == 0:
                    bucket = '0'
                elif price <= 50000:
                    bucket = '1-50K'
                elif price <= 200000:
                    bucket = '50K-200K'
                else:
                    bucket = '200K+'
                price_buckets[bucket].append(lead)

            correlations = []
            for bucket, leads in price_buckets.items():
                if not leads:
                    continue
                won = len([l for l in leads if l.get('status_id') == 142])
                total = len(leads)
                avg_cycle = 0
                cycles = [(l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in leads if l.get('status_id') == 142]
                if cycles:
                    avg_cycle = round(sum(cycles) / len(cycles), 1)
                correlations.append({
                    'price_range': bucket,
                    'total_deals': total,
                    'won': won,
                    'win_rate': f'{round(won / max(total, 1) * 100)}%',
                    'avg_cycle_days': avg_cycle,
                })

            source_perf = {}
            for lead in all_leads:
                src = 'unknown'
                cf = lead.get('custom_fields_values') or []
                for f in cf:
                    if 'source' in (f.get('field_name') or '').lower() or 'источник' in (f.get('field_name') or '').lower():
                        vals = f.get('values', [])
                        if vals:
                            src = vals[0].get('value', 'unknown')
                if src not in source_perf:
                    source_perf[src] = {'total': 0, 'won': 0, 'revenue': 0}
                source_perf[src]['total'] += 1
                if lead.get('status_id') == 142:
                    source_perf[src]['won'] += 1
                    source_perf[src]['revenue'] += lead.get('price', 0) or 0

            return {
                'price_vs_conversion': correlations,
                'source_performance': {k: {**v, 'win_rate': f'{round(v["won"]/max(v["total"],1)*100)}%'} for k, v in source_perf.items() if v['total'] >= 3},
                'hint': 'Present correlations as insights: which deal sizes convert best, which sources perform best. Suggest focus areas.',
            }

        return {'error': f'Unknown compare action: {action}'}

    async def _handle_automation(self, session, headers, args: dict) -> dict:
        """Smart automation: auto-assign, round-robin, auto follow-up."""
        import time
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        lead_ids = args.get('lead_ids')
        user_ids = args.get('user_ids')
        dry_run = args.get('dry_run', True)
        now = int(time.time())

        uurl = f'{self.kommo_base_url}/api/v4/users'
        async with session.get(uurl, headers=headers) as resp:
            users = []
            if resp.status == 200:
                udata = await resp.json()
                users = udata.get('_embedded', {}).get('users', [])
        if user_ids:
            users = [u for u in users if u.get('id') in user_ids]
        active_users = [u for u in users if u.get('rights', {}).get('is_active', True)]

        if not active_users:
            return {'error': 'No active users found to assign leads to'}

        if action == 'auto_assign':
            if lead_ids:
                leads_to_assign = []
                for lid in lead_ids:
                    lurl = f'{self.kommo_base_url}/api/v4/leads/{lid}'
                    async with session.get(lurl, headers=headers) as resp:
                        if resp.status == 200:
                            leads_to_assign.append(await resp.json())
            else:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[responsible_user_id]': 0, 'limit': 100}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    leads_to_assign = []
                    if resp.status == 200:
                        data = await resp.json()
                        leads_to_assign = data.get('_embedded', {}).get('leads', [])

            if not leads_to_assign:
                return {'message': 'No unassigned leads found', 'leads_checked': True}

            lurl = f'{self.kommo_base_url}/api/v4/leads'
            lparams = {'limit': 250}
            async with session.get(lurl, headers=headers, params=lparams) as resp:
                all_active = []
                if resp.status == 200:
                    data = await resp.json()
                    all_active = [l for l in data.get('_embedded', {}).get('leads', []) if l.get('status_id') not in (142, 143)]

            workload = {u.get('id'): len([l for l in all_active if l.get('responsible_user_id') == u.get('id')]) for u in active_users}

            assignments = []
            for lead in leads_to_assign:
                min_user = min(workload, key=workload.get)
                assignments.append({
                    'lead_id': lead.get('id'),
                    'lead_name': lead.get('name'),
                    'assigned_to_id': min_user,
                    'assigned_to': next((u.get('name') for u in active_users if u.get('id') == min_user), '?'),
                    'user_current_load': workload[min_user],
                })
                workload[min_user] += 1

            if not dry_run:
                for a in assignments:
                    patch_url = f'{self.kommo_base_url}/api/v4/leads/{a["lead_id"]}'
                    async with session.patch(patch_url, headers=headers, json={'responsible_user_id': a['assigned_to_id']}) as resp:
                        a['status'] = 'assigned' if resp.status == 200 else f'error:{resp.status}'

            return {
                'action': 'auto_assign',
                'method': 'by_workload',
                'dry_run': dry_run,
                'assignments': assignments,
                'total': len(assignments),
                'hint': 'Show assignment plan. If dry_run, ask user to confirm with dry_run=false to execute.',
            }

        elif action == 'round_robin':
            if lead_ids:
                leads_to_assign = []
                for lid in lead_ids:
                    lurl = f'{self.kommo_base_url}/api/v4/leads/{lid}'
                    async with session.get(lurl, headers=headers) as resp:
                        if resp.status == 200:
                            leads_to_assign.append(await resp.json())
            else:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'filter[responsible_user_id]': 0, 'limit': 100}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    leads_to_assign = []
                    if resp.status == 200:
                        data = await resp.json()
                        leads_to_assign = data.get('_embedded', {}).get('leads', [])

            if not leads_to_assign:
                return {'message': 'No unassigned leads found'}

            assignments = []
            for i, lead in enumerate(leads_to_assign):
                user = active_users[i % len(active_users)]
                assignments.append({
                    'lead_id': lead.get('id'),
                    'lead_name': lead.get('name'),
                    'assigned_to_id': user.get('id'),
                    'assigned_to': user.get('name'),
                })

            if not dry_run:
                for a in assignments:
                    patch_url = f'{self.kommo_base_url}/api/v4/leads/{a["lead_id"]}'
                    async with session.patch(patch_url, headers=headers, json={'responsible_user_id': a['assigned_to_id']}) as resp:
                        a['status'] = 'assigned' if resp.status == 200 else f'error:{resp.status}'

            return {
                'action': 'round_robin',
                'dry_run': dry_run,
                'assignments': assignments,
                'total': len(assignments),
                'users_in_rotation': [u.get('name') for u in active_users],
                'hint': 'Show round-robin plan. If dry_run, ask user to confirm with dry_run=false.',
            }

        elif action == 'auto_followup':
            days_after = args.get('days_after', 3)
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = [l for l in data.get('_embedded', {}).get('leads', []) if l.get('status_id') not in (142, 143)]

            threshold = now - days_after * 86400
            stale_leads = [l for l in leads if (l.get('updated_at') or now) < threshold]

            needs_followup = []
            for lead in stale_leads[:30]:
                turl = f'{self.kommo_base_url}/api/v4/tasks'
                tparams = {'filter[entity_type]': 'leads', 'filter[entity_id]': lead.get('id'), 'filter[is_completed]': 0, 'limit': 1}
                async with session.get(turl, headers=headers, params=tparams) as resp:
                    has_task = False
                    if resp.status == 200:
                        tdata = await resp.json()
                        has_task = bool(tdata.get('_embedded', {}).get('tasks'))
                if not has_task:
                    needs_followup.append(lead)

            followups = []
            for lead in needs_followup:
                followups.append({
                    'lead_id': lead.get('id'),
                    'lead_name': lead.get('name'),
                    'days_inactive': round((now - (lead.get('updated_at') or now)) / 86400),
                    'responsible_user_id': lead.get('responsible_user_id'),
                })

            if not dry_run and followups:
                deadline = now + 86400
                for f in followups:
                    task_payload = [{
                        'text': f'Follow-up: {f["lead_name"]}',
                        'complete_till': deadline,
                        'entity_id': f['lead_id'],
                        'entity_type': 'leads',
                        'task_type_id': 1,
                        'responsible_user_id': f['responsible_user_id'],
                    }]
                    turl = f'{self.kommo_base_url}/api/v4/tasks'
                    async with session.post(turl, headers=headers, json=task_payload) as resp:
                        f['task_created'] = resp.status == 200

            return {
                'action': 'auto_followup',
                'dry_run': dry_run,
                'days_threshold': days_after,
                'followups_needed': followups,
                'total': len(followups),
                'hint': 'Show leads needing follow-up. If dry_run, ask to confirm with dry_run=false to create tasks.',
            }

        elif action == 'auto_archive':
            days_threshold = args.get('days', 90)
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])

            closed = [l for l in leads if l.get('status_id') in (142, 143)]
            old_closed = [l for l in closed if (now - (l.get('updated_at') or now)) > days_threshold * 86400]

            archive_plan = [{'lead_id': l.get('id'), 'name': l.get('name'), 'status': 'won' if l.get('status_id') == 142 else 'lost', 'days_since_close': round((now - (l.get('updated_at') or now)) / 86400)} for l in old_closed[:50]]

            return {
                'action': 'auto_archive',
                'days_threshold': days_threshold,
                'candidates': archive_plan,
                'total': len(old_closed),
                'hint': 'Present archive candidates. Note: Kommo API does not support archiving directly — suggest deleting or moving to a dedicated archive pipeline.',
            }

        elif action == 'auto_followup_smart':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            followups = []
            created_count = 0
            for l in active:
                last_act = (now - (l.get('updated_at') or now)) / 86400
                price = l.get('price', 0) or 0
                if last_act < 5:
                    continue
                if last_act > 14:
                    task_text = f'URGENT: Follow up on "{l.get("name")}" — {round(last_act)}d inactive'
                    delay = 0
                elif last_act > 7:
                    task_text = f'Follow up on "{l.get("name")}" — {round(last_act)}d since last activity'
                    delay = 1
                else:
                    task_text = f'Check in on "{l.get("name")}" — keep momentum'
                    delay = 2
                complete_till = now + delay * 86400
                payload = [{'text': task_text, 'complete_till': complete_till, 'responsible_user_id': l.get('responsible_user_id'), 'entity_id': l.get('id'), 'entity_type': 'leads', 'task_type_id': 1}]
                async with session.post(f'{self.kommo_base_url}/api/v4/tasks', headers=headers, json=payload) as resp:
                    if resp.status in (200, 201):
                        created_count += 1
                followups.append({
                    'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                    'days_inactive': round(last_act), 'task': task_text,
                    'urgency': 'urgent' if last_act > 14 else ('high' if last_act > 7 else 'normal'),
                })
            followups.sort(key=lambda x: x['days_inactive'], reverse=True)
            return {
                'smart_followups': followups[:20],
                'tasks_created': created_count,
                'total_needing_followup': len(followups),
                'hint': 'Smart follow-up tasks created based on inactivity and deal value. Urgent items need same-day action.',
            }

        return {'error': f'Unknown automation action: {action}'}

    async def _handle_my(self, session, headers, args: dict) -> dict:
        """Personal CRM view: my pipeline, my workload."""
        import time
        action = args.get('action')
        days = args.get('days', 7)
        now = int(time.time())

        aurl = f'{self.kommo_base_url}/api/v4/account'
        async with session.get(aurl, headers=headers) as resp:
            if resp.status != 200:
                return {'error': f'Cannot get account info: {resp.status}'}
            account = await resp.json()
        my_user_id = account.get('current_user_id')
        if not my_user_id:
            return {'error': 'Cannot determine current user ID'}

        if action == 'pipeline':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[responsible_user_id]': my_user_id, 'limit': 250, 'with': 'contacts'}
            async with session.get(url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in leads if l.get('status_id') not in (142, 143)]
            won = [l for l in leads if l.get('status_id') == 142]
            lost = [l for l in leads if l.get('status_id') == 143]

            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                pipelines = {}
                if resp.status == 200:
                    pdata = await resp.json()
                    for p in pdata.get('_embedded', {}).get('pipelines', []):
                        for s in p.get('_embedded', {}).get('statuses', []):
                            pipelines[s.get('id')] = {'pipeline': p.get('name'), 'stage': s.get('name')}

            by_stage = {}
            for lead in active:
                sid = lead.get('status_id')
                info = pipelines.get(sid, {})
                key = f'{info.get("pipeline", "?")} → {info.get("stage", "?")}'
                if key not in by_stage:
                    by_stage[key] = {'count': 0, 'value': 0}
                by_stage[key]['count'] += 1
                by_stage[key]['value'] += lead.get('price', 0) or 0

            stale = [l for l in active if (now - (l.get('updated_at') or now)) > 7 * 86400]

            return {
                'my_user_id': my_user_id,
                'active_deals': len(active),
                'total_pipeline_value': sum(l.get('price', 0) or 0 for l in active),
                'won_deals': len(won),
                'lost_deals': len(lost),
                'stale_deals': len(stale),
                'by_stage': by_stage,
                'top_deals': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0)} for l in sorted(active, key=lambda x: x.get('price', 0) or 0, reverse=True)[:5]],
                'hint': 'Present as personal dashboard. Show pipeline breakdown, highlight stale deals, list top deals by value.',
            }

        elif action == 'workload':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[responsible_user_id]': my_user_id, 'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = [l for l in data.get('_embedded', {}).get('leads', []) if l.get('status_id') not in (142, 143)]

            turl = f'{self.kommo_base_url}/api/v4/tasks'
            tparams = {'filter[responsible_user_id]': my_user_id, 'filter[is_completed]': 0, 'limit': 250}
            async with session.get(turl, headers=headers, params=tparams) as resp:
                tasks = []
                if resp.status == 200:
                    tdata = await resp.json()
                    tasks = tdata.get('_embedded', {}).get('tasks', [])

            overdue = [t for t in tasks if (t.get('complete_till') or now) < now]
            today_end = now + 86400
            today_tasks = [t for t in tasks if now <= (t.get('complete_till') or 0) < today_end]

            return {
                'my_user_id': my_user_id,
                'active_deals': len(leads),
                'pipeline_value': sum(l.get('price', 0) or 0 for l in leads),
                'open_tasks': len(tasks),
                'overdue_tasks': len(overdue),
                'today_tasks': len(today_tasks),
                'workload_score': min(100, len(leads) * 3 + len(tasks) * 2 + len(overdue) * 5),
                'hint': 'Present as workload summary. If workload_score > 70, suggest delegation. Show overdue tasks as priority.',
            }

        elif action == 'team':
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = []
                if resp.status == 200:
                    udata = await resp.json()
                    users = udata.get('_embedded', {}).get('users', [])

            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            team = []
            for user in users:
                uid = user.get('id')
                u_leads = [l for l in active if l.get('responsible_user_id') == uid]
                u_stale = [l for l in u_leads if (now - (l.get('updated_at') or now)) > 7 * 86400]
                team.append({
                    'user': user.get('name'),
                    'user_id': uid,
                    'active_deals': len(u_leads),
                    'pipeline_value': sum(l.get('price', 0) or 0 for l in u_leads),
                    'stale_deals': len(u_stale),
                })
            team.sort(key=lambda x: x['active_deals'], reverse=True)

            return {
                'team': team,
                'total_active': len(active),
                'total_value': sum(l.get('price', 0) or 0 for l in active),
                'hint': 'Present as team overview table. Highlight unbalanced workloads and users with many stale deals.',
            }

        elif action == 'insights':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            won = [l for l in all_leads if l.get('status_id') == 142]
            lost = [l for l in all_leads if l.get('status_id') == 143]

            insights = []
            if active:
                avg_age = sum((now - l.get('created_at', now)) / 86400 for l in active) / len(active)
                if avg_age > 30:
                    insights.append(f'Average deal age is {avg_age:.0f} days — consider cleaning up old deals')
                stale_pct = len([l for l in active if (now - (l.get('updated_at') or now)) > 7 * 86400]) / len(active) * 100
                if stale_pct > 30:
                    insights.append(f'{stale_pct:.0f}% of deals are stale (7+ days) — needs attention')
                no_price = len([l for l in active if not (l.get('price') or 0)]) / len(active) * 100
                if no_price > 20:
                    insights.append(f'{no_price:.0f}% of deals have no price — pipeline value is underestimated')

            if won and lost:
                win_rate = len(won) / (len(won) + len(lost)) * 100
                insights.append(f'Win rate: {win_rate:.0f}% ({len(won)} won / {len(lost)} lost)')
                avg_won_cycle = sum((l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in won) / len(won)
                insights.append(f'Average sales cycle: {avg_won_cycle:.0f} days')

            if not insights:
                insights.append('Pipeline looks healthy — no immediate concerns')

            return {
                'active_deals': len(active),
                'pipeline_value': sum(l.get('price', 0) or 0 for l in active),
                'insights': insights,
                'hint': 'Present insights as actionable recommendations. Prioritize by business impact.',
            }

        return {'error': f'Unknown my action: {action}'}

    async def _handle_gamification(self, session, headers, args: dict) -> dict:
        """Team gamification: leaderboards, achievements, challenges, points."""
        import time
        action = args.get('action')
        days = args.get('days', 30)
        metric = args.get('metric', 'deals_won')
        now = int(time.time())
        cutoff = now - days * 86400

        uurl = f'{self.kommo_base_url}/api/v4/users'
        async with session.get(uurl, headers=headers) as resp:
            users = []
            if resp.status == 200:
                udata = await resp.json()
                users = udata.get('_embedded', {}).get('users', [])
        user_map = {u.get('id'): u.get('name', f'User #{u.get("id")}') for u in users}

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250, 'order[created_at]': 'desc'}
        all_leads = []
        page = 1
        while page <= 4:
            params['page'] = page
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    all_leads.extend(leads)
                    if len(leads) < 250:
                        break
                    page += 1
                else:
                    break

        if action == 'leaderboard':
            scores = {}
            for lead in all_leads:
                uid = lead.get('responsible_user_id')
                if not uid or uid not in user_map:
                    continue
                if uid not in scores:
                    scores[uid] = {'deals_won': 0, 'revenue': 0, 'total_deals': 0, 'conversion': 0}
                if lead.get('created_at', 0) >= cutoff:
                    scores[uid]['total_deals'] += 1
                if lead.get('status_id') == 142 and lead.get('updated_at', 0) >= cutoff:
                    scores[uid]['deals_won'] += 1
                    scores[uid]['revenue'] += lead.get('price', 0) or 0

            for uid in scores:
                total = scores[uid]['total_deals']
                scores[uid]['conversion'] = round(scores[uid]['deals_won'] / max(total, 1) * 100, 1)

            leaderboard = sorted(
                [{'rank': 0, 'user': user_map.get(uid, '?'), 'user_id': uid, **s} for uid, s in scores.items()],
                key=lambda x: x.get(metric, 0), reverse=True
            )
            for i, entry in enumerate(leaderboard):
                entry['rank'] = i + 1

            return {
                'metric': metric,
                'period_days': days,
                'leaderboard': leaderboard,
                'hint': 'Present as a ranked leaderboard with medals: 🥇🥈🥉. Highlight the leader and any close competitions.',
            }

        elif action == 'achievements':
            achievements = []
            for uid, name in user_map.items():
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won = [l for l in user_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                badges = []
                if len(won) >= 10:
                    badges.append('🏆 Deal Machine (10+ deals)')
                elif len(won) >= 5:
                    badges.append('⭐ Rising Star (5+ deals)')
                total_rev = sum(l.get('price', 0) or 0 for l in won)
                if total_rev >= 1000000:
                    badges.append('💎 Million Maker')
                elif total_rev >= 500000:
                    badges.append('💰 Big Closer (500K+)')
                big_deals = [l for l in won if (l.get('price') or 0) >= 100000]
                if big_deals:
                    badges.append(f'🎯 Whale Hunter ({len(big_deals)} big deals)')
                fast_deals = [l for l in won if (l.get('updated_at', now) - l.get('created_at', now)) < 7 * 86400]
                if fast_deals:
                    badges.append(f'⚡ Speed Closer ({len(fast_deals)} fast wins)')
                if badges:
                    achievements.append({'user': name, 'user_id': uid, 'badges': badges, 'deals_won': len(won), 'revenue': total_rev})

            return {
                'period_days': days,
                'achievements': achievements,
                'hint': 'Present achievements with emoji badges. Celebrate top performers. Encourage others with "almost there" messages.',
            }

        elif action == 'challenges':
            user_stats = {}
            for uid, name in user_map.items():
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won = [l for l in user_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                user_stats[uid] = {'name': name, 'won': len(won), 'revenue': sum(l.get('price', 0) or 0 for l in won)}

            challenges = [
                {
                    'name': '🏁 Deal Sprint',
                    'description': f'Close the most deals in {days} days',
                    'metric': 'deals_won',
                    'standings': sorted([{'user': s['name'], 'score': s['won']} for s in user_stats.values()], key=lambda x: x['score'], reverse=True)[:5],
                },
                {
                    'name': '💰 Revenue Race',
                    'description': f'Highest revenue in {days} days',
                    'metric': 'revenue',
                    'standings': sorted([{'user': s['name'], 'score': s['revenue']} for s in user_stats.values()], key=lambda x: x['score'], reverse=True)[:5],
                },
            ]

            return {
                'period_days': days,
                'challenges': challenges,
                'hint': 'Present as active challenges with current standings. Show progress bars. Encourage competition.',
            }

        elif action == 'points':
            points = {}
            for uid, name in user_map.items():
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won = [l for l in user_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                score = 0
                breakdown = {}
                deal_pts = len(won) * 10
                score += deal_pts
                breakdown['deals_closed'] = f'{len(won)} x 10 = {deal_pts}'
                rev = sum(l.get('price', 0) or 0 for l in won)
                rev_pts = round(rev / 10000)
                score += rev_pts
                breakdown['revenue_bonus'] = f'{rev} / 10K = {rev_pts}'
                big = len([l for l in won if (l.get('price') or 0) >= 100000])
                big_pts = big * 25
                score += big_pts
                breakdown['big_deals'] = f'{big} x 25 = {big_pts}'
                fast = len([l for l in won if (l.get('updated_at', now) - l.get('created_at', now)) < 7 * 86400])
                fast_pts = fast * 15
                score += fast_pts
                breakdown['fast_closes'] = f'{fast} x 15 = {fast_pts}'
                if score > 0:
                    points[uid] = {'user': name, 'total_points': score, 'breakdown': breakdown}

            ranked = sorted(points.values(), key=lambda x: x['total_points'], reverse=True)
            return {
                'period_days': days,
                'points': ranked,
                'hint': 'Present as points breakdown per user. Show total and how points were earned. Gamify with levels.',
            }

        elif action == 'onboarding':
            new_hire_threshold = days
            onboarding_stats = []
            for uid, name in user_map.items():
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won = [l for l in user_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                lost = [l for l in user_leads if l.get('status_id') == 143 and l.get('updated_at', 0) >= cutoff]
                total_closed = len(won) + len(lost)
                active = [l for l in user_leads if l.get('status_id') not in (142, 143)]

                milestones = []
                if len(won) >= 1:
                    milestones.append('First deal closed')
                if len(won) >= 5:
                    milestones.append('5 deals milestone')
                if len(won) >= 10:
                    milestones.append('10 deals — fully ramped')
                revenue = sum(l.get('price', 0) or 0 for l in won)
                if revenue >= 100000:
                    milestones.append('100K revenue milestone')
                conversion = len(won) / max(total_closed, 1) * 100

                ramp_status = 'ramped' if len(won) >= 10 else ('progressing' if len(won) >= 3 else 'onboarding')
                onboarding_stats.append({
                    'user': name,
                    'deals_won': len(won),
                    'deals_lost': len(lost),
                    'conversion': f'{conversion:.0f}%',
                    'revenue': revenue,
                    'active_deals': len(active),
                    'milestones': milestones,
                    'ramp_status': ramp_status,
                })

            return {
                'period_days': days,
                'onboarding': onboarding_stats,
                'hint': 'Present as onboarding progress tracker. Show milestones achieved. Compare new hires with team average. Encourage with next milestone targets.',
            }

        elif action == 'badges':
            badge_defs = [
                {'id': 'first_deal', 'name': '🏆 First Deal', 'desc': 'Close your first deal', 'check': lambda s: s['won'] >= 1},
                {'id': 'deal_machine', 'name': '⚡ Deal Machine', 'desc': 'Close 10+ deals', 'check': lambda s: s['won'] >= 10},
                {'id': 'whale_hunter', 'name': '🐋 Whale Hunter', 'desc': 'Close a deal over 100k', 'check': lambda s: s['max_deal'] >= 100000},
                {'id': 'speed_closer', 'name': '🚀 Speed Closer', 'desc': 'Close a deal in under 7 days', 'check': lambda s: s['fastest_cycle'] < 7},
                {'id': 'consistent', 'name': '📈 Consistent', 'desc': 'Win rate above 40%', 'check': lambda s: s['win_rate'] > 0.4},
                {'id': 'volume_king', 'name': '👑 Volume King', 'desc': 'Revenue over 500k', 'check': lambda s: s['revenue'] >= 500000},
                {'id': 'active_player', 'name': '🔥 Active Player', 'desc': '20+ deals in period', 'check': lambda s: s['total'] >= 20},
                {'id': 'perfectionist', 'name': '💎 Perfectionist', 'desc': 'Win rate above 60%', 'check': lambda s: s['win_rate'] > 0.6 and s['total'] >= 5},
            ]
            user_badges = {}
            for uid, stats in user_stats.items():
                earned = []
                for badge in badge_defs:
                    if badge['check'](stats):
                        earned.append({'id': badge['id'], 'name': badge['name'], 'desc': badge['desc']})
                user_badges[uid] = {
                    'user': users.get(uid, f'User {uid}'),
                    'badges': earned,
                    'count': len(earned),
                    'total_possible': len(badge_defs),
                }
            results = sorted(user_badges.values(), key=lambda x: x['count'], reverse=True)
            return {
                'user_badges': results,
                'badge_catalog': [{'name': b['name'], 'desc': b['desc']} for b in badge_defs],
                'hint': 'Present badges per user. Show earned vs total. Celebrate top badge holders. Motivate others to earn more.',
            }

        elif action == 'daily_quests':
            quests = []
            for uid, stats in user_stats.items():
                user_quests = []
                if stats['won'] == 0:
                    user_quests.append({'quest': 'Close your first deal today!', 'reward': '50 pts', 'difficulty': 'hard'})
                if stats.get('active', 0) > 0:
                    user_quests.append({'quest': 'Follow up on 3 active deals', 'reward': '20 pts', 'difficulty': 'easy'})
                user_quests.append({'quest': 'Make 5 calls today', 'reward': '15 pts', 'difficulty': 'medium'})
                user_quests.append({'quest': 'Update all deal stages', 'reward': '10 pts', 'difficulty': 'easy'})
                if stats['revenue'] < 50000:
                    user_quests.append({'quest': 'Qualify a deal over 50k', 'reward': '30 pts', 'difficulty': 'hard'})
                quests.append({
                    'user': users.get(uid, f'User {uid}'), 'user_id': uid,
                    'quests': user_quests[:4],
                })
            return {
                'daily_quests': quests,
                'hint': 'Present daily quests per user. Show difficulty and rewards. Encourage completion for points.',
            }

        elif action == 'streaks':
            streak_data = []
            for uid, stats in user_stats.items():
                streak_data.append({
                    'user': users.get(uid, f'User {uid}'), 'user_id': uid,
                    'current_streak': min(stats['won'], 7),
                    'best_streak': stats['won'],
                    'active_days': min(stats['total'], days),
                    'streak_type': 'winning' if stats['won'] > 0 else 'activity',
                    'bonus': f'+{min(stats["won"], 7) * 10}% points' if stats['won'] > 0 else 'No active streak',
                })
            streak_data.sort(key=lambda x: x['current_streak'], reverse=True)
            return {
                'streaks': streak_data,
                'hint': 'Present performance streaks. Longer streaks = higher point multipliers. Encourage maintaining streaks.',
            }

        return {'error': f'Unknown gamification action: {action}'}

    async def _handle_loss_analysis(self, session, headers, args: dict) -> dict:
        """Deep analysis of lost deals."""
        import time
        from datetime import datetime
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        days = args.get('days', 90)
        now = int(time.time())
        cutoff = now - days * 86400

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'filter[statuses][0][status_id]': 143, 'limit': 250, 'order[updated_at]': 'desc'}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        lost_leads = []
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                lost_leads = data.get('_embedded', {}).get('leads', [])
        recent_lost = [l for l in lost_leads if l.get('updated_at', 0) >= cutoff]

        if action == 'reasons':
            loss_notes = []
            for lead in recent_lost[:20]:
                nurl = f'{self.kommo_base_url}/api/v4/leads/{lead["id"]}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 5}) as resp:
                    if resp.status == 200:
                        ndata = await resp.json()
                        for n in ndata.get('_embedded', {}).get('notes', []):
                            text = n.get('params', {}).get('text', '') if isinstance(n.get('params'), dict) else ''
                            if text:
                                loss_notes.append({'lead': lead.get('name'), 'lead_id': lead.get('id'), 'note': text[:200], 'price': lead.get('price', 0)})

            price_ranges = {'no_price': 0, 'small (<50K)': 0, 'medium (50-200K)': 0, 'large (>200K)': 0}
            for l in recent_lost:
                p = l.get('price', 0) or 0
                if p == 0: price_ranges['no_price'] += 1
                elif p < 50000: price_ranges['small (<50K)'] += 1
                elif p < 200000: price_ranges['medium (50-200K)'] += 1
                else: price_ranges['large (>200K)'] += 1

            return {
                'total_lost': len(recent_lost),
                'total_lost_value': sum(l.get('price', 0) or 0 for l in recent_lost),
                'by_price_range': price_ranges,
                'loss_notes_sample': loss_notes[:10],
                'hint': 'Analyze loss notes for common themes. Group by reason category. Suggest preventive actions for top reasons.',
            }

        elif action == 'patterns':
            by_month = {}
            by_dow = {}
            by_age = {'<7d': 0, '7-30d': 0, '30-60d': 0, '60-90d': 0, '>90d': 0}
            for l in recent_lost:
                dt = datetime.fromtimestamp(l.get('updated_at', now))
                month = dt.strftime('%Y-%m')
                dow = dt.strftime('%A')
                by_month[month] = by_month.get(month, 0) + 1
                by_dow[dow] = by_dow.get(dow, 0) + 1
                age = (l.get('updated_at', now) - l.get('created_at', now)) / 86400
                if age < 7: by_age['<7d'] += 1
                elif age < 30: by_age['7-30d'] += 1
                elif age < 60: by_age['30-60d'] += 1
                elif age < 90: by_age['60-90d'] += 1
                else: by_age['>90d'] += 1

            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                stage_map = {}
                if resp.status == 200:
                    pdata = await resp.json()
                    for p in pdata.get('_embedded', {}).get('pipelines', []):
                        for s in p.get('_embedded', {}).get('statuses', []):
                            stage_map[s.get('id')] = s.get('name')

            return {
                'total_lost': len(recent_lost),
                'by_month': dict(sorted(by_month.items())),
                'by_day_of_week': by_dow,
                'by_deal_age': by_age,
                'avg_loss_age_days': round(sum((l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in recent_lost) / max(len(recent_lost), 1), 1),
                'hint': 'Identify patterns: when deals are lost most, at what age. Suggest process improvements based on patterns.',
            }

        elif action == 'by_manager':
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            url2 = f'{self.kommo_base_url}/api/v4/leads'
            params2 = {'filter[statuses][0][status_id]': 142, 'limit': 250}
            won_leads = []
            async with session.get(url2, headers=headers, params=params2) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])

            manager_stats = {}
            for uid, name in users.items():
                u_lost = [l for l in recent_lost if l.get('responsible_user_id') == uid]
                u_won = [l for l in won_leads if l.get('responsible_user_id') == uid]
                if not u_lost and not u_won:
                    continue
                total = len(u_lost) + len(u_won)
                manager_stats[uid] = {
                    'manager': name,
                    'lost': len(u_lost),
                    'won': len(u_won),
                    'loss_rate': f'{len(u_lost) / max(total, 1) * 100:.0f}%',
                    'lost_value': sum(l.get('price', 0) or 0 for l in u_lost),
                    'avg_loss_age': round(sum((l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in u_lost) / max(len(u_lost), 1), 1) if u_lost else 0,
                }

            ranked = sorted(manager_stats.values(), key=lambda x: x['lost'], reverse=True)
            return {
                'period_days': days,
                'by_manager': ranked,
                'hint': 'Compare managers by loss rate, not just count. Identify who needs coaching. Look at avg loss age for early warning patterns.',
            }

        return {'error': f'Unknown loss_analysis action: {action}'}

    async def _handle_smart_time(self, session, headers, args: dict) -> dict:
        """Smart timing analysis: best call time, customer journey."""
        import time
        from datetime import datetime
        from collections import Counter
        action = args.get('action')
        days = args.get('days', 90)
        now = int(time.time())
        cutoff = now - days * 86400

        if action == 'best_call_time':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[statuses][0][status_id]': 142, 'limit': 250}
            won_leads = []
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])

            hour_success = Counter()
            dow_success = Counter()
            for lead in won_leads:
                created = lead.get('created_at', now)
                dt = datetime.fromtimestamp(created)
                hour_success[dt.hour] += 1
                dow_success[dt.strftime('%A')] += 1

            best_hours = hour_success.most_common(5)
            best_days = dow_success.most_common(7)
            peak_hour = best_hours[0] if best_hours else (12, 0)

            return {
                'best_hours': [{'hour': f'{h}:00-{h+1}:00', 'won_deals': c} for h, c in best_hours],
                'best_days': [{'day': d, 'won_deals': c} for d, c in best_days],
                'peak_hour': f'{peak_hour[0]}:00',
                'total_analyzed': len(won_leads),
                'hint': 'Present as optimal contact schedule. Recommend specific time slots for calls. Note that this is based on deal creation times of won deals.',
            }

        elif action == 'customer_journey':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[statuses][0][status_id]': 142, 'limit': 250}
            won_leads = []
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])

            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                pipelines = {}
                if resp.status == 200:
                    pdata = await resp.json()
                    for p in pdata.get('_embedded', {}).get('pipelines', []):
                        stages = [s.get('name') for s in p.get('_embedded', {}).get('statuses', []) if s.get('id') not in (142, 143)]
                        pipelines[p.get('id')] = {'name': p.get('name'), 'stages': stages, 'stage_count': len(stages)}

            cycles = [(l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in won_leads]
            prices = [l.get('price', 0) or 0 for l in won_leads if (l.get('price') or 0) > 0]

            fast_deals = [l for l in won_leads if (l.get('updated_at', now) - l.get('created_at', now)) < 14 * 86400]
            slow_deals = [l for l in won_leads if (l.get('updated_at', now) - l.get('created_at', now)) > 60 * 86400]

            return {
                'total_won_analyzed': len(won_leads),
                'avg_cycle_days': round(sum(cycles) / max(len(cycles), 1), 1),
                'median_cycle_days': round(sorted(cycles)[len(cycles)//2], 1) if cycles else 0,
                'fastest_deal_days': round(min(cycles), 1) if cycles else 0,
                'slowest_deal_days': round(max(cycles), 1) if cycles else 0,
                'avg_deal_value': round(sum(prices) / max(len(prices), 1)),
                'fast_deals_count': len(fast_deals),
                'slow_deals_count': len(slow_deals),
                'pipelines': {pid: {'name': p['name'], 'stages': p['stages']} for pid, p in pipelines.items()},
                'hint': 'Present as customer journey map: stages → avg time → close. Compare fast vs slow deals. Suggest where to accelerate.',
            }

        elif action == 'time_to_purchase':
            won = [l for l in all_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
            if not won:
                return {'message': 'No won deals in period', 'hint': 'Try a longer period.'}
            cycles = []
            for l in won:
                created = l.get('created_at', 0)
                closed = l.get('updated_at', 0)
                if created and closed:
                    days_to_close = (closed - created) / 86400
                    cycles.append({'lead_id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0), 'days': round(days_to_close)})
            cycles.sort(key=lambda x: x['days'])
            avg_days = sum(c['days'] for c in cycles) / max(len(cycles), 1)
            median_idx = len(cycles) // 2
            median_days = cycles[median_idx]['days'] if cycles else 0
            fast = [c for c in cycles if c['days'] <= avg_days * 0.5]
            slow = [c for c in cycles if c['days'] >= avg_days * 2]
            return {
                'avg_days_to_purchase': round(avg_days),
                'median_days': median_days,
                'fastest': cycles[:5],
                'slowest': cycles[-5:],
                'fast_deals_count': len(fast),
                'slow_deals_count': len(slow),
                'total_analyzed': len(cycles),
                'hint': 'Present time-to-purchase analysis. Compare fast vs slow deals. Suggest how to shorten the cycle based on fast deal patterns.',
            }

        elif action == 'lead_response':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if args.get('pipeline_id'):
                params['filter[pipeline_id]'] = args['pipeline_id']
            async with session.get(url, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
            recent = [l for l in leads if l.get('created_at', 0) >= cutoff]
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            user_response = {}
            for l in recent:
                uid = l.get('responsible_user_id')
                if not uid:
                    continue
                created = l.get('created_at', 0)
                updated = l.get('updated_at', 0)
                response_time = (updated - created) / 3600 if updated > created else 0
                if uid not in user_response:
                    user_response[uid] = {'times': [], 'name': users.get(uid, f'User {uid}')}
                user_response[uid]['times'].append(response_time)
            results = []
            for uid, data in user_response.items():
                avg_hours = sum(data['times']) / max(len(data['times']), 1)
                results.append({
                    'user': data['name'], 'user_id': uid,
                    'avg_response_hours': round(avg_hours, 1),
                    'leads_processed': len(data['times']),
                    'rating': 'excellent' if avg_hours < 1 else ('good' if avg_hours < 4 else ('fair' if avg_hours < 24 else 'slow')),
                })
            results.sort(key=lambda x: x['avg_response_hours'])
            return {
                'response_times': results,
                'team_avg_hours': round(sum(r['avg_response_hours'] for r in results) / max(len(results), 1), 1),
                'hint': 'Present lead response times by manager. <1h is excellent, <4h good, >24h needs improvement. Suggest SLA targets.',
            }

        return {'error': f'Unknown smart_time action: {action}'}

    async def _handle_team_planner(self, session, headers, args: dict) -> dict:
        """Team capacity planning."""
        import time
        action = args.get('action')
        days = args.get('days', 14)
        now = int(time.time())

        if action == 'capacity':
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = []
                if resp.status == 200:
                    udata = await resp.json()
                    users = udata.get('_embedded', {}).get('users', [])

            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]

            turl = f'{self.kommo_base_url}/api/v4/tasks'
            tparams = {'filter[is_completed]': 0, 'limit': 250}
            async with session.get(turl, headers=headers, params=tparams) as resp:
                all_tasks = []
                if resp.status == 200:
                    tdata = await resp.json()
                    all_tasks = tdata.get('_embedded', {}).get('tasks', [])

            capacity = []
            for user in users:
                uid = user.get('id')
                u_deals = len([l for l in active if l.get('responsible_user_id') == uid])
                u_tasks = len([t for t in all_tasks if t.get('responsible_user_id') == uid])
                u_overdue = len([t for t in all_tasks if t.get('responsible_user_id') == uid and (t.get('complete_till') or now) < now])
                load_score = u_deals * 3 + u_tasks * 2 + u_overdue * 5
                max_capacity = 100
                available = max(0, max_capacity - load_score)
                est_new_deals = available // 3

                capacity.append({
                    'user': user.get('name'),
                    'user_id': uid,
                    'current_deals': u_deals,
                    'open_tasks': u_tasks,
                    'overdue_tasks': u_overdue,
                    'load_score': min(load_score, 100),
                    'available_capacity': f'{available}%',
                    'can_take_new_deals': est_new_deals,
                    'status': 'overloaded' if load_score > 80 else ('busy' if load_score > 50 else 'available'),
                })

            capacity.sort(key=lambda x: x['load_score'])
            return {
                'planning_horizon_days': days,
                'team_capacity': capacity,
                'total_available_slots': sum(c['can_take_new_deals'] for c in capacity),
                'overloaded_count': len([c for c in capacity if c['status'] == 'overloaded']),
                'hint': 'Present as capacity planning table. Color-code by status. Recommend rebalancing if some are overloaded while others are available.',
            }

        elif action == 'forecast':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'order[created_at]': 'desc'}
            all_leads = []
            page = 1
            while page <= 3:
                params['page'] = page
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        leads = data.get('_embedded', {}).get('leads', [])
                        all_leads.extend(leads)
                        if len(leads) < 250:
                            break
                        page += 1
                    else:
                        break

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            recent_won = [l for l in all_leads if l.get('status_id') == 142 and (now - (l.get('updated_at') or now)) < 30 * 86400]
            avg_deals_per_user = len(active) / max(len(users), 1)
            est_new_per_week = len([l for l in all_leads if (now - l.get('created_at', now)) < 7 * 86400])

            forecast = []
            for user in users:
                uid = user.get('id')
                u_active = len([l for l in active if l.get('responsible_user_id') == uid])
                u_won_month = len([l for l in recent_won if l.get('responsible_user_id') == uid])
                est_incoming = round(est_new_per_week / max(len(users), 1))
                projected_load = u_active + est_incoming * (days // 7) - u_won_month
                forecast.append({
                    'user': user.get('name'),
                    'current_deals': u_active,
                    'est_new_per_week': est_incoming,
                    'est_closings_per_month': u_won_month,
                    'projected_load_in_days': max(0, projected_load),
                    'trend': 'growing' if projected_load > u_active * 1.2 else ('shrinking' if projected_load < u_active * 0.8 else 'stable'),
                })

            return {
                'forecast_horizon_days': days,
                'team_forecast': forecast,
                'est_new_deals_per_week': est_new_per_week,
                'hint': 'Present as workload forecast. Highlight users whose load is growing. Suggest preemptive rebalancing.',
            }

        return {'error': f'Unknown team_planner action: {action}'}

    async def _handle_segments(self, session, headers, args: dict) -> dict:
        """Customer segmentation: by volume, lookalike, best manager, basket."""
        import time
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        days = args.get('days', 90)
        now = int(time.time())

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250, 'order[created_at]': 'desc', 'with': 'contacts'}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        all_leads = []
        page = 1
        while page <= 4:
            params['page'] = page
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    all_leads.extend(leads)
                    if len(leads) < 250:
                        break
                    page += 1
                else:
                    break

        if action == 'by_volume':
            segments = {
                'enterprise (>500K)': {'count': 0, 'value': 0, 'won': 0},
                'mid-market (100-500K)': {'count': 0, 'value': 0, 'won': 0},
                'smb (10-100K)': {'count': 0, 'value': 0, 'won': 0},
                'micro (<10K)': {'count': 0, 'value': 0, 'won': 0},
                'no_price': {'count': 0, 'value': 0, 'won': 0},
            }
            for l in all_leads:
                p = l.get('price', 0) or 0
                if p >= 500000: seg = 'enterprise (>500K)'
                elif p >= 100000: seg = 'mid-market (100-500K)'
                elif p >= 10000: seg = 'smb (10-100K)'
                elif p > 0: seg = 'micro (<10K)'
                else: seg = 'no_price'
                segments[seg]['count'] += 1
                segments[seg]['value'] += p
                if l.get('status_id') == 142:
                    segments[seg]['won'] += 1

            for seg in segments:
                total = segments[seg]['count']
                segments[seg]['win_rate'] = f'{segments[seg]["won"] / max(total, 1) * 100:.0f}%'
                segments[seg]['avg_check'] = round(segments[seg]['value'] / max(total, 1))

            return {
                'segments': segments,
                'total_leads': len(all_leads),
                'hint': 'Present as segment breakdown. Highlight which segment has best win rate and highest value. Suggest focus areas.',
            }

        elif action == 'lookalike':
            lead_id = args.get('lead_id')
            if not lead_id:
                won = [l for l in all_leads if l.get('status_id') == 142]
                if won:
                    won.sort(key=lambda x: x.get('price', 0) or 0, reverse=True)
                    lead_id = won[0].get('id')
                else:
                    return {'error': 'No lead_id provided and no won deals to use as reference'}

            ref = next((l for l in all_leads if l.get('id') == lead_id), None)
            if not ref:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers) as resp:
                    if resp.status == 200:
                        ref = await resp.json()
                    else:
                        return {'error': f'Lead {lead_id} not found'}

            ref_price = ref.get('price', 0) or 0
            ref_pipeline = ref.get('pipeline_id')
            active = [l for l in all_leads if l.get('status_id') not in (142, 143) and l.get('id') != lead_id]

            scored = []
            for l in active:
                similarity = 0
                if l.get('pipeline_id') == ref_pipeline:
                    similarity += 30
                price = l.get('price', 0) or 0
                if ref_price > 0 and price > 0:
                    ratio = min(price, ref_price) / max(price, ref_price)
                    similarity += round(ratio * 40)
                if l.get('_embedded', {}).get('contacts') and ref.get('_embedded', {}).get('contacts'):
                    similarity += 10
                if similarity >= 30:
                    scored.append({'lead_id': l.get('id'), 'name': l.get('name'), 'price': price, 'similarity': f'{similarity}%'})

            scored.sort(key=lambda x: int(x['similarity'].rstrip('%')), reverse=True)
            return {
                'reference_deal': {'id': lead_id, 'name': ref.get('name'), 'price': ref_price},
                'similar_deals': scored[:10],
                'total_found': len(scored),
                'hint': 'Present as lookalike deals ranked by similarity. Suggest applying same strategy as the reference deal.',
            }

        elif action == 'best_manager':
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            segments = {'small': (0, 50000), 'medium': (50000, 200000), 'large': (200000, float('inf'))}
            results = {}
            for seg_name, (low, high) in segments.items():
                seg_leads = [l for l in all_leads if low <= (l.get('price') or 0) < high]
                manager_perf = {}
                for uid, name in users.items():
                    u_leads = [l for l in seg_leads if l.get('responsible_user_id') == uid]
                    u_won = [l for l in u_leads if l.get('status_id') == 142]
                    if len(u_leads) >= 3:
                        manager_perf[name] = {
                            'total': len(u_leads),
                            'won': len(u_won),
                            'win_rate': f'{len(u_won) / len(u_leads) * 100:.0f}%',
                            'revenue': sum(l.get('price', 0) or 0 for l in u_won),
                        }
                if manager_perf:
                    best = max(manager_perf.items(), key=lambda x: int(x[1]['win_rate'].rstrip('%')))
                    results[seg_name] = {'best_manager': best[0], **best[1], 'all_managers': manager_perf}

            return {
                'segment_champions': results,
                'hint': 'Present which manager is best for each deal size segment. Suggest routing rules based on strengths.',
            }

        elif action == 'basket':
            catalog_url = f'{self.kommo_base_url}/api/v4/catalogs'
            async with session.get(catalog_url, headers=headers) as resp:
                catalogs = []
                if resp.status == 200:
                    cdata = await resp.json()
                    catalogs = cdata.get('_embedded', {}).get('catalogs', [])

            if not catalogs:
                price_segments = {}
                for l in all_leads:
                    p = l.get('price', 0) or 0
                    if p == 0: continue
                    tags = [t.get('name') for t in (l.get('_embedded', {}).get('tags') or [])]
                    tag_key = ', '.join(tags) if tags else 'no_tags'
                    if tag_key not in price_segments:
                        price_segments[tag_key] = {'count': 0, 'total_value': 0, 'avg_value': 0}
                    price_segments[tag_key]['count'] += 1
                    price_segments[tag_key]['total_value'] += p

                for k in price_segments:
                    price_segments[k]['avg_value'] = round(price_segments[k]['total_value'] / max(price_segments[k]['count'], 1))

                return {
                    'note': 'No product catalogs found. Showing deal analysis by tags instead.',
                    'by_tags': dict(sorted(price_segments.items(), key=lambda x: x[1]['total_value'], reverse=True)[:10]),
                    'hint': 'Present tag-based analysis as product mix proxy. Suggest creating product catalogs for better basket analysis.',
                }

            results = {}
            for cat in catalogs[:3]:
                cid = cat.get('id')
                eurl = f'{self.kommo_base_url}/api/v4/catalogs/{cid}/elements'
                async with session.get(eurl, headers=headers, params={'limit': 50}) as resp:
                    elements = []
                    if resp.status == 200:
                        edata = await resp.json()
                        elements = edata.get('_embedded', {}).get('elements', [])
                results[cat.get('name')] = {
                    'total_products': len(elements),
                    'products': [{'name': e.get('name'), 'id': e.get('id')} for e in elements[:10]],
                }

            return {
                'catalogs': results,
                'hint': 'Present product catalog overview. For deeper basket analysis, link products to deals via catalog elements.',
            }

        elif action == 'by_behavior':
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            segments = {'hot': [], 'warm': [], 'cold': [], 'frozen': []}
            for l in active:
                last_activity = (now - (l.get('updated_at') or now)) / 86400
                if last_activity < 3:
                    segments['hot'].append(l)
                elif last_activity < 7:
                    segments['warm'].append(l)
                elif last_activity < 30:
                    segments['cold'].append(l)
                else:
                    segments['frozen'].append(l)

            result = {}
            for seg_name, seg_leads in segments.items():
                result[seg_name] = {
                    'count': len(seg_leads),
                    'value': sum(l.get('price', 0) or 0 for l in seg_leads),
                    'avg_price': round(sum(l.get('price', 0) or 0 for l in seg_leads) / max(len(seg_leads), 1)),
                    'sample': [{'id': l.get('id'), 'name': l.get('name'), 'days_inactive': round((now - (l.get('updated_at') or now)) / 86400)} for l in seg_leads[:3]],
                }

            return {
                'behavior_segments': result,
                'total_active': len(active),
                'hint': 'Present as activity-based segments. Hot = engaged, Frozen = needs reactivation. Suggest actions per segment.',
            }

        elif action == 'retention':
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            won = [l for l in all_leads if l.get('status_id') == 142]
            contact_deals = {}
            for l in won:
                contacts = l.get('_embedded', {}).get('contacts', [])
                for c in contacts:
                    cid = c.get('id')
                    if cid not in contact_deals:
                        contact_deals[cid] = []
                    contact_deals[cid].append(l)

            repeat_clients = {cid: deals for cid, deals in contact_deals.items() if len(deals) > 1}

            manager_retention = {}
            for uid, name in users.items():
                u_won = [l for l in won if l.get('responsible_user_id') == uid]
                u_contacts = set()
                u_repeat = 0
                for l in u_won:
                    for c in l.get('_embedded', {}).get('contacts', []):
                        cid = c.get('id')
                        if cid in u_contacts:
                            u_repeat += 1
                        u_contacts.add(cid)
                if len(u_contacts) >= 3:
                    manager_retention[name] = {
                        'total_clients': len(u_contacts),
                        'repeat_clients': u_repeat,
                        'retention_rate': f'{u_repeat / max(len(u_contacts), 1) * 100:.0f}%',
                        'total_won': len(u_won),
                    }

            return {
                'total_repeat_clients': len(repeat_clients),
                'total_unique_clients': len(contact_deals),
                'overall_retention': f'{len(repeat_clients) / max(len(contact_deals), 1) * 100:.0f}%',
                'by_manager': dict(sorted(manager_retention.items(), key=lambda x: int(x[1]['retention_rate'].rstrip('%')), reverse=True)),
                'hint': 'Present retention rates by manager. Higher retention = better relationship management. Suggest best practices from top performers.',
            }

        return {'error': f'Unknown segments action: {action}'}

    async def _handle_escalation(self, session, headers, args: dict) -> dict:
        """Deal escalation: problematic deals, SLA violations, notifications."""
        import time
        action = args.get('action')
        days = args.get('days', 7)
        pipeline_id = args.get('pipeline_id')
        now = int(time.time())

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        async with session.get(url, headers=headers, params=params) as resp:
            all_leads = []
            if resp.status == 200:
                data = await resp.json()
                all_leads = data.get('_embedded', {}).get('leads', [])
        active = [l for l in all_leads if l.get('status_id') not in (142, 143)]

        uurl = f'{self.kommo_base_url}/api/v4/users'
        async with session.get(uurl, headers=headers) as resp:
            users = {}
            if resp.status == 200:
                udata = await resp.json()
                users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

        if action == 'check':
            escalations = []
            for l in active:
                issues = []
                age = (now - (l.get('updated_at') or now)) / 86400
                price = l.get('price', 0) or 0
                if age > days and price > 50000:
                    issues.append(f'High-value deal stale {age:.0f} days')
                elif age > days * 2:
                    issues.append(f'Deal inactive {age:.0f} days (2x threshold)')
                if not l.get('responsible_user_id'):
                    issues.append('No responsible user assigned')
                if issues:
                    escalations.append({
                        'lead_id': l.get('id'),
                        'name': l.get('name'),
                        'price': price,
                        'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                        'days_inactive': round(age),
                        'issues': issues,
                        'priority': 'critical' if price > 100000 else ('high' if price > 50000 else 'medium'),
                    })
            escalations.sort(key=lambda x: {'critical': 0, 'high': 1, 'medium': 2}.get(x['priority'], 3))

            return {
                'escalations': escalations[:20],
                'total': len(escalations),
                'threshold_days': days,
                'hint': 'Present escalations by priority. Critical first. Suggest immediate actions: reassign, contact client, or close.',
            }

        elif action == 'notify':
            critical = [l for l in active if (l.get('price') or 0) > 100000 and (now - (l.get('updated_at') or now)) > days * 86400]
            high = [l for l in active if 50000 < (l.get('price') or 0) <= 100000 and (now - (l.get('updated_at') or now)) > days * 86400]
            notifications = []
            for l in critical:
                notifications.append({
                    'type': 'critical',
                    'lead_id': l.get('id'),
                    'name': l.get('name'),
                    'price': l.get('price'),
                    'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                    'message': f'CRITICAL: Deal "{l.get("name")}" ({l.get("price")}₽) inactive {round((now - (l.get("updated_at") or now)) / 86400)}d',
                })
            for l in high:
                notifications.append({
                    'type': 'high',
                    'lead_id': l.get('id'),
                    'name': l.get('name'),
                    'price': l.get('price'),
                    'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                    'message': f'HIGH: Deal "{l.get("name")}" ({l.get("price")}₽) needs attention',
                })

            return {
                'notifications': notifications,
                'total': len(notifications),
                'hint': 'Present as notification list. These are deals that need immediate manager/ROP attention. Suggest creating tasks or reassigning.',
            }

        elif action == 'sla':
            sla_rules = {
                'first_contact': 1,
                'follow_up': 3,
                'proposal': 7,
                'decision': 14,
            }
            violations = []
            for l in active:
                age = (now - l.get('created_at', now)) / 86400
                last_activity = (now - (l.get('updated_at') or now)) / 86400
                if age < 3 and last_activity > sla_rules['first_contact']:
                    violations.append({'lead_id': l.get('id'), 'name': l.get('name'), 'sla': 'first_contact', 'breach_days': round(last_activity - sla_rules['first_contact']), 'responsible': users.get(l.get('responsible_user_id'), 'Unassigned')})
                elif last_activity > sla_rules['follow_up']:
                    violations.append({'lead_id': l.get('id'), 'name': l.get('name'), 'sla': 'follow_up', 'breach_days': round(last_activity - sla_rules['follow_up']), 'responsible': users.get(l.get('responsible_user_id'), 'Unassigned')})

            violations.sort(key=lambda x: x['breach_days'], reverse=True)
            by_user = {}
            for v in violations:
                resp_name = v['responsible']
                if resp_name not in by_user:
                    by_user[resp_name] = 0
                by_user[resp_name] += 1

            return {
                'sla_rules': sla_rules,
                'violations': violations[:20],
                'total_violations': len(violations),
                'by_responsible': by_user,
                'hint': 'Present SLA violations sorted by breach severity. Show which users have most violations. Suggest process improvements.',
            }

        elif action == 'support':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'with': 'contacts'}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            complex_cases = []
            for l in active:
                age = (now - l.get('created_at', now)) / 86400
                last_act = (now - (l.get('updated_at') or now)) / 86400
                price = l.get('price', 0) or 0
                contacts = l.get('_embedded', {}).get('contacts', [])
                complexity = 0
                reasons = []
                if age > 30 and last_act > 7:
                    complexity += 3
                    reasons.append(f'Stale {age:.0f}d, no activity {last_act:.0f}d')
                if price > 100000:
                    complexity += 2
                    reasons.append(f'High value {price}₽')
                if not contacts:
                    complexity += 1
                    reasons.append('No contacts linked')
                if complexity >= 3:
                    complex_cases.append({
                        'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                        'complexity': complexity, 'reasons': reasons,
                        'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                        'suggestion': 'Escalate to senior manager' if complexity >= 5 else 'Needs team review',
                    })
            complex_cases.sort(key=lambda x: x['complexity'], reverse=True)
            return {
                'complex_cases': complex_cases[:15],
                'total': len(complex_cases),
                'hint': 'Present complex cases needing support escalation. Suggest assigning senior managers or scheduling team reviews.',
            }

        return {'error': f'Unknown escalation action: {action}'}

    async def _handle_reactivation(self, session, headers, args: dict) -> dict:
        """Client reactivation: sleeping, lost nurture, churn prevention."""
        import time
        action = args.get('action')
        days = args.get('days', 30)
        min_value = args.get('min_value', 0)
        now = int(time.time())
        cutoff = now - days * 86400

        if action == 'sleeping':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            sleeping = [l for l in active if (now - (l.get('updated_at') or now)) > days * 86400 and (l.get('price') or 0) >= min_value]
            sleeping.sort(key=lambda x: x.get('price', 0) or 0, reverse=True)

            candidates = [{'lead_id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0), 'days_inactive': round((now - (l.get('updated_at') or now)) / 86400), 'suggestion': 'Send check-in message' if (now - (l.get('updated_at') or now)) < 60 * 86400 else 'Consider closing or reactivation campaign'} for l in sleeping[:20]]

            return {
                'sleeping_clients': candidates,
                'total': len(sleeping),
                'total_value_at_risk': sum(l.get('price', 0) or 0 for l in sleeping),
                'hint': 'Present sleeping clients by value. Suggest reactivation actions: call, email, special offer. High-value first.',
            }

        elif action == 'lost_nurture':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'filter[statuses][0][status_id]': 143, 'limit': 250, 'order[updated_at]': 'desc'}
            async with session.get(url, headers=headers, params=params) as resp:
                lost = []
                if resp.status == 200:
                    data = await resp.json()
                    lost = data.get('_embedded', {}).get('leads', [])

            worth_retrying = [l for l in lost if (l.get('price') or 0) >= max(min_value, 10000) and (now - (l.get('updated_at') or now)) < 180 * 86400]
            worth_retrying.sort(key=lambda x: x.get('price', 0) or 0, reverse=True)

            candidates = []
            for l in worth_retrying[:20]:
                days_since_loss = round((now - (l.get('updated_at') or now)) / 86400)
                candidates.append({
                    'lead_id': l.get('id'),
                    'name': l.get('name'),
                    'price': l.get('price', 0),
                    'days_since_loss': days_since_loss,
                    'strategy': 'New offer/discount' if days_since_loss < 30 else ('Check-in call' if days_since_loss < 90 else 'Reactivation campaign'),
                })

            return {
                'nurture_candidates': candidates,
                'total': len(worth_retrying),
                'total_potential_value': sum(l.get('price', 0) or 0 for l in worth_retrying),
                'hint': 'Present lost deals worth retrying. Suggest specific nurture strategies based on time since loss. Focus on high-value deals.',
            }

        elif action == 'churn_prevention':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])

            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            at_risk = []
            for l in active:
                risk_score = 0
                risk_factors = []
                inactive_days = (now - (l.get('updated_at') or now)) / 86400
                if inactive_days > 14:
                    risk_score += 30
                    risk_factors.append(f'Inactive {inactive_days:.0f} days')
                if inactive_days > 30:
                    risk_score += 20
                age = (now - l.get('created_at', now)) / 86400
                if age > 60:
                    risk_score += 15
                    risk_factors.append(f'Deal age {age:.0f} days')
                if not (l.get('price') or 0):
                    risk_score += 10
                    risk_factors.append('No price set')
                if risk_score >= 30:
                    at_risk.append({
                        'lead_id': l.get('id'),
                        'name': l.get('name'),
                        'price': l.get('price', 0),
                        'risk_score': min(risk_score, 100),
                        'risk_factors': risk_factors,
                        'action': 'Urgent outreach' if risk_score > 60 else 'Schedule follow-up',
                    })

            at_risk.sort(key=lambda x: x['risk_score'], reverse=True)
            return {
                'at_risk_deals': at_risk[:20],
                'total_at_risk': len(at_risk),
                'total_value_at_risk': sum(d['price'] for d in at_risk),
                'hint': 'Present at-risk deals by risk score. Suggest preventive actions. Focus on high-value deals with high risk.',
            }

        elif action == 'prevent':
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            at_risk = []
            for l in active:
                age = (now - l.get('created_at', now)) / 86400
                last_act = (now - (l.get('updated_at') or now)) / 86400
                price = l.get('price', 0) or 0
                risk = 0
                actions = []
                if last_act > 14:
                    risk += 40
                    actions.append('Immediate follow-up call')
                elif last_act > 7:
                    risk += 20
                    actions.append('Send check-in message')
                if age > 45:
                    risk += 20
                    actions.append('Review deal stage — may need acceleration')
                if not price:
                    risk += 15
                    actions.append('Qualify budget')
                if risk >= 30:
                    at_risk.append({
                        'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                        'risk_score': min(risk, 100), 'age_days': round(age),
                        'last_activity_days': round(last_act),
                        'preventive_actions': actions,
                        'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                    })
            at_risk.sort(key=lambda x: x['risk_score'], reverse=True)
            return {
                'at_risk_deals': at_risk[:20],
                'total': len(at_risk),
                'hint': 'Present deals at risk of being lost. Suggest specific preventive actions for each. Focus on high-value deals.',
            }

        elif action == 'win_back':
            lost = [l for l in all_leads if l.get('status_id') == 143]
            lost_recent = [l for l in lost if l.get('updated_at', 0) >= cutoff]
            strategies = []
            for l in lost_recent:
                price = l.get('price', 0) or 0
                age_since_loss = (now - (l.get('updated_at') or now)) / 86400
                strategy = {
                    'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                    'days_since_loss': round(age_since_loss),
                    'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                }
                if age_since_loss < 14:
                    strategy['approach'] = 'Quick follow-up'
                    strategy['script'] = 'Здравствуйте! Мы пересмотрели наше предложение и хотели бы обсудить новые условия. Удобно ли вам на этой неделе?'
                elif age_since_loss < 60:
                    strategy['approach'] = 'Value reminder'
                    strategy['script'] = 'Добрый день! С момента нашего общения у нас появились новые возможности, которые могут быть вам интересны. Можем обсудить?'
                else:
                    strategy['approach'] = 'Fresh start'
                    strategy['script'] = 'Здравствуйте! Давно не общались. Хотел узнать, как обстоят дела с [проблемой]. У нас есть новое решение.'
                strategy['priority'] = 'high' if price > 50000 else ('medium' if price > 10000 else 'low')
                strategies.append(strategy)
            strategies.sort(key=lambda x: (0 if x['priority'] == 'high' else 1 if x['priority'] == 'medium' else 2, x['days_since_loss']))
            return {
                'win_back_strategies': strategies[:20],
                'total_lost': len(lost_recent),
                'total_value_at_stake': sum(l.get('price', 0) or 0 for l in lost_recent),
                'hint': 'Present win-back strategies sorted by priority. Include personalized scripts. Focus on recent high-value losses.',
            }

        return {'error': f'Unknown reactivation action: {action}'}

    async def _handle_contact_enrichment(self, session, headers, args: dict) -> dict:
        """Contact data enrichment: analyze, merge duplicates, enrich."""
        import time
        action = args.get('action')
        limit = args.get('limit', 50)
        now = int(time.time())

        url = f'{self.kommo_base_url}/api/v4/contacts'
        params = {'limit': min(limit, 250), 'with': 'leads'}
        async with session.get(url, headers=headers, params=params) as resp:
            contacts = []
            if resp.status == 200:
                data = await resp.json()
                contacts = data.get('_embedded', {}).get('contacts', [])

        if action == 'analyze':
            quality_scores = []
            for c in contacts:
                score = 0
                fields_present = []
                fields_missing = []
                if c.get('name') and c['name'] != 'Unknown':
                    score += 20
                    fields_present.append('name')
                else:
                    fields_missing.append('name')
                cfs = c.get('custom_fields_values') or []
                has_phone = any(f.get('field_code') == 'PHONE' for f in cfs)
                has_email = any(f.get('field_code') == 'EMAIL' for f in cfs)
                if has_phone:
                    score += 25
                    fields_present.append('phone')
                else:
                    fields_missing.append('phone')
                if has_email:
                    score += 25
                    fields_present.append('email')
                else:
                    fields_missing.append('email')
                if c.get('company_id'):
                    score += 15
                    fields_present.append('company')
                else:
                    fields_missing.append('company')
                leads = c.get('_embedded', {}).get('leads', [])
                if leads:
                    score += 15
                    fields_present.append('linked_deals')
                else:
                    fields_missing.append('linked_deals')

                quality_scores.append({
                    'contact_id': c.get('id'),
                    'name': c.get('name'),
                    'quality_score': score,
                    'fields_present': fields_present,
                    'fields_missing': fields_missing,
                })

            avg_score = round(sum(q['quality_score'] for q in quality_scores) / max(len(quality_scores), 1))
            poor = [q for q in quality_scores if q['quality_score'] < 50]

            return {
                'total_analyzed': len(quality_scores),
                'avg_quality_score': avg_score,
                'poor_quality_count': len(poor),
                'poor_contacts': poor[:10],
                'score_distribution': {
                    'excellent (80-100)': len([q for q in quality_scores if q['quality_score'] >= 80]),
                    'good (60-79)': len([q for q in quality_scores if 60 <= q['quality_score'] < 80]),
                    'fair (40-59)': len([q for q in quality_scores if 40 <= q['quality_score'] < 60]),
                    'poor (<40)': len([q for q in quality_scores if q['quality_score'] < 40]),
                },
                'hint': 'Present quality score distribution. List poor contacts with missing fields. Suggest enrichment priorities.',
            }

        elif action == 'merge_duplicates':
            name_groups = {}
            for c in contacts:
                name = (c.get('name') or '').strip().lower()
                if name and name != 'unknown':
                    if name not in name_groups:
                        name_groups[name] = []
                    name_groups[name].append(c)

            phone_groups = {}
            for c in contacts:
                cfs = c.get('custom_fields_values') or []
                for f in cfs:
                    if f.get('field_code') == 'PHONE':
                        for v in f.get('values', []):
                            phone = v.get('value', '').replace(' ', '').replace('-', '').replace('+', '')
                            if phone and len(phone) >= 7:
                                if phone not in phone_groups:
                                    phone_groups[phone] = []
                                phone_groups[phone].append(c)

            duplicates = []
            seen = set()
            for name, group in name_groups.items():
                if len(group) > 1:
                    ids = tuple(sorted(c.get('id') for c in group))
                    if ids not in seen:
                        seen.add(ids)
                        duplicates.append({'match_type': 'name', 'match_value': name, 'contacts': [{'id': c.get('id'), 'name': c.get('name')} for c in group]})
            for phone, group in phone_groups.items():
                if len(group) > 1:
                    ids = tuple(sorted(c.get('id') for c in group))
                    if ids not in seen:
                        seen.add(ids)
                        duplicates.append({'match_type': 'phone', 'match_value': phone, 'contacts': [{'id': c.get('id'), 'name': c.get('name')} for c in group]})

            return {
                'duplicate_groups': duplicates[:15],
                'total_groups': len(duplicates),
                'hint': 'Present duplicate groups. Suggest merging — keep the contact with more data. Note: actual merge requires manual action in Kommo UI.',
            }

        elif action == 'enrich':
            needs_enrichment = []
            for c in contacts:
                missing = []
                cfs = c.get('custom_fields_values') or []
                if not any(f.get('field_code') == 'PHONE' for f in cfs):
                    missing.append('phone')
                if not any(f.get('field_code') == 'EMAIL' for f in cfs):
                    missing.append('email')
                if not c.get('company_id'):
                    missing.append('company')
                if missing:
                    needs_enrichment.append({
                        'contact_id': c.get('id'),
                        'name': c.get('name'),
                        'missing_fields': missing,
                        'linked_deals': len(c.get('_embedded', {}).get('leads', [])),
                        'priority': 'high' if len(c.get('_embedded', {}).get('leads', [])) > 0 else 'low',
                    })

            needs_enrichment.sort(key=lambda x: (0 if x['priority'] == 'high' else 1, -x['linked_deals']))
            return {
                'needs_enrichment': needs_enrichment[:20],
                'total': len(needs_enrichment),
                'hint': 'Present contacts needing enrichment. High priority = has active deals. Suggest data sources or manual outreach to fill gaps.',
            }

        elif action == 'profile':
            profiles = []
            for c in contacts:
                cfs = c.get('custom_fields_values') or []
                phone_vals = []
                email_vals = []
                for f in cfs:
                    if f.get('field_code') == 'PHONE':
                        phone_vals = [v.get('value') for v in f.get('values', [])]
                    elif f.get('field_code') == 'EMAIL':
                        email_vals = [v.get('value') for v in f.get('values', [])]
                leads = c.get('_embedded', {}).get('leads', [])
                profiles.append({
                    'contact_id': c.get('id'),
                    'name': c.get('name'),
                    'phones': phone_vals,
                    'emails': email_vals,
                    'company_id': c.get('company_id'),
                    'linked_deals': len(leads),
                    'created': c.get('created_at'),
                    'updated': c.get('updated_at'),
                    'custom_fields': len(cfs),
                    'completeness': round((bool(c.get('name')) * 20 + bool(phone_vals) * 25 + bool(email_vals) * 25 + bool(c.get('company_id')) * 15 + bool(leads) * 15)),
                })
            profiles.sort(key=lambda x: x['completeness'])
            return {
                'profiles': profiles[:20],
                'total': len(profiles),
                'hint': 'Present contact profiles with completeness scores. Suggest filling missing data for contacts with active deals.',
            }

        elif action == 'social':
            social_data = []
            for c in contacts:
                cfs = c.get('custom_fields_values') or []
                emails = []
                for f in cfs:
                    if f.get('field_code') == 'EMAIL':
                        emails = [v.get('value') for v in f.get('values', [])]
                social_hints = []
                for email in emails:
                    if email:
                        domain = email.split('@')[-1] if '@' in email else ''
                        if domain and domain not in ('gmail.com', 'mail.ru', 'yandex.ru', 'yahoo.com', 'hotmail.com', 'outlook.com'):
                            social_hints.append(f'Corporate email ({domain}) — check company website')
                        social_hints.append(f'Search LinkedIn/Facebook by email')
                if not emails:
                    social_hints.append('No email — try searching by name on social networks')
                social_data.append({
                    'contact_id': c.get('id'),
                    'name': c.get('name'),
                    'emails': emails,
                    'social_hints': social_hints,
                    'linked_deals': len(c.get('_embedded', {}).get('leads', [])),
                })
            social_data.sort(key=lambda x: x['linked_deals'], reverse=True)
            return {
                'contacts': social_data[:20],
                'total': len(social_data),
                'hint': 'Present social enrichment suggestions. Prioritize contacts with active deals. Suggest LinkedIn, Facebook, company website lookups.',
            }

        return {'error': f'Unknown contact_enrichment action: {action}'}

    async def _handle_templates(self, session, headers, args: dict) -> dict:
        """Message templates: list, generate, personalize, sales scripts."""
        import time
        action = args.get('action')
        template_type = args.get('template_type', 'followup')
        lead_id = args.get('lead_id')
        pipeline_id = args.get('pipeline_id')
        stage_name = args.get('stage_name')
        now = int(time.time())

        templates_db = {
            'welcome': {
                'name': 'Welcome / First Contact',
                'template': 'Здравствуйте, {contact_name}! Меня зовут {manager_name}, я представляю {company}. Благодарю за интерес к нашим услугам. Когда вам будет удобно обсудить детали?',
                'variables': ['contact_name', 'manager_name', 'company'],
            },
            'followup': {
                'name': 'Follow-up',
                'template': '{contact_name}, добрый день! Напоминаю о нашем разговоре по поводу {deal_name}. Есть ли у вас вопросы? Готов обсудить в удобное для вас время.',
                'variables': ['contact_name', 'deal_name'],
            },
            'proposal': {
                'name': 'Commercial Proposal',
                'template': '{contact_name}, направляю коммерческое предложение по {deal_name} на сумму {price}₽. Основные преимущества: [перечислить]. Готов ответить на вопросы.',
                'variables': ['contact_name', 'deal_name', 'price'],
            },
            'closing': {
                'name': 'Closing',
                'template': '{contact_name}, мы обсудили все детали по {deal_name}. Предлагаю зафиксировать договоренности и перейти к оформлению. Какой следующий шаг будет удобен?',
                'variables': ['contact_name', 'deal_name'],
            },
            'reactivation': {
                'name': 'Reactivation',
                'template': '{contact_name}, давно не общались! У нас появились новые возможности, которые могут быть вам интересны. Можем ли мы назначить короткий звонок?',
                'variables': ['contact_name'],
            },
        }

        if action == 'list':
            return {
                'templates': {k: {'name': v['name'], 'variables': v['variables']} for k, v in templates_db.items()},
                'hint': 'Present available templates. User can ask to generate, personalize, or apply any template.',
            }

        elif action == 'generate':
            return {
                'generated_template': templates_db.get(template_type, templates_db['followup']),
                'template_type': template_type,
                'hint': 'Present the template. Offer to personalize it for a specific lead using personalize action with lead_id.',
            }

        elif action == 'apply' or action == 'personalize':
            template = templates_db.get(template_type, templates_db['followup'])
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status == 200:
                        lead = await resp.json()
                        contact_name = 'Клиент'
                        contacts = lead.get('_embedded', {}).get('contacts', [])
                        if contacts:
                            curl = f'{self.kommo_base_url}/api/v4/contacts/{contacts[0]["id"]}'
                            async with session.get(curl, headers=headers) as cresp:
                                if cresp.status == 200:
                                    cdata = await cresp.json()
                                    contact_name = cdata.get('name', 'Клиент')

                        filled = template['template'].replace('{contact_name}', contact_name).replace('{deal_name}', lead.get('name', 'сделка')).replace('{price}', str(lead.get('price', 0)))

                        return {
                            'personalized_message': filled,
                            'lead': lead.get('name'),
                            'contact': contact_name,
                            'template_type': template_type,
                            'hint': 'Present the personalized message ready to send. Offer to adjust tone or add details.',
                        }
                    else:
                        return {'error': f'Lead {lead_id} not found'}
            return {
                'template': template['template'],
                'note': 'Provide lead_id to personalize this template',
                'hint': 'Template shown without personalization. Ask user for lead_id to fill in details.',
            }

        elif action == 'sales_script':
            purl = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(purl, headers=headers) as resp:
                pipelines = []
                if resp.status == 200:
                    pdata = await resp.json()
                    pipelines = pdata.get('_embedded', {}).get('pipelines', [])

            scripts = {}
            for p in pipelines:
                if pipeline_id and p.get('id') != pipeline_id:
                    continue
                stages = [s for s in p.get('_embedded', {}).get('statuses', []) if s.get('id') not in (142, 143)]
                pipeline_scripts = {}
                for s in stages:
                    sname = s.get('name', '')
                    pipeline_scripts[sname] = {
                        'goal': f'Move deal to next stage from "{sname}"',
                        'key_questions': [
                            'What is the client\'s main pain point?',
                            'What is the decision timeline?',
                            'Who are the decision makers?',
                        ],
                        'objection_handlers': [
                            'Price too high → Focus on ROI and value',
                            'Need to think → Set specific follow-up date',
                            'Competitor offer → Highlight unique advantages',
                        ],
                        'next_action': f'Schedule next touchpoint and move to next stage',
                    }
                scripts[p.get('name')] = pipeline_scripts

            return {
                'sales_scripts': scripts,
                'hint': 'Present stage-specific sales scripts. Each stage has goals, key questions, objection handlers. Customize based on deal context.',
            }

        elif action == 'follow_up':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for follow_up template'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 5}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            contacts = lead.get('_embedded', {}).get('contacts', [])
            contact_name = 'клиент'
            if contacts:
                curl = f'{self.kommo_base_url}/api/v4/contacts/{contacts[0]["id"]}'
                async with session.get(curl, headers=headers) as cresp:
                    if cresp.status == 200:
                        cdata = await cresp.json()
                        contact_name = cdata.get('name', 'клиент')
            age = (now - lead.get('created_at', now)) / 86400
            last_act = (now - (lead.get('updated_at') or now)) / 86400
            templates = []
            if last_act < 3:
                templates.append({
                    'type': 'quick_followup',
                    'subject': f'По нашему разговору — {lead.get("name")}',
                    'body': f'Добрый день, {contact_name}!\n\nСпасибо за наш разговор. Как и обещал, отправляю [материалы/предложение].\n\nЕсли возникнут вопросы — я на связи.\n\nС уважением,\n[Ваше имя]',
                })
            if last_act >= 3 and last_act < 14:
                templates.append({
                    'type': 'check_in',
                    'subject': f'Как дела с {lead.get("name")}?',
                    'body': f'Добрый день, {contact_name}!\n\nХотел уточнить, удалось ли вам ознакомиться с нашим предложением? Буду рад ответить на любые вопросы.\n\nС уважением,\n[Ваше имя]',
                })
            if last_act >= 14:
                templates.append({
                    'type': 'reengagement',
                    'subject': f'Новые возможности для вас — {lead.get("name")}',
                    'body': f'Добрый день, {contact_name}!\n\nДавно не общались. У нас появились новые [возможности/условия], которые могут быть вам интересны.\n\nМожем обсудить в удобное время?\n\nС уважением,\n[Ваше имя]',
                })
            templates.append({
                'type': 'value_add',
                'subject': f'Полезный материал для вас',
                'body': f'Добрый день, {contact_name}!\n\nНашёл интересный [кейс/статью/исследование], который может быть полезен для вашего проекта.\n\n[Ссылка/описание]\n\nБуду рад обсудить, как это применимо к вашей ситуации.\n\nС уважением,\n[Ваше имя]',
            })
            return {
                'follow_up_templates': templates,
                'context': {'deal': lead.get('name'), 'contact': contact_name, 'days_inactive': round(last_act), 'age_days': round(age)},
                'hint': 'Present follow-up templates personalized for this deal. Let user pick and customize. Suggest timing for sending.',
            }

        elif action == 'closing_script':
            lead_id = args.get('lead_id')
            lead_info = {}
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers) as resp:
                    if resp.status == 200:
                        lead_info = await resp.json()
            price = lead_info.get('price', 0) or 0
            name = lead_info.get('name', 'клиент')
            scripts = [
                {
                    'technique': 'Assumptive close',
                    'script': f'Итак, мы обсудили все детали. Давайте оформим договор — когда вам удобно подписать?',
                    'when_to_use': 'When all objections are handled and client shows buying signals',
                },
                {
                    'technique': 'Summary close',
                    'script': f'Подведём итог: вы получаете [перечислить ключевые выгоды]. Стоимость — {price}₽. Это полностью решает вашу задачу. Приступаем?',
                    'when_to_use': 'After a long negotiation to remind of all value',
                },
                {
                    'technique': 'Urgency close',
                    'script': 'Текущие условия действуют до [дата]. После этого стоимость изменится. Рекомендую зафиксировать сейчас.',
                    'when_to_use': 'When there is a genuine deadline or price change',
                },
                {
                    'technique': 'Alternative close',
                    'script': 'Какой вариант вам больше подходит — базовый пакет или расширенный? Оба включают [ключевую выгоду].',
                    'when_to_use': 'When client is deciding between options (not whether to buy)',
                },
                {
                    'technique': 'Trial close',
                    'script': 'Если мы решим вопрос с [последнее возражение], вы готовы двигаться дальше?',
                    'when_to_use': 'To test readiness and identify remaining blockers',
                },
            ]
            return {
                'closing_scripts': scripts,
                'deal_context': {'name': name, 'price': price} if lead_info else None,
                'hint': 'Present closing scripts with context. Help user pick the right technique for their situation. Customize with deal details.',
            }

        return {'error': f'Unknown templates action: {action}'}

    async def _handle_anomaly(self, session, headers, args: dict) -> dict:
        """Anomaly detection in deals and sales."""
        import time
        from datetime import datetime
        from collections import Counter
        action = args.get('action')
        days = args.get('days', 30)
        pipeline_id = args.get('pipeline_id')
        now = int(time.time())
        cutoff = now - days * 86400

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250, 'order[created_at]': 'desc'}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        all_leads = []
        page = 1
        while page <= 4:
            params['page'] = page
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    all_leads.extend(leads)
                    if len(leads) < 250:
                        break
                    page += 1
                else:
                    break

        recent = [l for l in all_leads if l.get('created_at', 0) >= cutoff]

        if action == 'detect':
            anomalies = []
            prices = [l.get('price', 0) or 0 for l in recent if (l.get('price') or 0) > 0]
            if prices:
                avg_price = sum(prices) / len(prices)
                std_price = (sum((p - avg_price) ** 2 for p in prices) / len(prices)) ** 0.5
                for l in recent:
                    p = l.get('price', 0) or 0
                    if p > 0 and std_price > 0 and abs(p - avg_price) > 2 * std_price:
                        anomalies.append({'type': 'price_outlier', 'lead_id': l.get('id'), 'name': l.get('name'), 'price': p, 'avg_price': round(avg_price), 'deviation': f'{(p - avg_price) / std_price:.1f}σ'})

            daily_counts = Counter()
            for l in recent:
                dt = datetime.fromtimestamp(l.get('created_at', now))
                daily_counts[dt.strftime('%Y-%m-%d')] += 1
            if daily_counts:
                avg_daily = sum(daily_counts.values()) / max(len(daily_counts), 1)
                for day, count in daily_counts.items():
                    if count > avg_daily * 2.5:
                        anomalies.append({'type': 'volume_spike', 'date': day, 'count': count, 'avg_daily': round(avg_daily, 1), 'message': f'{day}: {count} deals (avg {avg_daily:.0f})'})
                    elif count == 0 or count < avg_daily * 0.2:
                        anomalies.append({'type': 'volume_drop', 'date': day, 'count': count, 'avg_daily': round(avg_daily, 1), 'message': f'{day}: only {count} deals (avg {avg_daily:.0f})'})

            user_counts = Counter(l.get('responsible_user_id') for l in recent if l.get('responsible_user_id'))
            if user_counts:
                avg_user = sum(user_counts.values()) / len(user_counts)
                for uid, cnt in user_counts.items():
                    if cnt > avg_user * 3:
                        anomalies.append({'type': 'user_concentration', 'user_id': uid, 'count': cnt, 'avg': round(avg_user), 'message': f'User {uid} has {cnt} deals (avg {avg_user:.0f})'})

            if not anomalies:
                anomalies.append({'type': 'none', 'message': 'No anomalies detected in the period'})

            return {
                'period_days': days,
                'total_analyzed': len(recent),
                'anomalies': anomalies,
                'hint': 'Present anomalies by type. Price outliers may be data entry errors or genuine big deals. Volume spikes/drops need investigation.',
            }

        elif action == 'sales':
            won = [l for l in recent if l.get('status_id') == 142]
            lost = [l for l in recent if l.get('status_id') == 143]
            active = [l for l in recent if l.get('status_id') not in (142, 143)]

            anomalies = []
            if won and lost:
                win_rate = len(won) / (len(won) + len(lost))
                if win_rate < 0.15:
                    anomalies.append({'type': 'low_win_rate', 'value': f'{win_rate:.0%}', 'message': f'Win rate critically low: {win_rate:.0%}'})
                elif win_rate > 0.8:
                    anomalies.append({'type': 'high_win_rate', 'value': f'{win_rate:.0%}', 'message': f'Win rate unusually high: {win_rate:.0%} — may indicate cherry-picking'})

            won_prices = [l.get('price', 0) or 0 for l in won if (l.get('price') or 0) > 0]
            lost_prices = [l.get('price', 0) or 0 for l in lost if (l.get('price') or 0) > 0]
            if won_prices and lost_prices:
                avg_won = sum(won_prices) / len(won_prices)
                avg_lost = sum(lost_prices) / len(lost_prices)
                if avg_lost > avg_won * 1.5:
                    anomalies.append({'type': 'losing_big_deals', 'avg_won': round(avg_won), 'avg_lost': round(avg_lost), 'message': f'Losing bigger deals (avg lost {avg_lost:.0f} vs avg won {avg_won:.0f})'})

            cycles = [(l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in won]
            if cycles:
                avg_cycle = sum(cycles) / len(cycles)
                very_fast = [c for c in cycles if c < 1]
                if len(very_fast) > len(cycles) * 0.3:
                    anomalies.append({'type': 'instant_wins', 'count': len(very_fast), 'message': f'{len(very_fast)} deals closed in <1 day — verify data quality'})

            if not anomalies:
                anomalies.append({'type': 'none', 'message': 'No sales anomalies detected'})

            return {
                'period_days': days,
                'stats': {'won': len(won), 'lost': len(lost), 'active': len(active)},
                'anomalies': anomalies,
                'hint': 'Present sales anomalies with context. Low win rate needs process review. Losing big deals needs strategy change. Instant wins need data verification.',
            }

        return {'error': f'Unknown anomaly action: {action}'}

    async def _handle_objections(self, session, headers, args: dict) -> dict:
        """Objection handling: scripts, library, prediction."""
        import time
        action = args.get('action')
        objection = args.get('objection', '')
        lead_id = args.get('lead_id')
        pipeline_id = args.get('pipeline_id')

        objections_library = {
            'price': {
                'category': 'Price / Budget',
                'examples': ['Слишком дорого', 'У конкурентов дешевле', 'Нет бюджета', 'Не готовы столько платить'],
                'strategies': [
                    {'name': 'ROI Focus', 'script': 'Понимаю вашу позицию. Давайте посчитаем: наше решение окупается за X месяцев. Вот как это работает...'},
                    {'name': 'Value Breakdown', 'script': 'Давайте разберём, что входит в стоимость. Вы получаете: [перечислить ценности]. Какой из этих пунктов для вас наиболее важен?'},
                    {'name': 'Comparison', 'script': 'Да, есть варианты дешевле. Но давайте сравним: [уникальные преимущества]. Экономия сейчас может обойтись дороже в перспективе.'},
                ],
            },
            'timing': {
                'category': 'Timing / Not Now',
                'examples': ['Не сейчас', 'Нужно подумать', 'Перезвоните через месяц', 'Сейчас не приоритет'],
                'strategies': [
                    {'name': 'Urgency', 'script': 'Понимаю. Но каждый день без решения стоит вам [потери]. Давайте хотя бы зафиксируем условия?'},
                    {'name': 'Micro-commitment', 'script': 'Конечно, не тороплю. Давайте назначим конкретную дату для следующего разговора. Когда вам удобно?'},
                    {'name': 'Pain Amplification', 'script': 'Что произойдёт, если отложить решение ещё на месяц? Какие последствия для бизнеса?'},
                ],
            },
            'competitor': {
                'category': 'Competitor',
                'examples': ['Мы работаем с другими', 'У нас уже есть поставщик', 'Конкуренты предлагают лучше'],
                'strategies': [
                    {'name': 'Differentiation', 'script': 'Отлично, что вы сравниваете. Наше ключевое отличие: [УТП]. Это то, чего нет у конкурентов.'},
                    {'name': 'Pilot', 'script': 'Предлагаю пилотный проект. Вы сможете сравнить результаты на практике, без рисков.'},
                ],
            },
            'authority': {
                'category': 'Decision Authority',
                'examples': ['Мне нужно согласовать', 'Решает руководство', 'Я не принимаю решения'],
                'strategies': [
                    {'name': 'Champion Building', 'script': 'Понимаю. Давайте подготовим для руководства краткое обоснование с цифрами. Что для них будет самым убедительным?'},
                    {'name': 'Meeting Setup', 'script': 'Можем ли мы организовать совместную встречу с лицом, принимающим решение? Я подготовлю презентацию под их вопросы.'},
                ],
            },
            'trust': {
                'category': 'Trust / Risk',
                'examples': ['Не уверены в качестве', 'Нет гарантий', 'А если не сработает?'],
                'strategies': [
                    {'name': 'Social Proof', 'script': 'Вот кейсы наших клиентов из вашей отрасли: [примеры]. Могу организовать разговор с ними.'},
                    {'name': 'Risk Reversal', 'script': 'Мы предлагаем гарантию возврата / пилотный период. Вы ничем не рискуете.'},
                ],
            },
        }

        if action == 'library':
            return {
                'objection_categories': {k: {'category': v['category'], 'examples': v['examples'], 'strategies_count': len(v['strategies'])} for k, v in objections_library.items()},
                'hint': 'Present objection categories with examples. User can ask for specific handling scripts by category or by providing the actual objection text.',
            }

        elif action == 'handle':
            if not objection:
                return {'error': 'Provide objection text to get handling script'}
            obj_lower = objection.lower()
            matched_category = None
            for key, data in objections_library.items():
                for example in data['examples']:
                    if any(word in obj_lower for word in example.lower().split()):
                        matched_category = key
                        break
                if matched_category:
                    break
            if not matched_category:
                matched_category = 'price'
            cat_data = objections_library[matched_category]
            return {
                'objection': objection,
                'matched_category': cat_data['category'],
                'strategies': cat_data['strategies'],
                'general_tips': [
                    'Acknowledge the objection first — show empathy',
                    'Ask clarifying questions before responding',
                    'Focus on value, not features',
                    'Use specific numbers and examples',
                ],
                'hint': 'Present matched strategies for the objection. Suggest the best one based on context. Offer to personalize for a specific deal.',
            }

        elif action == 'predict':
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status == 200:
                        lead = await resp.json()
                        price = lead.get('price', 0) or 0
                        predicted = []
                        if price > 100000:
                            predicted.append({'objection': 'price', 'probability': 'high', 'reason': f'High deal value ({price}₽)'})
                        predicted.append({'objection': 'timing', 'probability': 'medium', 'reason': 'Common in all deals'})
                        if not lead.get('_embedded', {}).get('contacts', []):
                            predicted.append({'objection': 'authority', 'probability': 'high', 'reason': 'No contacts linked — unclear decision maker'})
                        now = int(time.time())
                        age = (now - lead.get('created_at', now)) / 86400
                        if age > 30:
                            predicted.append({'objection': 'competitor', 'probability': 'medium', 'reason': f'Deal age {age:.0f}d — client may be comparing'})
                        for p in predicted:
                            p['preparation'] = objections_library.get(p['objection'], {}).get('strategies', [{}])[0].get('script', '')
                        return {
                            'lead': lead.get('name'),
                            'predicted_objections': predicted,
                            'hint': 'Present predicted objections with preparation scripts. Help manager prepare before the call.',
                        }
                    return {'error': f'Lead {lead_id} not found'}
            else:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    all_leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])
                lost = [l for l in all_leads if l.get('status_id') == 143]
                active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
                high_value = [l for l in active if (l.get('price') or 0) > 50000]
                return {
                    'pipeline_prediction': {
                        'most_common': 'price' if len(high_value) > len(active) * 0.3 else 'timing',
                        'high_value_deals': len(high_value),
                        'tip': 'Prepare price justification for high-value deals, timing scripts for others',
                    },
                    'hint': 'Present pipeline-level objection prediction. Suggest team preparation focus areas.',
                }

        elif action == 'best_practices':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            won = [l for l in all_leads if l.get('status_id') == 142]
            lost = [l for l in all_leads if l.get('status_id') == 143]
            user_stats = {}
            for l in won + lost:
                uid = l.get('responsible_user_id')
                if not uid:
                    continue
                if uid not in user_stats:
                    user_stats[uid] = {'won': 0, 'lost': 0, 'won_value': 0}
                if l.get('status_id') == 142:
                    user_stats[uid]['won'] += 1
                    user_stats[uid]['won_value'] += l.get('price', 0) or 0
                else:
                    user_stats[uid]['lost'] += 1
            best_closers = []
            for uid, stats in user_stats.items():
                wr = stats['won'] / max(stats['won'] + stats['lost'], 1)
                if wr > 0.3 and stats['won'] >= 2:
                    best_closers.append({
                        'user': users.get(uid, f'User {uid}'), 'user_id': uid,
                        'win_rate': f'{wr:.0%}', 'deals_won': stats['won'],
                        'total_value': stats['won_value'],
                        'practices': [
                            'Quick follow-up after first contact' if wr > 0.5 else 'Consistent follow-up cadence',
                            'Strong qualification — fewer but better deals' if stats['lost'] < stats['won'] else 'High volume approach with good conversion',
                            f'Avg deal value {stats["won_value"] // max(stats["won"], 1)}₽ — {"premium positioning" if stats["won_value"] // max(stats["won"], 1) > 50000 else "volume strategy"}',
                        ],
                    })
            best_closers.sort(key=lambda x: float(x['win_rate'].strip('%')) / 100, reverse=True)
            return {
                'top_performers': best_closers[:10],
                'team_avg_win_rate': f'{len(won) / max(len(won) + len(lost), 1):.0%}',
                'hint': 'Present best practices from top performers. Suggest team learning sessions. Highlight what makes top closers successful.',
            }

        return {'error': f'Unknown objections action: {action}'}

    async def _handle_deal_intelligence(self, session, headers, args: dict) -> dict:
        """Deal intelligence: enterprise deals, stakeholders, reviews."""
        import time
        action = args.get('action')
        lead_id = args.get('lead_id')
        pipeline_id = args.get('pipeline_id')
        min_value = args.get('min_value', 100000)
        now = int(time.time())

        if action == 'enterprise':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'with': 'contacts'}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            enterprise = [l for l in all_leads if l.get('status_id') not in (142, 143) and (l.get('price') or 0) >= min_value]
            enterprise.sort(key=lambda x: x.get('price', 0) or 0, reverse=True)

            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            deals = []
            for l in enterprise[:15]:
                age = (now - l.get('created_at', now)) / 86400
                last_activity = (now - (l.get('updated_at') or now)) / 86400
                contacts = l.get('_embedded', {}).get('contacts', [])
                risk_level = 'low'
                if last_activity > 14:
                    risk_level = 'high'
                elif last_activity > 7:
                    risk_level = 'medium'
                deals.append({
                    'lead_id': l.get('id'),
                    'name': l.get('name'),
                    'price': l.get('price'),
                    'responsible': users.get(l.get('responsible_user_id'), 'Unassigned'),
                    'age_days': round(age),
                    'last_activity_days': round(last_activity),
                    'contacts_count': len(contacts),
                    'risk_level': risk_level,
                    'next_step': 'Urgent follow-up' if last_activity > 7 else ('Schedule meeting' if age < 14 else 'Advance to next stage'),
                })
            return {
                'enterprise_deals': deals,
                'total': len(enterprise),
                'total_value': sum(l.get('price', 0) or 0 for l in enterprise),
                'hint': 'Present enterprise deals by value. Highlight risk levels. Suggest specific next steps for each deal.',
            }

        elif action == 'stakeholders':
            if not lead_id:
                return {'error': 'lead_id required for stakeholders action'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            contacts = lead.get('_embedded', {}).get('contacts', [])
            stakeholders = []
            for c in contacts:
                curl = f'{self.kommo_base_url}/api/v4/contacts/{c["id"]}'
                async with session.get(curl, headers=headers) as cresp:
                    if cresp.status == 200:
                        cdata = await cresp.json()
                        cfs = cdata.get('custom_fields_values') or []
                        position = ''
                        for f in cfs:
                            if f.get('field_name', '').lower() in ('должность', 'position', 'title'):
                                vals = f.get('values', [])
                                if vals:
                                    position = vals[0].get('value', '')
                        stakeholders.append({
                            'contact_id': cdata.get('id'),
                            'name': cdata.get('name'),
                            'position': position or 'Unknown',
                            'role': 'Decision Maker' if any(w in position.lower() for w in ('директор', 'director', 'ceo', 'owner', 'руководитель', 'head')) else ('Influencer' if any(w in position.lower() for w in ('менеджер', 'manager', 'lead')) else 'User'),
                            'company_id': cdata.get('company_id'),
                        })
            missing_roles = []
            roles_found = [s['role'] for s in stakeholders]
            if 'Decision Maker' not in roles_found:
                missing_roles.append('Decision Maker — critical for closing')
            if 'Influencer' not in roles_found:
                missing_roles.append('Influencer — helps champion internally')
            return {
                'lead': lead.get('name'),
                'price': lead.get('price'),
                'stakeholders': stakeholders,
                'total_contacts': len(stakeholders),
                'missing_roles': missing_roles,
                'hint': 'Present stakeholder map. Highlight missing roles. Suggest finding Decision Maker if not identified.',
            }

        elif action == 'review':
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                age = (now - lead.get('created_at', now)) / 86400
                last_activity = (now - (lead.get('updated_at') or now)) / 86400
                price = lead.get('price', 0) or 0
                contacts = lead.get('_embedded', {}).get('contacts', [])
                health_score = 100
                issues = []
                if last_activity > 14:
                    health_score -= 30
                    issues.append(f'No activity for {last_activity:.0f} days')
                elif last_activity > 7:
                    health_score -= 15
                    issues.append(f'Last activity {last_activity:.0f} days ago')
                if not price:
                    health_score -= 20
                    issues.append('No price set')
                if not contacts:
                    health_score -= 20
                    issues.append('No contacts linked')
                if age > 60:
                    health_score -= 15
                    issues.append(f'Deal age {age:.0f} days — may be stale')
                strengths = []
                if price > 0:
                    strengths.append(f'Deal value: {price}₽')
                if contacts:
                    strengths.append(f'{len(contacts)} contacts linked')
                if last_activity < 3:
                    strengths.append('Recent activity')
                return {
                    'lead': lead.get('name'),
                    'health_score': max(health_score, 0),
                    'price': price,
                    'age_days': round(age),
                    'last_activity_days': round(last_activity),
                    'issues': issues,
                    'strengths': strengths,
                    'recommendation': 'Immediate action needed' if health_score < 40 else ('Monitor closely' if health_score < 70 else 'On track'),
                    'hint': 'Present deal health review. Highlight issues and strengths. Suggest specific actions to improve health score.',
                }
            else:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250, 'with': 'contacts'}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    all_leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])
                active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
                reviews = []
                for l in active:
                    age = (now - l.get('created_at', now)) / 86400
                    last_act = (now - (l.get('updated_at') or now)) / 86400
                    score = 100
                    if last_act > 14: score -= 30
                    elif last_act > 7: score -= 15
                    if not (l.get('price') or 0): score -= 20
                    if not l.get('_embedded', {}).get('contacts', []): score -= 20
                    if age > 60: score -= 15
                    reviews.append({'lead_id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0), 'health_score': max(score, 0)})
                reviews.sort(key=lambda x: x['health_score'])
                return {
                    'deal_reviews': reviews[:20],
                    'total_active': len(active),
                    'avg_health': round(sum(r['health_score'] for r in reviews) / max(len(reviews), 1)),
                    'critical': len([r for r in reviews if r['health_score'] < 40]),
                    'hint': 'Present deals sorted by health score (worst first). Focus on critical deals. Suggest actions to improve.',
                }

        elif action == 'pipeline_review':
            pipeline_id = args.get('pipeline_id')
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'with': 'contacts'}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            won = [l for l in all_leads if l.get('status_id') == 142]
            lost = [l for l in all_leads if l.get('status_id') == 143]
            total_value = sum(l.get('price', 0) or 0 for l in active)
            won_value = sum(l.get('price', 0) or 0 for l in won)
            win_rate = len(won) / max(len(won) + len(lost), 1)
            stale = [l for l in active if (now - (l.get('updated_at') or now)) / 86400 > 14]
            no_price = [l for l in active if not (l.get('price') or 0)]
            no_contacts = [l for l in active if not l.get('_embedded', {}).get('contacts', [])]
            health_issues = []
            if len(stale) > len(active) * 0.3:
                health_issues.append(f'{len(stale)} stale deals ({len(stale)/max(len(active),1)*100:.0f}%) — need follow-up')
            if len(no_price) > len(active) * 0.2:
                health_issues.append(f'{len(no_price)} deals without price — need qualification')
            if len(no_contacts) > len(active) * 0.2:
                health_issues.append(f'{len(no_contacts)} deals without contacts — need stakeholder mapping')
            if win_rate < 0.2:
                health_issues.append(f'Low win rate {win_rate:.0%} — review qualification criteria')
            strengths = []
            if win_rate >= 0.3:
                strengths.append(f'Healthy win rate: {win_rate:.0%}')
            if total_value > won_value:
                strengths.append(f'Pipeline value {total_value}₽ exceeds closed {won_value}₽')
            return {
                'summary': {
                    'active_deals': len(active), 'total_value': total_value,
                    'won': len(won), 'lost': len(lost), 'win_rate': f'{win_rate:.0%}',
                    'stale_deals': len(stale), 'no_price': len(no_price), 'no_contacts': len(no_contacts),
                },
                'health_issues': health_issues,
                'strengths': strengths,
                'action_items': [
                    f'Review {len(stale)} stale deals' if stale else None,
                    f'Set prices on {len(no_price)} deals' if no_price else None,
                    f'Add contacts to {len(no_contacts)} deals' if no_contacts else None,
                ],
                'hint': 'Present as pipeline review report. Highlight issues and strengths. Provide specific action items with counts.',
            }

        elif action == 'closing_signals':
            lead_id = args.get('lead_id')
            if not lead_id:
                url = f'{self.kommo_base_url}/api/v4/leads'
                params = {'limit': 250}
                if pipeline_id:
                    params['filter[pipeline_id]'] = pipeline_id
                async with session.get(url, headers=headers, params=params) as resp:
                    all_leads = []
                    if resp.status == 200:
                        data = await resp.json()
                        all_leads = data.get('_embedded', {}).get('leads', [])
                active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
                results = []
                for l in active[:20]:
                    signals = []
                    price = l.get('price', 0) or 0
                    age = (now - l.get('created_at', now)) / 86400
                    activity = (now - (l.get('updated_at') or now)) / 86400
                    if price > 0:
                        signals.append('Budget discussed')
                    if activity < 3:
                        signals.append('Recent activity')
                    if age > 14 and activity < 7:
                        signals.append('Mature deal with engagement')
                    score = len(signals) * 33
                    if signals:
                        results.append({
                            'lead_id': l.get('id'), 'name': l.get('name'), 'price': price,
                            'closing_score': min(score, 100), 'signals': signals,
                        })
                results.sort(key=lambda x: x['closing_score'], reverse=True)
                return {
                    'closing_candidates': results[:10],
                    'hint': 'Present deals with strongest closing signals. Prioritize highest-scoring deals for immediate action.',
                }
            else:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 20}) as resp:
                    notes = []
                    if resp.status == 200:
                        ndata = await resp.json()
                        notes = ndata.get('_embedded', {}).get('notes', [])
                price = lead.get('price', 0) or 0
                contacts = lead.get('_embedded', {}).get('contacts', [])
                age = (now - lead.get('created_at', now)) / 86400
                activity = (now - (lead.get('updated_at') or now)) / 86400
                all_text = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
                signals = []
                blockers = []
                if price > 0:
                    signals.append({'signal': 'Budget identified', 'strength': 'strong'})
                else:
                    blockers.append('No budget discussed')
                if contacts:
                    signals.append({'signal': 'Stakeholders engaged', 'strength': 'strong'})
                else:
                    blockers.append('No contacts linked')
                if activity < 5:
                    signals.append({'signal': 'Active engagement', 'strength': 'strong'})
                elif activity < 14:
                    signals.append({'signal': 'Recent activity', 'strength': 'moderate'})
                else:
                    blockers.append(f'No activity for {round(activity)} days')
                if 'согласов' in all_text or 'подпис' in all_text or 'договор' in all_text:
                    signals.append({'signal': 'Contract/approval language detected', 'strength': 'strong'})
                if 'конкурент' in all_text or 'альтернатив' in all_text:
                    blockers.append('Competitor mentioned in communications')
                score = min(len(signals) * 25, 100)
                readiness = 'Ready to close' if score >= 75 else ('Warm' if score >= 50 else ('Needs nurturing' if score >= 25 else 'Cold'))
                return {
                    'closing_analysis': {
                        'lead': lead.get('name'), 'price': price,
                        'closing_score': score, 'readiness': readiness,
                        'signals': signals, 'blockers': blockers,
                        'recommended_action': blockers[0] if blockers else 'Push for close — all signals positive',
                    },
                    'hint': 'Present closing signal analysis. Show signals and blockers. Recommend specific next action to move toward close.',
                }

        return {'error': f'Unknown deal_intelligence action: {action}'}

    async def _handle_contact_scoring(self, session, headers, args: dict) -> dict:
        """Contact scoring and value segmentation."""
        import time
        action = args.get('action')
        limit = args.get('limit', 50)
        now = int(time.time())

        url = f'{self.kommo_base_url}/api/v4/contacts'
        params = {'limit': min(limit, 250), 'with': 'leads'}
        async with session.get(url, headers=headers, params=params) as resp:
            contacts = []
            if resp.status == 200:
                data = await resp.json()
                contacts = data.get('_embedded', {}).get('contacts', [])

        if action == 'score':
            scored = []
            for c in contacts:
                score = 0
                factors = []
                leads = c.get('_embedded', {}).get('leads', [])
                if leads:
                    score += min(len(leads) * 15, 40)
                    factors.append(f'{len(leads)} linked deals')
                cfs = c.get('custom_fields_values') or []
                has_phone = any(f.get('field_code') == 'PHONE' for f in cfs)
                has_email = any(f.get('field_code') == 'EMAIL' for f in cfs)
                if has_phone:
                    score += 10
                    factors.append('Has phone')
                if has_email:
                    score += 10
                    factors.append('Has email')
                if c.get('company_id'):
                    score += 10
                    factors.append('Has company')
                recency = (now - (c.get('updated_at') or now)) / 86400
                if recency < 7:
                    score += 20
                    factors.append('Active this week')
                elif recency < 30:
                    score += 10
                    factors.append('Active this month')
                if c.get('name') and c['name'] != 'Unknown':
                    score += 10
                scored.append({
                    'contact_id': c.get('id'),
                    'name': c.get('name'),
                    'score': min(score, 100),
                    'factors': factors,
                    'tier': 'hot' if score >= 70 else ('warm' if score >= 40 else 'cold'),
                })
            scored.sort(key=lambda x: x['score'], reverse=True)
            return {
                'scored_contacts': scored[:20],
                'total': len(scored),
                'distribution': {
                    'hot': len([s for s in scored if s['tier'] == 'hot']),
                    'warm': len([s for s in scored if s['tier'] == 'warm']),
                    'cold': len([s for s in scored if s['tier'] == 'cold']),
                },
                'hint': 'Present scored contacts by tier. Hot contacts should get priority attention. Suggest actions per tier.',
            }

        elif action == 'value_segments':
            lurl = f'{self.kommo_base_url}/api/v4/leads'
            lparams = {'limit': 250, 'filter[statuses][0][status_id]': 142}
            async with session.get(lurl, headers=headers, params=lparams) as resp:
                won_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])
            contact_value = {}
            for l in won_leads:
                price = l.get('price', 0) or 0
                lcontacts = l.get('_embedded', {}).get('contacts', [])
                for lc in lcontacts:
                    cid = lc.get('id')
                    if cid not in contact_value:
                        contact_value[cid] = {'total': 0, 'deals': 0}
                    contact_value[cid]['total'] += price
                    contact_value[cid]['deals'] += 1
            segments = {'vip': [], 'regular': [], 'occasional': []}
            for c in contacts:
                cid = c.get('id')
                cv = contact_value.get(cid, {'total': 0, 'deals': 0})
                entry = {'contact_id': cid, 'name': c.get('name'), 'lifetime_value': cv['total'], 'deals_won': cv['deals']}
                if cv['total'] >= 100000 or cv['deals'] >= 3:
                    segments['vip'].append(entry)
                elif cv['total'] > 0:
                    segments['regular'].append(entry)
                else:
                    segments['occasional'].append(entry)
            for seg in segments.values():
                seg.sort(key=lambda x: x['lifetime_value'], reverse=True)
            return {
                'segments': {k: v[:10] for k, v in segments.items()},
                'counts': {k: len(v) for k, v in segments.items()},
                'total_ltv': sum(cv['total'] for cv in contact_value.values()),
                'hint': 'Present value segments. VIP contacts deserve premium attention. Regular contacts can be nurtured. Occasional need reactivation.',
            }

        elif action == 'by_value':
            scored = []
            for c in contacts:
                leads = c.get('_embedded', {}).get('leads', [])
                total_value = 0
                for lead_ref in leads:
                    lid = lead_ref.get('id')
                    if lid:
                        lurl = f'{self.kommo_base_url}/api/v4/leads/{lid}'
                        async with session.get(lurl, headers=headers) as resp:
                            if resp.status == 200:
                                ldata = await resp.json()
                                total_value += ldata.get('price', 0) or 0
                scored.append({
                    'contact_id': c.get('id'),
                    'name': c.get('name'),
                    'total_deal_value': total_value,
                    'deals_count': len(leads),
                    'avg_deal': round(total_value / max(len(leads), 1)),
                    'segment': 'premium' if total_value >= 200000 else ('standard' if total_value >= 50000 else ('basic' if total_value > 0 else 'no_deals')),
                })
            scored.sort(key=lambda x: x['total_deal_value'], reverse=True)
            segments = {}
            for s in scored:
                seg = s['segment']
                if seg not in segments:
                    segments[seg] = {'count': 0, 'total_value': 0}
                segments[seg]['count'] += 1
                segments[seg]['total_value'] += s['total_deal_value']
            return {
                'contacts_by_value': scored[:20],
                'segments': segments,
                'total': len(scored),
                'hint': 'Present contacts segmented by deal value. Premium contacts need VIP treatment. No-deals contacts need activation campaigns.',
            }

        elif action == 'company_scoring':
            curl = f'{self.kommo_base_url}/api/v4/companies'
            async with session.get(curl, headers=headers, params={'limit': 50}) as resp:
                companies = []
                if resp.status == 200:
                    cdata = await resp.json()
                    companies = cdata.get('_embedded', {}).get('companies', [])
            results = []
            for c in companies[:30]:
                cid = c.get('id')
                lurl = f'{self.kommo_base_url}/api/v4/leads'
                async with session.get(lurl, headers=headers, params={'filter[company_id]': cid, 'limit': 50}) as resp:
                    leads = []
                    if resp.status == 200:
                        ldata = await resp.json()
                        leads = ldata.get('_embedded', {}).get('leads', [])
                won = [l for l in leads if l.get('status_id') == 142]
                revenue = sum(l.get('price', 0) or 0 for l in won)
                active = [l for l in leads if l.get('status_id') not in (142, 143)]
                score = min(100, len(won) * 20 + len(active) * 10 + (30 if revenue > 100000 else (15 if revenue > 30000 else 0)))
                results.append({
                    'company': c.get('name'), 'company_id': cid,
                    'score': score, 'total_deals': len(leads), 'won': len(won),
                    'revenue': revenue, 'active_deals': len(active),
                    'tier': 'Enterprise' if score >= 70 else ('Growth' if score >= 40 else 'SMB'),
                })
            results.sort(key=lambda x: x['score'], reverse=True)
            return {
                'company_scores': results[:20],
                'hint': 'Present company scores ranked by tier. Enterprise companies need dedicated account management.',
            }

        elif action == 'relationship_strength':
            url = f'{self.kommo_base_url}/api/v4/contacts'
            async with session.get(url, headers=headers, params={'limit': limit, 'with': 'leads'}) as resp:
                contacts = []
                if resp.status == 200:
                    data = await resp.json()
                    contacts = data.get('_embedded', {}).get('contacts', [])
            results = []
            for c in contacts:
                leads = c.get('_embedded', {}).get('leads', [])
                won_count = 0
                total_value = 0
                for lid in [l.get('id') for l in leads[:5]]:
                    lurl = f'{self.kommo_base_url}/api/v4/leads/{lid}'
                    async with session.get(lurl, headers=headers) as resp:
                        if resp.status == 200:
                            lead = await resp.json()
                            if lead.get('status_id') == 142:
                                won_count += 1
                                total_value += lead.get('price', 0) or 0
                deal_count = len(leads)
                strength = min(100, deal_count * 15 + won_count * 25 + (20 if total_value > 50000 else 0))
                level = 'Strong' if strength >= 70 else ('Moderate' if strength >= 40 else ('Weak' if strength >= 15 else 'New'))
                results.append({
                    'contact': c.get('name'), 'contact_id': c.get('id'),
                    'strength_score': strength, 'level': level,
                    'deals': deal_count, 'won': won_count, 'total_value': total_value,
                })
            results.sort(key=lambda x: x['strength_score'], reverse=True)
            return {
                'relationships': results[:20],
                'hint': 'Present relationship strength. Strong relationships are assets. Weak ones need nurturing. New contacts need engagement.',
            }

        elif action == 'account_scoring':
            curl = f'{self.kommo_base_url}/api/v4/companies'
            async with session.get(curl, headers=headers, params={'limit': 50, 'with': 'leads,contacts'}) as resp:
                companies = []
                if resp.status == 200:
                    cdata = await resp.json()
                    companies = cdata.get('_embedded', {}).get('companies', [])
            results = []
            for c in companies[:20]:
                leads = c.get('_embedded', {}).get('leads', [])
                contacts = c.get('_embedded', {}).get('contacts', [])
                won = sum(1 for l in leads if l.get('status_id') == 142) if isinstance(leads, list) and leads and isinstance(leads[0], dict) else 0
                engagement = len(contacts) * 10 + len(leads) * 15 + won * 25
                score = min(100, engagement)
                results.append({
                    'company': c.get('name'), 'company_id': c.get('id'),
                    'account_score': score, 'contacts': len(contacts), 'deals': len(leads),
                    'priority': 'Tier 1' if score >= 70 else ('Tier 2' if score >= 40 else 'Tier 3'),
                })
            results.sort(key=lambda x: x['account_score'], reverse=True)
            return {
                'account_scores': results,
                'hint': 'Present account scores by tier. Tier 1 accounts need strategic focus. Tier 3 may need re-evaluation.',
            }

        return {'error': f'Unknown contact_scoring action: {action}'}

    async def _handle_ai_coach(self, session, headers, args: dict) -> dict:
        """AI sales coaching: deal review, skill assessment, gaps, roleplay."""
        import time
        action = args.get('action')
        lead_id = args.get('lead_id')
        user_id = args.get('user_id')
        days = args.get('days', 30)
        now = int(time.time())
        cutoff = now - days * 86400

        uurl = f'{self.kommo_base_url}/api/v4/users'
        async with session.get(uurl, headers=headers) as resp:
            users = {}
            if resp.status == 200:
                udata = await resp.json()
                users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

        if action == 'review_deal':
            if not lead_id:
                return {'error': 'lead_id required for review_deal'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            age = (now - lead.get('created_at', now)) / 86400
            last_activity = (now - (lead.get('updated_at') or now)) / 86400
            price = lead.get('price', 0) or 0
            contacts = lead.get('_embedded', {}).get('contacts', [])
            coaching_points = []
            if last_activity > 7:
                coaching_points.append({'area': 'Follow-up Discipline', 'issue': f'No activity for {last_activity:.0f} days', 'advice': 'Set a recurring reminder. Best practice: touch base every 3-5 days on active deals.'})
            if not price:
                coaching_points.append({'area': 'Qualification', 'issue': 'No price set', 'advice': 'Always qualify budget early. Ask: "What budget have you allocated for this?" in the first meeting.'})
            if not contacts:
                coaching_points.append({'area': 'Stakeholder Mapping', 'issue': 'No contacts linked', 'advice': 'Always link contacts to deals. Ask: "Who else is involved in this decision?"'})
            if age > 30 and last_activity > 7:
                coaching_points.append({'area': 'Pipeline Hygiene', 'issue': f'Deal is {age:.0f} days old with low activity', 'advice': 'Consider: Is this deal still alive? If yes, create urgency. If no, close and move on.'})
            if not coaching_points:
                coaching_points.append({'area': 'General', 'issue': 'Deal looks healthy', 'advice': 'Keep momentum. Plan next step and set a clear timeline for closing.'})
            return {
                'lead': lead.get('name'),
                'price': price,
                'responsible': users.get(lead.get('responsible_user_id'), 'Unknown'),
                'coaching_points': coaching_points,
                'overall_grade': 'A' if len(coaching_points) <= 1 else ('B' if len(coaching_points) <= 2 else ('C' if len(coaching_points) <= 3 else 'D')),
                'hint': 'Present coaching points as constructive feedback. Focus on actionable advice. Encourage good practices.',
            }

        elif action == 'skill_assessment':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if user_id:
                params['filter[responsible_user_id]'] = user_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            recent = [l for l in all_leads if l.get('created_at', 0) >= cutoff]
            won = [l for l in recent if l.get('status_id') == 142]
            lost = [l for l in recent if l.get('status_id') == 143]
            active = [l for l in recent if l.get('status_id') not in (142, 143)]
            win_rate = len(won) / max(len(won) + len(lost), 1)
            avg_cycle = sum((l.get('updated_at', now) - l.get('created_at', now)) / 86400 for l in won) / max(len(won), 1) if won else 0
            avg_deal = sum(l.get('price', 0) or 0 for l in won) / max(len(won), 1)
            skills = {
                'closing': {'score': min(round(win_rate * 100 * 1.5), 100), 'metric': f'{win_rate:.0%} win rate'},
                'speed': {'score': max(0, 100 - round(avg_cycle * 2)), 'metric': f'{avg_cycle:.0f}d avg cycle'},
                'deal_size': {'score': min(round(avg_deal / 1000), 100), 'metric': f'{avg_deal:.0f}₽ avg deal'},
                'pipeline_management': {'score': min(round(len(active) / max(len(recent), 1) * 200), 100), 'metric': f'{len(active)} active deals'},
                'activity': {'score': min(round(len(recent) / max(days / 7, 1) * 10), 100), 'metric': f'{len(recent)} deals in {days}d'},
            }
            overall = round(sum(s['score'] for s in skills.values()) / len(skills))
            return {
                'user': users.get(user_id, 'All users') if user_id else 'All users',
                'period_days': days,
                'skills': skills,
                'overall_score': overall,
                'grade': 'A' if overall >= 80 else ('B' if overall >= 60 else ('C' if overall >= 40 else 'D')),
                'hint': 'Present skill assessment as a radar chart description. Highlight strongest and weakest areas. Suggest improvement focus.',
            }

        elif action == 'skill_gaps':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            recent = [l for l in all_leads if l.get('created_at', 0) >= cutoff]
            user_stats = {}
            for l in recent:
                uid = l.get('responsible_user_id')
                if not uid:
                    continue
                if uid not in user_stats:
                    user_stats[uid] = {'won': 0, 'lost': 0, 'total_value': 0, 'cycles': []}
                if l.get('status_id') == 142:
                    user_stats[uid]['won'] += 1
                    user_stats[uid]['total_value'] += l.get('price', 0) or 0
                    user_stats[uid]['cycles'].append((l.get('updated_at', now) - l.get('created_at', now)) / 86400)
                elif l.get('status_id') == 143:
                    user_stats[uid]['lost'] += 1
            gaps = []
            team_win_rate = sum(s['won'] for s in user_stats.values()) / max(sum(s['won'] + s['lost'] for s in user_stats.values()), 1)
            for uid, stats in user_stats.items():
                user_wr = stats['won'] / max(stats['won'] + stats['lost'], 1)
                user_gaps = []
                if user_wr < team_win_rate * 0.7:
                    user_gaps.append({'skill': 'Closing', 'gap': f'Win rate {user_wr:.0%} vs team avg {team_win_rate:.0%}', 'training': 'Closing techniques workshop'})
                if stats['cycles']:
                    avg_cycle = sum(stats['cycles']) / len(stats['cycles'])
                    if avg_cycle > 30:
                        user_gaps.append({'skill': 'Speed', 'gap': f'Avg cycle {avg_cycle:.0f}d', 'training': 'Pipeline acceleration techniques'})
                if stats['won'] > 0 and stats['total_value'] / stats['won'] < 30000:
                    user_gaps.append({'skill': 'Upselling', 'gap': f'Low avg deal {stats["total_value"] / stats["won"]:.0f}₽', 'training': 'Value selling & upselling'})
                if user_gaps:
                    gaps.append({'user': users.get(uid, f'User {uid}'), 'user_id': uid, 'gaps': user_gaps})
            return {
                'team_gaps': gaps,
                'team_avg_win_rate': f'{team_win_rate:.0%}',
                'hint': 'Present skill gaps per user. Suggest specific training for each gap. Focus on highest-impact improvements.',
            }

        elif action == 'roleplay':
            scenarios = [
                {
                    'scenario': 'Cold Call — First Contact',
                    'context': 'You are calling a potential client who has never heard of your company.',
                    'objectives': ['Introduce yourself and company', 'Identify pain points', 'Schedule a meeting'],
                    'client_persona': 'Busy executive, skeptical, has 2 minutes',
                    'success_criteria': 'Meeting scheduled or follow-up agreed',
                },
                {
                    'scenario': 'Objection Handling — Price',
                    'context': 'Client says your solution is too expensive compared to competitors.',
                    'objectives': ['Acknowledge the concern', 'Reframe value', 'Get commitment to next step'],
                    'client_persona': 'Budget-conscious manager, comparing 3 vendors',
                    'success_criteria': 'Client agrees to ROI calculation meeting',
                },
                {
                    'scenario': 'Closing — Final Decision',
                    'context': 'Client has seen the demo, received the proposal, and is ready to decide.',
                    'objectives': ['Address final concerns', 'Create urgency', 'Get signature'],
                    'client_persona': 'Decision maker, likes the product but hesitant',
                    'success_criteria': 'Deal closed or clear timeline set',
                },
                {
                    'scenario': 'Reactivation — Lost Client',
                    'context': 'Calling a client who chose a competitor 3 months ago.',
                    'objectives': ['Learn about their experience', 'Identify dissatisfaction', 'Propose new value'],
                    'client_persona': 'Somewhat satisfied with competitor, open to listening',
                    'success_criteria': 'Meeting scheduled to discuss new offer',
                },
            ]
            return {
                'roleplay_scenarios': scenarios,
                'instructions': 'Pick a scenario and I will play the client role. You practice your sales pitch. I will give feedback after.',
                'hint': 'Present scenarios as options. When user picks one, switch to roleplay mode — play the client persona and give coaching feedback.',
            }

        elif action == 'best_practices':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            won = [l for l in all_leads if l.get('status_id') == 142]
            lost = [l for l in all_leads if l.get('status_id') == 143]
            user_perf = {}
            for l in won + lost:
                uid = l.get('responsible_user_id')
                if not uid:
                    continue
                if uid not in user_perf:
                    user_perf[uid] = {'won': 0, 'lost': 0, 'revenue': 0, 'cycles': []}
                if l.get('status_id') == 142:
                    user_perf[uid]['won'] += 1
                    user_perf[uid]['revenue'] += l.get('price', 0) or 0
                    cycle = (l.get('updated_at', now) - l.get('created_at', now)) / 86400
                    user_perf[uid]['cycles'].append(cycle)
                else:
                    user_perf[uid]['lost'] += 1
            practices = []
            for uid, perf in user_perf.items():
                wr = perf['won'] / max(perf['won'] + perf['lost'], 1)
                if wr < 0.2 or perf['won'] < 2:
                    continue
                avg_cycle = sum(perf['cycles']) / max(len(perf['cycles']), 1) if perf['cycles'] else 0
                avg_deal = perf['revenue'] / max(perf['won'], 1)
                tips = []
                if wr > 0.5:
                    tips.append('Strong qualification — focuses on high-probability deals')
                if avg_cycle < 20:
                    tips.append('Fast closer — maintains momentum through the pipeline')
                if avg_deal > 50000:
                    tips.append('Premium positioning — targets high-value opportunities')
                if perf['won'] > 5:
                    tips.append('Consistent performer — reliable deal flow')
                practices.append({
                    'user': users.get(uid, f'User {uid}'), 'user_id': uid,
                    'win_rate': f'{wr:.0%}', 'avg_cycle_days': round(avg_cycle),
                    'avg_deal_value': round(avg_deal), 'deals_won': perf['won'],
                    'practices': tips if tips else ['Solid overall performance'],
                })
            practices.sort(key=lambda x: float(x['win_rate'].strip('%')) / 100, reverse=True)
            return {
                'best_practices': practices[:10],
                'team_insights': [
                    'Top performers qualify harder — fewer deals but higher win rate',
                    'Speed matters — fastest closers have highest conversion',
                    'Regular follow-up cadence is key differentiator',
                ],
                'hint': 'Present best practices from top performers. Suggest team learning sessions. Help replicate winning behaviors.',
            }

        elif action == 'micro_learning':
            user_id = args.get('user_id')
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            target_users = [user_id] if user_id else list(users.keys())
            lessons = []
            for uid in target_users[:5]:
                name = users.get(uid, f'User {uid}')
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won = [l for l in user_leads if l.get('status_id') == 142]
                lost = [l for l in user_leads if l.get('status_id') == 143]
                active = [l for l in user_leads if l.get('status_id') not in (142, 143)]
                wr = len(won) / max(len(won) + len(lost), 1)
                stale = [l for l in active if (now - (l.get('updated_at') or now)) / 86400 > 14]
                user_lessons = []
                if wr < 0.25 and len(won) + len(lost) > 3:
                    user_lessons.append({
                        'topic': 'Improving Win Rate',
                        'lesson': 'Focus on qualification: ask BANT questions early. Disqualify poor-fit leads faster to focus energy on winnable deals.',
                        'duration': '3 min', 'difficulty': 'beginner',
                    })
                if len(stale) > 3:
                    user_lessons.append({
                        'topic': 'Pipeline Hygiene',
                        'lesson': f'You have {len(stale)} stale deals. Set a rule: if no activity in 14 days, either follow up or close. Clean pipeline = clear focus.',
                        'duration': '2 min', 'difficulty': 'beginner',
                    })
                avg_price = sum(l.get('price', 0) or 0 for l in won) / max(len(won), 1)
                if avg_price < 30000 and won:
                    user_lessons.append({
                        'topic': 'Increasing Deal Size',
                        'lesson': 'Your avg deal is below 30K. Try upselling: offer premium packages, bundle services, or suggest add-ons during closing.',
                        'duration': '4 min', 'difficulty': 'intermediate',
                    })
                if not user_lessons:
                    user_lessons.append({
                        'topic': 'Advanced Closing Techniques',
                        'lesson': 'You\'re performing well! Level up with advanced techniques: trial closes, assumptive language, and strategic silence.',
                        'duration': '5 min', 'difficulty': 'advanced',
                    })
                lessons.append({'user': name, 'user_id': uid, 'lessons': user_lessons})
            return {
                'micro_learning': lessons,
                'hint': 'Present personalized micro-lessons per user. Each is short and actionable. Suggest scheduling daily learning time.',
            }

        return {'error': f'Unknown ai_coach action: {action}'}

    async def _handle_smart_reply(self, session, headers, args: dict) -> dict:
        """Smart reply suggestions based on deal context."""
        import time
        action = args.get('action')
        lead_id = args.get('lead_id')
        message = args.get('message', '')
        now = int(time.time())

        if action == 'suggest':
            if not lead_id:
                return {'error': 'lead_id required for suggest action'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 10}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            price = lead.get('price', 0) or 0
            age = (now - lead.get('created_at', now)) / 86400
            last_act = (now - (lead.get('updated_at') or now)) / 86400
            recent_texts = [n.get('params', {}).get('text', '') for n in notes if n.get('params', {}).get('text')][:5]
            suggestions = []
            if last_act > 7:
                suggestions.append({
                    'type': 'follow_up',
                    'text': f'Добрый день! Хотел уточнить, удалось ли вам рассмотреть наше предложение? Буду рад ответить на вопросы.',
                    'reason': f'No activity for {last_act:.0f} days',
                })
            if price > 0 and age < 14:
                suggestions.append({
                    'type': 'value_proposition',
                    'text': 'Хочу поделиться кейсом клиента из вашей отрасли — результаты впечатляющие. Удобно обсудить?',
                    'reason': 'Early stage — build value',
                })
            if age > 30:
                suggestions.append({
                    'type': 'urgency',
                    'text': 'Напоминаю, что текущие условия действуют до конца месяца. Давайте зафиксируем?',
                    'reason': f'Deal age {age:.0f}d — create urgency',
                })
            suggestions.append({
                'type': 'check_in',
                'text': 'Как продвигается ваш проект? Есть ли вопросы, с которыми могу помочь?',
                'reason': 'General check-in',
            })
            if message:
                suggestions.insert(0, {
                    'type': 'direct_response',
                    'text': f'Спасибо за ваш вопрос. Давайте разберём подробнее...',
                    'reason': f'Response to: {message[:50]}',
                })
            return {
                'lead': lead.get('name'),
                'price': price,
                'suggestions': suggestions,
                'context': {'age_days': round(age), 'last_activity_days': round(last_act), 'recent_notes': len(recent_texts)},
                'hint': 'Present reply suggestions with context. Let user pick and customize. Offer to personalize further.',
            }

        elif action == 'objection_response':
            if not message:
                return {'error': 'Provide client message to generate objection response'}
            obj_lower = message.lower()
            responses = []
            if any(w in obj_lower for w in ('дорого', 'цена', 'бюджет', 'expensive', 'price', 'cost')):
                responses.append({'approach': 'ROI', 'text': 'Понимаю вашу позицию по цене. Давайте посчитаем: при текущих потерях [X] в месяц, наше решение окупится за [Y] месяцев. Хотите, покажу расчёт?'})
                responses.append({'approach': 'Value', 'text': 'Стоимость включает [перечислить]. Если сравнить с альтернативами, вы получаете значительно больше за эти деньги.'})
            elif any(w in obj_lower for w in ('подумать', 'позже', 'не сейчас', 'think', 'later')):
                responses.append({'approach': 'Urgency', 'text': 'Конечно, решение важное. Но хочу отметить: [специальные условия] действуют до [дата]. Давайте хотя бы зафиксируем?'})
                responses.append({'approach': 'Micro-step', 'text': 'Понимаю. Давайте сделаем небольшой шаг — я подготовлю персональный расчёт, а вы посмотрите в удобное время?'})
            elif any(w in obj_lower for w in ('конкурент', 'другие', 'competitor', 'alternative')):
                responses.append({'approach': 'Differentiation', 'text': 'Рад, что сравниваете! Наше ключевое отличие — [УТП]. Давайте сделаем сравнительную таблицу?'})
                responses.append({'approach': 'Pilot', 'text': 'Предлагаю пилот на 2 недели. Вы сможете сравнить на практике, без рисков.'})
            else:
                responses.append({'approach': 'Empathy', 'text': 'Понимаю вашу позицию. Расскажите подробнее, что именно вызывает сомнения? Хочу найти лучшее решение для вас.'})
                responses.append({'approach': 'Question', 'text': 'Спасибо за честность. Что было бы для вас идеальным вариантом? Давайте обсудим, как мы можем к этому приблизиться.'})
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers) as resp:
                    if resp.status == 200:
                        lead = await resp.json()
                        price = lead.get('price', 0) or 0
                        if price:
                            for r in responses:
                                r['personalization'] = f'Deal value: {price}₽'
            return {
                'client_message': message,
                'responses': responses,
                'tips': ['Mirror the client\'s language', 'Acknowledge before countering', 'End with a question to keep dialogue'],
                'hint': 'Present response options. Help user pick and customize for their specific situation.',
            }

        elif action == 'context':
            if not lead_id:
                return {'error': 'lead_id required for context action'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 30}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            comm_types = {}
            for n in notes:
                nt = n.get('note_type', 'unknown')
                comm_types[nt] = comm_types.get(nt, 0) + 1
            texts = []
            for n in notes:
                text = n.get('params', {}).get('text', '')
                if text:
                    texts.append({'date': n.get('created_at'), 'type': n.get('note_type'), 'text': text[:150]})
            contacts = lead.get('_embedded', {}).get('contacts', [])
            return {
                'lead': lead.get('name'),
                'price': lead.get('price'),
                'communication_summary': {
                    'total_notes': len(notes),
                    'by_type': comm_types,
                    'recent_messages': texts[:10],
                },
                'contacts_count': len(contacts),
                'age_days': round((now - lead.get('created_at', now)) / 86400),
                'hint': 'Present communication context: history summary, recent messages, key topics discussed. Help user prepare for next interaction.',
            }

        elif action == 'auto_reply':
            message = args.get('message', '')
            if not message:
                return {'error': 'message required for auto_reply'}
            msg_lower = message.lower()
            auto_responses = []
            if any(w in msg_lower for w in ['цена', 'стоимость', 'сколько', 'прайс', 'price']):
                auto_responses.append({
                    'category': 'pricing',
                    'response': 'Спасибо за интерес! Стоимость зависит от объёма и конфигурации. Давайте обсудим ваши потребности, чтобы подготовить точное предложение. Когда вам удобно созвониться?',
                    'tone': 'professional',
                })
            if any(w in msg_lower for w in ['доставка', 'срок', 'когда', 'время', 'delivery']):
                auto_responses.append({
                    'category': 'delivery',
                    'response': 'Стандартные сроки — [X] рабочих дней. Для срочных заказов возможна ускоренная обработка. Уточните, пожалуйста, ваш регион доставки.',
                    'tone': 'helpful',
                })
            if any(w in msg_lower for w in ['гарантия', 'возврат', 'обмен', 'warranty']):
                auto_responses.append({
                    'category': 'warranty',
                    'response': 'Мы предоставляем гарантию [X] месяцев на все товары/услуги. Возврат возможен в течение 14 дней. Подробные условия могу отправить отдельно.',
                    'tone': 'reassuring',
                })
            if any(w in msg_lower for w in ['спасибо', 'благодар', 'thanks']):
                auto_responses.append({
                    'category': 'gratitude',
                    'response': 'Рады помочь! Если возникнут дополнительные вопросы — обращайтесь в любое время.',
                    'tone': 'warm',
                })
            if any(w in msg_lower for w in ['проблем', 'не работает', 'ошибка', 'баг', 'issue']):
                auto_responses.append({
                    'category': 'support',
                    'response': 'Понимаю ситуацию. Давайте разберёмся. Можете описать подробнее, что именно произошло? Мы оперативно решим вопрос.',
                    'tone': 'empathetic',
                })
            if not auto_responses:
                auto_responses.append({
                    'category': 'general',
                    'response': f'Спасибо за обращение! Ваш вопрос принят. Менеджер свяжется с вами в ближайшее время.',
                    'tone': 'neutral',
                })
            return {
                'auto_replies': auto_responses,
                'original_message': message[:100],
                'hint': 'Present auto-reply options. Let user pick and customize before sending. Suggest best match based on message content.',
            }

        return {'error': f'Unknown smart_reply action: {action}'}

    async def _handle_communication_analytics(self, session, headers, args: dict) -> dict:
        """Communication analytics: summaries and quality monitoring."""
        import time
        action = args.get('action')
        lead_id = args.get('lead_id')
        user_id = args.get('user_id')
        days = args.get('days', 30)
        now = int(time.time())
        cutoff = now - days * 86400

        if action == 'summary':
            if not lead_id:
                return {'error': 'lead_id required for summary action'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 100}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            calls = [n for n in notes if n.get('note_type') in ('call_in', 'call_out')]
            messages = [n for n in notes if n.get('note_type') in ('common', 'sms_in', 'sms_out')]
            emails = [n for n in notes if n.get('note_type') in ('mail_in', 'mail_out')]
            all_texts = []
            for n in notes:
                text = n.get('params', {}).get('text', '')
                if text:
                    all_texts.append(text[:200])
            key_topics = []
            topic_keywords = {'price': ['цена', 'стоимость', 'бюджет', 'price', 'cost'], 'timeline': ['срок', 'когда', 'дата', 'deadline', 'when'], 'product': ['продукт', 'функци', 'возможност', 'feature'], 'competitor': ['конкурент', 'альтернатив', 'competitor']}
            combined = ' '.join(all_texts).lower()
            for topic, keywords in topic_keywords.items():
                if any(kw in combined for kw in keywords):
                    key_topics.append(topic)
            first_note = notes[-1] if notes else None
            last_note = notes[0] if notes else None
            return {
                'lead': lead.get('name'),
                'price': lead.get('price'),
                'communication_stats': {
                    'total_interactions': len(notes),
                    'calls': len(calls),
                    'messages': len(messages),
                    'emails': len(emails),
                },
                'timeline': {
                    'first_contact': first_note.get('created_at') if first_note else None,
                    'last_contact': last_note.get('created_at') if last_note else None,
                    'span_days': round((last_note.get('created_at', 0) - first_note.get('created_at', 0)) / 86400) if first_note and last_note else 0,
                },
                'key_topics': key_topics,
                'recent_messages': all_texts[:5],
                'hint': 'Present conversation summary: stats, timeline, key topics. Help user prepare for next call with full context.',
            }

        elif action == 'quality':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if user_id:
                params['filter[responsible_user_id]'] = user_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            recent = [l for l in all_leads if l.get('created_at', 0) >= cutoff]
            user_quality = {}
            for l in recent:
                uid = l.get('responsible_user_id')
                if not uid:
                    continue
                if uid not in user_quality:
                    user_quality[uid] = {'leads': 0, 'with_notes': 0, 'won': 0, 'lost': 0, 'total_value': 0}
                user_quality[uid]['leads'] += 1
                if l.get('status_id') == 142:
                    user_quality[uid]['won'] += 1
                    user_quality[uid]['total_value'] += l.get('price', 0) or 0
                elif l.get('status_id') == 143:
                    user_quality[uid]['lost'] += 1
            for uid in user_quality:
                sample_leads = [l for l in recent if l.get('responsible_user_id') == uid][:10]
                for l in sample_leads:
                    nurl = f'{self.kommo_base_url}/api/v4/leads/{l["id"]}/notes'
                    async with session.get(nurl, headers=headers, params={'limit': 1}) as resp:
                        if resp.status == 200:
                            ndata = await resp.json()
                            if ndata.get('_embedded', {}).get('notes', []):
                                user_quality[uid]['with_notes'] += 1
            results = []
            for uid, q in user_quality.items():
                note_rate = q['with_notes'] / max(min(q['leads'], 10), 1)
                wr = q['won'] / max(q['won'] + q['lost'], 1)
                score = round(note_rate * 40 + wr * 40 + min(q['leads'] / 10, 1) * 20)
                results.append({
                    'user': users.get(uid, f'User {uid}'), 'user_id': uid,
                    'quality_score': min(score, 100),
                    'note_rate': f'{note_rate:.0%}',
                    'win_rate': f'{wr:.0%}',
                    'leads': q['leads'],
                    'rating': 'excellent' if score >= 80 else ('good' if score >= 60 else ('needs_improvement' if score >= 40 else 'poor')),
                })
            results.sort(key=lambda x: x['quality_score'], reverse=True)
            return {
                'quality_report': results,
                'period_days': days,
                'hint': 'Present communication quality by manager. Note rate shows CRM discipline. Suggest improvements for low scorers.',
            }

        elif action == 'sentiment':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for sentiment analysis'}
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 50}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            positive_words = ['спасибо', 'отлично', 'хорошо', 'супер', 'рад', 'доволен', 'нравится', 'согласен', 'подходит', 'интересно']
            negative_words = ['проблем', 'плохо', 'дорого', 'не устраивает', 'отказ', 'жалоба', 'недоволен', 'разочаров', 'ужасно', 'конкурент']
            neutral_count = 0
            positive_count = 0
            negative_count = 0
            timeline = []
            for n in notes:
                text = (n.get('params', {}).get('text', '') or '').lower()
                if not text:
                    continue
                pos = sum(1 for w in positive_words if w in text)
                neg = sum(1 for w in negative_words if w in text)
                if pos > neg:
                    sentiment = 'positive'
                    positive_count += 1
                elif neg > pos:
                    sentiment = 'negative'
                    negative_count += 1
                else:
                    sentiment = 'neutral'
                    neutral_count += 1
                timeline.append({'timestamp': n.get('created_at'), 'sentiment': sentiment, 'snippet': text[:80]})
            total = positive_count + negative_count + neutral_count
            overall = 'positive' if positive_count > negative_count * 2 else ('negative' if negative_count > positive_count else 'mixed')
            return {
                'sentiment_analysis': {
                    'overall': overall,
                    'positive': positive_count, 'negative': negative_count, 'neutral': neutral_count,
                    'total_analyzed': total,
                    'score': round((positive_count - negative_count) / max(total, 1) * 100),
                    'timeline': timeline[:10],
                },
                'hint': 'Present sentiment analysis. Show overall mood and trend over time. Flag negative sentiment for attention.',
            }

        elif action == 'patterns':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            won = [l for l in all_leads if l.get('status_id') == 142]
            lost = [l for l in all_leads if l.get('status_id') == 143]
            won_notes_count = 0
            lost_notes_count = 0
            for l in won[:30]:
                nurl = f'{self.kommo_base_url}/api/v4/leads/{l["id"]}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 50}) as resp:
                    if resp.status == 200:
                        ndata = await resp.json()
                        won_notes_count += len(ndata.get('_embedded', {}).get('notes', []))
            for l in lost[:30]:
                nurl = f'{self.kommo_base_url}/api/v4/leads/{l["id"]}/notes'
                async with session.get(nurl, headers=headers, params={'limit': 50}) as resp:
                    if resp.status == 200:
                        ndata = await resp.json()
                        lost_notes_count += len(ndata.get('_embedded', {}).get('notes', []))
            avg_won = won_notes_count / max(len(won[:30]), 1)
            avg_lost = lost_notes_count / max(len(lost[:30]), 1)
            patterns = []
            if avg_won > avg_lost * 1.5:
                patterns.append({'pattern': 'More communication = more wins', 'detail': f'Won deals avg {avg_won:.1f} notes vs lost {avg_lost:.1f}', 'actionable': True})
            patterns.append({'pattern': 'Communication frequency', 'detail': f'Won: {avg_won:.1f} interactions, Lost: {avg_lost:.1f} interactions', 'actionable': True})
            patterns.append({'pattern': 'Follow-up cadence', 'detail': 'Consistent follow-up within 3 days correlates with higher win rates', 'actionable': True})
            patterns.append({'pattern': 'Multi-channel approach', 'detail': 'Deals with notes from multiple channels close faster', 'actionable': True})
            return {
                'communication_patterns': patterns,
                'stats': {'won_avg_notes': round(avg_won, 1), 'lost_avg_notes': round(avg_lost, 1), 'won_sample': min(len(won), 30), 'lost_sample': min(len(lost), 30)},
                'hint': 'Present communication patterns that correlate with success. Help team replicate winning behaviors.',
            }

        elif action == 'insights':
            lead_id = args.get('lead_id')
            if not lead_id:
                return {'error': 'lead_id required for communication insights'}
            nurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/notes'
            async with session.get(nurl, headers=headers, params={'limit': 30}) as resp:
                notes = []
                if resp.status == 200:
                    ndata = await resp.json()
                    notes = ndata.get('_embedded', {}).get('notes', [])
            all_text = ' '.join((n.get('params', {}).get('text', '') or '') for n in notes).lower()
            insights = []
            if 'цена' in all_text or 'бюджет' in all_text or 'стоимость' in all_text:
                insights.append({'topic': 'Pricing discussed', 'importance': 'high', 'detail': 'Client has raised pricing questions'})
            if 'конкурент' in all_text or 'альтернатив' in all_text:
                insights.append({'topic': 'Competitor mentioned', 'importance': 'high', 'detail': 'Client is evaluating alternatives'})
            if 'срок' in all_text or 'дедлайн' in all_text or 'когда' in all_text:
                insights.append({'topic': 'Timeline pressure', 'importance': 'medium', 'detail': 'Client has timeline concerns'})
            if 'руководств' in all_text or 'директор' in all_text or 'согласов' in all_text:
                insights.append({'topic': 'Decision chain', 'importance': 'medium', 'detail': 'Multiple decision makers involved'})
            if 'доволен' in all_text or 'нравится' in all_text or 'отлично' in all_text:
                insights.append({'topic': 'Positive signals', 'importance': 'low', 'detail': 'Client shows positive sentiment'})
            if not insights:
                insights.append({'topic': 'No strong signals', 'importance': 'low', 'detail': 'Communication appears routine — no red flags or strong buying signals detected'})
            return {
                'communication_insights': insights,
                'total_interactions': len(notes),
                'hint': 'Present key insights from communications. High-importance items need immediate attention. Help user prepare talking points.',
            }

        return {'error': f'Unknown communication_analytics action: {action}'}

    async def _handle_doc_generator(self, session, headers, args: dict) -> dict:
        """Document generation: presentations, proposals, case studies."""
        import time
        action = args.get('action')
        lead_id = args.get('lead_id')
        pipeline_id = args.get('pipeline_id')
        now = int(time.time())

        if action == 'presentation':
            if lead_id:
                lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                    if resp.status != 200:
                        return {'error': f'Lead {lead_id} not found'}
                    lead = await resp.json()
                contacts = lead.get('_embedded', {}).get('contacts', [])
                contact_names = []
                for c in contacts[:3]:
                    curl = f'{self.kommo_base_url}/api/v4/contacts/{c["id"]}'
                    async with session.get(curl, headers=headers) as cresp:
                        if cresp.status == 200:
                            cdata = await cresp.json()
                            contact_names.append(cdata.get('name', 'Unknown'))
                return {
                    'presentation_outline': {
                        'title': f'Presentation for {lead.get("name")}',
                        'client': ', '.join(contact_names) if contact_names else 'Client',
                        'slides': [
                            {'slide': 1, 'title': 'Introduction', 'content': 'Company overview, team, mission'},
                            {'slide': 2, 'title': 'Understanding Your Needs', 'content': f'Based on deal: {lead.get("name")}'},
                            {'slide': 3, 'title': 'Our Solution', 'content': 'Key features and benefits tailored to client needs'},
                            {'slide': 4, 'title': 'Case Studies', 'content': 'Similar clients and their results'},
                            {'slide': 5, 'title': 'Pricing', 'content': f'Investment: {lead.get("price", "TBD")}₽'},
                            {'slide': 6, 'title': 'Implementation Timeline', 'content': 'Onboarding steps and milestones'},
                            {'slide': 7, 'title': 'Next Steps', 'content': 'Call to action and follow-up plan'},
                        ],
                    },
                    'hint': 'Present presentation outline. Offer to expand any slide. Suggest personalizing based on client industry.',
                }
            return {
                'presentation_template': {
                    'slides': [
                        {'slide': 1, 'title': 'Company Overview'},
                        {'slide': 2, 'title': 'Problem Statement'},
                        {'slide': 3, 'title': 'Our Solution'},
                        {'slide': 4, 'title': 'Benefits & ROI'},
                        {'slide': 5, 'title': 'Social Proof'},
                        {'slide': 6, 'title': 'Pricing Options'},
                        {'slide': 7, 'title': 'Next Steps'},
                    ],
                },
                'hint': 'Present generic template. Suggest providing lead_id for personalization.',
            }

        elif action == 'proposal':
            if not lead_id:
                return {'error': 'lead_id required for personalized proposal'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            contacts = lead.get('_embedded', {}).get('contacts', [])
            contact_info = []
            for c in contacts[:3]:
                curl = f'{self.kommo_base_url}/api/v4/contacts/{c["id"]}'
                async with session.get(curl, headers=headers) as cresp:
                    if cresp.status == 200:
                        cdata = await cresp.json()
                        contact_info.append({'name': cdata.get('name'), 'id': cdata.get('id')})
            price = lead.get('price', 0) or 0
            return {
                'proposal': {
                    'title': f'Commercial Proposal: {lead.get("name")}',
                    'to': contact_info[0]['name'] if contact_info else 'Client',
                    'sections': [
                        {'section': 'Executive Summary', 'content': f'Proposal for {lead.get("name")} — tailored solution addressing your business needs.'},
                        {'section': 'Scope of Work', 'content': 'Detailed description of deliverables, timeline, and milestones.'},
                        {'section': 'Investment', 'content': f'Total investment: {price}₽' if price else 'To be discussed based on requirements.'},
                        {'section': 'Terms & Conditions', 'content': 'Payment terms, warranties, SLA.'},
                        {'section': 'Why Us', 'content': 'Key differentiators, team expertise, relevant experience.'},
                        {'section': 'Next Steps', 'content': 'Sign-off process and implementation kickoff.'},
                    ],
                },
                'hint': 'Present proposal structure. Offer to expand any section with specific content. Suggest adding industry-specific details.',
            }

        elif action == 'case_study':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 50, 'filter[statuses][0][status_id]': 142}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                won_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    won_leads = data.get('_embedded', {}).get('leads', [])
            won_leads.sort(key=lambda x: x.get('price', 0) or 0, reverse=True)
            case_studies = []
            for l in won_leads[:5]:
                cycle = (l.get('updated_at', now) - l.get('created_at', now)) / 86400
                case_studies.append({
                    'lead_id': l.get('id'),
                    'title': l.get('name'),
                    'value': l.get('price', 0),
                    'cycle_days': round(cycle),
                    'template': {
                        'challenge': f'Client needed a solution for {l.get("name")}',
                        'solution': 'We provided [describe solution and approach]',
                        'results': f'Deal closed at {l.get("price", 0)}₽ in {round(cycle)} days',
                        'testimonial': '[Add client quote here]',
                    },
                })
            return {
                'case_studies': case_studies,
                'total_won': len(won_leads),
                'hint': 'Present case study templates based on real won deals. Help user fill in details. Suggest using for similar prospects.',
            }

        elif action == 'commercial_offer':
            if not lead_id:
                return {'error': 'lead_id required for commercial_offer'}
            lurl = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
            async with session.get(lurl, headers=headers, params={'with': 'contacts'}) as resp:
                if resp.status != 200:
                    return {'error': f'Lead {lead_id} not found'}
                lead = await resp.json()
            contacts = lead.get('_embedded', {}).get('contacts', [])
            contact_names = []
            for c in contacts[:3]:
                curl = f'{self.kommo_base_url}/api/v4/contacts/{c["id"]}'
                async with session.get(curl, headers=headers) as cresp:
                    if cresp.status == 200:
                        cdata = await cresp.json()
                        contact_names.append(cdata.get('name', 'Unknown'))
            price = lead.get('price', 0) or 0
            return {
                'commercial_offer': {
                    'title': f'Коммерческое предложение: {lead.get("name")}',
                    'to': contact_names[0] if contact_names else 'Уважаемый клиент',
                    'sections': [
                        {'section': 'Введение', 'content': f'Благодарим за интерес к нашим услугам. На основании обсуждения подготовили для вас предложение по "{lead.get("name")}".'},
                        {'section': 'Описание решения', 'content': 'Детальное описание предлагаемого решения, включая все компоненты и этапы.'},
                        {'section': 'Преимущества', 'content': '1. [Ключевое преимущество 1]\n2. [Ключевое преимущество 2]\n3. [Ключевое преимущество 3]'},
                        {'section': 'Стоимость', 'content': f'Инвестиция: {price}₽' if price else 'По запросу — зависит от объёма работ.'},
                        {'section': 'Сроки', 'content': 'Ориентировочные сроки реализации: [X] рабочих дней.'},
                        {'section': 'Гарантии', 'content': 'Гарантийный период, SLA, условия поддержки.'},
                        {'section': 'Следующие шаги', 'content': 'Для начала работы необходимо: 1) Согласование КП, 2) Подписание договора, 3) Оплата аванса.'},
                    ],
                },
                'hint': 'Present as ready-to-use commercial offer in Russian. Offer to customize sections. Suggest adding specific product details.',
            }

        elif action == 'report':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            days = args.get('days', 30)
            cutoff = now - days * 86400
            recent = [l for l in all_leads if l.get('created_at', 0) >= cutoff]
            won = [l for l in all_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
            lost = [l for l in all_leads if l.get('status_id') == 143 and l.get('updated_at', 0) >= cutoff]
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            revenue = sum(l.get('price', 0) or 0 for l in won)
            pipeline_value = sum(l.get('price', 0) or 0 for l in active)
            win_rate = len(won) / max(len(won) + len(lost), 1)
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            by_user = {}
            for l in won:
                uid = l.get('responsible_user_id')
                if uid:
                    if uid not in by_user:
                        by_user[uid] = {'name': users.get(uid, f'User {uid}'), 'deals': 0, 'revenue': 0}
                    by_user[uid]['deals'] += 1
                    by_user[uid]['revenue'] += l.get('price', 0) or 0
            return {
                'report': {
                    'title': f'Sales Report — Last {days} Days',
                    'summary': {
                        'new_leads': len(recent), 'won': len(won), 'lost': len(lost),
                        'active': len(active), 'revenue': revenue,
                        'pipeline_value': pipeline_value, 'win_rate': f'{win_rate:.0%}',
                    },
                    'by_manager': sorted(by_user.values(), key=lambda x: x['revenue'], reverse=True),
                    'highlights': [
                        f'Revenue: {revenue}₽ from {len(won)} deals',
                        f'Pipeline: {pipeline_value}₽ in {len(active)} active deals',
                        f'Win rate: {win_rate:.0%}',
                        f'New leads: {len(recent)}',
                    ],
                },
                'hint': 'Present as formatted sales report. Include summary, by-manager breakdown, and key highlights.',
            }

        elif action == 'partner_report':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            days = args.get('days', 90)
            cutoff = now - days * 86400
            won = [l for l in all_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            revenue = sum(l.get('price', 0) or 0 for l in won)
            pipeline_value = sum(l.get('price', 0) or 0 for l in active)
            return {
                'partner_report': {
                    'title': f'Partnership Performance Report — Last {days} Days',
                    'sections': [
                        {'section': 'Executive Summary', 'content': f'Revenue: {revenue}₽ from {len(won)} closed deals. Active pipeline: {pipeline_value}₽ in {len(active)} deals.'},
                        {'section': 'Key Metrics', 'content': f'Deals closed: {len(won)}\nRevenue: {revenue}₽\nActive pipeline: {pipeline_value}₽\nAvg deal size: {revenue // max(len(won), 1)}₽'},
                        {'section': 'Growth Trajectory', 'content': 'Quarter-over-quarter comparison and growth trends.'},
                        {'section': 'Collaboration Highlights', 'content': 'Key joint wins, successful initiatives, and partnership milestones.'},
                        {'section': 'Next Steps', 'content': 'Planned activities, joint targets, and strategic initiatives for next period.'},
                    ],
                },
                'hint': 'Present as professional partner report. Customize sections with specific partnership details. Suitable for external sharing.',
            }

        elif action == 'exportable_report':
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(url, headers=headers, params=params) as resp:
                all_leads = []
                if resp.status == 200:
                    data = await resp.json()
                    all_leads = data.get('_embedded', {}).get('leads', [])
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            days = args.get('days', 30)
            cutoff = now - days * 86400
            won = [l for l in all_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
            lost = [l for l in all_leads if l.get('status_id') == 143 and l.get('updated_at', 0) >= cutoff]
            active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
            revenue = sum(l.get('price', 0) or 0 for l in won)
            rows = []
            for l in won + lost + active[:20]:
                status = 'Won' if l.get('status_id') == 142 else ('Lost' if l.get('status_id') == 143 else 'Active')
                uid = l.get('responsible_user_id')
                rows.append({
                    'deal': l.get('name'), 'price': l.get('price', 0) or 0,
                    'status': status, 'manager': users.get(uid, f'User {uid}'),
                    'created': l.get('created_at'), 'updated': l.get('updated_at'),
                })
            return {
                'exportable_report': {
                    'title': f'CRM Export — Last {days} Days',
                    'summary': {'won': len(won), 'lost': len(lost), 'active': len(active), 'revenue': revenue},
                    'data': rows[:50],
                    'format_hint': 'CSV-ready data with columns: deal, price, status, manager, created, updated',
                },
                'hint': 'Present as exportable table. Data is ready for CSV/Excel export. Include summary stats above the table.',
            }

        return {'error': f'Unknown doc_generator action: {action}'}

    async def _handle_insights(self, session, headers, args: dict) -> dict:
        """Actionable insights and root cause analysis."""
        import time
        action = args.get('action')
        pipeline_id = args.get('pipeline_id')
        days = args.get('days', 30)
        now = int(time.time())
        cutoff = now - days * 86400

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        async with session.get(url, headers=headers, params=params) as resp:
            all_leads = []
            if resp.status == 200:
                data = await resp.json()
                all_leads = data.get('_embedded', {}).get('leads', [])

        won = [l for l in all_leads if l.get('status_id') == 142]
        lost = [l for l in all_leads if l.get('status_id') == 143]
        active = [l for l in all_leads if l.get('status_id') not in (142, 143)]
        recent_won = [l for l in won if l.get('updated_at', 0) >= cutoff]
        recent_lost = [l for l in lost if l.get('updated_at', 0) >= cutoff]

        if action == 'actionable':
            revenue = sum(l.get('price', 0) or 0 for l in recent_won)
            pipeline_value = sum(l.get('price', 0) or 0 for l in active)
            stale = [l for l in active if (now - (l.get('updated_at') or now)) / 86400 > 14]
            high_value_stale = [l for l in stale if (l.get('price', 0) or 0) > 50000]
            win_rate = len(recent_won) / max(len(recent_won) + len(recent_lost), 1)

            insights = []
            if high_value_stale:
                total_at_risk = sum(l.get('price', 0) or 0 for l in high_value_stale)
                insights.append({
                    'type': 'risk', 'priority': 'high',
                    'insight': f'{len(high_value_stale)} high-value deals ({total_at_risk}₽) are stale',
                    'action': 'Schedule follow-ups for these deals today',
                    'impact': f'Potential revenue at risk: {total_at_risk}₽',
                })
            if win_rate < 0.25 and len(recent_won) + len(recent_lost) > 5:
                insights.append({
                    'type': 'conversion', 'priority': 'high',
                    'insight': f'Win rate is {win_rate:.0%} — below healthy threshold',
                    'action': 'Review qualification criteria and lost deal reasons',
                    'impact': 'Improving win rate by 10% could add significant revenue',
                })
            no_price = [l for l in active if not l.get('price')]
            if len(no_price) > len(active) * 0.3:
                insights.append({
                    'type': 'data_quality', 'priority': 'medium',
                    'insight': f'{len(no_price)} active deals have no price set',
                    'action': 'Update deal values for accurate forecasting',
                    'impact': 'Better pipeline visibility and forecast accuracy',
                })
            if pipeline_value > 0 and revenue > 0:
                coverage = pipeline_value / revenue
                if coverage < 3:
                    insights.append({
                        'type': 'pipeline', 'priority': 'high',
                        'insight': f'Pipeline coverage is {coverage:.1f}x — below 3x target',
                        'action': 'Increase lead generation activities',
                        'impact': 'Risk of missing revenue targets next period',
                    })
            if not insights:
                insights.append({
                    'type': 'positive', 'priority': 'low',
                    'insight': 'No critical issues detected',
                    'action': 'Continue current strategy and monitor trends',
                    'impact': 'Maintain momentum',
                })
            return {
                'actionable_insights': insights,
                'summary': {'revenue': revenue, 'pipeline_value': pipeline_value, 'win_rate': f'{win_rate:.0%}', 'stale_deals': len(stale)},
                'hint': 'Present insights sorted by priority. Each has a clear action item. Help user execute the highest-priority action first.',
            }

        elif action == 'root_cause':
            if not recent_lost:
                return {'root_cause': [], 'message': 'No lost deals in the period to analyze'}
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}
            by_stage = {}
            by_user = {}
            by_price = {'low': 0, 'mid': 0, 'high': 0}
            cycles = []
            for l in recent_lost:
                sid = l.get('pipeline_id', 0)
                uid = l.get('responsible_user_id')
                price = l.get('price', 0) or 0
                cycle = (l.get('updated_at', now) - l.get('created_at', now)) / 86400
                cycles.append(cycle)
                by_stage[sid] = by_stage.get(sid, 0) + 1
                if uid:
                    if uid not in by_user:
                        by_user[uid] = {'name': users.get(uid, f'User {uid}'), 'lost': 0, 'value': 0}
                    by_user[uid]['lost'] += 1
                    by_user[uid]['value'] += price
                if price < 30000:
                    by_price['low'] += 1
                elif price < 100000:
                    by_price['mid'] += 1
                else:
                    by_price['high'] += 1
            avg_cycle = sum(cycles) / max(len(cycles), 1)
            causes = []
            if avg_cycle < 7:
                causes.append({'cause': 'Quick losses — deals lost within a week', 'likelihood': 'high', 'fix': 'Improve initial qualification to filter out poor-fit leads early'})
            if avg_cycle > 60:
                causes.append({'cause': 'Slow death — deals lingering too long before loss', 'likelihood': 'high', 'fix': 'Set stage time limits and escalation triggers'})
            if by_price['high'] > len(recent_lost) * 0.3:
                causes.append({'cause': 'Losing big deals disproportionately', 'likelihood': 'medium', 'fix': 'Review enterprise deal process — may need executive sponsorship or different approach'})
            top_loser = max(by_user.values(), key=lambda x: x['lost']) if by_user else None
            if top_loser and top_loser['lost'] > len(recent_lost) * 0.4:
                causes.append({'cause': f'{top_loser["name"]} has disproportionate losses ({top_loser["lost"]})', 'likelihood': 'medium', 'fix': 'Coaching session and deal review for this manager'})
            if not causes:
                causes.append({'cause': 'No dominant pattern detected', 'likelihood': 'low', 'fix': 'Losses appear distributed — review individual deal notes for specific reasons'})
            return {
                'root_cause_analysis': {
                    'total_lost': len(recent_lost),
                    'total_value_lost': sum(l.get('price', 0) or 0 for l in recent_lost),
                    'avg_cycle_days': round(avg_cycle),
                    'by_price_range': by_price,
                    'by_manager': sorted(by_user.values(), key=lambda x: x['lost'], reverse=True)[:5],
                    'causes': causes,
                },
                'hint': 'Present root cause analysis. Focus on the most likely causes. Suggest specific corrective actions for each.',
            }

        elif action == 'stale_analysis':
            stale_buckets = {'14-30d': [], '30-60d': [], '60d+': []}
            for l in active:
                age = (now - (l.get('updated_at') or now)) / 86400
                if age > 60:
                    stale_buckets['60d+'].append(l)
                elif age > 30:
                    stale_buckets['30-60d'].append(l)
                elif age > 14:
                    stale_buckets['14-30d'].append(l)
            total_stale = sum(len(v) for v in stale_buckets.values())
            value_at_risk = sum(l.get('price', 0) or 0 for bucket in stale_buckets.values() for l in bucket)
            breakdown = []
            for bucket, leads in stale_buckets.items():
                if leads:
                    breakdown.append({
                        'period': bucket, 'count': len(leads),
                        'value': sum(l.get('price', 0) or 0 for l in leads),
                        'top_deals': [{'id': l.get('id'), 'name': l.get('name'), 'price': l.get('price', 0)} for l in sorted(leads, key=lambda x: x.get('price', 0) or 0, reverse=True)[:3]],
                    })
            return {
                'stale_analysis': {
                    'total_stale': total_stale, 'value_at_risk': value_at_risk,
                    'stale_rate': f'{total_stale / max(len(active), 1):.0%}',
                    'breakdown': breakdown,
                },
                'hint': 'Present stale deal analysis by aging bucket. 60d+ are critical. Show value at risk. Recommend cleanup actions.',
            }

        elif action == 'campaign_roi':
            surl = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            if pipeline_id:
                params['filter[pipeline_id]'] = pipeline_id
            async with session.get(surl, headers=headers, params=params) as resp:
                leads = []
                if resp.status == 200:
                    sdata = await resp.json()
                    leads = sdata.get('_embedded', {}).get('leads', [])
            src_url = f'{self.kommo_base_url}/api/v4/leads/sources'
            sources = {}
            try:
                async with session.get(src_url, headers=headers) as resp:
                    if resp.status == 200:
                        src_data = await resp.json()
                        for s in src_data.get('_embedded', {}).get('sources', []):
                            sources[s.get('id')] = s.get('name', f'Source {s.get("id")}')
            except Exception:
                pass
            by_source = {}
            for l in leads:
                src = l.get('source_id') or 'unknown'
                if src not in by_source:
                    by_source[src] = {'source': sources.get(src, f'Source {src}'), 'leads': 0, 'won': 0, 'revenue': 0, 'pipeline_value': 0}
                by_source[src]['leads'] += 1
                if l.get('status_id') == 142:
                    by_source[src]['won'] += 1
                    by_source[src]['revenue'] += l.get('price', 0) or 0
                elif l.get('status_id') not in (142, 143):
                    by_source[src]['pipeline_value'] += l.get('price', 0) or 0
            results = []
            for src_id, s in by_source.items():
                wr = s['won'] / max(s['leads'], 1)
                results.append({
                    'source': s['source'], 'leads': s['leads'], 'won': s['won'],
                    'revenue': s['revenue'], 'pipeline_value': s['pipeline_value'],
                    'win_rate': f'{wr:.0%}',
                    'efficiency': 'high' if wr > 0.3 else ('medium' if wr > 0.15 else 'low'),
                })
            results.sort(key=lambda x: x['revenue'], reverse=True)
            return {
                'campaign_roi': results[:15],
                'hint': 'Present campaign/source ROI. Rank by revenue. Highlight high-efficiency sources. Suggest reallocating budget from low to high performers.',
            }

        elif action == 'top_clients':
            # Top clients by revenue
            limit = args.get('limit', 10)
            contacts_url = f'{self.kommo_base_url}/api/v4/contacts'
            async with session.get(contacts_url, headers=headers, params={'limit': 250}) as resp:
                contacts = []
                if resp.status == 200:
                    cdata = await resp.json()
                    contacts = cdata.get('_embedded', {}).get('contacts', [])
            contact_map = {c['id']: c.get('name', f'Contact {c["id"]}') for c in contacts}

            # Aggregate revenue by contact from won deals
            client_revenue = {}
            for l in won:
                embedded = l.get('_embedded', {})
                lead_contacts = embedded.get('contacts', [])
                price = l.get('price', 0) or 0
                for c in lead_contacts:
                    cid = c.get('id')
                    if cid not in client_revenue:
                        client_revenue[cid] = {'name': contact_map.get(cid, f'Contact {cid}'), 'deals': 0, 'revenue': 0}
                    client_revenue[cid]['deals'] += 1
                    client_revenue[cid]['revenue'] += price
                if not lead_contacts:
                    key = f'lead_{l.get("id")}'
                    client_revenue[key] = {'name': l.get('name', 'Unknown')[:40], 'deals': 1, 'revenue': price}

            top = sorted(client_revenue.values(), key=lambda x: x['revenue'], reverse=True)[:limit]
            return {
                'top_clients': top,
                'total_clients': len(client_revenue),
                'hint': 'Present top clients ranked by revenue. Highlight VIPs. Suggest retention strategies for top accounts.',
            }

        elif action == 'rfm':
            # RFM analysis: Recency, Frequency, Monetary
            contact_rfm = {}
            for l in all_leads:
                embedded = l.get('_embedded', {})
                lead_contacts = embedded.get('contacts', [])
                price = l.get('price', 0) or 0
                updated = l.get('updated_at', 0)
                is_won = l.get('status_id') == 142
                for c in lead_contacts:
                    cid = c.get('id')
                    if cid not in contact_rfm:
                        contact_rfm[cid] = {'recency': 0, 'frequency': 0, 'monetary': 0}
                    contact_rfm[cid]['frequency'] += 1
                    contact_rfm[cid]['monetary'] += price if is_won else 0
                    contact_rfm[cid]['recency'] = max(contact_rfm[cid]['recency'], updated)

            segments = {'champions': 0, 'loyal': 0, 'at_risk': 0, 'lost': 0, 'new': 0}
            for cid, rfm in contact_rfm.items():
                days_since = (now - rfm['recency']) / 86400 if rfm['recency'] else 999
                if days_since < 30 and rfm['frequency'] >= 3 and rfm['monetary'] > 0:
                    segments['champions'] += 1
                elif rfm['frequency'] >= 2 and rfm['monetary'] > 0:
                    segments['loyal'] += 1
                elif days_since > 60 and rfm['monetary'] > 0:
                    segments['at_risk'] += 1
                elif days_since > 90:
                    segments['lost'] += 1
                else:
                    segments['new'] += 1

            return {
                'rfm_segments': segments,
                'total_contacts': len(contact_rfm),
                'hint': 'Present RFM segments. Champions are top priority for upsell. At-risk need re-engagement. Lost need win-back campaigns.',
            }

        elif action == 'workload':
            # Workload distribution across users
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            by_user = {}
            for l in active:
                uid = l.get('responsible_user_id')
                uname = users.get(uid, f'User {uid}')
                if uname not in by_user:
                    by_user[uname] = {'active': 0, 'value': 0, 'stale': 0}
                by_user[uname]['active'] += 1
                by_user[uname]['value'] += l.get('price', 0) or 0
                if (now - (l.get('updated_at') or now)) / 86400 > 14:
                    by_user[uname]['stale'] += 1

            workload = sorted([{'user': k, **v} for k, v in by_user.items()], key=lambda x: x['active'], reverse=True)
            avg_load = len(active) / max(len(by_user), 1)
            overloaded = [w for w in workload if w['active'] > avg_load * 1.5]
            underloaded = [w for w in workload if w['active'] < avg_load * 0.5]

            return {
                'workload': workload,
                'avg_deals_per_user': round(avg_load, 1),
                'overloaded': [w['user'] for w in overloaded],
                'underloaded': [w['user'] for w in underloaded],
                'hint': 'Present workload balance. Flag overloaded managers. Suggest redistribution if imbalanced.',
            }

        elif action == 'opportunities':
            # Find opportunities: high-value active deals, recently active
            high_value = sorted(
                [l for l in active if (l.get('price', 0) or 0) > 0],
                key=lambda x: x.get('price', 0) or 0, reverse=True
            )[:20]
            return {
                'opportunities': [
                    {
                        'id': l['id'], 'name': l.get('name', '')[:40],
                        'price': l.get('price', 0),
                        'days_in_pipeline': (now - l.get('created_at', now)) // 86400,
                        'last_update_days': (now - l.get('updated_at', now)) // 86400,
                    }
                    for l in high_value
                ],
                'total_pipeline_value': sum(l.get('price', 0) or 0 for l in active),
                'hint': 'Present top opportunities by value. Flag stale ones. Suggest next actions for each.',
            }

        elif action == 'big_deals':
            # Big deals analysis
            limit = args.get('limit', 10)
            all_with_price = [l for l in all_leads if (l.get('price', 0) or 0) > 0]
            big = sorted(all_with_price, key=lambda x: x.get('price', 0) or 0, reverse=True)[:limit]
            return {
                'big_deals': [
                    {
                        'id': l['id'], 'name': l.get('name', '')[:40],
                        'price': l.get('price', 0),
                        'status': 'won' if l.get('status_id') == 142 else ('lost' if l.get('status_id') == 143 else 'active'),
                        'created_days_ago': (now - l.get('created_at', now)) // 86400,
                    }
                    for l in big
                ],
                'hint': 'Present biggest deals. Show status and age. Active big deals need special attention.',
            }

        elif action == 'ranking':
            # Manager ranking by various metrics
            uurl = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(uurl, headers=headers) as resp:
                users = {}
                if resp.status == 200:
                    udata = await resp.json()
                    users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

            ranking = {}
            for l in all_leads:
                uid = l.get('responsible_user_id')
                uname = users.get(uid, f'User {uid}')
                if uname not in ranking:
                    ranking[uname] = {'won': 0, 'lost': 0, 'active': 0, 'revenue': 0}
                if l.get('status_id') == 142:
                    ranking[uname]['won'] += 1
                    ranking[uname]['revenue'] += l.get('price', 0) or 0
                elif l.get('status_id') == 143:
                    ranking[uname]['lost'] += 1
                else:
                    ranking[uname]['active'] += 1

            result = []
            for uname, stats in ranking.items():
                wr = stats['won'] / max(stats['won'] + stats['lost'], 1)
                result.append({'user': uname, **stats, 'win_rate': f'{wr:.0%}'})
            result.sort(key=lambda x: x['revenue'], reverse=True)

            return {
                'ranking': result,
                'hint': 'Present manager ranking. Highlight top performers. Identify who needs coaching.',
            }

        elif action == 'compare':
            # Compare current period vs previous
            prev_cutoff = cutoff - days * 86400
            current = [l for l in all_leads if l.get('created_at', 0) >= cutoff]
            previous = [l for l in all_leads if prev_cutoff <= l.get('created_at', 0) < cutoff]

            def period_stats(leads_list):
                w = [l for l in leads_list if l.get('status_id') == 142]
                lo = [l for l in leads_list if l.get('status_id') == 143]
                return {
                    'total': len(leads_list),
                    'won': len(w),
                    'lost': len(lo),
                    'revenue': sum(l.get('price', 0) or 0 for l in w),
                    'pipeline_value': sum(l.get('price', 0) or 0 for l in leads_list),
                    'win_rate': f'{len(w) / max(len(w) + len(lo), 1):.0%}',
                }

            curr_stats = period_stats(current)
            prev_stats = period_stats(previous)

            def delta(curr, prev):
                if prev == 0:
                    return '+∞' if curr > 0 else '0%'
                pct = ((curr - prev) / prev) * 100
                return f'{pct:+.0f}%'

            return {
                'current_period': curr_stats,
                'previous_period': prev_stats,
                'changes': {
                    'leads': delta(curr_stats['total'], prev_stats['total']),
                    'won': delta(curr_stats['won'], prev_stats['won']),
                    'revenue': delta(curr_stats['revenue'], prev_stats['revenue']),
                },
                'hint': 'Present period comparison. Highlight improvements and declines. Suggest actions for declining metrics.',
            }

        elif action == 'yoy':
            # Year-over-year comparison
            from datetime import datetime as dt
            this_year = dt.now().year
            by_year = {}
            for l in all_leads:
                created = l.get('created_at', 0)
                if created:
                    year = dt.fromtimestamp(created).year
                    if year not in by_year:
                        by_year[year] = {'total': 0, 'won': 0, 'revenue': 0}
                    by_year[year]['total'] += 1
                    if l.get('status_id') == 142:
                        by_year[year]['won'] += 1
                        by_year[year]['revenue'] += l.get('price', 0) or 0

            return {
                'yoy': dict(sorted(by_year.items())),
                'hint': 'Present year-over-year trends. Show growth or decline in key metrics.',
            }

        return {'error': f'Unknown insights action: {action}'}

    async def _handle_activity(self, session, headers, args: dict) -> dict:
        """Activity analytics: feed, productivity, KPI, recommendations, correlations."""
        import time
        from datetime import datetime
        action = args.get('action')
        user_id = args.get('user_id')
        days = args.get('days', 30)
        pipeline_id = args.get('pipeline_id')
        now = int(time.time())
        cutoff = now - days * 86400

        uurl = f'{self.kommo_base_url}/api/v4/users'
        async with session.get(uurl, headers=headers) as resp:
            users = {}
            if resp.status == 200:
                udata = await resp.json()
                users = {u.get('id'): u.get('name') for u in udata.get('_embedded', {}).get('users', [])}

        url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id
        async with session.get(url, headers=headers, params=params) as resp:
            all_leads = []
            if resp.status == 200:
                data = await resp.json()
                all_leads = data.get('_embedded', {}).get('leads', [])

        turl = f'{self.kommo_base_url}/api/v4/tasks'
        tparams = {'limit': 250}
        async with session.get(turl, headers=headers, params=tparams) as resp:
            all_tasks = []
            if resp.status == 200:
                tdata = await resp.json()
                all_tasks = tdata.get('_embedded', {}).get('tasks', [])

        if action == 'feed':
            events = []
            for l in all_leads:
                if l.get('created_at', 0) >= cutoff:
                    uid = l.get('responsible_user_id')
                    if user_id and uid != user_id:
                        continue
                    events.append({
                        'type': 'lead_created', 'timestamp': l.get('created_at'),
                        'user': users.get(uid, f'User {uid}'),
                        'detail': f'Created deal "{l.get("name")}" ({l.get("price", 0)}₽)',
                    })
                if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff:
                    uid = l.get('responsible_user_id')
                    if user_id and uid != user_id:
                        continue
                    events.append({
                        'type': 'deal_won', 'timestamp': l.get('updated_at'),
                        'user': users.get(uid, f'User {uid}'),
                        'detail': f'Won deal "{l.get("name")}" ({l.get("price", 0)}₽)',
                    })
            for t in all_tasks:
                if t.get('is_completed') and t.get('updated_at', 0) >= cutoff:
                    uid = t.get('responsible_user_id')
                    if user_id and uid != user_id:
                        continue
                    events.append({
                        'type': 'task_completed', 'timestamp': t.get('updated_at'),
                        'user': users.get(uid, f'User {uid}'),
                        'detail': f'Completed: {(t.get("text", "")[:60])}',
                    })
            events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return {
                'activity_feed': events[:30],
                'total_events': len(events),
                'period_days': days,
                'hint': 'Present as chronological activity feed. Group by day. Highlight wins and important milestones.',
            }

        elif action == 'productivity':
            user_prod = {}
            for uid, name in users.items():
                if user_id and uid != user_id:
                    continue
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                user_tasks_list = [t for t in all_tasks if t.get('responsible_user_id') == uid]
                created = [l for l in user_leads if l.get('created_at', 0) >= cutoff]
                won_deals = [l for l in user_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                completed_tasks = [t for t in user_tasks_list if t.get('is_completed') and t.get('updated_at', 0) >= cutoff]
                revenue = sum(l.get('price', 0) or 0 for l in won_deals)
                user_prod[uid] = {
                    'user': name, 'user_id': uid,
                    'deals_created': len(created), 'deals_won': len(won_deals),
                    'revenue': revenue, 'tasks_completed': len(completed_tasks),
                    'productivity_score': len(won_deals) * 30 + len(completed_tasks) * 5 + len(created) * 10,
                    'revenue_per_day': round(revenue / max(days, 1)),
                }
            results = sorted(user_prod.values(), key=lambda x: x['productivity_score'], reverse=True)
            return {
                'productivity': results,
                'period_days': days,
                'hint': 'Present productivity rankings. Show score breakdown. Highlight top performers and suggest improvements for lower-ranked.',
            }

        elif action == 'kpi':
            user_kpis = {}
            for uid, name in users.items():
                if user_id and uid != user_id:
                    continue
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won_deals = [l for l in user_leads if l.get('status_id') == 142 and l.get('updated_at', 0) >= cutoff]
                lost_deals = [l for l in user_leads if l.get('status_id') == 143 and l.get('updated_at', 0) >= cutoff]
                active_deals = [l for l in user_leads if l.get('status_id') not in (142, 143)]
                user_tasks_list = [t for t in all_tasks if t.get('responsible_user_id') == uid]
                completed = [t for t in user_tasks_list if t.get('is_completed')]
                overdue = [t for t in user_tasks_list if not t.get('is_completed') and t.get('complete_till', now + 1) < now]
                revenue = sum(l.get('price', 0) or 0 for l in won_deals)
                wr = len(won_deals) / max(len(won_deals) + len(lost_deals), 1)
                user_kpis[uid] = {
                    'user': name, 'user_id': uid,
                    'kpis': {
                        'deals_won': len(won_deals), 'revenue': revenue,
                        'win_rate': f'{wr:.0%}',
                        'active_deals': len(active_deals),
                        'tasks_completed': len(completed),
                        'tasks_overdue': len(overdue),
                        'avg_deal_value': round(revenue / max(len(won_deals), 1)),
                    },
                    'health': 'good' if wr > 0.3 and len(overdue) < 3 else ('warning' if wr > 0.15 else 'critical'),
                }
            results = sorted(user_kpis.values(), key=lambda x: x['kpis']['revenue'], reverse=True)
            return {
                'activity_kpis': results,
                'period_days': days,
                'hint': 'Present KPIs per user in a dashboard format. Color-code health status. Focus on actionable metrics.',
            }

        elif action == 'recommendations':
            recs = []
            for uid, name in users.items():
                if user_id and uid != user_id:
                    continue
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won_deals = [l for l in user_leads if l.get('status_id') == 142]
                lost_deals = [l for l in user_leads if l.get('status_id') == 143]
                active_deals = [l for l in user_leads if l.get('status_id') not in (142, 143)]
                stale = [l for l in active_deals if (now - (l.get('updated_at') or now)) / 86400 > 14]
                user_recs = []
                if len(stale) > 3:
                    user_recs.append(f'Follow up on {len(stale)} stale deals — they need attention')
                wr = len(won_deals) / max(len(won_deals) + len(lost_deals), 1)
                if wr < 0.2 and len(won_deals) + len(lost_deals) > 3:
                    user_recs.append('Focus on qualification — win rate is below 20%')
                if len(active_deals) > 20:
                    user_recs.append(f'Pipeline is large ({len(active_deals)} deals) — prioritize top opportunities')
                if not user_recs:
                    user_recs.append('Keep up the good work! Consider mentoring teammates.')
                recs.append({'user': name, 'user_id': uid, 'recommendations': user_recs})
            return {
                'recommendations': recs,
                'hint': 'Present personalized recommendations per user. Be constructive and actionable.',
            }

        elif action == 'correlations':
            corr_data = []
            for uid, name in users.items():
                user_leads = [l for l in all_leads if l.get('responsible_user_id') == uid]
                won_deals = [l for l in user_leads if l.get('status_id') == 142]
                lost_deals = [l for l in user_leads if l.get('status_id') == 143]
                active_deals = [l for l in user_leads if l.get('status_id') not in (142, 143)]
                user_tasks_list = [t for t in all_tasks if t.get('responsible_user_id') == uid]
                completed = len([t for t in user_tasks_list if t.get('is_completed')])
                total_tasks = len(user_tasks_list)
                wr = len(won_deals) / max(len(won_deals) + len(lost_deals), 1)
                revenue = sum(l.get('price', 0) or 0 for l in won_deals)
                corr_data.append({
                    'user': name, 'user_id': uid,
                    'tasks_completed': completed, 'total_tasks': total_tasks,
                    'deals_won': len(won_deals), 'win_rate': f'{wr:.0%}',
                    'revenue': revenue, 'active_deals': len(active_deals),
                    'task_completion_rate': f'{completed / max(total_tasks, 1):.0%}',
                })
            corr_data.sort(key=lambda x: x['revenue'], reverse=True)
            high_perf = [c for c in corr_data if c['revenue'] > 0]
            insights = []
            if high_perf:
                avg_tasks_top = sum(c['tasks_completed'] for c in high_perf[:3]) / min(len(high_perf), 3)
                avg_tasks_all = sum(c['tasks_completed'] for c in corr_data) / max(len(corr_data), 1)
                if avg_tasks_top > avg_tasks_all * 1.3:
                    insights.append('Top performers complete 30%+ more tasks than average')
                else:
                    insights.append('Task volume does not strongly correlate with revenue — quality over quantity')
            return {
                'correlations': corr_data,
                'insights': insights,
                'hint': 'Present activity-result correlations. Show which activities drive results. Help identify what top performers do differently.',
            }

        return {'error': f'Unknown activity action: {action}'}

    async def _handle_manager_stats(self, session, headers, args: dict) -> dict:
        """Manager performance statistics: deals, revenue, conversion, tasks."""
        import time as _time
        from datetime import datetime, timedelta

        user_id = args.get('user_id')
        date_from_str = args.get('date_from')
        date_to_str = args.get('date_to')

        # Parse dates
        if date_from_str:
            try:
                date_from = int(datetime.strptime(date_from_str, '%Y-%m-%d').timestamp())
            except Exception:
                date_from = int((datetime.now() - timedelta(days=30)).timestamp())
        else:
            date_from = int((datetime.now() - timedelta(days=30)).timestamp())

        if date_to_str:
            try:
                date_to = int(datetime.strptime(date_to_str, '%Y-%m-%d').timestamp())
            except Exception:
                date_to = int(_time.time())
        else:
            date_to = int(_time.time())

        # Get users
        users_url = f'{self.kommo_base_url}/api/v4/users'
        async with session.get(users_url, headers=headers) as resp:
            if resp.status != 200:
                return {'error': f'Failed to get users: {resp.status}'}
            users_data = await resp.json()
            users = users_data.get('_embedded', {}).get('users', [])

        if user_id:
            users = [u for u in users if u.get('id') == user_id]

        if not users:
            return {'error': 'No users found'}

        managers = []
        for user in users[:15]:
            uid = user.get('id')
            uname = user.get('name', 'Unknown')

            # Get leads for this user in date range
            leads_url = f'{self.kommo_base_url}/api/v4/leads'
            params = {
                'filter[responsible_user_id]': uid,
                'filter[created_at][from]': date_from,
                'filter[created_at][to]': date_to,
                'limit': 250,
            }
            async with session.get(leads_url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    leads_data = await resp.json()
                    leads = leads_data.get('_embedded', {}).get('leads', [])
                elif resp.status == 204:
                    leads = []
                else:
                    leads = []

            won = [l for l in leads if l.get('status_id') == 142]
            lost = [l for l in leads if l.get('status_id') == 143]
            active = [l for l in leads if l.get('status_id') not in (142, 143)]
            total_revenue = sum(l.get('price', 0) or 0 for l in leads)
            won_revenue = sum(l.get('price', 0) or 0 for l in won)

            # Get tasks for this user
            tasks_url = f'{self.kommo_base_url}/api/v4/tasks'
            tasks_params = {'filter[responsible_user_id]': uid, 'limit': 250}
            async with session.get(tasks_url, headers=headers, params=tasks_params) as resp:
                if resp.status == 200:
                    tasks_data = await resp.json()
                    tasks = tasks_data.get('_embedded', {}).get('tasks', [])
                else:
                    tasks = []

            completed_tasks = [t for t in tasks if t.get('is_completed')]
            overdue_tasks = [t for t in tasks if not t.get('is_completed') and t.get('complete_till', 0) < int(_time.time())]

            conversion = len(won) / max(len(won) + len(lost), 1)

            managers.append({
                'user': uname,
                'user_id': uid,
                'total_leads': len(leads),
                'active_leads': len(active),
                'won': len(won),
                'lost': len(lost),
                'conversion_rate': f'{conversion:.1%}',
                'total_revenue': total_revenue,
                'won_revenue': won_revenue,
                'avg_deal': won_revenue // max(len(won), 1),
                'total_tasks': len(tasks),
                'completed_tasks': len(completed_tasks),
                'overdue_tasks': len(overdue_tasks),
            })

        managers.sort(key=lambda x: x['won_revenue'], reverse=True)

        return {
            'period': f'{date_from_str or "30d ago"} — {date_to_str or "today"}',
            'managers': managers,
            'total_managers': len(managers),
            'summary': {
                'total_leads': sum(m['total_leads'] for m in managers),
                'total_won': sum(m['won'] for m in managers),
                'total_revenue': sum(m['won_revenue'] for m in managers),
            },
        }

    async def _handle_deals_ext(self, session, headers, args: dict) -> dict:
        """Extended deal management: by_stage, health, velocity, at_risk, by_user."""
        import time as _time

        action = args.get('action', 'by_stage')
        pipeline_id = args.get('pipeline_id')
        days = args.get('days', 30)
        limit = args.get('limit', 20)

        # Get leads
        leads_url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250}
        if pipeline_id:
            params['filter[pipeline_id]'] = pipeline_id

        async with session.get(leads_url, headers=headers, params=params) as resp:
            if resp.status == 200:
                leads_data = await resp.json()
                leads = leads_data.get('_embedded', {}).get('leads', [])
            elif resp.status == 204:
                return {'deals': [], 'total': 0, 'message': 'No deals found'}
            else:
                return {'error': f'API error: {resp.status}'}

        now = int(_time.time())

        if action == 'by_stage':
            # Get pipeline structure for stage names
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status == 200:
                    p_data = await resp.json()
                    all_pipelines = p_data.get('_embedded', {}).get('pipelines', [])
                else:
                    all_pipelines = []

            status_map = {}
            for p in all_pipelines:
                for s in p.get('_embedded', {}).get('statuses', []):
                    status_map[s['id']] = {'name': s['name'], 'pipeline': p['name']}

            by_stage = {}
            for lead in leads:
                sid = lead.get('status_id')
                info = status_map.get(sid, {'name': str(sid), 'pipeline': 'Unknown'})
                key = f"{info['pipeline']} / {info['name']}"
                if key not in by_stage:
                    by_stage[key] = {'count': 0, 'revenue': 0, 'deals': []}
                by_stage[key]['count'] += 1
                by_stage[key]['revenue'] += lead.get('price', 0) or 0
                if len(by_stage[key]['deals']) < 3:
                    by_stage[key]['deals'].append({
                        'id': lead.get('id'),
                        'name': lead.get('name', '')[:40],
                        'price': lead.get('price', 0),
                    })

            return {'by_stage': by_stage, 'total_deals': len(leads)}

        elif action == 'health':
            # Deal health: stale, no tasks, no contacts
            stale_threshold = now - (days * 86400)
            active = [l for l in leads if l.get('status_id') not in (142, 143)]
            stale = [l for l in active if l.get('updated_at', 0) < stale_threshold]
            no_price = [l for l in active if not l.get('price')]

            return {
                'total_active': len(active),
                'stale_deals': len(stale),
                'stale_threshold_days': days,
                'no_price_deals': len(no_price),
                'health_score': f'{max(0, 100 - len(stale) * 5 - len(no_price) * 3)}/100',
                'stale_list': [
                    {'id': l['id'], 'name': l.get('name', '')[:40], 'days_stale': (now - l.get('updated_at', now)) // 86400, 'price': l.get('price', 0)}
                    for l in sorted(stale, key=lambda x: x.get('updated_at', 0))[:limit]
                ],
            }

        elif action == 'velocity':
            # Deal velocity: time from creation to close
            won = [l for l in leads if l.get('status_id') == 142]
            if not won:
                return {'message': 'No won deals to calculate velocity', 'total_deals': len(leads)}

            velocities = []
            for l in won:
                created = l.get('created_at', 0)
                closed = l.get('closed_at') or l.get('updated_at', 0)
                if created and closed:
                    days_to_close = max(1, (closed - created) // 86400)
                    velocities.append({
                        'id': l['id'],
                        'name': l.get('name', '')[:40],
                        'price': l.get('price', 0),
                        'days_to_close': days_to_close,
                    })

            if velocities:
                avg_days = sum(v['days_to_close'] for v in velocities) / len(velocities)
                fastest = sorted(velocities, key=lambda x: x['days_to_close'])[:5]
                slowest = sorted(velocities, key=lambda x: -x['days_to_close'])[:5]
            else:
                avg_days = 0
                fastest = []
                slowest = []

            return {
                'avg_days_to_close': round(avg_days, 1),
                'total_won': len(won),
                'fastest': fastest,
                'slowest': slowest,
            }

        elif action == 'at_risk':
            # At-risk deals: stale, high value, no recent activity
            active = [l for l in leads if l.get('status_id') not in (142, 143)]
            risk_threshold = now - (days * 86400)

            at_risk = []
            for l in active:
                risk_score = 0
                reasons = []
                if l.get('updated_at', 0) < risk_threshold:
                    risk_score += 40
                    reasons.append(f'No update for {(now - l.get("updated_at", now)) // 86400}d')
                price = l.get('price', 0) or 0
                if price > 100000:
                    risk_score += 20
                    reasons.append('High value deal')
                if not l.get('responsible_user_id'):
                    risk_score += 30
                    reasons.append('No responsible user')

                if risk_score >= 40:
                    at_risk.append({
                        'id': l['id'],
                        'name': l.get('name', '')[:40],
                        'price': price,
                        'risk_score': risk_score,
                        'reasons': reasons,
                    })

            at_risk.sort(key=lambda x: x['risk_score'], reverse=True)
            return {'at_risk': at_risk[:limit], 'total_at_risk': len(at_risk), 'total_active': len(active)}

        elif action == 'by_user':
            # Deals grouped by responsible user
            users_url = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(users_url, headers=headers) as resp:
                if resp.status == 200:
                    u_data = await resp.json()
                    all_users = {u['id']: u['name'] for u in u_data.get('_embedded', {}).get('users', [])}
                else:
                    all_users = {}

            by_user = {}
            for l in leads:
                uid = l.get('responsible_user_id')
                uname = all_users.get(uid, f'User {uid}')
                if uname not in by_user:
                    by_user[uname] = {'count': 0, 'revenue': 0, 'won': 0, 'active': 0}
                by_user[uname]['count'] += 1
                by_user[uname]['revenue'] += l.get('price', 0) or 0
                if l.get('status_id') == 142:
                    by_user[uname]['won'] += 1
                elif l.get('status_id') not in (142, 143):
                    by_user[uname]['active'] += 1

            return {'by_user': by_user, 'total_deals': len(leads)}

        return {'error': f'Unknown deals_ext action: {action}'}

    async def _handle_communications(self, session, headers, args: dict) -> dict:
        """Communication history: history, calls, timeline, last_contact, by_user, summary, no_contact."""
        import time as _time

        action = args.get('action', 'history')
        entity_type = args.get('entity_type', 'leads')
        entity_id = args.get('entity_id')
        days = args.get('days', 30)

        if action == 'history' and entity_id:
            # Get notes/events for entity
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/notes'
            async with session.get(url, headers=headers, params={'limit': 50}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])
                    return {
                        'entity_id': entity_id,
                        'entity_type': entity_type,
                        'communications': [
                            {
                                'id': n.get('id'),
                                'type': n.get('note_type'),
                                'text': (n.get('params', {}).get('text', '') or '')[:200],
                                'created_at': n.get('created_at'),
                                'created_by': n.get('created_by'),
                            }
                            for n in notes
                        ],
                        'total': len(notes),
                    }
                elif resp.status == 204:
                    return {'entity_id': entity_id, 'communications': [], 'total': 0}
                return {'error': f'API error: {resp.status}'}

        elif action == 'calls':
            # Get call events
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {'filter[type]': 'incoming_call,outgoing_call', 'limit': 50}
            if entity_id:
                params['filter[entity_id]'] = entity_id

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    return {
                        'calls': [
                            {
                                'id': e.get('id'),
                                'type': e.get('type'),
                                'entity_id': e.get('entity_id'),
                                'created_at': e.get('created_at'),
                                'created_by': e.get('created_by'),
                            }
                            for e in events
                        ],
                        'total': len(events),
                    }
                elif resp.status == 204:
                    return {'calls': [], 'total': 0}
                return {'error': f'API error: {resp.status}'}

        elif action == 'timeline' and entity_id:
            # Get all events for entity
            url = f'{self.kommo_base_url}/api/v4/events'
            params = {'filter[entity_id]': entity_id, 'filter[entity][]': entity_type.rstrip('s'), 'limit': 50}

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    events = data.get('_embedded', {}).get('events', [])
                    return {
                        'entity_id': entity_id,
                        'timeline': [
                            {
                                'type': e.get('type'),
                                'created_at': e.get('created_at'),
                                'created_by': e.get('created_by'),
                                'value_after': str(e.get('value_after', ''))[:100],
                            }
                            for e in events
                        ],
                        'total': len(events),
                    }
                elif resp.status == 204:
                    return {'entity_id': entity_id, 'timeline': [], 'total': 0}
                return {'error': f'API error: {resp.status}'}

        elif action == 'last_contact':
            # Find entities with most recent communication
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250, 'order[updated_at]': 'desc'}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    return {
                        'recent_contacts': [
                            {
                                'id': l['id'],
                                'name': l.get('name', '')[:40],
                                'updated_at': l.get('updated_at'),
                                'days_ago': (int(_time.time()) - l.get('updated_at', 0)) // 86400,
                            }
                            for l in leads[:20]
                        ],
                    }
                return {'error': f'API error: {resp.status}'}

        elif action == 'by_user':
            # Communication stats by user
            users_url = f'{self.kommo_base_url}/api/v4/users'
            async with session.get(users_url, headers=headers) as resp:
                if resp.status != 200:
                    return {'error': f'Failed to get users: {resp.status}'}
                users = (await resp.json()).get('_embedded', {}).get('users', [])

            result = []
            for u in users[:10]:
                uid = u['id']
                events_url = f'{self.kommo_base_url}/api/v4/events'
                params = {'filter[created_by]': uid, 'limit': 1}
                async with session.get(events_url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        ev_data = await resp.json()
                        events = ev_data.get('_embedded', {}).get('events', [])
                        last_event = events[0].get('created_at') if events else None
                    else:
                        last_event = None

                result.append({
                    'user': u.get('name'),
                    'user_id': uid,
                    'last_activity': last_event,
                })
            return {'by_user': result}

        elif action == 'summary':
            # Communication summary for entity
            if not entity_id:
                return {'error': 'entity_id required for summary'}
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/{entity_id}/notes'
            async with session.get(url, headers=headers, params={'limit': 100}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    notes = data.get('_embedded', {}).get('notes', [])
                    by_type = {}
                    for n in notes:
                        ntype = n.get('note_type', 'unknown')
                        by_type[ntype] = by_type.get(ntype, 0) + 1
                    return {
                        'entity_id': entity_id,
                        'total_communications': len(notes),
                        'by_type': by_type,
                        'first_contact': notes[-1].get('created_at') if notes else None,
                        'last_contact': notes[0].get('created_at') if notes else None,
                    }
                elif resp.status == 204:
                    return {'entity_id': entity_id, 'total_communications': 0, 'by_type': {}}
                return {'error': f'API error: {resp.status}'}

        elif action == 'no_contact':
            # Find leads with no recent communication
            now = int(_time.time())
            threshold = now - (days * 86400)
            url = f'{self.kommo_base_url}/api/v4/leads'
            params = {'limit': 250}
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    leads = data.get('_embedded', {}).get('leads', [])
                    active = [l for l in leads if l.get('status_id') not in (142, 143)]
                    no_contact = [l for l in active if l.get('updated_at', 0) < threshold]
                    return {
                        'no_contact_leads': [
                            {
                                'id': l['id'],
                                'name': l.get('name', '')[:40],
                                'price': l.get('price', 0),
                                'days_since_update': (now - l.get('updated_at', now)) // 86400,
                            }
                            for l in sorted(no_contact, key=lambda x: x.get('updated_at', 0))[:20]
                        ],
                        'total_no_contact': len(no_contact),
                        'threshold_days': days,
                    }
                return {'error': f'API error: {resp.status}'}

        return {'error': f'Unknown communications action: {action}'}

    async def _handle_ltv(self, session, headers, args: dict) -> dict:
        """Customer LTV analytics: by_source, by_pipeline, cohorts, segments."""
        import time as _time
        from datetime import datetime, timedelta

        action = args.get('action', 'by_pipeline')
        days = args.get('days', 180)

        # Get all leads
        leads_url = f'{self.kommo_base_url}/api/v4/leads'
        params = {'limit': 250}
        all_leads = []

        async with session.get(leads_url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                all_leads = data.get('_embedded', {}).get('leads', [])
            elif resp.status == 204:
                return {'message': 'No leads found for LTV analysis'}
            else:
                return {'error': f'API error: {resp.status}'}

        won_leads = [l for l in all_leads if l.get('status_id') == 142]

        if action == 'by_pipeline':
            # Get pipelines
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status == 200:
                    p_data = await resp.json()
                    pipeline_map = {p['id']: p['name'] for p in p_data.get('_embedded', {}).get('pipelines', [])}
                else:
                    pipeline_map = {}

            by_pipeline = {}
            for l in won_leads:
                pid = l.get('pipeline_id')
                pname = pipeline_map.get(pid, f'Pipeline {pid}')
                if pname not in by_pipeline:
                    by_pipeline[pname] = {'deals': 0, 'revenue': 0, 'prices': []}
                by_pipeline[pname]['deals'] += 1
                price = l.get('price', 0) or 0
                by_pipeline[pname]['revenue'] += price
                by_pipeline[pname]['prices'].append(price)

            result = {}
            for pname, data in by_pipeline.items():
                prices = data['prices']
                result[pname] = {
                    'won_deals': data['deals'],
                    'total_revenue': data['revenue'],
                    'avg_deal': data['revenue'] // max(data['deals'], 1),
                    'median_deal': sorted(prices)[len(prices) // 2] if prices else 0,
                    'max_deal': max(prices) if prices else 0,
                }

            return {'ltv_by_pipeline': result, 'total_won': len(won_leads)}

        elif action == 'by_source':
            # Group won deals by source
            by_source = {}
            for l in won_leads:
                source = None
                # Try to get source from custom fields or tags
                tags = l.get('_embedded', {}).get('tags', [])
                source = tags[0].get('name') if tags else 'Unknown'
                if source not in by_source:
                    by_source[source] = {'deals': 0, 'revenue': 0}
                by_source[source]['deals'] += 1
                by_source[source]['revenue'] += l.get('price', 0) or 0

            for src in by_source:
                by_source[src]['avg_deal'] = by_source[src]['revenue'] // max(by_source[src]['deals'], 1)

            return {'ltv_by_source': by_source, 'total_won': len(won_leads)}

        elif action == 'cohorts':
            # Group by creation month
            cohorts = {}
            for l in won_leads:
                created = l.get('created_at', 0)
                if created:
                    month = datetime.fromtimestamp(created).strftime('%Y-%m')
                else:
                    month = 'Unknown'
                if month not in cohorts:
                    cohorts[month] = {'deals': 0, 'revenue': 0}
                cohorts[month]['deals'] += 1
                cohorts[month]['revenue'] += l.get('price', 0) or 0

            for m in cohorts:
                cohorts[m]['avg_deal'] = cohorts[m]['revenue'] // max(cohorts[m]['deals'], 1)

            return {
                'cohorts': dict(sorted(cohorts.items())),
                'total_won': len(won_leads),
                'total_revenue': sum(c['revenue'] for c in cohorts.values()),
            }

        elif action == 'segments':
            # Segment by deal value
            if not won_leads:
                return {'message': 'No won deals for segmentation'}

            prices = [l.get('price', 0) or 0 for l in won_leads]
            prices.sort()
            median = prices[len(prices) // 2]

            segments = {
                'high_value': {'threshold': median * 2, 'deals': 0, 'revenue': 0},
                'medium_value': {'threshold': median, 'deals': 0, 'revenue': 0},
                'low_value': {'threshold': 0, 'deals': 0, 'revenue': 0},
            }

            for l in won_leads:
                price = l.get('price', 0) or 0
                if price >= median * 2:
                    segments['high_value']['deals'] += 1
                    segments['high_value']['revenue'] += price
                elif price >= median:
                    segments['medium_value']['deals'] += 1
                    segments['medium_value']['revenue'] += price
                else:
                    segments['low_value']['deals'] += 1
                    segments['low_value']['revenue'] += price

            return {
                'segments': segments,
                'total_won': len(won_leads),
                'median_deal': median,
                'total_revenue': sum(s['revenue'] for s in segments.values()),
            }

        return {'error': f'Unknown LTV action: {action}'}

    # --- Region KLADR mapping for DaData ---
    REGION_KLADR = {
        'москва': '77',
        'московская область': '50',
        'санкт-петербург': '78',
        'ленинградская область': '47',
        'краснодарский край': '23',
        'ростовская область': '61',
        'свердловская область': '66',
        'новосибирская область': '54',
        'нижегородская область': '52',
        'самарская область': '63',
        'татарстан': '16',
        'челябинская область': '74',
        'башкортостан': '02',
        'пермский край': '59',
        'воронежская область': '36',
        'волгоградская область': '34',
        'красноярский край': '24',
        'саратовская область': '64',
        'тюменская область': '72',
        'омская область': '55',
        'ставропольский край': '26',
        'кабардино-балкария': '07',
        'дагестан': '05',
        'приморский край': '25',
        'хабаровский край': '27',
        'иркутская область': '38',
        'калининградская область': '39',
        'крым': '91',
        'севастополь': '92',
        'сочи': '23',
        'адыгея': '01',
    }

    # --- 2GIS region IDs ---
    TWOGIS_REGIONS = {
        'сочи': 11,
        'москва': 32,
        'санкт-петербург': 38,
        'краснодар': 10,
        'новосибирск': 1,
        'екатеринбург': 7,
        'нижний новгород': 18,
        'казань': 12,
        'ростов-на-дону': 3,
        'самара': 8,
        'воронеж': 4,
        'волгоград': 5,
        'красноярск': 19,
        'саратов': 9,
        'тюмень': 6,
        'омск': 2,
        'челябинск': 13,
        'пермь': 14,
        'уфа': 15,
    }

    async def _handle_lead_gen(self, session, headers, args: dict) -> dict:
        """Handle kommo_lead_gen tool - B2B lead generation via DaData/2GIS + import to CRM."""
        action = args.get('action')

        if action == 'search_companies':
            return await self._lead_gen_search_dadata(args)

        elif action == 'search_horeca':
            return await self._lead_gen_search_2gis(args)

        elif action == 'preview':
            # Preview is same as search but with explicit preview flag
            okved = args.get('okved')
            if okved:
                result = await self._lead_gen_search_dadata(args)
            else:
                result = await self._lead_gen_search_2gis(args)
            result['preview'] = True
            result['message'] = f'Найдено {result.get("total", 0)} компаний. Для импорта используйте action=import_to_crm.'
            return result

        elif action == 'enrich':
            return await self._lead_gen_enrich(args)

        elif action == 'import_to_crm':
            return await self._lead_gen_import(session, headers, args)

        return {'error': f'Unknown lead_gen action: {action}'}

    async def _lead_gen_search_dadata(self, args: dict) -> dict:
        """Search companies via DaData suggest/party API."""
        dadata_token = os.getenv('DADATA_API_TOKEN', '')
        if not dadata_token:
            return {'error': 'DADATA_API_TOKEN not configured. Set it in environment variables.'}

        okved = args.get('okved', '')
        query = args.get('query', '*')
        region = args.get('region', '')
        limit = min(args.get('limit', 20), 100)

        url = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party'
        req_headers = {
            'Authorization': f'Token {dadata_token}',
            'Content-Type': 'application/json',
        }

        payload = {
            'query': query if query else '*',
            'count': limit,
            'status': ['ACTIVE'],
        }

        # Add OKVED filter
        if okved:
            payload['okved'] = [okved]

        # Add region filter
        if region:
            region_lower = region.lower().strip()
            kladr = self.REGION_KLADR.get(region_lower, '')
            if kladr:
                payload['locations'] = [{'kladr_id': kladr}]
            else:
                # Try as-is, DaData might understand
                payload['locations'] = [{'region': region}]

        try:
            async with aiohttp.ClientSession() as dadata_session:
                async with dadata_session.post(url, json=payload, headers=req_headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {'error': f'DaData API error {resp.status}', 'details': error_text[:300]}

                    data = await resp.json()
                    suggestions = data.get('suggestions', [])

                    companies = []
                    for s in suggestions:
                        d = s.get('data', {})
                        address = d.get('address', {})
                        management = d.get('management', {})
                        name_info = d.get('name', {})

                        company = {
                            'name': name_info.get('short_with_opf') or name_info.get('full_with_opf') or s.get('value', ''),
                            'inn': d.get('inn', ''),
                            'ogrn': d.get('ogrn', ''),
                            'okved': d.get('okved', ''),
                            'okved_type': d.get('okved_type', ''),
                            'address': address.get('unrestricted_value', '') if isinstance(address, dict) else str(address),
                            'region': address.get('data', {}).get('region_with_type', '') if isinstance(address, dict) else '',
                            'city': address.get('data', {}).get('city', '') if isinstance(address, dict) else '',
                            'director': management.get('name', ''),
                            'director_post': management.get('post', ''),
                            'type': d.get('type', ''),  # LEGAL / INDIVIDUAL
                            'status': d.get('state', {}).get('status', ''),
                            'employees': d.get('employee_count'),
                        }
                        companies.append(company)

                    # Store in instance for subsequent import
                    self._lead_gen_cache = companies

                    return {
                        'total': len(companies),
                        'companies': companies,
                        'filters': {
                            'okved': okved,
                            'region': region,
                            'query': query,
                        },
                        'message': f'Найдено {len(companies)} компаний. Для импорта в CRM используйте action=import_to_crm.',
                    }

        except asyncio.TimeoutError:
            return {'error': 'DaData API timeout'}
        except Exception as e:
            logger.error(f'DaData search error: {e}')
            return {'error': f'DaData search error: {str(e)}'}

    async def _lead_gen_search_2gis(self, args: dict) -> dict:
        """Search HoReCa via 2GIS API."""
        twogis_key = os.getenv('TWOGIS_API_KEY', '')
        if not twogis_key:
            return {'error': 'TWOGIS_API_KEY not configured. Set it in environment variables.'}

        city = args.get('city', 'Сочи')
        rubric = args.get('rubric', 'рестораны')
        limit = min(args.get('limit', 20), 50)

        city_lower = city.lower().strip()
        region_id = self.TWOGIS_REGIONS.get(city_lower)

        url = 'https://catalog.api.2gis.com/3.0/items'
        params = {
            'q': rubric,
            'type': 'branch',
            'fields': 'items.contact_groups,items.org,items.address',
            'key': twogis_key,
            'page_size': limit,
        }
        if region_id:
            params['region_id'] = region_id
        else:
            params['q'] = f'{rubric} {city}'

        try:
            async with aiohttp.ClientSession() as gis_session:
                async with gis_session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return {'error': f'2GIS API error {resp.status}', 'details': error_text[:300]}

                    data = await resp.json()
                    items = data.get('result', {}).get('items', [])

                    companies = []
                    for item in items:
                        # Extract phones
                        phones = []
                        contact_groups = item.get('contact_groups', [])
                        for group in contact_groups:
                            for contact in group.get('contacts', []):
                                if contact.get('type') == 'phone':
                                    phones.append(contact.get('text', ''))

                        # Extract address
                        addr = item.get('address_name', '')
                        full_addr = item.get('full_address_name', '')

                        org = item.get('org', {})

                        company = {
                            'name': item.get('name', ''),
                            'full_name': org.get('name', ''),
                            'address': full_addr or addr,
                            'city': city,
                            'phones': phones[:3],  # max 3 phones
                            'rubrics': [r.get('name', '') for r in item.get('rubrics', [])[:3]],
                            'source': '2gis',
                        }
                        companies.append(company)

                    self._lead_gen_cache = companies

                    return {
                        'total': len(companies),
                        'companies': companies,
                        'filters': {
                            'city': city,
                            'rubric': rubric,
                        },
                        'with_phones': sum(1 for c in companies if c.get('phones')),
                        'message': f'Найдено {len(companies)} заведений в {city}. С телефонами: {sum(1 for c in companies if c.get("phones"))}.',
                    }

        except asyncio.TimeoutError:
            return {'error': '2GIS API timeout'}
        except Exception as e:
            logger.error(f'2GIS search error: {e}')
            return {'error': f'2GIS search error: {str(e)}'}

    async def _lead_gen_enrich(self, args: dict) -> dict:
        """Enrich company by INN via DaData find-party API."""
        dadata_token = os.getenv('DADATA_API_TOKEN', '')
        if not dadata_token:
            return {'error': 'DADATA_API_TOKEN not configured'}

        inn = args.get('inn', '')
        if not inn:
            return {'error': 'INN is required for enrich action'}

        url = 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party'
        req_headers = {
            'Authorization': f'Token {dadata_token}',
            'Content-Type': 'application/json',
        }

        try:
            async with aiohttp.ClientSession() as dadata_session:
                async with dadata_session.post(url, json={'query': inn}, headers=req_headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return {'error': f'DaData API error {resp.status}'}

                    data = await resp.json()
                    suggestions = data.get('suggestions', [])

                    if not suggestions:
                        return {'error': f'Company not found by INN {inn}'}

                    s = suggestions[0]
                    d = s.get('data', {})
                    address = d.get('address', {})
                    management = d.get('management', {})
                    name_info = d.get('name', {})
                    state = d.get('state', {})
                    finance = d.get('finance', {})
                    phones = d.get('phones', [])
                    emails = d.get('emails', [])

                    return {
                        'name': name_info.get('short_with_opf') or s.get('value', ''),
                        'full_name': name_info.get('full_with_opf', ''),
                        'inn': d.get('inn', ''),
                        'kpp': d.get('kpp', ''),
                        'ogrn': d.get('ogrn', ''),
                        'okved': d.get('okved', ''),
                        'address': address.get('unrestricted_value', '') if isinstance(address, dict) else '',
                        'director': management.get('name', ''),
                        'director_post': management.get('post', ''),
                        'status': state.get('status', ''),
                        'registration_date': state.get('registration_date'),
                        'employees': d.get('employee_count'),
                        'phones': [p.get('data', p) if isinstance(p, dict) else p for p in (phones or [])],
                        'emails': [e.get('data', e) if isinstance(e, dict) else e for e in (emails or [])],
                        'revenue': finance.get('revenue'),
                        'tax_system': finance.get('tax_system'),
                    }

        except Exception as e:
            logger.error(f'DaData enrich error: {e}')
            return {'error': f'Enrich error: {str(e)}'}

    async def _lead_gen_import(self, session, headers, args: dict) -> dict:
        """Import found companies into AmoCRM as companies + contacts + leads."""
        pipeline_id = args.get('pipeline_id')
        status_id = args.get('status_id')
        tag = args.get('tag', 'lead_gen')
        responsible_user_id = args.get('responsible_user_id')
        limit = min(args.get('limit', 20), 100)

        # Use cached results from previous search or do a new search
        companies = getattr(self, '_lead_gen_cache', None)

        if not companies:
            # Try to search first
            okved = args.get('okved')
            if okved:
                search_result = await self._lead_gen_search_dadata(args)
            else:
                search_result = await self._lead_gen_search_2gis(args)

            if 'error' in search_result:
                return search_result

            companies = search_result.get('companies', [])

        if not companies:
            return {'error': 'No companies to import. Run search_companies or search_horeca first.'}

        companies = companies[:limit]

        # If no pipeline_id, get the first pipeline
        if not pipeline_id:
            pipelines_url = f'{self.kommo_base_url}/api/v4/leads/pipelines'
            async with session.get(pipelines_url, headers=headers) as resp:
                if resp.status == 200:
                    p_data = await resp.json()
                    pipelines = p_data.get('_embedded', {}).get('pipelines', [])
                    if pipelines:
                        pipeline_id = pipelines[0].get('id')
                        if not status_id:
                            statuses = pipelines[0].get('_embedded', {}).get('statuses', [])
                            if statuses:
                                status_id = statuses[0].get('id')

        imported = 0
        errors = 0
        duplicates = 0
        results = []

        for comp in companies:
            try:
                comp_name = comp.get('name', '') or comp.get('full_name', '')
                if not comp_name:
                    errors += 1
                    continue

                # Check for duplicate by name
                search_url = f'{self.kommo_base_url}/api/v4/companies'
                search_params = {'query': comp_name[:50], 'limit': 1}
                async with session.get(search_url, headers=headers, params=search_params) as resp:
                    if resp.status == 200:
                        existing = await resp.json()
                        if existing.get('_embedded', {}).get('companies', []):
                            duplicates += 1
                            continue

                # 1. Create company
                company_payload = [
                    {
                        'name': comp_name,
                        'custom_fields_values': [],
                    }
                ]

                # Add tags
                if tag:
                    company_payload[0]['_embedded'] = {
                        'tags': [{'name': tag}]
                    }

                if responsible_user_id:
                    company_payload[0]['responsible_user_id'] = responsible_user_id

                company_url = f'{self.kommo_base_url}/api/v4/companies'
                async with session.post(company_url, json=company_payload, headers=headers) as resp:
                    if resp.status not in (200, 201):
                        errors += 1
                        continue
                    company_data = await resp.json()
                    created_companies = company_data.get('_embedded', {}).get('companies', [])
                    if not created_companies:
                        errors += 1
                        continue
                    company_id = created_companies[0].get('id')

                # 2. Create contact (director)
                contact_id = None
                director = comp.get('director', '')
                if director:
                    contact_payload = [
                        {
                            'name': director,
                            'company_id': company_id,
                            'custom_fields_values': [],
                        }
                    ]

                    # Add phone if available
                    phones = comp.get('phones', [])
                    if phones:
                        phone_val = phones[0] if isinstance(phones[0], str) else str(phones[0])
                        contact_payload[0]['custom_fields_values'].append({
                            'field_code': 'PHONE',
                            'values': [{'value': phone_val, 'enum_code': 'WORK'}],
                        })

                    if tag:
                        contact_payload[0]['_embedded'] = {
                            'tags': [{'name': tag}]
                        }

                    if responsible_user_id:
                        contact_payload[0]['responsible_user_id'] = responsible_user_id

                    contact_url = f'{self.kommo_base_url}/api/v4/contacts'
                    async with session.post(contact_url, json=contact_payload, headers=headers) as resp:
                        if resp.status in (200, 201):
                            contact_data = await resp.json()
                            contacts = contact_data.get('_embedded', {}).get('contacts', [])
                            if contacts:
                                contact_id = contacts[0].get('id')

                # 3. Create lead
                lead_name = f'B2B: {comp_name}'
                lead_payload = [
                    {
                        'name': lead_name[:255],
                        '_embedded': {
                            'tags': [{'name': tag}] if tag else [],
                            'companies': [{'id': company_id}],
                        },
                    }
                ]

                if contact_id:
                    lead_payload[0]['_embedded']['contacts'] = [{'id': contact_id}]

                if pipeline_id:
                    lead_payload[0]['pipeline_id'] = pipeline_id
                if status_id:
                    lead_payload[0]['status_id'] = status_id
                if responsible_user_id:
                    lead_payload[0]['responsible_user_id'] = responsible_user_id

                leads_url = f'{self.kommo_base_url}/api/v4/leads'
                async with session.post(leads_url, json=lead_payload, headers=headers) as resp:
                    if resp.status in (200, 201):
                        lead_data = await resp.json()
                        created_leads = lead_data.get('_embedded', {}).get('leads', [])
                        if created_leads:
                            imported += 1
                            results.append({
                                'company': comp_name,
                                'company_id': company_id,
                                'contact_id': contact_id,
                                'lead_id': created_leads[0].get('id'),
                            })
                    else:
                        errors += 1

                # Rate limiting - AmoCRM has 7 requests/sec limit
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f'Import error for {comp.get("name", "?")}: {e}')
                errors += 1

        # Clear cache after import
        self._lead_gen_cache = None

        return {
            'imported': imported,
            'duplicates': duplicates,
            'errors': errors,
            'total_processed': len(companies),
            'tag': tag,
            'pipeline_id': pipeline_id,
            'results': results[:10],  # first 10 for display
            'message': f'Импортировано {imported} лидов (дубликатов: {duplicates}, ошибок: {errors}). Тег: #{tag}',
        }
