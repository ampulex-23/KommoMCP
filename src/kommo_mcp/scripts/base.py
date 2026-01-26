"""Base script class."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ScriptStatus(BaseModel):
    """Script execution status."""
    
    job_id: str
    script_name: str
    status: str = 'pending'  # pending, running, completed, failed
    progress: float = 0.0  # 0.0 to 1.0
    message: str = ''
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class BaseScript(ABC):
    """Base class for all scripts."""
    
    name: str = 'base_script'
    description: str = 'Base script'
    
    def __init__(self, params: dict[str, Any] | None = None):
        self.params = params or {}
        self.job_id = str(uuid4())
        self._status = ScriptStatus(
            job_id=self.job_id,
            script_name=self.name,
        )
    
    @property
    def status(self) -> ScriptStatus:
        return self._status
    
    def update_progress(self, progress: float, message: str = ''):
        """Update script progress."""
        self._status.progress = min(max(progress, 0.0), 1.0)
        self._status.message = message
        logger.info(f'Script {self.name} [{self.job_id}]: {progress:.0%} - {message}')
    
    async def run(self) -> ScriptStatus:
        """Execute the script."""
        self._status.status = 'running'
        self._status.started_at = datetime.now()
        
        try:
            result = await self.execute()
            self._status.status = 'completed'
            self._status.progress = 1.0
            self._status.result = result
            self._status.completed_at = datetime.now()
            logger.info(f'Script {self.name} [{self.job_id}] completed')
        except Exception as e:
            self._status.status = 'failed'
            self._status.error = str(e)
            self._status.completed_at = datetime.now()
            logger.exception(f'Script {self.name} [{self.job_id}] failed')
        
        return self._status
    
    @abstractmethod
    async def execute(self) -> dict[str, Any]:
        """Execute script logic. Override in subclasses."""
        pass
