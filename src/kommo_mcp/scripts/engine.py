"""Scripts engine for managing and executing scripts."""

import asyncio
import logging
from typing import Any, Type

from kommo_mcp.scripts.base import BaseScript, ScriptStatus
from kommo_mcp.scripts.builtin import (
    BulkUpdateStatusScript,
    CleanupOldDataScript,
    ExportLeadsScript,
    FindDuplicatesScript,
    RecalculateAnalyticsScript,
)

logger = logging.getLogger(__name__)


class ScriptsEngine:
    """
    Engine for managing and executing scripts.
    
    Supports:
    - Running scripts synchronously or asynchronously
    - Tracking job status
    - Built-in scripts for common operations
    """

    # Registry of available scripts
    SCRIPTS: dict[str, Type[BaseScript]] = {
        'export_leads': ExportLeadsScript,
        'bulk_update_status': BulkUpdateStatusScript,
        'find_duplicates': FindDuplicatesScript,
        'recalculate_analytics': RecalculateAnalyticsScript,
        'cleanup_old_data': CleanupOldDataScript,
    }

    def __init__(self):
        self._jobs: dict[str, ScriptStatus] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}

    def list_scripts(self) -> list[dict[str, str]]:
        """List available scripts."""
        return [
            {
                'name': name,
                'description': script_class.description,
            }
            for name, script_class in self.SCRIPTS.items()
        ]

    def get_job_status(self, job_id: str) -> ScriptStatus | None:
        """Get status of a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[ScriptStatus]:
        """List all jobs, optionally filtered by status."""
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    async def run_script(
        self,
        script_name: str,
        params: dict[str, Any] | None = None,
        async_mode: bool = False,
    ) -> ScriptStatus:
        """
        Run a script.
        
        Args:
            script_name: Name of the script to run
            params: Script parameters
            async_mode: If True, run in background and return immediately
        
        Returns:
            ScriptStatus with job_id and current status
        """
        if script_name not in self.SCRIPTS:
            raise ValueError(f'Unknown script: {script_name}. Available: {list(self.SCRIPTS.keys())}')
        
        script_class = self.SCRIPTS[script_name]
        script = script_class(params)
        
        # Store initial status
        self._jobs[script.job_id] = script.status
        
        if async_mode:
            # Run in background
            task = asyncio.create_task(self._run_async(script))
            self._running_tasks[script.job_id] = task
            return script.status
        else:
            # Run synchronously
            status = await script.run()
            self._jobs[script.job_id] = status
            return status

    async def _run_async(self, script: BaseScript):
        """Run script asynchronously and update status."""
        try:
            status = await script.run()
            self._jobs[script.job_id] = status
        except Exception as e:
            logger.exception(f'Async script {script.name} failed')
            script._status.status = 'failed'
            script._status.error = str(e)
            self._jobs[script.job_id] = script.status
        finally:
            # Clean up task reference
            self._running_tasks.pop(script.job_id, None)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            if job_id in self._jobs:
                self._jobs[job_id].status = 'cancelled'
            
            return True
        return False

    def register_script(self, name: str, script_class: Type[BaseScript]):
        """Register a custom script."""
        self.SCRIPTS[name] = script_class
        logger.info(f'Registered script: {name}')


# Global engine instance
_engine: ScriptsEngine | None = None


def get_scripts_engine() -> ScriptsEngine:
    """Get or create scripts engine instance."""
    global _engine
    if _engine is None:
        _engine = ScriptsEngine()
    return _engine
