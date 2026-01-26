"""Webhooks module for receiving Kommo events."""

from kommo_mcp.webhooks.server import create_webhook_app
from kommo_mcp.webhooks.handlers import WebhookHandler

__all__ = ['create_webhook_app', 'WebhookHandler']
