from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "app.db"
DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    app_title: str
    database_url: str
    secret_key: str
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int


def _default_database_url() -> str:
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def load_settings() -> Settings:
    return Settings(
        app_title=os.getenv("APP_TITLE", "Counseling Agent API"),
        database_url=os.getenv("DATABASE_URL", _default_database_url()),
        secret_key=os.getenv("APP_SECRET_KEY", "dev-only-change-me"),
        access_token_ttl_seconds=int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "86400")),
        refresh_token_ttl_seconds=int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000")),
    )


settings = load_settings()
