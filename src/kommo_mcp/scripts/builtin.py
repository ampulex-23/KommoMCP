"""Built-in scripts for common operations."""

import csv
import io
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kommo_mcp.api.client import KommoClient
from kommo_mcp.db.models import ContactDB, LeadDB, StageDB
from kommo_mcp.db.session import _get_session_factory
from kommo_mcp.scripts.base import BaseScript

logger = logging.getLogger(__name__)


class ExportLeadsScript(BaseScript):
    """Export leads to CSV format."""
    
    name = 'export_leads'
    description = 'Export leads to CSV with optional filters'
    
    async def execute(self) -> dict[str, Any]:
        """Export leads from database to CSV."""
        pipeline_id = self.params.get('pipeline_id')
        status_id = self.params.get('status_id')
        date_from = self.params.get('date_from')
        date_to = self.params.get('date_to')
        
        async with _get_session_factory()() as session:
            query = select(
                LeadDB.id,
                LeadDB.name,
                LeadDB.price,
                LeadDB.pipeline_id,
                LeadDB.status_id,
                LeadDB.responsible_user_id,
                LeadDB.kommo_created_at,
                LeadDB.closed_at,
            ).where(LeadDB.is_deleted == False)  # noqa: E712
            
            if pipeline_id:
                query = query.where(LeadDB.pipeline_id == pipeline_id)
            if status_id:
                query = query.where(LeadDB.status_id == status_id)
            if date_from:
                query = query.where(LeadDB.kommo_created_at >= date_from)
            if date_to:
                query = query.where(LeadDB.kommo_created_at <= date_to)
            
            self.update_progress(0.1, 'Querying database...')
            result = await session.execute(query)
            rows = result.all()
            
            self.update_progress(0.5, f'Exporting {len(rows)} leads...')
            
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                'id', 'name', 'price', 'pipeline_id', 'status_id',
                'responsible_user_id', 'created_at', 'closed_at',
            ])
            
            for row in rows:
                writer.writerow([
                    row.id,
                    row.name,
                    row.price,
                    row.pipeline_id,
                    row.status_id,
                    row.responsible_user_id,
                    row.kommo_created_at.isoformat() if row.kommo_created_at else '',
                    row.closed_at.isoformat() if row.closed_at else '',
                ])
            
            csv_content = output.getvalue()
            self.update_progress(1.0, 'Export completed')
            
            return {
                'rows_exported': len(rows),
                'csv_preview': csv_content[:1000] + '...' if len(csv_content) > 1000 else csv_content,
                'csv_size_bytes': len(csv_content.encode()),
            }


