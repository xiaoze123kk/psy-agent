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
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_chat_model: str
    deepseek_knowledge_model: str
    deepseek_timeout_seconds: float
    knowledge_llm_answers_enabled: bool


def _default_database_url() -> str:
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def load_settings() -> Settings:
    return Settings(
        app_title=os.getenv("APP_TITLE", "Counseling Agent API"),
        database_url=os.getenv("DATABASE_URL", _default_database_url()),
        secret_key=os.getenv("APP_SECRET_KEY", "dev-only-change-me"),
        access_token_ttl_seconds=int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "86400")),
        refresh_token_ttl_seconds=int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000")),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        deepseek_chat_model=os.getenv("DEEPSEEK_CHAT_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")),
        deepseek_knowledge_model=os.getenv(
            "DEEPSEEK_KNOWLEDGE_MODEL",
            os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        ),
        deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20")),
        knowledge_llm_answers_enabled=os.getenv("KNOWLEDGE_LLM_ANSWERS_ENABLED", "0").lower()
        in {"1", "true", "yes", "on"},
    )


settings = load_settings()
