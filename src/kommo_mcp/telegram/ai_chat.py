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
                            'link_contact', 'unlink_contact'
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
        model: str = 'gpt-4o',
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
            
            if dry_run:
                return {'dry_run': True, 'message': f'Would DELETE pipeline {pipeline_id}. This is irreversible!'}
            
            url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline_id}'
            
            # First, get all leads in this pipeline and delete them with unlinking
            leads_deleted = 0
            leads_found = 0
            page = 1
            
            async def get_lead_links(lead_id: int) -> list:
                """Get all links for a lead."""
                link_url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/links'
                async with session.get(link_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('_embedded', {}).get('links', [])
                return []
            
            async def unlink_lead(lead_id: int, links: list) -> int:
                """Remove all links from a lead."""
                if not links:
                    return 0
                unlink_url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}/unlink'
                unlinked = 0
                for link in links:
                    payload = [{
                        'to_entity_type': link.get('to_entity_type'),
                        'to_entity_id': link.get('to_entity_id'),
                    }]
                    async with session.post(unlink_url, headers=headers, json=payload) as resp:
                        if resp.status in [200, 204]:
                            unlinked += 1
                return unlinked
            
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
                    logger.info(f'Found {len(leads)} leads on page {page}')
                    if not leads:
                        break
                    
                    # Unlink and delete each lead
                    for lead in leads:
                        lead_id = lead['id']
                        # First unlink
                        links = await get_lead_links(lead_id)
                        if links:
                            await unlink_lead(lead_id, links)
                        # Then move to lost status (143) since DELETE is not supported for leads
                        del_url = f'{self.kommo_base_url}/api/v4/leads/{lead_id}'
                        payload = {'status_id': 143}  # 143 = Closed and not realized (lost)
                        async with session.patch(del_url, headers=headers, json=payload) as del_resp:
                            if del_resp.status in [200, 204]:
                                leads_deleted += 1
                            else:
                                logger.warning(f'Failed to close lead {lead_id}: {del_resp.status}')
                    
                    page += 1
                    if len(leads) < 250:
                        break
            
            logger.info(f'Total leads found: {leads_found}, deleted: {leads_deleted}')
            
            # Now delete the pipeline
            async with session.delete(url, headers=headers) as resp:
                if resp.status in [200, 204]:
                    result = {'success': True, 'deleted_pipeline_id': pipeline_id}
                    if leads_deleted > 0:
                        result['leads_deleted'] = leads_deleted
                        result['message'] = f'Auto-deleted {leads_deleted} leads before removing pipeline'
                    return result
                error_text = await resp.text()
                if leads_deleted > 0:
                    return {'error': f'Failed after deleting {leads_deleted} leads: {error_text[:200]}'}
                return {'error': f'Failed to delete pipeline: {error_text[:200]}'}
        
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
        """Handle custom fields management."""
        action = args.get('action')
        entity_type = args.get('entity_type', 'leads')
        entity_id = args.get('entity_id')
        field_id = args.get('field_id')
        value = args.get('value')
        
        if action == 'list':
            url = f'{self.kommo_base_url}/api/v4/{entity_type}/custom_fields'
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    fields = data.get('_embedded', {}).get('custom_fields', [])
                    return {
                        'fields': [
                            {
                                'id': f.get('id'),
                                'name': f.get('name'),
                                'type': f.get('type'),
                                'enums': [e.get('value') for e in f.get('enums', [])] if f.get('enums') else None,
                            }
                            for f in fields
                        ],
                        'total': len(fields),
                    }
                return {'error': f'API error: {resp.status}'}
        
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
                    {'field_id': field_id, 'values': [{'value': value}]}
                ]
            }
            
            async with session.patch(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    return {'success': True, 'entity_id': entity_id, 'field_id': field_id, 'value': value}
                error = await resp.text()
                return {'error': f'Failed to set field value: {error[:200]}'}
        
        return {'error': f'Unknown custom_fields action: {action}'}
    
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
        
        if action == 'preview':
            leads = await get_all_entities('leads')
            contacts = await get_all_entities('contacts')
            companies = await get_all_entities('companies')
            pipelines = await get_pipelines()
            
            return {
                'preview': True,
                'leads_count': len(leads),
                'contacts_count': len(contacts),
                'companies_count': len(companies),
                'pipelines_count': len(pipelines),
                'pipelines': [{'id': p['id'], 'name': p['name']} for p in pipelines],
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
        
        elif action == 'reset_pipelines':
            pipelines = await get_pipelines()
            deleted_pipelines = 0
            
            for pipeline in pipelines:
                if not pipeline.get('is_main', False):
                    url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline["id"]}'
                    async with session.delete(url, headers=headers) as resp:
                        if resp.status in [200, 204]:
                            deleted_pipelines += 1
            
            return {
                'action': 'reset_pipelines',
                'pipelines_found': len(pipelines),
                'pipelines_deleted': deleted_pipelines,
                'note': 'Main pipeline preserved, custom pipelines deleted',
            }
        
        elif action == 'full_reset':
            results = {}
            
            # 1. Smart delete leads
            leads = await get_all_entities('leads')
            results['leads'] = await smart_delete_all('leads', leads)
            
            # 2. Smart delete contacts
            contacts = await get_all_entities('contacts')
            results['contacts'] = await smart_delete_all('contacts', contacts)
            
            # 3. Smart delete companies
            companies = await get_all_entities('companies')
            results['companies'] = await smart_delete_all('companies', companies)
            
            # 4. Reset pipelines
            pipelines = await get_pipelines()
            deleted_pipelines = 0
            for pipeline in pipelines:
                if not pipeline.get('is_main', False):
                    url = f'{self.kommo_base_url}/api/v4/leads/pipelines/{pipeline["id"]}'
                    async with session.delete(url, headers=headers) as resp:
                        if resp.status in [200, 204]:
                            deleted_pipelines += 1
            
            results['pipelines'] = {
                'found': len(pipelines),
                'deleted': deleted_pipelines,
            }
            
            return {'action': 'full_reset', 'success': True, **results}
        
        return {'error': f'Unknown cleanup action: {action}'}
