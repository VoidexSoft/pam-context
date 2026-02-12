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

    # Auth
    auth_required: bool = False  # Optional in dev mode; set True in production
    jwt_secret: str = "dev-secret-change-in-production-32b"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Google OAuth2
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/callback"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_search_ttl: int = 900  # 15 minutes for search results
    redis_segment_ttl: int = 3600  # 1 hour for segment data
    redis_session_ttl: int = 86400  # 24 hours for conversation sessions

    # Reranking
    rerank_enabled: bool = False  # Set True to enable cross-encoder reranking
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # DuckDB (analytics queries)
    duckdb_data_dir: str = ""  # Directory containing data files (CSV, Parquet, JSON)
    duckdb_max_rows: int = 1000  # Max rows returned per query

    # Ingestion
    chunk_size_tokens: int = 512

    # App
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
