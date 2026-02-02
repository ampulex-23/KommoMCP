"""
Orchestrator - manages Docker containers and databases per tenant.
"""

import asyncio
import subprocess
import secrets
from typing import Optional, Tuple
from datetime import datetime

from .tenant import Tenant, TenantStatus
from .manager import TenantManager


class Orchestrator:
    """
    Handles infrastructure provisioning:
    - PostgreSQL database creation
    - Docker container lifecycle
    - Port allocation
    """
    
    def __init__(
        self,
        tenant_manager: TenantManager,
        postgres_host: str = 'localhost',
        postgres_port: int = 5432,
        postgres_user: str = 'postgres',
        postgres_password: str = '',
        docker_image: str = 'kommo-mcp:latest',
        port_range_start: int = 9000,
        port_range_end: int = 9999,
    ):
        self.tenant_manager = tenant_manager
        self.postgres_host = postgres_host
        self.postgres_port = postgres_port
        self.postgres_user = postgres_user
        self.postgres_password = postgres_password
        self.docker_image = docker_image
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end
        self._allocated_ports: set = set()
    
    async def init(self):
        """Initialize orchestrator, scan existing containers."""
        # Load allocated ports from existing tenants
        tenants = await self.tenant_manager.list_all()
        for tenant in tenants:
            if tenant.container_port:
                self._allocated_ports.add(tenant.container_port)
    
    def _allocate_port(self) -> int:
        """Allocate a free port for new container."""
        for port in range(self.port_range_start, self.port_range_end):
            if port not in self._allocated_ports:
                self._allocated_ports.add(port)
                return port
        raise RuntimeError('No free ports available')
    
    def _generate_db_name(self, tenant_id: str) -> str:
        """Generate database name for tenant."""
        # Use first 8 chars of tenant ID
        short_id = tenant_id.replace('-', '')[:8]
        return f'kommo_tenant_{short_id}'
    
    async def _create_database(self, db_name: str) -> bool:
        """Create PostgreSQL database for tenant."""
        try:
            # Use psql to create database
            env = {'PGPASSWORD': self.postgres_password} if self.postgres_password else {}
            
            cmd = [
                'psql',
                '-h', self.postgres_host,
                '-p', str(self.postgres_port),
                '-U', self.postgres_user,
                '-c', f'CREATE DATABASE {db_name};',
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env={**env},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                # Check if database already exists
                if b'already exists' in stderr:
                    return True
                print(f'Error creating database: {stderr.decode()}')
                return False
            
            return True
        except Exception as e:
            print(f'Exception creating database: {e}')
            return False
    
    async def _run_migrations(self, db_name: str) -> bool:
        """Run database migrations for tenant."""
        try:
            db_url = (
                f'postgresql://{self.postgres_user}:{self.postgres_password}@'
                f'{self.postgres_host}:{self.postgres_port}/{db_name}'
            )
            
            # Run alembic migrations
            proc = await asyncio.create_subprocess_exec(
                'alembic', 'upgrade', 'head',
                env={'DATABASE_URL': db_url},
                cwd='/opt/kommo-mcp',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                print(f'Migration error: {stderr.decode()}')
                return False
            
            return True
        except Exception as e:
            print(f'Exception running migrations: {e}')
            return False
    
    async def _start_container(
        self,
        tenant: Tenant,
        db_name: str,
        port: int,
    ) -> Optional[str]:
        """Start Docker container for tenant."""
        try:
            container_name = f'kommo-tenant-{tenant.id[:8]}'
            
            db_url = (
                f'postgresql://{self.postgres_user}:{self.postgres_password}@'
                f'host.docker.internal:{self.postgres_port}/{db_name}'
            )
            
            cmd = [
                'docker', 'run', '-d',
                '--name', container_name,
                '-p', f'{port}:8001',
                '-e', f'DATABASE_URL={db_url}',
                '-e', f'KOMMO_DOMAIN={tenant.kommo_domain}',
                '-e', f'KOMMO_ACCESS_TOKEN={tenant.kommo_access_token}',
                '-e', f'KOMMO_REFRESH_TOKEN={tenant.kommo_refresh_token or ""}',
                '--restart', 'unless-stopped',
                self.docker_image,
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                print(f'Error starting container: {stderr.decode()}')
                return None
            
            container_id = stdout.decode().strip()
            return container_id
        except Exception as e:
            print(f'Exception starting container: {e}')
            return None
    
    async def _stop_container(self, container_id: str) -> bool:
        """Stop and remove Docker container."""
        try:
            # Stop container
            proc = await asyncio.create_subprocess_exec(
                'docker', 'stop', container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            
            # Remove container
            proc = await asyncio.create_subprocess_exec(
                'docker', 'rm', container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            
            return True
        except Exception as e:
            print(f'Exception stopping container: {e}')
            return False
    
    async def provision(self, tenant_id: str) -> Tuple[bool, str]:
        """
        Provision infrastructure for tenant:
        1. Create database
        2. Run migrations
        3. Start container
        
        Returns (success, message).
        """
        tenant = await self.tenant_manager.get_by_id(tenant_id)
        if not tenant:
            return False, 'Tenant not found'
        
        if not tenant.has_kommo_credentials():
            return False, 'Kommo credentials not configured'
        
        # Update status
        await self.tenant_manager.set_status(tenant_id, TenantStatus.PROVISIONING)
        
        # 1. Create database
        db_name = self._generate_db_name(tenant_id)
        if not await self._create_database(db_name):
            await self.tenant_manager.set_status(
                tenant_id, TenantStatus.ERROR, 'Failed to create database'
            )
            return False, 'Failed to create database'
        
        # 2. Run migrations
        if not await self._run_migrations(db_name):
            await self.tenant_manager.set_status(
                tenant_id, TenantStatus.ERROR, 'Failed to run migrations'
            )
            return False, 'Failed to run migrations'
        
        # 3. Allocate port and start container
        port = self._allocate_port()
        
        # Refresh tenant data
        tenant = await self.tenant_manager.get_by_id(tenant_id)
        container_id = await self._start_container(tenant, db_name, port)
        
        if not container_id:
            self._allocated_ports.discard(port)
            await self.tenant_manager.set_status(
                tenant_id, TenantStatus.ERROR, 'Failed to start container'
            )
            return False, 'Failed to start container'
        
        # Update tenant with infrastructure details
        await self.tenant_manager.set_infrastructure(
            tenant_id, db_name, container_id, port
        )
        
        # Set status to syncing (initial sync will happen next)
        await self.tenant_manager.set_status(tenant_id, TenantStatus.SYNCING)
        
        return True, f'Provisioned successfully on port {port}'
    
    async def deprovision(self, tenant_id: str) -> Tuple[bool, str]:
        """
        Remove tenant infrastructure:
        1. Stop container
        2. Optionally drop database
        """
        tenant = await self.tenant_manager.get_by_id(tenant_id)
        if not tenant:
            return False, 'Tenant not found'
        
        # Stop container
        if tenant.container_id:
            await self._stop_container(tenant.container_id)
        
        # Free port
        if tenant.container_port:
            self._allocated_ports.discard(tenant.container_port)
        
        # Update tenant
        tenant.container_id = None
        tenant.container_port = None
        tenant.status = TenantStatus.SUSPENDED
        await self.tenant_manager.update(tenant)
        
        return True, 'Deprovisioned successfully'
    
    async def restart_container(self, tenant_id: str) -> Tuple[bool, str]:
        """Restart tenant container."""
        tenant = await self.tenant_manager.get_by_id(tenant_id)
        if not tenant or not tenant.container_id:
            return False, 'Container not found'
        
        try:
            proc = await asyncio.create_subprocess_exec(
                'docker', 'restart', tenant.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                return False, f'Restart failed: {stderr.decode()}'
            
            return True, 'Container restarted'
        except Exception as e:
            return False, f'Exception: {e}'
    
    async def get_container_status(self, tenant_id: str) -> Optional[str]:
        """Get container status (running, exited, etc)."""
        tenant = await self.tenant_manager.get_by_id(tenant_id)
        if not tenant or not tenant.container_id:
            return None
        
        try:
            proc = await asyncio.create_subprocess_exec(
                'docker', 'inspect', '-f', '{{.State.Status}}', tenant.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                return stdout.decode().strip()
            return None
        except Exception:
            return None
    
    async def trigger_sync(self, tenant_id: str) -> Tuple[bool, str]:
        """Trigger data sync for tenant."""
        tenant = await self.tenant_manager.get_by_id(tenant_id)
        if not tenant:
            return False, 'Tenant not found'
        
        mcp_url = tenant.get_mcp_url()
        if not mcp_url:
            return False, 'Container not running'
        
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'tools/call',
                    'params': {
                        'name': 'kommo_sync',
                        'arguments': {'action': 'full'},
                    },
                }
                async with session.post(mcp_url, json=payload) as resp:
                    if resp.status == 200:
                        tenant.last_sync_at = datetime.now()
                        tenant.status = TenantStatus.ACTIVE
                        await self.tenant_manager.update(tenant)
                        return True, 'Sync triggered'
                    return False, f'Sync failed: {resp.status}'
        except Exception as e:
            return False, f'Sync error: {e}'
