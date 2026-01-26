"""Webhook event handlers."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from kommo_mcp.db.models import LeadDB, ContactDB, CompanyDB, TaskDB
from kommo_mcp.db.session import _get_session_factory

logger = logging.getLogger(__name__)


class WebhookHandler:
    """
    Handles incoming webhook events from Kommo.
    
    Supported events:
    - leads: add, update, delete, status, responsible
    - contacts: add, update, delete
    - companies: add, update, delete
    - tasks: add, update, delete, complete
    """

    # Event type mappings
    ENTITY_EVENTS = {
        'leads': ['add', 'update', 'delete', 'status', 'responsible'],
        'contacts': ['add', 'update', 'delete'],
        'companies': ['add', 'update', 'delete'],
        'tasks': ['add', 'update', 'delete', 'complete'],
    }

    def __init__(self):
        self._callbacks: dict[str, list] = {}

    def on(self, event: str, callback):
        """Register callback for event."""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    async def _emit(self, event: str, data: dict):
        """Emit event to registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                await callback(data)
            except Exception as e:
                logger.error(f'Callback error for {event}: {e}')

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Handle incoming webhook payload.
        
        Args:
            payload: Webhook payload from Kommo
        
        Returns:
            Processing result
        """
        results = []
        
        # Process each entity type in payload
        for entity_type in ['leads', 'contacts', 'companies', 'tasks']:
            entity_data = payload.get(entity_type, {})
            
            for event_type in self.ENTITY_EVENTS.get(entity_type, []):
                items = entity_data.get(event_type, [])
                if items:
                    for item in items:
                        result = await self._process_event(entity_type, event_type, item)
                        results.append(result)
        
        return {
            'status': 'processed',
            'events_count': len(results),
            'results': results,
        }

    async def _process_event(
        self,
        entity_type: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Process a single webhook event."""
        event_name = f'{entity_type}_{event_type}'
        logger.info(f'Processing webhook event: {event_name}, id={data.get("id")}')
        
        try:
            # Route to specific handler
            handler_method = getattr(self, f'_handle_{entity_type}_{event_type}', None)
            if handler_method:
                await handler_method(data)
            
            # Emit event for external listeners
            await self._emit(event_name, data)
            
            return {
                'event': event_name,
                'entity_id': data.get('id'),
                'status': 'success',
            }
        except Exception as e:
            logger.exception(f'Error processing {event_name}')
            return {
                'event': event_name,
                'entity_id': data.get('id'),
                'status': 'error',
                'error': str(e),
            }

    # === Lead Handlers ===

    async def _handle_leads_add(self, data: dict[str, Any]):
        """Handle new lead creation."""
        async with _get_session_factory()() as session:
            lead = LeadDB(
                id=int(data['id']),
                name=data.get('name', ''),
                price=float(data.get('price', 0)),
                responsible_user_id=int(data['responsible_user_id']) if data.get('responsible_user_id') else None,
                pipeline_id=int(data['pipeline_id']) if data.get('pipeline_id') else None,
                status_id=int(data['status_id']) if data.get('status_id') else None,
                kommo_created_at=datetime.fromtimestamp(int(data['created_at'])) if data.get('created_at') else None,
                kommo_updated_at=datetime.fromtimestamp(int(data['updated_at'])) if data.get('updated_at') else None,
                synced_at=datetime.now(),
            )
            session.add(lead)
            await session.commit()
            logger.info(f'Lead {data["id"]} added via webhook')

    async def _handle_leads_update(self, data: dict[str, Any]):
        """Handle lead update."""
        async with _get_session_factory()() as session:
            lead = await session.get(LeadDB, int(data['id']))
            if lead:
                if data.get('name'):
                    lead.name = data['name']
                if data.get('price'):
                    lead.price = float(data['price'])
                if data.get('responsible_user_id'):
                    lead.responsible_user_id = int(data['responsible_user_id'])
                if data.get('updated_at'):
                    lead.kommo_updated_at = datetime.fromtimestamp(int(data['updated_at']))
                lead.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Lead {data["id"]} updated via webhook')

    async def _handle_leads_status(self, data: dict[str, Any]):
        """Handle lead status change."""
        async with _get_session_factory()() as session:
            lead = await session.get(LeadDB, int(data['id']))
            if lead:
                if data.get('status_id'):
                    lead.status_id = int(data['status_id'])
                if data.get('pipeline_id'):
                    lead.pipeline_id = int(data['pipeline_id'])
                if data.get('updated_at'):
                    lead.kommo_updated_at = datetime.fromtimestamp(int(data['updated_at']))
                lead.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Lead {data["id"]} status changed via webhook')

    async def _handle_leads_responsible(self, data: dict[str, Any]):
        """Handle lead responsible user change."""
        async with _get_session_factory()() as session:
            lead = await session.get(LeadDB, int(data['id']))
            if lead and data.get('responsible_user_id'):
                lead.responsible_user_id = int(data['responsible_user_id'])
                lead.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Lead {data["id"]} responsible changed via webhook')

    async def _handle_leads_delete(self, data: dict[str, Any]):
        """Handle lead deletion (soft delete)."""
        async with _get_session_factory()() as session:
            lead = await session.get(LeadDB, int(data['id']))
            if lead:
                lead.is_deleted = True
                lead.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Lead {data["id"]} deleted via webhook')

    # === Contact Handlers ===

    async def _handle_contacts_add(self, data: dict[str, Any]):
        """Handle new contact creation."""
        async with _get_session_factory()() as session:
            contact = ContactDB(
                id=int(data['id']),
                name=data.get('name', ''),
                first_name=data.get('first_name'),
                last_name=data.get('last_name'),
                responsible_user_id=int(data['responsible_user_id']) if data.get('responsible_user_id') else None,
                kommo_created_at=datetime.fromtimestamp(int(data['created_at'])) if data.get('created_at') else None,
                kommo_updated_at=datetime.fromtimestamp(int(data['updated_at'])) if data.get('updated_at') else None,
                synced_at=datetime.now(),
            )
            session.add(contact)
            await session.commit()
            logger.info(f'Contact {data["id"]} added via webhook')

    async def _handle_contacts_update(self, data: dict[str, Any]):
        """Handle contact update."""
        async with _get_session_factory()() as session:
            contact = await session.get(ContactDB, int(data['id']))
            if contact:
                if data.get('name'):
                    contact.name = data['name']
                if data.get('first_name'):
                    contact.first_name = data['first_name']
                if data.get('last_name'):
                    contact.last_name = data['last_name']
                if data.get('updated_at'):
                    contact.kommo_updated_at = datetime.fromtimestamp(int(data['updated_at']))
                contact.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Contact {data["id"]} updated via webhook')

    async def _handle_contacts_delete(self, data: dict[str, Any]):
        """Handle contact deletion."""
        async with _get_session_factory()() as session:
            contact = await session.get(ContactDB, int(data['id']))
            if contact:
                contact.is_deleted = True
                contact.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Contact {data["id"]} deleted via webhook')

    # === Company Handlers ===

    async def _handle_companies_add(self, data: dict[str, Any]):
        """Handle new company creation."""
        async with _get_session_factory()() as session:
            company = CompanyDB(
                id=int(data['id']),
                name=data.get('name', ''),
                responsible_user_id=int(data['responsible_user_id']) if data.get('responsible_user_id') else None,
                kommo_created_at=datetime.fromtimestamp(int(data['created_at'])) if data.get('created_at') else None,
                kommo_updated_at=datetime.fromtimestamp(int(data['updated_at'])) if data.get('updated_at') else None,
                synced_at=datetime.now(),
            )
            session.add(company)
            await session.commit()
            logger.info(f'Company {data["id"]} added via webhook')

    async def _handle_companies_update(self, data: dict[str, Any]):
        """Handle company update."""
        async with _get_session_factory()() as session:
            company = await session.get(CompanyDB, int(data['id']))
            if company:
                if data.get('name'):
                    company.name = data['name']
                if data.get('updated_at'):
                    company.kommo_updated_at = datetime.fromtimestamp(int(data['updated_at']))
                company.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Company {data["id"]} updated via webhook')

    async def _handle_companies_delete(self, data: dict[str, Any]):
        """Handle company deletion."""
        async with _get_session_factory()() as session:
            company = await session.get(CompanyDB, int(data['id']))
            if company:
                company.is_deleted = True
                company.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Company {data["id"]} deleted via webhook')

    # === Task Handlers ===

    async def _handle_tasks_add(self, data: dict[str, Any]):
        """Handle new task creation."""
        async with _get_session_factory()() as session:
            task = TaskDB(
                id=int(data['id']),
                text=data.get('text', ''),
                task_type_id=int(data.get('task_type', 1)),
                entity_id=int(data['element_id']) if data.get('element_id') else None,
                entity_type=data.get('element_type'),
                responsible_user_id=int(data['responsible_user_id']) if data.get('responsible_user_id') else None,
                complete_till=datetime.fromtimestamp(int(data['complete_till'])) if data.get('complete_till') else None,
                kommo_created_at=datetime.fromtimestamp(int(data['created_at'])) if data.get('created_at') else None,
                synced_at=datetime.now(),
            )
            session.add(task)
            await session.commit()
            logger.info(f'Task {data["id"]} added via webhook')

    async def _handle_tasks_update(self, data: dict[str, Any]):
        """Handle task update."""
        async with _get_session_factory()() as session:
            task = await session.get(TaskDB, int(data['id']))
            if task:
                if data.get('text'):
                    task.text = data['text']
                if data.get('complete_till'):
                    task.complete_till = datetime.fromtimestamp(int(data['complete_till']))
                task.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Task {data["id"]} updated via webhook')

    async def _handle_tasks_complete(self, data: dict[str, Any]):
        """Handle task completion."""
        async with _get_session_factory()() as session:
            task = await session.get(TaskDB, int(data['id']))
            if task:
                task.is_completed = True
                if data.get('result'):
                    task.result = data['result']
                task.synced_at = datetime.now()
                await session.commit()
                logger.info(f'Task {data["id"]} completed via webhook')

    async def _handle_tasks_delete(self, data: dict[str, Any]):
        """Handle task deletion."""
        async with _get_session_factory()() as session:
            task = await session.get(TaskDB, int(data['id']))
            if task:
                await session.delete(task)
                await session.commit()
                logger.info(f'Task {data["id"]} deleted via webhook')
