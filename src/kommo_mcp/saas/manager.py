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
    - Registration (multiple CRMs per Telegram user)
    - Credential storage
    - Active tenant switching
    - Database provisioning
    - Container orchestration
    """
    
    def __init__(self, data_dir: str = '/var/lib/kommo-saas'):
        self.data_dir = Path(data_dir)
        self.tenants_file = self.data_dir / 'tenants.json'
        self.active_file = self.data_dir / 'active_tenants.json'
        self._tenants: Dict[str, Tenant] = {}
        # 1:N mapping — one Telegram user can have multiple CRMs
        self._by_telegram_id: Dict[int, List[str]] = {}  # telegram_user_id -> [tenant_ids]
        # Active tenant per user for switching
        self._active_tenant: Dict[int, str] = {}  # telegram_user_id -> active tenant_id
        self._lock = asyncio.Lock()
    
    async def init(self):
        """Initialize manager, load existing tenants."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        await self._load_tenants()
        await self._load_active()
    
    async def _load_tenants(self):
        """Load tenants from disk."""
        if self.tenants_file.exists():
            try:
                data = json.loads(self.tenants_file.read_text())
                for t_data in data:
                    tenant = Tenant(**t_data)
                    self._tenants[tenant.id] = tenant
                    uid = tenant.telegram_user_id
                    if uid not in self._by_telegram_id:
                        self._by_telegram_id[uid] = []
                    if tenant.id not in self._by_telegram_id[uid]:
                        self._by_telegram_id[uid].append(tenant.id)
            except Exception as e:
                print(f'Error loading tenants: {e}')
    
    async def _load_active(self):
        """Load active tenant selections from disk."""
        if self.active_file.exists():
            try:
                data = json.loads(self.active_file.read_text())
                # data: {"telegram_user_id": "tenant_id", ...}
                for uid_str, tid in data.items():
                    uid = int(uid_str)
                    if tid in self._tenants:
                        self._active_tenant[uid] = tid
            except Exception as e:
                print(f'Error loading active tenants: {e}')
        # Auto-set active for users who have tenants but no active selection
        for uid, tenant_ids in self._by_telegram_id.items():
            if uid not in self._active_tenant and tenant_ids:
                self._active_tenant[uid] = tenant_ids[0]
    
    async def _save_tenants(self):
        """Persist tenants to disk."""
        async with self._lock:
            data = [t.model_dump(mode='json') for t in self._tenants.values()]
            self.tenants_file.write_text(json.dumps(data, indent=2, default=str))
    
    async def _save_active(self):
        """Persist active tenant selections to disk."""
        data = {str(uid): tid for uid, tid in self._active_tenant.items()}
        self.active_file.write_text(json.dumps(data, indent=2))
    
    # ─── Active tenant management ───
    
    async def get_active_tenant(self, telegram_user_id: int) -> Optional[Tenant]:
        """Get the currently active tenant for a Telegram user."""
        tid = self._active_tenant.get(telegram_user_id)
        if tid:
            return self._tenants.get(tid)
        return None
    
    async def set_active_tenant(self, telegram_user_id: int, tenant_id: str) -> bool:
        """Switch active tenant for a Telegram user."""
        # Verify tenant belongs to this user
        user_tenants = self._by_telegram_id.get(telegram_user_id, [])
        if tenant_id not in user_tenants:
            return False
        self._active_tenant[telegram_user_id] = tenant_id
        await self._save_active()
        return True
    
    async def get_tenants_for_user(self, telegram_user_id: int) -> List[Tenant]:
        """Get all tenants belonging to a Telegram user."""
        tenant_ids = self._by_telegram_id.get(telegram_user_id, [])
        return [self._tenants[tid] for tid in tenant_ids if tid in self._tenants]
    
    # ─── Legacy compat: get_by_telegram_id now returns active tenant ───
    
    async def get_by_telegram_id(self, telegram_user_id: int) -> Optional[Tenant]:
        """Get active tenant by Telegram user ID (backward compatible)."""
        return await self.get_active_tenant(telegram_user_id)
    
    async def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        return self._tenants.get(tenant_id)
    
    async def register(
        self,
        telegram_user_id: int,
        telegram_username: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Tenant:
        """Register new tenant (CRM connection) for a Telegram user.
        
        Unlike before, this always creates a new tenant — one user can have many.
        Use get_active_tenant() to get the currently selected one.
        """
        tenant = Tenant(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            label=label,
            status=TenantStatus.PENDING,
        )
        
        self._tenants[tenant.id] = tenant
        if telegram_user_id not in self._by_telegram_id:
            self._by_telegram_id[telegram_user_id] = []
        self._by_telegram_id[telegram_user_id].append(tenant.id)
        
        # Auto-activate if this is the first tenant for user
        if len(self._by_telegram_id[telegram_user_id]) == 1:
            self._active_tenant[telegram_user_id] = tenant.id
            await self._save_active()
        
        await self._save_tenants()
        return tenant
    
    async def remove_tenant(self, telegram_user_id: int, tenant_id: str) -> bool:
        """Remove a tenant (CRM connection) for a user."""
        user_tenants = self._by_telegram_id.get(telegram_user_id, [])
        if tenant_id not in user_tenants:
            return False
        
        user_tenants.remove(tenant_id)
        del self._tenants[tenant_id]
        
        # Fix active tenant if we removed the active one
        if self._active_tenant.get(telegram_user_id) == tenant_id:
            if user_tenants:
                self._active_tenant[telegram_user_id] = user_tenants[0]
            else:
                self._active_tenant.pop(telegram_user_id, None)
            await self._save_active()
        
        await self._save_tenants()
        return True
    
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
        
        # Auto-set label from domain if not set
        if not tenant.label:
            tenant.label = domain.split('.')[0]
        
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
