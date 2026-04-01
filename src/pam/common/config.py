"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic import model_validator
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
    agent_model: str = "claude-sonnet-4-6"

    # Auth
    auth_required: bool = False  # Optional in dev mode; set True in production
    jwt_secret: str = "dev-secret-change-in-production-32b"  # noqa: S105
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

    # Haystack
    use_haystack_retrieval: bool = False  # Set True to use Haystack-based retrieval pipeline

    # Reranking
    rerank_enabled: bool = False  # Set True to enable cross-encoder reranking
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Neo4j / Graphiti
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "pam_graph"  # noqa: S105
    graphiti_model: str = "claude-sonnet-4-6"
    graphiti_embedding_model: str = "text-embedding-3-small"

    # DuckDB (analytics queries)
    duckdb_data_dir: str = ""  # Directory containing data files (CSV, Parquet, JSON)
    duckdb_max_rows: int = 1000  # Max rows returned per query

    # Entity/Relationship VDB indices
    entity_index: str = "pam_entities"
    relationship_index: str = "pam_relationships"

    # Smart Search
    smart_search_es_limit: int = 5  # Max document results from ES hybrid search
    smart_search_graph_limit: int = 5  # Max graph results from Graphiti search
    smart_search_entity_limit: int = 5  # Max entity VDB results
    smart_search_relationship_limit: int = 5  # Max relationship VDB results

    # Context Assembly Token Budgets
    context_entity_budget: int = 4000
    context_relationship_budget: int = 6000
    context_max_tokens: int = 12000

    # Mode Router
    mode_confidence_threshold: float = 0.7  # Below this, fall back to hybrid
    mode_temporal_keywords: str = "when,history,changed,before,after,since,recently,timeline,evolution,over time"
    mode_factual_patterns: str = "what is,define,how many,who is,list the,describe,what does,what are"
    mode_conceptual_keywords: str = (
        "depends on,related to,connect,impact,affects,why does,relationship,architecture,pattern,interaction"
    )
    mode_llm_fallback_enabled: bool = True  # Set False to use rules-only (no LLM call)

    # Ingestion
    chunk_size_tokens: int = 512
    ingest_root: str = ""  # Required base directory for folder ingestion; empty = reject all
    max_concurrent_ingestions: int = 3  # Max background ingestion tasks

    # MCP Server
    mcp_enabled: bool = True  # Enable MCP SSE transport on /mcp

    # Memory Service
    memory_index: str = "pam_memories"  # ES index for memory embeddings
    memory_dedup_threshold: float = 0.9  # Cosine similarity threshold for dedup
    memory_merge_model: str = "claude-haiku-4-5-20251001"  # LLM for content merge

    # Conversation Service
    conversation_extraction_enabled: bool = True
    conversation_extraction_model: str = "claude-haiku-4-5-20251001"
    conversation_summary_threshold: int = 20  # messages before auto-summarization
    conversation_summary_token_limit: int = 8000  # token budget for summary
    conversation_context_max_tokens: int = 2000  # max tokens for conversation context in assembly

    # Context Assembly — memory budget
    context_memory_budget: int = 2000  # token budget for user memories in context

    # CLI connectors
    github_repos: list[dict] = []  # [{"repo":"owner/repo","branch":"main","paths":[],"extensions":[]}]
    use_cli_connectors: bool = False  # Use gws CLI instead of Google API connectors
    cli_timeout: int = 30  # Seconds per CLI subprocess call

    # Google connectors
    google_folder_ids: list[str] = []  # Google Drive folder IDs to ingest from
    google_credentials_path: str = ""  # Path to Google service account credentials JSON

    # Rate limiting
    rate_limit_default: str = "100/minute"
    rate_limit_chat: str = "10/minute"
    rate_limit_ingest: str = "5/minute"
    rate_limit_search: str = "30/minute"
    rate_limit_memory: str = "30/minute"

    # App
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        """Raise if auth is required but JWT secret is insecure."""
        if self.auth_required and self.jwt_secret in _INSECURE_SECRETS:
            raise ValueError(
                "Insecure JWT secret detected with AUTH_REQUIRED=true. "
                "Set JWT_SECRET to a strong, unique value (>= 32 characters)."
            )
        if self.auth_required and len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters when AUTH_REQUIRED=true.")
        return self

    @model_validator(mode="after")
    def _check_api_keys(self) -> "Settings":
        """Reject empty API keys — app will fail at runtime without them."""
        if not self.anthropic_api_key:
            raise ValueError("anthropic_api_key is required. Set ANTHROPIC_API_KEY in your environment.")
        if not self.openai_api_key:
            raise ValueError("openai_api_key is required. Set OPENAI_API_KEY in your environment.")
        return self

    @model_validator(mode="after")
    def _check_constraints(self) -> "Settings":
        """Validate numeric constraints between settings."""
        if not 0.0 <= self.mode_confidence_threshold <= 1.0:
            raise ValueError(f"mode_confidence_threshold must be 0.0-1.0, got {self.mode_confidence_threshold}")
        if not 0.0 <= self.memory_dedup_threshold <= 1.0:
            raise ValueError(f"memory_dedup_threshold must be 0.0-1.0, got {self.memory_dedup_threshold}")
        if self.context_entity_budget + self.context_relationship_budget > self.context_max_tokens:
            raise ValueError(
                f"context budget overflow: entity ({self.context_entity_budget}) + "
                f"relationship ({self.context_relationship_budget}) > "
                f"max ({self.context_max_tokens})"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (created on first call)."""
    return Settings()


def reset_settings() -> None:
    """Clear the cached settings so the next call re-reads env vars."""
    get_settings.cache_clear()


class _SettingsProxy:
    """Proxy that delegates attribute access to the lazily-created Settings."""

    def __getattr__(self, name: str) -> object:
        return getattr(get_settings(), name)

    def __repr__(self) -> str:
        return repr(get_settings())


settings: Settings = _SettingsProxy()  # type: ignore[assignment]
