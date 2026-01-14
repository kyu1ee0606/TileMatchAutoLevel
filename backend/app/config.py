"""Application configuration settings."""
from pydantic_settings import BaseSettings
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
    ]

    # GBoost settings
    gboost_url: Optional[str] = None
    gboost_api_key: Optional[str] = None
    gboost_project_id: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