class BulkUpdateStatusScript(BaseScript):
    """Bulk update lead statuses."""
    
    name = 'bulk_update_status'
    description = 'Move multiple leads to a new status'
    
    async def execute(self) -> dict[str, Any]:
        """Update status for multiple leads."""
        lead_ids = self.params.get('lead_ids', [])
        new_status_id = self.params.get('new_status_id')
        
        if not lead_ids or not new_status_id:
            raise ValueError('lead_ids and new_status_id are required')
        
        self.update_progress(0.1, f'Updating {len(lead_ids)} leads...')
        
        # Update in database
        async with _get_session_factory()() as session:
            stmt = (
                update(LeadDB)
                .where(LeadDB.id.in_(lead_ids))
                .values(
                    status_id=new_status_id,
                    synced_at=datetime.now(),
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            updated_count = result.rowcount
        
        self.update_progress(0.5, f'Updated {updated_count} leads in DB')
        
        # Update in Kommo API
        api = KommoClient()
        batch_size = 50
        api_updated = 0
        
        for i in range(0, len(lead_ids), batch_size):
            batch = lead_ids[i:i + batch_size]
            updates = [{'id': lid, 'status_id': new_status_id} for lid in batch]
            
            try:
                await api.patch('leads', json=updates)
                api_updated += len(batch)
            except Exception as e:
                logger.error(f'API update failed for batch: {e}')
            
            progress = 0.5 + (i / len(lead_ids)) * 0.5
            self.update_progress(progress, f'API updated {api_updated}/{len(lead_ids)}')
        
        await api.close()
        
        return {
            'leads_requested': len(lead_ids),
            'db_updated': updated_count,
            'api_updated': api_updated,
        }


class FindDuplicatesScript(BaseScript):
    """Find duplicate contacts by phone or email."""
    
    name = 'find_duplicates'
    description = 'Find duplicate contacts based on phone or email'
    
    async def execute(self) -> dict[str, Any]:
        """Find duplicate contacts."""
        field = self.params.get('field', 'phone')  # 'phone' or 'email'
        
        self.update_progress(0.1, f'Searching for duplicates by {field}...')
        
        async with _get_session_factory()() as session:
            # Find contacts with same custom field values
            # This is simplified - real implementation would parse custom_fields JSON
            query = select(
                ContactDB.id,
                ContactDB.name,
                ContactDB.custom_fields,
            ).where(ContactDB.is_deleted == False)  # noqa: E712
            
            result = await session.execute(query)
            contacts = result.all()
            
            self.update_progress(0.5, f'Analyzing {len(contacts)} contacts...')
            
            # Group by field value
            field_map: dict[str, list] = {}
            for contact in contacts:
                custom_fields = contact.custom_fields or {}
                for field_id, field_data in custom_fields.items():
                    if field_data.get('code', '').upper() == field.upper():
                        for value in field_data.get('values', []):
                            val = value.get('value', '')
                            if val:
                                if val not in field_map:
                                    field_map[val] = []
                                field_map[val].append({
                                    'id': contact.id,
                                    'name': contact.name,
                                })
            
            # Find duplicates (more than one contact with same value)
            duplicates = {
                k: v for k, v in field_map.items()
                if len(v) > 1
            }
            
            self.update_progress(1.0, f'Found {len(duplicates)} duplicate groups')
            
            return {
                'field': field,
                'total_contacts': len(contacts),
                'duplicate_groups': len(duplicates),
                'duplicates': dict(list(duplicates.items())[:20]),  # Limit output
            }


class RecalculateAnalyticsScript(BaseScript):
    """Recalculate and cache analytics data."""
    
    name = 'recalculate_analytics'
    description = 'Recalculate analytics aggregations for faster queries'
    
    async def execute(self) -> dict[str, Any]:
        """Recalculate analytics."""
        self.update_progress(0.1, 'Starting analytics recalculation...')
        
        async with _get_session_factory()() as session:
            # Pipeline stats
            self.update_progress(0.2, 'Calculating pipeline stats...')
            pipeline_stats = await session.execute(
                select(
                    LeadDB.pipeline_id,
                    func.count(LeadDB.id).label('total'),
                    func.sum(LeadDB.price).label('total_value'),
                    func.avg(LeadDB.price).label('avg_value'),
                ).where(
                    LeadDB.is_deleted == False  # noqa: E712
                ).group_by(LeadDB.pipeline_id)
            )
            pipelines = pipeline_stats.all()
            
            # Stage stats
            self.update_progress(0.5, 'Calculating stage stats...')
            stage_stats = await session.execute(
                select(
                    LeadDB.status_id,
                    StageDB.name,
                    StageDB.type,
                    func.count(LeadDB.id).label('count'),
                    func.sum(LeadDB.price).label('value'),
                ).join(
                    StageDB, LeadDB.status_id == StageDB.id
                ).where(
                    LeadDB.is_deleted == False  # noqa: E712
                ).group_by(
                    LeadDB.status_id, StageDB.name, StageDB.type
                )
            )
            stages = stage_stats.all()
            
            # Conversion metrics
            self.update_progress(0.8, 'Calculating conversion metrics...')
            conversion_stats = await session.execute(
                select(
                    func.count(LeadDB.id).filter(StageDB.type == 2).label('won'),
                    func.count(LeadDB.id).filter(StageDB.type == 3).label('lost'),
                    func.count(LeadDB.id).label('total'),
                ).join(
                    StageDB, LeadDB.status_id == StageDB.id
                ).where(
                    LeadDB.is_deleted == False  # noqa: E712
                )
            )
            conversion = conversion_stats.one()
            
            self.update_progress(1.0, 'Analytics recalculation completed')
            
            return {
                'pipelines_analyzed': len(pipelines),
                'stages_analyzed': len(stages),
                'total_leads': conversion.total,
                'won_leads': conversion.won,
                'lost_leads': conversion.lost,
                'conversion_rate': conversion.won / (conversion.won + conversion.lost) if (conversion.won + conversion.lost) > 0 else 0,
            }


class CleanupOldDataScript(BaseScript):
    """Clean up old synced data."""
    
    name = 'cleanup_old_data'
    description = 'Remove old deleted records from database'
    
    async def execute(self) -> dict[str, Any]:
        """Clean up old deleted records."""
        days_old = self.params.get('days_old', 90)
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        self.update_progress(0.1, f'Cleaning records older than {days_old} days...')
        
        deleted_counts = {}
        
        async with _get_session_factory()() as session:
            # Note: In production, you'd want to actually delete or archive
            # For safety, we just count what would be deleted
            
            for model, name in [(LeadDB, 'leads'), (ContactDB, 'contacts')]:
                query = select(func.count(model.id)).where(
                    model.is_deleted == True,  # noqa: E712
                    model.synced_at < cutoff_date,
                )
                result = await session.execute(query)
                count = result.scalar() or 0
                deleted_counts[name] = count
            
            self.update_progress(1.0, 'Cleanup analysis completed')
            
            return {
                'days_old': days_old,
                'cutoff_date': cutoff_date.isoformat(),
                'records_to_cleanup': deleted_counts,
                'note': 'Dry run - no records were actually deleted',
            }
