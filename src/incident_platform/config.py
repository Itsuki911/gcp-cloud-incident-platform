from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "Cloud-Native AI Incident & Support Triage System"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://incident:incident@localhost:5432/incidents"
    google_cloud_project: str = ""
    pubsub_topic: str = "incident-tickets"
    pubsub_subscription: str = "incident-tickets-worker"
    ai_api_secret_name: str = "ai-api-key"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
