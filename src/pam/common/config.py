"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    database_url: str = "postgresql+psycopg://pam:pam@localhost:5432/pam_context"

    # Elasticsearch
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "pam_segments"

    # OpenAI (embeddings)
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-large"
    embedding_dims: int = 1536

    # Anthropic (agent)
    anthropic_api_key: str = ""
    agent_model: str = "claude-sonnet-4-5-20250514"

    # Google OAuth2
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/callback"

    # Ingestion
    chunk_size_tokens: int = 512

    # App
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
