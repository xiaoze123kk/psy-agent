"""一次性数据迁移脚本：给已有用户设置默认密保问题。

在密码重置功能上线前已经注册的旧用户没有密保问题，
运行此脚本可为它们填充默认值。

用法（当前分支开发中）：
    cd backend && python scripts/backfill_security_questions.py

合并到主分支后删除此文件。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.security import hash_password
from app.db.models import UserProfile
from app.db.session import SessionLocal, init_db

DEFAULT_QUESTION = "输入123"
DEFAULT_ANSWER = "123"


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        profiles = db.scalars(select(UserProfile)).all()
        updated = 0
        skipped = 0

        for profile in profiles:
            if profile.security_question and profile.security_answer_hash:
                skipped += 1
                continue

            if not profile.security_question:
                profile.security_question = DEFAULT_QUESTION
            if not profile.security_answer_hash:
                profile.security_answer_hash = hash_password(DEFAULT_ANSWER)
            updated += 1

        db.commit()
        print(f"已完成：{updated} 个用户设置了密保，{skipped} 个用户已存在密保（跳过）。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
