"""Application configuration settings."""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App settings
    app_name: str = "TileMatch Level Designer Tool"
    app_version: str = "1.0.0"
    debug: bool = False

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS settings - includes localhost for dev and vercel for production
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://*.vercel.app",
        "https://tile-match-auto-level.vercel.app",
    ]

    # GBoost settings
    gboost_url: Optional[str] = None
    gboost_api_key: Optional[str] = None
    gboost_project_id: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Don't use lru_cache in production to allow env var updates
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get settings instance (cached in production for performance)."""
    global _settings
    if _settings is None or os.getenv("DEBUG", "false").lower() == "true":
        _settings = Settings()
    return _settings
