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
    _apply_user_settings_style_compat_migrations()
    _apply_companion_styles_compat_migrations()
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


def _apply_user_settings_style_compat_migrations() -> None:
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "user_settings" not in inspector.get_table_names():
            return

        settings_columns = {column["name"] for column in inspector.get_columns("user_settings")}
        if "companion_style" not in settings_columns:
            return

        if engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE user_settings ALTER COLUMN companion_style TYPE TEXT"))
            connection.execute(text("ALTER TABLE user_settings ALTER COLUMN companion_style SET DEFAULT ''"))

        connection.execute(
            text(
                """
                UPDATE user_settings
                SET companion_style = ''
                WHERE companion_style IS NULL
                   OR companion_style IN ('gentle', 'rational', 'reflective', 'action')
                """
            )
        )


def _apply_companion_styles_compat_migrations() -> None:
    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        if "user_settings" not in table_names or "companion_styles" not in table_names:
            return

        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    """
                    INSERT INTO companion_styles (
                        id,
                        user_id,
                        title,
                        definition,
                        is_default,
                        sort_order,
                        created_at,
                        updated_at
                    )
                    SELECT
                        gen_random_uuid(),
                        user_settings.user_id,
                        '当前风格',
                        LEFT(BTRIM(user_settings.companion_style), 500),
                        TRUE,
                        0,
                        NOW(),
                        NOW()
                    FROM user_settings
                    WHERE user_settings.companion_style IS NOT NULL
                      AND BTRIM(user_settings.companion_style) <> ''
                      AND user_settings.companion_style NOT IN ('gentle', 'rational', 'reflective', 'action')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM companion_styles
                          WHERE companion_styles.user_id = user_settings.user_id
                      )
                    """
                )
            )
            return

        if engine.dialect.name == "sqlite":
            connection.execute(
                text(
                    """
                    INSERT INTO companion_styles (
                        id,
                        user_id,
                        title,
                        definition,
                        is_default,
                        sort_order,
                        created_at,
                        updated_at
                    )
                    SELECT
                        lower(hex(randomblob(16))),
                        user_settings.user_id,
                        '当前风格',
                        substr(trim(user_settings.companion_style), 1, 500),
                        1,
                        0,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    FROM user_settings
                    WHERE user_settings.companion_style IS NOT NULL
                      AND trim(user_settings.companion_style) <> ''
                      AND user_settings.companion_style NOT IN ('gentle', 'rational', 'reflective', 'action')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM companion_styles
                          WHERE companion_styles.user_id = user_settings.user_id
                      )
                    """
                )
            )


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
