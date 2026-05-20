from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "app.db"
DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_env_files() -> None:
    external_env_keys = set(os.environ.keys())

    for env_path in (BASE_DIR / ".env", BASE_DIR / ".env.local"):
        if not env_path.exists():
            continue

        allow_override = env_path.name == ".env.local"
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")

            # Keep externally injected env vars as highest priority.
            if key in external_env_keys:
                continue

            if allow_override:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


_load_env_files()


@dataclass(frozen=True)
class Settings:
    app_title: str
    database_url: str
    secret_key: str
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    cookie_secure: bool
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_chat_model: str
    deepseek_knowledge_model: str
    deepseek_timeout_seconds: float
    deepseek_chat_temperature: float
    deepseek_chat_max_tokens: int
    deepseek_knowledge_temperature: float
    deepseek_knowledge_max_tokens: int
    deepseek_thinking_enabled: bool
    risk_semantic_llm_enabled: bool
    risk_semantic_llm_timeout_seconds: float
    chat_turn_timeout_seconds: float
    rag_retrieval_timeout_seconds: float
    memory_background_worker_enabled: bool
    memory_job_batch_size: int
    memory_job_max_attempts: int
    memory_job_poll_interval_seconds: float
    knowledge_llm_answers_enabled: bool
    knowledge_warm_index_on_startup: bool
    counseling_rag_enabled: bool
    milvus_enabled: bool
    milvus_uri: str
    milvus_token: str | None
    milvus_db_name: str
    milvus_collection_prefix: str
    milvus_connect_timeout_seconds: float
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_index_version: str
    local_embedding_device: str
    local_embedding_batch_size: int
    local_embedding_max_length: int
    local_embedding_query_max_length: int
    local_embedding_document_max_length: int
    local_embedding_use_fp16: str
    local_embedding_cache_dir: str | None
    local_embedding_warm_on_startup: bool
    dashscope_api_key: str | None
    dashscope_base_url: str
    embedding_timeout_seconds: float
    embedding_query_cache_size: int
    counseling_rerank_enabled: bool
    counseling_rerank_model: str
    counseling_recall_top_n: int
    counseling_rerank_top_n: int
    counseling_rerank_batch_size: int
    counseling_rerank_max_length: int
    counseling_rerank_timeout_seconds: float


