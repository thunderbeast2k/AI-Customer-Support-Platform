"""
Application Configuration Module using Pydantic Settings.
Centralizes all environment variables and configuration for the platform.
"""
from typing import List, Union
import json
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base Application Metadata
    PROJECT_NAME: str = "AI Customer Support Platform"
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL & pgvector Database Settings
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/customer_support_db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_TIMEOUT_SECONDS: int = 10

    # Security & Authentication
    SECRET_KEY: str = "dev_secret_key_change_in_production_at_least_32_characters_long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS Settings
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["http://localhost:3000"]

    # Machine Learning Settings
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    CLASSIFIER_ARTIFACTS_DIR: str = "app/ml/artifacts"

    # Generative AI / LLM Adapter Settings
    LLM_PROVIDER: str = "mock"  # Options: mock, gemini, openai
    LLM_MODEL_NAME: str = "gemini-1.5-flash"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 800

    # Structured Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Phase 10: Multi-Channel Webhooks & Production Hardening
    WEBHOOK_SLACK_SIGNING_SECRET: str = "slack_test_secret_dev"
    WEBHOOK_GENERIC_SECRET: str = "webhook_generic_secret_32char_key"
    WEBHOOK_ZENDESK_TOKEN: str = "zendesk_bearer_token_dev"
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 120
    SECURITY_HEADERS_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
