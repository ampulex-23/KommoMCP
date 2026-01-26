"""Configuration management for KommoMCP."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    # Kommo API
    kommo_subdomain: str
    kommo_access_token: str
    kommo_refresh_token: str | None = None
    kommo_client_id: str | None = None
    kommo_client_secret: str | None = None

    # Database
    database_url: str = 'postgresql+asyncpg://postgres:postgres@localhost:5432/kommo_mcp'

    # MCP Server
    mcp_transport: str = 'stdio'
    mcp_host: str = '127.0.0.1'
    mcp_port: int = 8000

    # Webhook Server
    webhook_enabled: bool = False
    webhook_host: str = '0.0.0.0'
    webhook_port: int = 8001
    webhook_secret: str | None = None

    # Logging
    log_level: str = 'INFO'
    log_format: str = 'text'  # 'text' or 'json'

    # Sync
    sync_batch_size: int = 50
    sync_interval_minutes: int = 5

    @property
    def kommo_base_url(self) -> str:
        """Get Kommo API base URL."""
        return f'https://{self.kommo_subdomain}.kommo.com/api/v4'


def get_settings() -> Settings:
    """Get settings instance (lazy loading)."""
    return Settings()  # type: ignore[call-arg]


# Lazy settings - will be initialized when first accessed
settings: Settings | None = None


def init_settings() -> Settings:
    """Initialize settings from environment."""
    global settings
    if settings is None:
        settings = get_settings()
    return settings