def _default_database_url() -> str:
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def load_settings() -> Settings:
    return Settings(
        app_title=os.getenv("APP_TITLE", "Counseling Agent API"),
        database_url=os.getenv("DATABASE_URL", _default_database_url()),
        secret_key=os.getenv("APP_SECRET_KEY", "dev-only-change-me"),
        access_token_ttl_seconds=int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900")),
        refresh_token_ttl_seconds=int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000")),
        cookie_secure=os.getenv("COOKIE_SECURE", "0").lower() in {"1", "true", "yes", "on"},
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        deepseek_chat_model=os.getenv("DEEPSEEK_CHAT_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")),
        deepseek_knowledge_model=os.getenv(
            "DEEPSEEK_KNOWLEDGE_MODEL",
            os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        ),
        deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20")),
        deepseek_chat_temperature=float(os.getenv("DEEPSEEK_CHAT_TEMPERATURE", "0.75")),
        deepseek_chat_max_tokens=int(os.getenv("DEEPSEEK_CHAT_MAX_TOKENS", "420")),
        deepseek_knowledge_temperature=float(os.getenv("DEEPSEEK_KNOWLEDGE_TEMPERATURE", "0.3")),
        deepseek_knowledge_max_tokens=int(os.getenv("DEEPSEEK_KNOWLEDGE_MAX_TOKENS", "760")),
        deepseek_thinking_enabled=os.getenv("DEEPSEEK_THINKING_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"},
        risk_semantic_llm_enabled=os.getenv("RISK_SEMANTIC_LLM_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"},
        risk_semantic_llm_timeout_seconds=float(os.getenv("RISK_SEMANTIC_LLM_TIMEOUT_SECONDS", "1.5")),
        chat_turn_timeout_seconds=float(os.getenv("CHAT_TURN_TIMEOUT_SECONDS", "120")),
        rag_retrieval_timeout_seconds=float(os.getenv("RAG_RETRIEVAL_TIMEOUT_SECONDS", "60")),
        memory_background_worker_enabled=os.getenv("MEMORY_BACKGROUND_WORKER_ENABLED", "1").lower()
        in {"1", "true", "yes", "on"},
        memory_job_batch_size=int(os.getenv("MEMORY_JOB_BATCH_SIZE", "5")),
        memory_job_max_attempts=int(os.getenv("MEMORY_JOB_MAX_ATTEMPTS", "3")),
        memory_job_poll_interval_seconds=float(os.getenv("MEMORY_JOB_POLL_INTERVAL_SECONDS", "2")),
        knowledge_llm_answers_enabled=os.getenv("KNOWLEDGE_LLM_ANSWERS_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"},
        knowledge_warm_index_on_startup=os.getenv("KNOWLEDGE_WARM_INDEX_ON_STARTUP", "0").lower()
        in {"1", "true", "yes", "on"},
        counseling_rag_enabled=os.getenv("COUNSELING_RAG_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
        milvus_enabled=os.getenv("MILVUS_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
        milvus_uri=os.getenv("MILVUS_URI", "http://localhost:19530"),
        milvus_token=os.getenv("MILVUS_TOKEN") or None,
        milvus_db_name=os.getenv("MILVUS_DB_NAME", "default"),
        milvus_collection_prefix=os.getenv("MILVUS_COLLECTION_PREFIX", "psych_agent"),
        milvus_connect_timeout_seconds=float(os.getenv("MILVUS_CONNECT_TIMEOUT_SECONDS", "1.5")),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "local"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1024")),
        embedding_index_version=os.getenv("EMBEDDING_INDEX_VERSION", "").strip(),
        local_embedding_device=os.getenv("LOCAL_EMBEDDING_DEVICE", "auto"),
        local_embedding_batch_size=int(os.getenv("LOCAL_EMBEDDING_BATCH_SIZE", "8")),
        local_embedding_max_length=int(os.getenv("LOCAL_EMBEDDING_MAX_LENGTH", "1024")),
        local_embedding_query_max_length=int(
            os.getenv("LOCAL_EMBEDDING_QUERY_MAX_LENGTH", os.getenv("LOCAL_EMBEDDING_MAX_LENGTH", "512"))
        ),
        local_embedding_document_max_length=int(
            os.getenv("LOCAL_EMBEDDING_DOCUMENT_MAX_LENGTH", os.getenv("LOCAL_EMBEDDING_MAX_LENGTH", "2048"))
        ),
        local_embedding_use_fp16=os.getenv("LOCAL_EMBEDDING_USE_FP16", "auto"),
        local_embedding_cache_dir=os.getenv("LOCAL_EMBEDDING_CACHE_DIR") or None,
        local_embedding_warm_on_startup=os.getenv("LOCAL_EMBEDDING_WARM_ON_STARTUP", "0").lower()
        in {"1", "true", "yes", "on"},
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY") or None,
        dashscope_base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30")),
        embedding_query_cache_size=int(os.getenv("EMBEDDING_QUERY_CACHE_SIZE", "128")),
        counseling_rerank_enabled=os.getenv("COUNSELING_RERANK_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"},
        counseling_rerank_model=os.getenv("COUNSELING_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
        counseling_recall_top_n=int(os.getenv("COUNSELING_RECALL_TOP_N", "40")),
        counseling_rerank_top_n=int(os.getenv("COUNSELING_RERANK_TOP_N", "12")),
        counseling_rerank_batch_size=int(os.getenv("COUNSELING_RERANK_BATCH_SIZE", "8")),
        counseling_rerank_max_length=int(os.getenv("COUNSELING_RERANK_MAX_LENGTH", "1024")),
        counseling_rerank_timeout_seconds=float(os.getenv("COUNSELING_RERANK_TIMEOUT_SECONDS", "20")),
    )


settings = load_settings()
