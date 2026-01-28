"""FastAPI webhook server for receiving Kommo events."""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from kommo_mcp.config import init_settings
from kommo_mcp.webhooks.handlers import WebhookHandler

logger = logging.getLogger(__name__)


def create_webhook_app() -> FastAPI:
    """Create FastAPI application for webhooks and MCP HTTP."""
    app = FastAPI(
        title='KommoMCP Server',
        description='MCP Server for Kommo CRM with webhooks and HTTP transport',
        version='1.0.0',
    )
    
    handler = WebhookHandler()
    
    @app.get('/health')
    async def health_check():
        """Health check endpoint."""
        return {'status': 'ok', 'service': 'kommo-mcp'}
    
    @app.get('/mcp')
    async def mcp_info():
        """MCP server info."""
        return {
            'name': 'kommo-mcp',
            'version': '1.0.0',
            'protocol_version': '2024-11-05',
            'capabilities': {'tools': {}, 'resources': {}},
        }
    
    @app.post('/mcp')
    async def mcp_endpoint(request: Request):
        """MCP HTTP Streamable endpoint for n8n."""
        import json
        from kommo_mcp.mcp_http.server import (
            _handle_initialize,
            _handle_tools_list,
            _handle_tools_call,
            _handle_resources_list,
            _handle_resources_read,
        )
        
        try:
            body = await request.json()
            logger.info(f'MCP request: {body.get("method")}')
            
            method = body.get('method')
            params = body.get('params', {})
            request_id = body.get('id')
            
            if method == 'initialize':
                result = await _handle_initialize(params)
            elif method == 'tools/list':
                result = await _handle_tools_list()
            elif method == 'tools/call':
                result = await _handle_tools_call(params)
            elif method == 'resources/list':
                result = await _handle_resources_list()
            elif method == 'resources/read':
                result = await _handle_resources_read(params)
            elif method == 'ping':
                result = {}
            else:
                return JSONResponse(content={
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'error': {'code': -32601, 'message': f'Method not found: {method}'},
                })
            
            return JSONResponse(content={
                'jsonrpc': '2.0',
                'id': request_id,
                'result': result,
            })
        except Exception as e:
            logger.exception('MCP request error')
            return JSONResponse(status_code=500, content={
                'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32603, 'message': str(e)},
            })
    
    @app.post('/webhook/kommo')
    async def receive_webhook(
        request: Request,
        x_signature: str | None = Header(None, alias='X-Signature'),
    ):
        """
        Receive webhook from Kommo.
        
        Kommo sends webhooks as form-urlencoded data.
        """
        try:
            # Get raw body for signature verification
            body = await request.body()
            
            # Verify signature if secret is configured
            settings = init_settings()
            if settings.webhook_secret and x_signature:
                if not _verify_signature(body, x_signature, settings.webhook_secret):
                    logger.warning('Invalid webhook signature')
                    raise HTTPException(status_code=401, detail='Invalid signature')
            
            # Parse form data
            form_data = await request.form()
            payload = _parse_form_data(dict(form_data))
            
            logger.info(f'Received webhook: {list(payload.keys())}')
            
            # Process webhook
            result = await handler.handle(payload)
            
            return JSONResponse(content=result)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception('Error processing webhook')
            return JSONResponse(
                status_code=500,
                content={'status': 'error', 'message': str(e)},
            )
    
    @app.post('/webhook/kommo/json')
    async def receive_webhook_json(
        request: Request,
        x_signature: str | None = Header(None, alias='X-Signature'),
    ):
        """
        Receive webhook as JSON (alternative endpoint).
        """
        try:
            body = await request.body()
            
            settings = init_settings()
            if settings.webhook_secret and x_signature:
                if not _verify_signature(body, x_signature, settings.webhook_secret):
                    raise HTTPException(status_code=401, detail='Invalid signature')
            
            payload = await request.json()
            logger.info(f'Received JSON webhook: {list(payload.keys())}')
            
            result = await handler.handle(payload)
            return JSONResponse(content=result)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception('Error processing webhook')
            return JSONResponse(
                status_code=500,
                content={'status': 'error', 'message': str(e)},
            )
    
    return app


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify webhook signature."""
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _parse_form_data(form_data: dict[str, Any]) -> dict[str, Any]:
    """
    Parse Kommo webhook form data into structured dict.
    
    Kommo sends data like:
    - leads[add][0][id] = 123
    - leads[add][0][name] = Test
    """
    result: dict[str, Any] = {}
    
    for key, value in form_data.items():
        # Parse nested keys like leads[add][0][id]
        parts = []
        current = key
        while '[' in current:
            idx = current.index('[')
            if idx > 0:
                parts.append(current[:idx])
            end_idx = current.index(']')
            parts.append(current[idx + 1:end_idx])
            current = current[end_idx + 1:]
        if current:
            parts.append(current)
        
        # Build nested structure
        _set_nested(result, parts, value)
    
    return result


def _set_nested(d: dict, keys: list[str], value: Any):
    """Set value in nested dict structure."""
    for i, key in enumerate(keys[:-1]):
        if key.isdigit():
            key = int(key)
            # Parent should be a list
            parent_key = keys[i - 1] if i > 0 else None
            if parent_key and isinstance(d.get(parent_key), dict):
                if parent_key not in d or not isinstance(d[parent_key], list):
                    d[parent_key] = []
                while len(d[parent_key]) <= key:
                    d[parent_key].append({})
                d = d[parent_key][key]
                continue
        
        if key not in d:
            # Check if next key is numeric (need list)
            next_key = keys[i + 1] if i + 1 < len(keys) else None
            if next_key and next_key.isdigit():
                d[key] = []
            else:
                d[key] = {}
        
        if isinstance(d[key], list):
            next_key = keys[i + 1]
            if next_key.isdigit():
                idx = int(next_key)
                while len(d[key]) <= idx:
                    d[key].append({})
                d = d[key][idx]
                # Skip the numeric key
                continue
        
        d = d[key]
    
    # Set final value
    final_key = keys[-1]
    if final_key.isdigit():
        return  # Already handled
    d[final_key] = value


def run_webhook_server():
    """Run webhook server standalone."""
    import uvicorn
    
    settings = init_settings()
    app = create_webhook_app()
    
    uvicorn.run(
        app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == '__main__':
    run_webhook_server()
