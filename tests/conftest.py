"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_api_client():
    """Mock Kommo API client."""
    client = AsyncMock()
    client.get_account = AsyncMock(return_value={'name': 'Test Account'})
    client.get_pipelines = AsyncMock(return_value=[
        {
            'id': 1,
            'name': 'Main Pipeline',
            'is_main': True,
            '_embedded': {
                'statuses': [
                    {'id': 101, 'name': 'New', 'sort': 10, 'type': 1},
                    {'id': 102, 'name': 'In Progress', 'sort': 20, 'type': 0},
                    {'id': 142, 'name': 'Won', 'sort': 10000, 'type': 2},
                    {'id': 143, 'name': 'Lost', 'sort': 10001, 'type': 3},
                ]
            }
        }
    ])
    client.get_users = AsyncMock(return_value=[
        {'id': 1, 'name': 'Admin', 'email': 'admin@test.com'},
        {'id': 2, 'name': 'Manager', 'email': 'manager@test.com'},
    ])
    return client


@pytest.fixture
def sample_lead():
    """Sample lead data."""
    return {
        'id': 12345,
        'name': 'Test Lead',
        'price': 100000,
        'pipeline_id': 1,
        'status_id': 101,
        'responsible_user_id': 1,
        'created_at': 1704067200,  # 2024-01-01
        'updated_at': 1704153600,  # 2024-01-02
        'closed_at': None,
        'custom_fields_values': [],
    }


@pytest.fixture
def sample_leads(sample_lead):
    """List of sample leads."""
    return [
        sample_lead,
        {**sample_lead, 'id': 12346, 'name': 'Test Lead 2', 'price': 200000},
        {**sample_lead, 'id': 12347, 'name': 'Test Lead 3', 'price': 150000, 'status_id': 142},
    ]
