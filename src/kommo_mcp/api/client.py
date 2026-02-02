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

    # === Pipeline management ===

    async def create_pipeline(
        self,
        name: str,
        sort: int = 1,
        is_main: bool = False,
        is_unsorted_on: bool = True,
        statuses: list[dict] | None = None,
    ) -> dict:
        """
        Create a new pipeline with stages.
        
        Args:
            name: Pipeline name.
            sort: Sort order.
            is_main: Is this the main pipeline.
            is_unsorted_on: Enable unsorted leads.
            statuses: List of stages with name, sort, color.
        
        Returns:
            Created pipeline data.
        """
        pipeline_data = {
            'name': name,
            'sort': sort,
            'is_main': is_main,
            'is_unsorted_on': is_unsorted_on,
        }
        
        if statuses:
            pipeline_data['_embedded'] = {'statuses': statuses}
        
        result = await self.post('leads/pipelines', json=[pipeline_data])
        pipelines = result.get('_embedded', {}).get('pipelines', [])
        return pipelines[0] if pipelines else {}

    async def update_pipeline(
        self,
        pipeline_id: int,
        name: str | None = None,
        sort: int | None = None,
        is_main: bool | None = None,
    ) -> dict:
        """Update pipeline settings."""
        data: dict = {}
        if name is not None:
            data['name'] = name
        if sort is not None:
            data['sort'] = sort
        if is_main is not None:
            data['is_main'] = is_main
        
        return await self.patch(f'leads/pipelines/{pipeline_id}', json=data)

    async def create_stage(
        self,
        pipeline_id: int,
        name: str,
        sort: int,
        color: str = '#fffeb2',
    ) -> dict:
        """
        Create a new stage in pipeline.
        
        Args:
            pipeline_id: Pipeline ID.
            name: Stage name.
            sort: Sort order (10, 20, 30...).
            color: Stage color hex.
        
        Returns:
            Created stage data.
        """
        stage_data = {
            'name': name,
            'sort': sort,
            'color': color,
        }
        
        result = await self.post(
            f'leads/pipelines/{pipeline_id}/statuses',
            json=[stage_data],
        )
        statuses = result.get('_embedded', {}).get('statuses', [])
        return statuses[0] if statuses else {}

    async def update_stage(
        self,
        pipeline_id: int,
        status_id: int,
        name: str | None = None,
        sort: int | None = None,
        color: str | None = None,
    ) -> dict:
        """Update stage settings."""
        data: dict = {}
        if name is not None:
            data['name'] = name
        if sort is not None:
            data['sort'] = sort
        if color is not None:
            data['color'] = color
        
        return await self.patch(
            f'leads/pipelines/{pipeline_id}/statuses/{status_id}',
            json=data,
        )

    async def delete_stage(self, pipeline_id: int, status_id: int) -> dict:
        """Delete a stage from pipeline."""
        return await self.delete(
            f'leads/pipelines/{pipeline_id}/statuses/{status_id}'
        )

    # === Custom fields ===

    async def get_custom_fields(self, entity_type: str = 'leads') -> list[dict]:
        """
        Get custom fields for entity type.
        
        Args:
            entity_type: leads, contacts, companies, customers.
        """
        data = await self.get(f'{entity_type}/custom_fields')
        return data.get('_embedded', {}).get('custom_fields', [])

    async def create_custom_field(
        self,
        entity_type: str,
        name: str,
        field_type: str = 'text',
        sort: int = 100,
        enums: list[dict] | None = None,
        is_required: bool = False,
    ) -> dict:
        """
        Create a custom field.
        
        Args:
            entity_type: leads, contacts, companies.
            name: Field name.
            field_type: text, numeric, checkbox, select, multiselect, date, url, textarea, price, etc.
            sort: Sort order.
            enums: For select/multiselect - list of {value, sort}.
            is_required: Is field required.
        
        Returns:
            Created field data.
        """
        field_data: dict = {
            'name': name,
            'type': field_type,
            'sort': sort,
        }
        
        if enums:
            field_data['enums'] = enums
        if is_required:
            field_data['is_required'] = is_required
        
        result = await self.post(
            f'{entity_type}/custom_fields',
            json=[field_data],
        )
        fields = result.get('_embedded', {}).get('custom_fields', [])
        return fields[0] if fields else {}

    # === Sources ===

    async def get_sources(self, pipeline_id: int) -> list[dict]:
        """Get lead sources for pipeline."""
        data = await self.get(f'leads/pipelines/{pipeline_id}/sources')
        return data.get('_embedded', {}).get('sources', [])

    async def create_source(
        self,
        pipeline_id: int,
        name: str,
        external_id: str | None = None,
    ) -> dict:
        """Create a lead source."""
        source_data = {'name': name}
        if external_id:
            source_data['external_id'] = external_id
        
        result = await self.post(
            f'leads/pipelines/{pipeline_id}/sources',
            json=[source_data],
        )
        sources = result.get('_embedded', {}).get('sources', [])
        return sources[0] if sources else {}
