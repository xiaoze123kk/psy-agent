from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    threads: Mapped[list["ConversationThread"]] = relationship(back_populates="user")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(80))
    age_range: Mapped[str] = mapped_column(String(32))
    user_mode: Mapped[str] = mapped_column(String(16))
    usage_goals: Mapped[list[str]] = mapped_column(JSON, default=list)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    memory_mode: Mapped[str] = mapped_column(String(24), default="summary_only")
    companion_style: Mapped[str] = mapped_column(String(32), default="gentle")
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    save_voice_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    save_transcript: Mapped[bool] = mapped_column(Boolean, default=True)
    crisis_resource_region: Mapped[str] = mapped_column(String(12), default="CN")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="settings")


class ConversationThread(Base):
    __tablename__ = "conversation_threads"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    langgraph_thread_id: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="companion")
    last_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_risk_level: Mapped[str] = mapped_column(String(8), default="L0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="threads")
    messages: Mapped[list["Message"]] = relationship(back_populates="thread")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    thread_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    input_type: Mapped[str] = mapped_column(String(16), default="text")
    risk_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    thread: Mapped[ConversationThread] = relationship(back_populates="messages")


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    structured_value: Mapped[dict] = mapped_column(JSON, default=dict)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.500)
    source_thread_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_threads.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_message_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    visibility: Mapped[str] = mapped_column(String(24), default="user_visible")
    status: Mapped[str] = mapped_column(String(24), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MoodLog(Base):
    __tablename__ = "mood_logs"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mood_score: Mapped[int] = mapped_column(Integer)
    anxiety_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="checkin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(32), index=True)
    audience: Mapped[str] = mapped_column(String(16), default="all", index=True)
    summary_30s: Mapped[str] = mapped_column(Text)
    explanation_3min: Mapped[str] = mapped_column(Text)
    advanced_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_misunderstandings: Mapped[list[str]] = mapped_column(JSON, default=list)
    actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    seek_help_when: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        index=True,
    )
    message_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    risk_level: Mapped[str] = mapped_column(String(8))
    trigger_text: Mapped[str] = mapped_column(Text)
    safety_action_taken: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TestAttempt(Base):
    __tablename__ = "test_attempts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[str] = mapped_column(String(64))
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="in_progress")
    result_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TestHistory(Base):
    __tablename__ = "test_history"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    attempt_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("test_attempts.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[str] = mapped_column(String(64))
    test_title: Mapped[str] = mapped_column(String(160))
    result_code: Mapped[str] = mapped_column(String(32))
    result_label: Mapped[str] = mapped_column(String(80))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
