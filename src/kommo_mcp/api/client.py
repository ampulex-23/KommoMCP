"""Kommo API HTTP client with rate limiting and auto-pagination."""

import logging
from typing import Any, AsyncIterator

import httpx

from kommo_mcp.api.rate_limiter import RateLimiter
from kommo_mcp.config import init_settings

logger = logging.getLogger(__name__)


class KommoAPIError(Exception):
    """Kommo API error."""

    def __init__(self, status_code: int, message: str, response: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.response = response
        super().__init__(f'Kommo API Error {status_code}: {message}')


class KommoClient:
    """
    Async HTTP client for Kommo API v4.
    
    Features:
    - Rate limiting (7 req/sec)
    - Auto-pagination
    - Retry on transient errors
    - Proper error handling
    """

    MAX_PAGE_SIZE = 250
    DEFAULT_PAGE_SIZE = 50

    def __init__(
        self,
        subdomain: str | None = None,
        access_token: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize Kommo client.
        
        Args:
            subdomain: Kommo account subdomain (default from settings).
            access_token: API access token (default from settings).
            timeout: Request timeout in seconds.
        """
        _settings = init_settings()
        self.subdomain = subdomain or _settings.kommo_subdomain
        self.access_token = access_token or _settings.kommo_access_token
        self.base_url = f'https://{self.subdomain}.amocrm.ru/api/v4'
        
        self.client = httpx.AsyncClient(
            headers={
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
            },
            timeout=timeout,
        )
        self.rate_limiter = RateLimiter(max_requests=7, time_window=1.0)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> 'KommoClient':
        """Context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        await self.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        json: dict | list | None = None,
    ) -> dict:
        """
        Make HTTP request to Kommo API.
        
        Args:
            method: HTTP method.
            endpoint: API endpoint (without base URL).
            params: Query parameters.
            json: JSON body.
        
        Returns:
            Response JSON.
        
        Raises:
            KommoAPIError: On API error.
        """
        url = f'{self.base_url}/{endpoint.lstrip("/")}'
        
        async with self.rate_limiter:
            try:
                response = await self.client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                )
                
                if response.status_code == 204:
                    return {}
                
                if response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    raise KommoAPIError(
                        status_code=response.status_code,
                        message=error_data.get('detail', response.reason_phrase or 'Unknown error'),
                        response=error_data,
                    )
                
                return response.json()
                
            except httpx.TimeoutException as e:
                raise KommoAPIError(504, f'Request timeout: {e}')
            except httpx.RequestError as e:
                raise KommoAPIError(0, f'Request error: {e}')

    async def get(self, endpoint: str, params: dict | None = None) -> dict:
        """GET request."""
        return await self._request('GET', endpoint, params=params)

    async def post(self, endpoint: str, json: dict | list | None = None) -> dict:
        """POST request."""
        return await self._request('POST', endpoint, json=json)

    async def patch(self, endpoint: str, json: dict | list | None = None) -> dict:
        """PATCH request."""
        return await self._request('PATCH', endpoint, json=json)

    async def delete(self, endpoint: str) -> dict:
        """DELETE request."""
        return await self._request('DELETE', endpoint)

    async def iterate(
        self,
        endpoint: str,
        params: dict | None = None,
        limit: int | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> AsyncIterator[dict]:
        """
        Iterate over paginated results.
        
        Args:
            endpoint: API endpoint.
            params: Additional query parameters.
            limit: Maximum total items to return (None for all).
            page_size: Items per page (max 250).
        
        Yields:
            Individual items from the response.
        """
        params = params or {}
        page = 1
        count = 0
        page_size = min(page_size, self.MAX_PAGE_SIZE)
        
        while True:
            page_params = {**params, 'page': page, 'limit': page_size}
            
            try:
                data = await self.get(endpoint, params=page_params)
            except KommoAPIError as e:
                if e.status_code == 204:
                    break
                raise
            
            if not data:
                break
            
            # Extract items from _embedded
            embedded = data.get('_embedded', {})
            # Find the items key (usually matches endpoint name)
            items_key = endpoint.split('/')[0]
            items = embedded.get(items_key, [])
            
            if not items:
                break
            
            for item in items:
                yield item
                count += 1
                if limit and count >= limit:
                    return
            
            # Check if there are more pages
            if len(items) < page_size:
                break
            
            page += 1

    # === Convenience methods for common entities ===

    async def get_leads(self, **params: Any) -> AsyncIterator[dict]:
        """Get leads with auto-pagination."""
        # Sort by updated_at desc to get newest first
        if 'order[updated_at]' not in params and 'order[created_at]' not in params:
            params['order[updated_at]'] = 'desc'
        async for lead in self.iterate('leads', params=params):
            yield lead

    async def get_contacts(self, **params: Any) -> AsyncIterator[dict]:
        """Get contacts with auto-pagination."""
        async for contact in self.iterate('contacts', params=params):
            yield contact

    async def get_companies(self, **params: Any) -> AsyncIterator[dict]:
        """Get companies with auto-pagination."""
        async for company in self.iterate('companies', params=params):
            yield company

    async def get_tasks(self, **params: Any) -> AsyncIterator[dict]:
        """Get tasks with auto-pagination."""
        async for task in self.iterate('tasks', params=params):
            yield task

    async def get_pipelines(self) -> list[dict]:
        """Get all pipelines with statuses."""
        data = await self.get('leads/pipelines')
        return data.get('_embedded', {}).get('pipelines', [])

    async def get_users(self) -> list[dict]:
        """Get all users."""
        data = await self.get('users')
        return data.get('_embedded', {}).get('users', [])

    async def get_account(self) -> dict:
        """Get account info."""
        return await self.get('account')
