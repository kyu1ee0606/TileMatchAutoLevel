"""Application configuration settings."""
import os
import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App settings
    app_name: str = "TileMatch Level Designer Tool"
    app_version: str = "1.0.0"
    debug: bool = False

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS settings - as comma-separated string or JSON array
    cors_origins: str = "http://localhost:5173,http://localhost:3000,https://tile-match-auto-level.vercel.app"

    # GBoost settings
    gboost_url: Optional[str] = None
    gboost_api_key: Optional[str] = None
    gboost_project_id: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_cors_origins(self) -> List[str]:
        """Parse CORS origins from string (comma-separated or JSON)."""
        if not self.cors_origins:
            return ["http://localhost:5173"]

        # Try JSON parse first
        try:
            origins = json.loads(self.cors_origins)
            if isinstance(origins, list):
                return origins
        except json.JSONDecodeError:
            pass

        # Fall back to comma-separated
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Don't use lru_cache in production to allow env var updates
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get settings instance (cached in production for performance)."""
    global _settings
    if _settings is None or os.getenv("DEBUG", "false").lower() == "true":
        _settings = Settings()
    return _settings
