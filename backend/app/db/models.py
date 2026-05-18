from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid
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
    companion_styles: Mapped[list["CompanionStyle"]] = relationship(back_populates="user", cascade="all, delete-orphan")


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
    companion_style: Mapped[str] = mapped_column(Text, default="")
    crisis_resource_region: Mapped[str] = mapped_column(String(12), default="CN")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="settings")


class CompanionStyle(Base):
    __tablename__ = "companion_styles"
    __table_args__ = (
        Index("idx_companion_styles_user_updated_at", "user_id", "updated_at"),
        Index("idx_companion_styles_user_default", "user_id", "is_default"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    definition: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="companion_styles")


class ConversationThread(Base):
    __tablename__ = "conversation_threads"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    langgraph_thread_id: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="companion")
    last_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_digest: Mapped[dict] = mapped_column(JSON, default=dict)
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


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", "client_message_id", name="uq_conversation_turns_client_message"),
        Index("idx_conversation_turns_thread_created", "thread_id", "created_at"),
        Index("idx_conversation_turns_status_updated", "turn_status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        index=True,
    )
    client_message_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    turn_status: Mapped[str] = mapped_column(String(16), default="running")
    delivery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    user_message_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    response_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConversationTurnTrace(Base):
    __tablename__ = "conversation_turn_traces"
    __table_args__ = (
        UniqueConstraint("turn_id", "sequence", name="uq_conversation_turn_traces_turn_sequence"),
        Index("idx_conversation_turn_traces_turn", "turn_id"),
        Index("idx_conversation_turn_traces_thread_created", "thread_id", "created_at"),
        Index("idx_conversation_turn_traces_node_status", "node_name", "status"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    turn_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    trace_type: Mapped[str] = mapped_column(String(32), default="graph_node")
    node_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), default="completed")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PendingMemoryJob(Base):
    __tablename__ = "pending_memory_jobs"
    __table_args__ = (
        UniqueConstraint("turn_id", "job_type", name="uq_pending_memory_jobs_turn_type"),
        Index("idx_pending_memory_jobs_status_next_run", "status", "next_run_at"),
        Index("idx_pending_memory_jobs_turn", "turn_id"),
        Index("idx_pending_memory_jobs_thread_created", "thread_id", "created_at"),
        Index("idx_pending_memory_jobs_assistant_message", "assistant_message_id"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        index=True,
    )
    turn_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        index=True,
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(32), default="memory_write")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserMemory(Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        Index("idx_user_memories_user_type_status", "user_id", "memory_type", "status"),
        Index("idx_user_memories_user_review", "user_id", "review_state"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    structured_value: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
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
    source: Mapped[str] = mapped_column(String(32), default="chat")
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("user_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_state: Mapped[str] = mapped_column(String(24), default="normal")
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"
    __table_args__ = (
        Index("idx_memory_embeddings_user_memory", "user_id", "memory_id"),
        Index("idx_memory_embeddings_key", "embedding_key"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    memory_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("user_memories.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    embedding_model: Mapped[str] = mapped_column(String(80))
    embedding_key: Mapped[str] = mapped_column(String(256), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MemoryOperation(Base):
    __tablename__ = "memory_operations"
    __table_args__ = (
        Index("idx_memory_operations_user_created_at", "user_id", "created_at"),
        Index("idx_memory_operations_memory_created_at", "memory_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("user_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32))
    before_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(32), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryConsolidationRun(Base):
    __tablename__ = "memory_consolidation_runs"
    __table_args__ = (
        Index("idx_memory_consolidation_runs_user_started", "user_id", "started_at"),
        Index("idx_memory_consolidation_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    trigger: Mapped[str] = mapped_column(String(24), default="manual")
    sessions_reviewed: Mapped[int] = mapped_column(Integer, default=0)
    memories_touched: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    source_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("knowledge_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    review_status: Mapped[str] = mapped_column(String(24), default="published", index=True)
    license: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source: Mapped["KnowledgeSource | None"] = relationship(back_populates="articles")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="article", cascade="all, delete-orphan")


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    source_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    is_commercial_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    articles: Mapped[list[KnowledgeArticle]] = relationship(back_populates="source")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("article_id", "chunk_index", name="uq_knowledge_chunks_article_index"),
        Index("idx_knowledge_chunks_status_updated", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    article_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("knowledge_articles.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(180))
    content: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    article: Mapped[KnowledgeArticle] = relationship(back_populates="chunks")


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str] = mapped_column(Text, index=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    audience: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    coverage_status: Mapped[str] = mapped_column(String(24), default="insufficient")
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    top_score: Mapped[int] = mapped_column(Integer, default=0)
    source_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=1)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_article_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("knowledge_articles.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CounselingCorpusSource(Base):
    __tablename__ = "counseling_corpus_sources"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    source_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    is_commercial_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chunks: Mapped[list["CounselingExampleChunk"]] = relationship(back_populates="source")


class CounselingExampleChunk(Base):
    __tablename__ = "counseling_example_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", "chunk_index", name="uq_counseling_examples_source_external_chunk"),
        Index("idx_counseling_examples_mode_status", "mode", "status"),
        Index("idx_counseling_examples_topic_status", "topic", "status"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("counseling_corpus_sources.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(160), default="")
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(24), default="counseling", index=True)
    topic: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    user_text: Mapped[str] = mapped_column(Text)
    assistant_text: Mapped[str] = mapped_column(Text)
    context_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source: Mapped[CounselingCorpusSource] = relationship(back_populates="chunks")


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


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(30))  # assistant_message / knowledge_answer / test_result
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rating: Mapped[int] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrivacyActionLog(Base):
    __tablename__ = "privacy_action_logs"
    __table_args__ = (
        Index("idx_privacy_action_logs_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(32))
    affected_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
