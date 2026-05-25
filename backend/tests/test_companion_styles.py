from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.api.v1.endpoints import me
from app.core.security import create_access_token
from app.db.models import Base, CompanionStyle, User, UserProfile, UserSettings
from app.db.session import get_db_session


class CompanionStyleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, class_=Session)
        self.db = self.SessionLocal()

        self.app = FastAPI()
        self.app.include_router(me.router, prefix="/api/v1")

        def override_db_session():
            yield self.db

        self.app.dependency_overrides[get_db_session] = override_db_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_user(self, username: str = "demo") -> User:
        user = User(username=username, password_hash="test-hash")
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserProfile(
                    user_id=user.id,
                    nickname=username,
                    age_range="18_plus",
                    user_mode="adult",
                    usage_goals=["heard"],
                    onboarding_completed=True,
                ),
                UserSettings(
                    user_id=user.id,
                    memory_mode="summary_only",
                    companion_style="",
                    crisis_resource_region="CN",
                ),
            ]
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def auth_headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def test_replace_companion_styles_persists_library_and_selected_definition(self) -> None:
        user = self.create_user("owner")

        response = self.client.put(
            "/api/v1/me/companion-styles",
            headers=self.auth_headers(user),
            json={
                "selected_style_id": "local-action",
                "items": [
                    {
                        "client_id": "local-calm",
                        "title": "Calm first",
                        "definition": "Respond gently before suggesting one tiny step.",
                    },
                    {
                        "client_id": "local-action",
                        "title": "Action next",
                        "definition": "Give a direct, practical next step after a brief reflection.",
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["items"]), 2)
        self.assertNotEqual(body["selected_style_id"], "default")
        self.assertEqual(body["companion_style"], "Give a direct, practical next step after a brief reflection.")

        self.db.refresh(user.settings)
        self.assertEqual(user.settings.companion_style, body["companion_style"])
        styles = list(self.db.scalars(select(CompanionStyle).where(CompanionStyle.user_id == user.id)))
        self.assertEqual(len(styles), 2)
        self.assertEqual(len([style for style in styles if style.is_default]), 1)

        get_response = self.client.get("/api/v1/me/companion-styles", headers=self.auth_headers(user))
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["selected_style_id"], body["selected_style_id"])

    def test_selecting_default_keeps_styles_but_clears_active_definition(self) -> None:
        user = self.create_user("owner")

        first_response = self.client.put(
            "/api/v1/me/companion-styles",
            headers=self.auth_headers(user),
            json={
                "selected_style_id": "local-calm",
                "items": [
                    {
                        "client_id": "local-calm",
                        "title": "Calm first",
                        "definition": "Keep the answer soft and short.",
                    }
                ],
            },
        )
        style_id = first_response.json()["items"][0]["style_id"]

        response = self.client.put(
            "/api/v1/me/companion-styles",
            headers=self.auth_headers(user),
            json={
                "selected_style_id": "default",
                "items": [
                    {
                        "style_id": style_id,
                        "client_id": style_id,
                        "title": "Calm first",
                        "definition": "Keep the answer soft and short.",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["selected_style_id"], "default")
        self.assertEqual(body["companion_style"], "")
        self.assertEqual(len(body["items"]), 1)
        self.assertFalse(body["items"][0]["is_default"])
        self.db.refresh(user.settings)
        self.assertEqual(user.settings.companion_style, "")

    def test_legacy_settings_patch_syncs_into_companion_style_library(self) -> None:
        user = self.create_user("owner")

        response = self.client.patch(
            "/api/v1/me/settings",
            headers=self.auth_headers(user),
            json={"companion_style": "Use fewer questions and offer one grounded next step."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["companion_style"], "Use fewer questions and offer one grounded next step.")

        library = self.client.get("/api/v1/me/companion-styles", headers=self.auth_headers(user)).json()
        self.assertEqual(len(library["items"]), 1)
        self.assertEqual(library["items"][0]["title"], "当前风格")
        self.assertTrue(library["items"][0]["is_default"])
        self.assertEqual(library["companion_style"], response.json()["companion_style"])


if __name__ == "__main__":
    unittest.main()
