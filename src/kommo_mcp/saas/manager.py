"""
Tenant Manager - handles tenant lifecycle and persistence.
"""

import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from .tenant import Tenant, TenantStatus


class TenantManager:
    """
    Manages tenant lifecycle:
    - Registration
    - Credential storage
    - Database provisioning
    - Container orchestration
    """
    
    def __init__(self, data_dir: str = '/var/lib/kommo-saas'):
        self.data_dir = Path(data_dir)
        self.tenants_file = self.data_dir / 'tenants.json'
        self._tenants: Dict[str, Tenant] = {}
        self._by_telegram_id: Dict[int, str] = {}  # telegram_user_id -> tenant_id
        self._lock = asyncio.Lock()
    
    async def init(self):
        """Initialize manager, load existing tenants."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        await self._load_tenants()
    
    async def _load_tenants(self):
        """Load tenants from disk."""
        if self.tenants_file.exists():
            try:
                data = json.loads(self.tenants_file.read_text())
                for t_data in data:
                    tenant = Tenant(**t_data)
                    self._tenants[tenant.id] = tenant
                    self._by_telegram_id[tenant.telegram_user_id] = tenant.id
            except Exception as e:
                print(f'Error loading tenants: {e}')
    
    async def _save_tenants(self):
        """Persist tenants to disk."""
        async with self._lock:
            data = [t.model_dump(mode='json') for t in self._tenants.values()]
            self.tenants_file.write_text(json.dumps(data, indent=2, default=str))
    
    async def get_by_telegram_id(self, telegram_user_id: int) -> Optional[Tenant]:
        """Get tenant by Telegram user ID."""
        tenant_id = self._by_telegram_id.get(telegram_user_id)
        if tenant_id:
            return self._tenants.get(tenant_id)
        return None
    
    async def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        return self._tenants.get(tenant_id)
    
    async def register(
        self,
        telegram_user_id: int,
        telegram_username: Optional[str] = None,
    ) -> Tenant:
        """Register new tenant from Telegram."""
        # Check if already exists
        existing = await self.get_by_telegram_id(telegram_user_id)
        if existing:
            return existing
        
        tenant = Tenant(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            status=TenantStatus.PENDING,
        )
        
        self._tenants[tenant.id] = tenant
        self._by_telegram_id[telegram_user_id] = tenant.id
        await self._save_tenants()
        
        return tenant
    
    async def update(self, tenant: Tenant) -> Tenant:
        """Update tenant data."""
        tenant.updated_at = datetime.now()
        self._tenants[tenant.id] = tenant
        await self._save_tenants()
        return tenant
    
    async def set_kommo_credentials(
        self,
        tenant_id: str,
        domain: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> Optional[Tenant]:
        """Set Kommo API credentials for tenant."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant:
            return None
        
        tenant.kommo_domain = domain
        tenant.kommo_access_token = access_token
        tenant.kommo_refresh_token = refresh_token
        
        return await self.update(tenant)
    
    async def set_openai_key(
        self,
        tenant_id: str,
        api_key: str,
    ) -> Optional[Tenant]:
        """Set OpenAI API key for tenant."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant:
            return None
        
        tenant.openai_api_key = api_key
        return await self.update(tenant)
    
    async def set_status(
        self,
        tenant_id: str,
        status: TenantStatus,
        error_message: Optional[str] = None,
    ) -> Optional[Tenant]:
        """Update tenant status."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant:
            return None
        
        tenant.status = status
        tenant.error_message = error_message
        return await self.update(tenant)
    
    async def set_infrastructure(
        self,
        tenant_id: str,
        db_name: str,
        container_id: str,
        container_port: int,
    ) -> Optional[Tenant]:
        """Set infrastructure details after provisioning."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant:
            return None
        
        tenant.db_name = db_name
        tenant.container_id = container_id
        tenant.container_port = container_port
        return await self.update(tenant)
    
    async def list_active(self) -> List[Tenant]:
        """List all active tenants."""
        return [t for t in self._tenants.values() if t.status == TenantStatus.ACTIVE]
    
    async def list_all(self) -> List[Tenant]:
        """List all tenants."""
        return list(self._tenants.values())
    
    async def increment_requests(self, tenant_id: str) -> bool:
        """Increment request counter, return False if limit exceeded."""
        tenant = await self.get_by_id(tenant_id)
        if not tenant:
            return False
        
        if tenant.requests_today >= tenant.requests_limit:
            return False
        
        tenant.requests_today += 1
        tenant.last_activity_at = datetime.now()
        await self.update(tenant)
        return True
    
    async def reset_daily_counters(self):
        """Reset daily request counters for all tenants."""
        for tenant in self._tenants.values():
            tenant.requests_today = 0
        await self._save_tenants()
