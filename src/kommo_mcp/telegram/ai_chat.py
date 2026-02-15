"""
AI Chat module - integrates OpenAI with MCP tools.
Uses RAG-based tool retrieval for dynamic prompt generation.
"""

import json
import logging
import re
from typing import Optional, List, Dict, Any

import aiohttp

from kommo_mcp.telegram.tool_retriever import get_retriever, build_dynamic_prompt
from kommo_mcp.telegram.interaction_logger import get_interaction_logger

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
                        'enum': ['overdue', 'stats', 'by_entity', 'today', 'without_responsible', 'prioritize', 'reassign', 'postpone', 'plan_day'],
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
            'description': 'Search CRM: all, leads, contacts, query, related, recent, similar, top_deals',
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['all', 'leads', 'contacts', 'query', 'related', 'recent', 'similar', 'top_deals'],
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
                        'enum': ['next_action', 'pipeline_tips', 'loss_analysis', 'closing_tips', 'objections'],
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
                        'enum': ['check', 'velocity', 'bottlenecks', 'win_loss'],
                        'description': 'Analysis type: check (overall health), velocity (speed), bottlenecks (stuck stages), win_loss (ratio analysis)',
                    },
                    'pipeline_id': {'type': 'integer', 'description': 'Pipeline ID (optional, analyzes all if omitted)'},
                    'days': {'type': 'integer', 'description': 'Analysis period in days (default 30)', 'default': 30},
                },
                'required': ['action'],
            },
        },
    },
]

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
    ):
        self.openai_api_key = openai_api_key
        self.kommo_domain = kommo_domain
        self.kommo_token = kommo_token
        self.model = model
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
            # Build dynamic prompt based on user query using RAG
            if use_rag:
                retriever = get_retriever()
                dynamic_prompt = build_dynamic_prompt(message, retriever, top_k=5)
                logger.info(f'RAG: retrieved tools for query, prompt size: {len(dynamic_prompt)} chars')
            else:
                dynamic_prompt = SYSTEM_PROMPT
            
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
                response = await self._openai_request(messages=messages, tools=MCP_TOOLS)
                
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
