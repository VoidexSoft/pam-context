"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings

_INSECURE_SECRETS = {
    "dev-secret-change-in-production-32b",
    "secret",
    "changeme",
    "password",
}


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

    # LLM provider abstraction
    llm_provider: str = "anthropic"  # anthropic | openai | ollama
    openai_llm_model: str = "gpt-4o"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_embedding_dims: int = 768
    embedding_provider: str = "openai"  # openai | ollama

    # Multimodal processing
    enable_multimodal: bool = False  # Feature flag, off by default
    enable_image_processing: bool = True
    enable_table_processing: bool = True
    vision_model: str = ""  # Empty = use agent_model
    multimodal_context_chars: int = 2000

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

    # Neo4j (knowledge graph)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"
    neo4j_database: str = "neo4j"
    graph_context_enabled: bool = True  # Inject graph context into search results

    # Haystack
    use_haystack_retrieval: bool = False  # Set True to use Haystack-based retrieval pipeline

    # Reranking
    rerank_enabled: bool = False  # Set True to enable cross-encoder reranking
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # DuckDB (analytics queries)
    duckdb_data_dir: str = ""  # Directory containing data files (CSV, Parquet, JSON)
    duckdb_max_rows: int = 1000  # Max rows returned per query

    # Parser
    parser: str = "docling"  # docling | mineru
    mineru_method: str = "auto"  # auto | txt | ocr

    # Ingestion
    chunk_size_tokens: int = 512
    ingest_root: str = ""  # Required base directory for folder ingestion; empty = reject all

    # App
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def validate_jwt_secret(self) -> None:
        """Raise if auth is required but JWT secret is insecure."""
        if self.auth_required and self.jwt_secret in _INSECURE_SECRETS:
            raise ValueError(
                "Insecure JWT secret detected with AUTH_REQUIRED=true. "
                "Set JWT_SECRET to a strong, unique value (>= 32 characters)."
            )
        if self.auth_required and len(self.jwt_secret) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters when AUTH_REQUIRED=true."
            )


settings = Settings()
