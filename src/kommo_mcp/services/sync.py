"""Data synchronization service."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kommo_mcp.api.client import KommoClient
from kommo_mcp.db.models import (
    CompanyDB,
    ContactDB,
    LeadDB,
    PipelineDB,
    StageDB,
    SyncStatusDB,
    TaskDB,
    UserDB,
)

logger = logging.getLogger(__name__)


class SyncManager:
    """
    Manages data synchronization from Kommo API to local PostgreSQL.
    
    Supports incremental sync based on updated_at timestamps.
    """

    def __init__(self, api_client: KommoClient, session: AsyncSession):
        self.api = api_client
        self.session = session

    async def sync_all(self, full: bool = False) -> dict[str, int]:
        """
        Sync all entities from Kommo API.
        
        Args:
            full: If True, perform full sync ignoring last_sync timestamp.
        
        Returns:
            Dict with entity names and synced counts.
        """
        results = {}
        
        # Order matters due to foreign key dependencies
        entities = [
            ('users', self.sync_users),
            ('pipelines', self.sync_pipelines),
            ('leads', self.sync_leads),
            ('contacts', self.sync_contacts),
            ('companies', self.sync_companies),
            ('tasks', self.sync_tasks),
        ]
        
        for entity_name, sync_func in entities:
            try:
                await self._set_sync_status(entity_name, 'running')
                count = await sync_func(full=full)
                results[entity_name] = count
                await self._set_sync_status(entity_name, 'completed', count)
                logger.info(f'Synced {count} {entity_name}')
            except Exception as e:
                logger.error(f'Error syncing {entity_name}: {e}')
                await self._set_sync_status(entity_name, 'failed', error=str(e))
                results[entity_name] = -1
        
        return results

    async def sync_users(self, full: bool = False) -> int:
        """Sync users from Kommo API."""
        users = await self.api.get_users()
        
        for user in users:
            stmt = insert(UserDB).values(
                id=user['id'],
                name=user.get('name', ''),
                email=user.get('email'),
                lang=user.get('lang', 'ru'),
                rights=user.get('rights', {}),
                is_active=True,
                synced_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': user.get('name', ''),
                    'email': user.get('email'),
                    'lang': user.get('lang', 'ru'),
                    'rights': user.get('rights', {}),
                    'synced_at': datetime.now(),
                }
            )
            await self.session.execute(stmt)
        
        await self.session.commit()
        return len(users)

    async def sync_pipelines(self, full: bool = False) -> int:
        """Sync pipelines and stages from Kommo API."""
        pipelines = await self.api.get_pipelines()
        count = 0
        
        for pipeline in pipelines:
            # Upsert pipeline
            stmt = insert(PipelineDB).values(
                id=pipeline['id'],
                name=pipeline.get('name', ''),
                sort=pipeline.get('sort', 1),
                is_main=pipeline.get('is_main', False),
                is_unsorted_on=pipeline.get('is_unsorted_on', True),
                is_archive=pipeline.get('is_archive', False),
                synced_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': pipeline.get('name', ''),
                    'sort': pipeline.get('sort', 1),
                    'is_main': pipeline.get('is_main', False),
                    'is_archive': pipeline.get('is_archive', False),
                    'synced_at': datetime.now(),
                }
            )
            await self.session.execute(stmt)
            count += 1
            
            # Upsert stages
            embedded = pipeline.get('_embedded', {})
            statuses = embedded.get('statuses', [])
            
            for status in statuses:
                stmt = insert(StageDB).values(
                    id=status['id'],
                    pipeline_id=pipeline['id'],
                    name=status.get('name', ''),
                    sort=status.get('sort', 0),
                    color=status.get('color', '#fffeb2'),
                    is_editable=status.get('is_editable', True),
                    type=status.get('type', 0),
                ).on_conflict_do_update(
                    index_elements=['id'],
                    set_={
                        'name': status.get('name', ''),
                        'sort': status.get('sort', 0),
                        'color': status.get('color', '#fffeb2'),
                        'type': status.get('type', 0),
                    }
                )
                await self.session.execute(stmt)
        
        await self.session.commit()
        return count

    async def sync_leads(self, full: bool = False) -> int:
        """Sync leads from Kommo API."""
        last_sync = None if full else await self._get_last_sync('leads')
        
        params = {'order[updated_at]': 'desc'}
        if last_sync:
            params['filter[updated_at][from]'] = int(last_sync.timestamp())
        
        count = 0
        page = 1
        page_size = 250
        
        while True:
            page_params = {**params, 'page': page, 'limit': page_size}
            try:
                data = await self.api.get('leads', params=page_params)
            except Exception as e:
                logger.warning(f'Error fetching leads page {page}: {e}')
                break
            
            if not data:
                break
            
            leads = data.get('_embedded', {}).get('leads', [])
            if not leads:
                break
            
            for lead in leads:
                await self._upsert_lead(lead)
                count += 1
            
            if count % 100 == 0:
                await self.session.commit()
                logger.debug(f'Synced {count} leads...')
            
            if len(leads) < page_size:
                break
            
            page += 1
        
        await self.session.commit()
        return count

    async def _upsert_lead(self, lead: dict[str, Any]) -> None:
        """Upsert a single lead."""
        stmt = insert(LeadDB).values(
            id=lead['id'],
            name=lead.get('name', ''),
            price=lead.get('price', 0),
            responsible_user_id=lead.get('responsible_user_id'),
            pipeline_id=lead['pipeline_id'],
            status_id=lead['status_id'],
            loss_reason_id=lead.get('loss_reason_id'),
            group_id=lead.get('group_id', 0),
            created_by=lead.get('created_by'),
            updated_by=lead.get('updated_by'),
            closed_at=datetime.fromtimestamp(lead['closed_at']) if lead.get('closed_at') else None,
            closest_task_at=datetime.fromtimestamp(lead['closest_task_at']) if lead.get('closest_task_at') else None,
            is_deleted=lead.get('is_deleted', False),
            custom_fields=self._extract_custom_fields(lead),
            kommo_created_at=datetime.fromtimestamp(lead['created_at']) if lead.get('created_at') else None,
            kommo_updated_at=datetime.fromtimestamp(lead['updated_at']) if lead.get('updated_at') else None,
            synced_at=datetime.now(),
        ).on_conflict_do_update(
            index_elements=['id'],
            set_={
                'name': lead.get('name', ''),
                'price': lead.get('price', 0),
                'responsible_user_id': lead.get('responsible_user_id'),
                'pipeline_id': lead['pipeline_id'],
                'status_id': lead['status_id'],
                'loss_reason_id': lead.get('loss_reason_id'),
                'updated_by': lead.get('updated_by'),
                'closed_at': datetime.fromtimestamp(lead['closed_at']) if lead.get('closed_at') else None,
                'is_deleted': lead.get('is_deleted', False),
                'custom_fields': self._extract_custom_fields(lead),
                'kommo_updated_at': datetime.fromtimestamp(lead['updated_at']) if lead.get('updated_at') else None,
                'synced_at': datetime.now(),
            }
        )
        await self.session.execute(stmt)

    async def sync_contacts(self, full: bool = False) -> int:
        """Sync contacts from Kommo API."""
        last_sync = None if full else await self._get_last_sync('contacts')
        
        params = {}
        if last_sync:
            params['filter[updated_at][from]'] = int(last_sync.timestamp())
        
        count = 0
        try:
          async for contact in self.api.get_contacts(**params):
            stmt = insert(ContactDB).values(
                id=contact['id'],
                name=contact.get('name', ''),
                first_name=contact.get('first_name'),
                last_name=contact.get('last_name'),
                responsible_user_id=contact.get('responsible_user_id'),
                group_id=contact.get('group_id', 0),
                created_by=contact.get('created_by'),
                updated_by=contact.get('updated_by'),
                is_deleted=contact.get('is_deleted', False),
                custom_fields=self._extract_custom_fields(contact),
                kommo_created_at=datetime.fromtimestamp(contact['created_at']) if contact.get('created_at') else None,
                kommo_updated_at=datetime.fromtimestamp(contact['updated_at']) if contact.get('updated_at') else None,
                synced_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': contact.get('name', ''),
                    'first_name': contact.get('first_name'),
                    'last_name': contact.get('last_name'),
                    'responsible_user_id': contact.get('responsible_user_id'),
                    'updated_by': contact.get('updated_by'),
                    'is_deleted': contact.get('is_deleted', False),
                    'custom_fields': self._extract_custom_fields(contact),
                    'kommo_updated_at': datetime.fromtimestamp(contact['updated_at']) if contact.get('updated_at') else None,
                    'synced_at': datetime.now(),
                }
            )
            await self.session.execute(stmt)
            count += 1
            
            if count % 100 == 0:
                await self.session.commit()
        except TypeError as e:
            if 'NoneType' in str(e):
                logger.warning('No contacts found or empty response')
            else:
                raise
        
        await self.session.commit()
        return count

    async def sync_companies(self, full: bool = False) -> int:
        """Sync companies from Kommo API."""
        last_sync = None if full else await self._get_last_sync('companies')
        
        params = {}
        if last_sync:
            params['filter[updated_at][from]'] = int(last_sync.timestamp())
        
        count = 0
        try:
          async for company in self.api.get_companies(**params):
            stmt = insert(CompanyDB).values(
                id=company['id'],
                name=company.get('name', ''),
                responsible_user_id=company.get('responsible_user_id'),
                group_id=company.get('group_id', 0),
                created_by=company.get('created_by'),
                updated_by=company.get('updated_by'),
                is_deleted=company.get('is_deleted', False),
                custom_fields=self._extract_custom_fields(company),
                kommo_created_at=datetime.fromtimestamp(company['created_at']) if company.get('created_at') else None,
                kommo_updated_at=datetime.fromtimestamp(company['updated_at']) if company.get('updated_at') else None,
                synced_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'name': company.get('name', ''),
                    'responsible_user_id': company.get('responsible_user_id'),
                    'updated_by': company.get('updated_by'),
                    'is_deleted': company.get('is_deleted', False),
                    'custom_fields': self._extract_custom_fields(company),
                    'kommo_updated_at': datetime.fromtimestamp(company['updated_at']) if company.get('updated_at') else None,
                    'synced_at': datetime.now(),
                }
            )
            await self.session.execute(stmt)
            count += 1
            
            if count % 100 == 0:
                await self.session.commit()
        except TypeError as e:
            if 'NoneType' in str(e):
                logger.warning('No companies found or empty response')
            else:
                raise
        
        await self.session.commit()
        return count

    async def sync_tasks(self, full: bool = False) -> int:
        """Sync tasks from Kommo API."""
        last_sync = None if full else await self._get_last_sync('tasks')
        
        params = {}
        if last_sync:
            params['filter[updated_at][from]'] = int(last_sync.timestamp())
        
        count = 0
        async for task in self.api.get_tasks(**params):
            stmt = insert(TaskDB).values(
                id=task['id'],
                text=task.get('text', ''),
                task_type_id=task.get('task_type_id', 1),
                entity_id=task.get('entity_id'),
                entity_type=task.get('entity_type'),
                responsible_user_id=task.get('responsible_user_id'),
                group_id=task.get('group_id', 0),
                created_by=task.get('created_by'),
                updated_by=task.get('updated_by'),
                is_completed=task.get('is_completed', False),
                complete_till=datetime.fromtimestamp(task['complete_till']) if task.get('complete_till') else None,
                duration=task.get('duration', 0),
                result=task.get('result', {}).get('text') if isinstance(task.get('result'), dict) else None,
                kommo_created_at=datetime.fromtimestamp(task['created_at']) if task.get('created_at') else None,
                kommo_updated_at=datetime.fromtimestamp(task['updated_at']) if task.get('updated_at') else None,
                synced_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=['id'],
                set_={
                    'text': task.get('text', ''),
                    'is_completed': task.get('is_completed', False),
                    'result': task.get('result', {}).get('text') if isinstance(task.get('result'), dict) else None,
                    'kommo_updated_at': datetime.fromtimestamp(task['updated_at']) if task.get('updated_at') else None,
                    'synced_at': datetime.now(),
                }
            )
            await self.session.execute(stmt)
            count += 1
            
            if count % 100 == 0:
                await self.session.commit()
        
        await self.session.commit()
        return count

    def _extract_custom_fields(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Extract custom fields from entity."""
        custom_fields = {}
        fields_values = entity.get('custom_fields_values') or []
        for field in fields_values:
            field_id = str(field.get('field_id'))
            values = field.get('values', [])
            if values:
                custom_fields[field_id] = {
                    'name': field.get('field_name'),
                    'code': field.get('field_code'),
                    'type': field.get('field_type'),
                    'values': values,
                }
        return custom_fields

    async def _get_last_sync(self, entity_type: str) -> datetime | None:
        """Get last sync timestamp for entity type."""
        result = await self.session.execute(
            select(SyncStatusDB.last_sync_at).where(SyncStatusDB.entity_type == entity_type)
        )
        row = result.scalar_one_or_none()
        return row

    async def _set_sync_status(
        self,
        entity_type: str,
        status: str,
        count: int = 0,
        error: str | None = None,
    ) -> None:
        """Update sync status for entity type."""
        stmt = insert(SyncStatusDB).values(
            entity_type=entity_type,
            status=status,
            last_sync_at=datetime.now() if status == 'completed' else None,
            records_count=count,
            error_message=error,
        ).on_conflict_do_update(
            index_elements=['entity_type'],
            set_={
                'status': status,
                'last_sync_at': datetime.now() if status == 'completed' else SyncStatusDB.last_sync_at,
                'records_count': count if status == 'completed' else SyncStatusDB.records_count,
                'error_message': error,
            }
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_sync_status(self) -> dict[str, Any]:
        """Get sync status for all entities."""
        result = await self.session.execute(select(SyncStatusDB))
        statuses = result.scalars().all()
        
        return {
            s.entity_type: {
                'status': s.status,
                'last_sync_at': s.last_sync_at.isoformat() if s.last_sync_at else None,
                'records_count': s.records_count,
                'error_message': s.error_message,
            }
            for s in statuses
        }
