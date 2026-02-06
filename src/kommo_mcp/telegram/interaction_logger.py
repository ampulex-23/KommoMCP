"""
Interaction Logger - logs all AI agent interactions for debugging and monitoring.

Captures:
- User prompts and system prompts
- Tool calls and their results
- Kommo API requests/responses
- Errors and final responses to user
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


class InteractionLogger:
    """Logs all interactions for a tenant/session."""
    
    def __init__(self, log_dir: str = '/var/lib/kommo-saas/logs'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_session: Optional[str] = None
        self._session_data: Dict[str, Any] = {}
    
    def start_session(self, user_id: int, message: str) -> str:
        """Start a new interaction session."""
        session_id = f'{datetime.now().strftime("%Y%m%d_%H%M%S")}_{user_id}_{uuid.uuid4().hex[:8]}'
        self._current_session = session_id
        self._session_data = {
            'session_id': session_id,
            'user_id': user_id,
            'started_at': datetime.now().isoformat(),
            'user_message': message,
            'system_prompt': None,
            'dynamic_prompt': None,
            'iterations': [],
            'api_calls': [],
            'errors': [],
            'final_response': None,
            'completed_at': None,
            'duration_ms': None,
        }
        self._start_time = datetime.now()
        logger.info(f'[SESSION:{session_id}] Started for user {user_id}')
        return session_id
    
    def log_prompt(self, system_prompt: str, dynamic_prompt: str = None):
        """Log the prompts used."""
        if not self._session_data:
            return
        self._session_data['system_prompt'] = system_prompt
        self._session_data['dynamic_prompt'] = dynamic_prompt
        logger.debug(f'[SESSION:{self._current_session}] Prompt logged ({len(system_prompt)} chars)')
    
    def log_iteration(self, iteration: int, tool_calls: List[Dict], results: List[Dict]):
        """Log a tool execution iteration."""
        if not self._session_data:
            return
        
        iteration_data = {
            'iteration': iteration,
            'timestamp': datetime.now().isoformat(),
            'tool_calls': [],
        }
        
        for i, (call, result) in enumerate(zip(tool_calls, results)):
            tool_data = {
                'tool_name': call.get('function', {}).get('name', 'unknown'),
                'arguments': self._safe_parse_json(call.get('function', {}).get('arguments', '{}')),
                'result': self._truncate_result(result),
                'success': not isinstance(result, dict) or 'error' not in result,
            }
            iteration_data['tool_calls'].append(tool_data)
        
        self._session_data['iterations'].append(iteration_data)
        logger.info(f'[SESSION:{self._current_session}] Iteration {iteration}: {len(tool_calls)} tool calls')
    
    def log_api_call(self, method: str, url: str, request_body: Any = None, 
                     response_status: int = None, response_body: Any = None, 
                     duration_ms: float = None, error: str = None):
        """Log a Kommo API call."""
        if not self._session_data:
            return
        
        api_data = {
            'timestamp': datetime.now().isoformat(),
            'method': method,
            'url': url,
            'request_body': self._truncate_result(request_body) if request_body else None,
            'response_status': response_status,
            'response_body': self._truncate_result(response_body) if response_body else None,
            'duration_ms': duration_ms,
            'error': error,
        }
        self._session_data['api_calls'].append(api_data)
        
        status_str = f'status={response_status}' if response_status else f'error={error}'
        logger.debug(f'[SESSION:{self._current_session}] API: {method} {url} -> {status_str}')
    
    def log_error(self, error_type: str, error_message: str, context: Dict = None):
        """Log an error."""
        if not self._session_data:
            return
        
        error_data = {
            'timestamp': datetime.now().isoformat(),
            'type': error_type,
            'message': error_message,
            'context': context,
        }
        self._session_data['errors'].append(error_data)
        logger.error(f'[SESSION:{self._current_session}] Error: {error_type} - {error_message}')
    
    def end_session(self, final_response: str):
        """End the session and save to file."""
        if not self._session_data:
            return
        
        self._session_data['final_response'] = final_response
        self._session_data['completed_at'] = datetime.now().isoformat()
        self._session_data['duration_ms'] = (datetime.now() - self._start_time).total_seconds() * 1000
        
        # Save to file
        self._save_session()
        
        logger.info(f'[SESSION:{self._current_session}] Completed in {self._session_data["duration_ms"]:.0f}ms')
        
        # Reset
        session_id = self._current_session
        self._current_session = None
        self._session_data = {}
        return session_id
    
    def _save_session(self):
        """Save session data to JSON file."""
        if not self._session_data:
            return
        
        # Organize by date
        date_dir = self.log_dir / datetime.now().strftime('%Y-%m-%d')
        date_dir.mkdir(exist_ok=True)
        
        filename = f'{self._current_session}.json'
        filepath = date_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self._session_data, f, ensure_ascii=False, indent=2)
            logger.debug(f'Session saved to {filepath}')
        except Exception as e:
            logger.error(f'Failed to save session: {e}')
    
    def _safe_parse_json(self, data: str) -> Any:
        """Safely parse JSON string."""
        if isinstance(data, dict):
            return data
        try:
            return json.loads(data)
        except:
            return data
    
    def _truncate_result(self, result: Any, max_length: int = 2000) -> Any:
        """Truncate large results for storage."""
        if result is None:
            return None
        
        if isinstance(result, str):
            if len(result) > max_length:
                return result[:max_length] + f'... [truncated, total {len(result)} chars]'
            return result
        
        if isinstance(result, dict):
            result_str = json.dumps(result, ensure_ascii=False)
            if len(result_str) > max_length:
                return {'_truncated': True, '_preview': result_str[:max_length], '_total_chars': len(result_str)}
            return result
        
        if isinstance(result, list):
            result_str = json.dumps(result, ensure_ascii=False)
            if len(result_str) > max_length:
                return {'_truncated': True, '_count': len(result), '_preview': result_str[:max_length]}
            return result
        
        return str(result)[:max_length]
    
    def get_recent_sessions(self, limit: int = 20) -> List[Dict]:
        """Get list of recent sessions."""
        sessions = []
        
        # Get all date directories, sorted descending
        date_dirs = sorted(self.log_dir.glob('20*-*-*'), reverse=True)
        
        for date_dir in date_dirs:
            if len(sessions) >= limit:
                break
            
            # Get all session files in this date, sorted descending
            session_files = sorted(date_dir.glob('*.json'), reverse=True)
            
            for session_file in session_files:
                if len(sessions) >= limit:
                    break
                
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        sessions.append({
                            'session_id': data.get('session_id'),
                            'user_id': data.get('user_id'),
                            'started_at': data.get('started_at'),
                            'duration_ms': data.get('duration_ms'),
                            'user_message': data.get('user_message', '')[:100],
                            'iterations': len(data.get('iterations', [])),
                            'api_calls': len(data.get('api_calls', [])),
                            'errors': len(data.get('errors', [])),
                        })
                except Exception as e:
                    logger.warning(f'Failed to read session {session_file}: {e}')
        
        return sessions
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get full session data by ID."""
        # Parse date from session_id (format: YYYYMMDD_HHMMSS_userid_uuid)
        try:
            date_str = session_id[:8]
            date_dir = self.log_dir / f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
            filepath = date_dir / f'{session_id}.json'
            
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f'Failed to get session {session_id}: {e}')
        
        return None


# Global instance for the test tenant
_interaction_logger: Optional[InteractionLogger] = None


def get_interaction_logger() -> InteractionLogger:
    """Get or create the global interaction logger."""
    global _interaction_logger
    if _interaction_logger is None:
        _interaction_logger = InteractionLogger()
    return _interaction_logger
