from __future__ import annotations

from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_auth_runtime_columns_are_covered_by_sql_migrations() -> None:
    migration_sql = "\n".join(path.read_text(encoding="utf-8").lower() for path in sorted(MIGRATIONS_DIR.glob("*.sql")))

    for column_name in (
        "token_version",
        "auto_login",
        "security_question",
        "security_answer_hash",
    ):
        assert column_name in migration_sql
