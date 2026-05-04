from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import Base


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_knowledge_beta_compat_migrations()
    if engine.dialect.name == "sqlite":
        _apply_sqlite_compat_migrations()


def _apply_knowledge_beta_compat_migrations() -> None:
    """Keep existing dev databases compatible with the Beta knowledge schema."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "knowledge_articles" not in inspector.get_table_names():
            return

        article_columns = {column["name"] for column in inspector.get_columns("knowledge_articles")}
        is_sqlite = engine.dialect.name == "sqlite"
        uuid_type = "VARCHAR(36)" if is_sqlite else "UUID"
        timestamp_type = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"

        additions = {
            "source_id": f"{uuid_type}",
            "review_status": "VARCHAR(24) NOT NULL DEFAULT 'published'",
            "license": "VARCHAR(120)",
            "source_url": "TEXT",
            "reviewer_note": "TEXT",
            "published_at": timestamp_type,
        }
        for column_name, column_type in additions.items():
            if column_name not in article_columns:
                connection.execute(text(f"ALTER TABLE knowledge_articles ADD COLUMN {column_name} {column_type}"))

        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_knowledge_articles_source_id ON knowledge_articles (source_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_knowledge_articles_review_status ON knowledge_articles (review_status)"))

        if engine.dialect.name == "postgresql" and "knowledge_gaps" in inspector.get_table_names():
            gap_columns = {column["name"]: column for column in inspector.get_columns("knowledge_gaps")}
            thread_column = gap_columns.get("thread_id")
            if thread_column is not None and str(thread_column["type"]).upper() == "UUID":
                connection.execute(text("ALTER TABLE knowledge_gaps ALTER COLUMN thread_id TYPE VARCHAR(128) USING thread_id::text"))


def _apply_sqlite_compat_migrations() -> None:
    """Keep local SQLite dev databases compatible with SQL-first migrations."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "users" not in inspector.get_table_names():
            return

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "username" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(40)"))
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET username = 'user_' || substr(replace(id, '-', ''), 1, 8)
                    WHERE username IS NULL OR username = ''
                    """
                )
            )
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))

        if "user_settings" in inspector.get_table_names():
            settings_columns = {column["name"] for column in inspector.get_columns("user_settings")}
            if "save_transcript" not in settings_columns:
                connection.execute(text("ALTER TABLE user_settings ADD COLUMN save_transcript BOOLEAN NOT NULL DEFAULT 1"))

        if "privacy_action_logs" in inspector.get_table_names():
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_privacy_action_logs_user_created_at
                    ON privacy_action_logs (user_id, created_at DESC)
                    """
                )
            )


def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
