"""
Entry point for running the Telegram bot.

Usage:
    python -m kommo_mcp.telegram
    
Environment variables:
    TELEGRAM_BOT_TOKEN - Bot token from @BotFather
    POSTGRES_HOST - PostgreSQL host
    POSTGRES_PORT - PostgreSQL port
    POSTGRES_USER - PostgreSQL user
    POSTGRES_PASSWORD - PostgreSQL password
    DATA_DIR - Directory for tenant data (default: /var/lib/kommo-saas)
"""

import os
import asyncio
import logging

from .bot import run_bot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        logger.error('TELEGRAM_BOT_TOKEN environment variable is required')
        return
    
    data_dir = os.getenv('DATA_DIR', '/var/lib/kommo-saas')
    
    logger.info('Starting KommoMCP Telegram Bot...')
    
    asyncio.run(run_bot(token, data_dir))


if __name__ == '__main__':
    main()
