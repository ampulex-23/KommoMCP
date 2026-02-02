"""
Tenant model and status definitions.
"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class TenantStatus(str, Enum):
    """Tenant lifecycle status."""
    PENDING = 'pending'           # Waiting for API keys
    PROVISIONING = 'provisioning' # Creating DB and container
    SYNCING = 'syncing'           # Initial data sync
    ACTIVE = 'active'             # Ready to use
    SUSPENDED = 'suspended'       # Temporarily disabled
    ERROR = 'error'               # Provisioning failed


class Tenant(BaseModel):
    """Tenant configuration and state."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    telegram_user_id: int
    telegram_username: Optional[str] = None
    
    # Kommo API credentials
    kommo_domain: Optional[str] = None  # e.g., 'mycompany.kommo.com'
    kommo_access_token: Optional[str] = None
    kommo_refresh_token: Optional[str] = None
    kommo_token_expires_at: Optional[datetime] = None
    
    # OpenAI credentials
    openai_api_key: Optional[str] = None
    
    # Infrastructure
    db_name: Optional[str] = None           # PostgreSQL database name
    container_id: Optional[str] = None      # Docker container ID
    container_port: Optional[int] = None    # MCP HTTP port
    
    # Status
    status: TenantStatus = TenantStatus.PENDING
    error_message: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_sync_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    
    # Limits
    requests_today: int = 0
    requests_limit: int = 1000  # Daily limit
    
    class Config:
        use_enum_values = True
    
    def is_ready(self) -> bool:
        """Check if tenant is ready for requests."""
        return self.status == TenantStatus.ACTIVE
    
    def has_kommo_credentials(self) -> bool:
        """Check if Kommo API is configured."""
        return bool(self.kommo_domain and self.kommo_access_token)
    
    def has_openai_credentials(self) -> bool:
        """Check if OpenAI API is configured."""
        return bool(self.openai_api_key)
    
    def get_mcp_url(self) -> Optional[str]:
        """Get MCP HTTP endpoint for this tenant."""
        if self.container_port:
            return f'http://localhost:{self.container_port}/mcp'
        return None
