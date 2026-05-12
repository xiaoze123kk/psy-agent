from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User, UserMemory, utcnow
from app.db.session import get_db_session
from app.schemas.memory import (
    MemoryAuditItem,
    MemoryAuditResponse,
    MemoryConsolidationResponse,
    MemoryFeedbackRequest,
    ListMemoriesResponse,
    MemoryItemResponse,
    MemoryMutationResponse,
    SearchMemoriesRequest,
    SearchMemoriesResponse,
    StatusResponse,
    UpdateMemoryRequest,
)
from app.services.memory_service import (
    MEMORY_TYPE_LABELS,
    MEMORY_TYPE_ORDER,
    consolidate_user_memories,
    count_memory_operations,
    list_memory_operations,
    log_memory_operation,
    record_memory_feedback,
    remove_memory_vectors,
    retrieve_memories_for_turn_async,
)


router = APIRouter(prefix="/memories", tags=["memory"])


def format_doc_datetime(value: datetime) -> str:
    display_value = value.astimezone() if value.tzinfo else value
    return display_value.strftime("%Y-%m-%d %H:%M")


def format_markdown_bullet(content: str) -> list[str]:
    normalized = content.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not normalized:
        normalized = "(空)"
    lines = normalized.split("\n")
    output = [f"- {lines[0]}"]
    output.extend([f"  {line}" for line in lines[1:]])
    return output


def build_memory_document(memories: list[UserMemory]) -> str:
    lines = ["# 记忆文档", "", f"生成时间：{format_doc_datetime(utcnow())}", ""]
    if not memories:
        lines.append("当前没有可见记忆。")
        return "\n".join(lines).rstrip() + "\n"

    grouped: dict[str, list[UserMemory]] = {}
    for memory in memories:
        grouped.setdefault(memory.memory_type, []).append(memory)

    known_types = [memory_type for memory_type in MEMORY_TYPE_ORDER if memory_type in grouped]
    unknown_types = sorted(memory_type for memory_type in grouped.keys() if memory_type not in MEMORY_TYPE_ORDER)

    for memory_type in [*known_types, *unknown_types]:
        lines.append(f"## {MEMORY_TYPE_LABELS.get(memory_type, '记忆')}")
        items = sorted(grouped[memory_type], key=lambda item: item.updated_at or item.created_at, reverse=True)
        for memory in items:
            lines.extend(format_markdown_bullet(memory.content))
            lines.append(f"  - 更新时间：{format_doc_datetime(memory.updated_at or memory.created_at)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@router.get("", response_model=ListMemoriesResponse)
async def list_memories(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ListMemoriesResponse:
    memory_filters = (
        UserMemory.user_id == current_user.id,
        UserMemory.status == "active",
        UserMemory.visibility == "user_visible",
    )
    total = int(db.scalar(select(func.count(UserMemory.id)).where(*memory_filters)) or 0)
    memories = list(
        db.scalars(
            select(UserMemory)
            .where(*memory_filters)
            .order_by(desc(UserMemory.updated_at))
            .limit(limit)
            .offset(offset)
        )
    )
    return ListMemoriesResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            MemoryItemResponse(
                memory_id=memory.id,
                memory_type=memory.memory_type,
                content=memory.content,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                title=memory.title,
                summary=memory.summary,
                tags=list(memory.tags or []),
                importance=memory.importance,
                confidence=float(memory.confidence or 0),
                review_state=memory.review_state,
                last_accessed_at=memory.last_accessed_at,
                access_count=memory.access_count or 0,
            )
            for memory in memories
        ]
    )


@router.post("/search", response_model=SearchMemoriesResponse)
async def search_memories(
    payload: SearchMemoriesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SearchMemoriesResponse:
    memory_mode = getattr(current_user.settings, "memory_mode", "summary_only") if current_user.settings else "summary_only"
    items = await retrieve_memories_for_turn_async(
        db,
        user_id=current_user.id,
        query=payload.query,
        memory_mode=memory_mode,
        risk_level=payload.risk_level,
        control_category=payload.control_category,
        limit=payload.limit,
        record_access=True,
    )
    db.commit()
    return SearchMemoriesResponse(items=[{**item, "memory_id": item["id"]} for item in items])


@router.get("/audit", response_model=MemoryAuditResponse)
async def memory_audit(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MemoryAuditResponse:
    total = count_memory_operations(db, user_id=current_user.id)
    operations = list_memory_operations(db, user_id=current_user.id, limit=limit, offset=offset)
    return MemoryAuditResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            MemoryAuditItem(
                operation_id=operation.id,
                memory_id=operation.memory_id,
                action=operation.action,
                reason=operation.reason,
                actor=operation.actor,
                before_value=operation.before_value,
                after_value=operation.after_value,
                created_at=operation.created_at,
            )
            for operation in operations
        ]
    )


@router.post("/consolidate", response_model=MemoryConsolidationResponse)
async def consolidate_memories(
    force: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MemoryConsolidationResponse:
    result = consolidate_user_memories(db, user_id=current_user.id, trigger="manual", force=force)
    db.commit()
    return MemoryConsolidationResponse(**result)


@router.post("/{memory_id}/feedback", response_model=MemoryMutationResponse)
async def feedback_memory(
    memory_id: str,
    payload: MemoryFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MemoryMutationResponse:
    memory = record_memory_feedback(
        db,
        user_id=current_user.id,
        memory_id=memory_id,
        feedback=payload.feedback,
        note=payload.note,
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    db.commit()
    return MemoryMutationResponse(memory_id=memory.id, content=memory.content, status=memory.status)


@router.patch("/{memory_id}", response_model=MemoryMutationResponse)
async def update_memory(
    memory_id: str,
    payload: UpdateMemoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MemoryMutationResponse:
    memory = db.scalar(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == current_user.id,
            UserMemory.status == "active",
            UserMemory.visibility == "user_visible",
        )
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")

    before_value = {
        "content": memory.content,
        "title": memory.title,
        "tags": list(memory.tags or []),
        "review_state": memory.review_state,
    }
    memory.content = payload.content
    if payload.title is not None:
        memory.title = payload.title
    if payload.tags is not None:
        memory.tags = payload.tags
    memory.summary = payload.content[:180]
    memory.review_state = "user_edited"
    memory.version = int(memory.version or 1) + 1
    memory.updated_at = utcnow()
    log_memory_operation(
        db,
        user_id=current_user.id,
        memory_id=memory.id,
        action="user_edit",
        before_value=before_value,
        after_value={
            "content": memory.content,
            "title": memory.title,
            "tags": list(memory.tags or []),
            "review_state": memory.review_state,
        },
        actor="user",
    )
    db.commit()
    db.refresh(memory)
    return MemoryMutationResponse(memory_id=memory.id, content=memory.content, status="updated")


@router.delete("/{memory_id}", response_model=MemoryMutationResponse)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MemoryMutationResponse:
    memory = db.scalar(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == current_user.id,
            UserMemory.status == "active",
            UserMemory.visibility == "user_visible",
        )
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")

    before_value = {"content": memory.content, "status": memory.status}
    memory.status = "deleted"
    memory.updated_at = utcnow()
    log_memory_operation(
        db,
        user_id=current_user.id,
        memory_id=memory.id,
        action="delete",
        before_value=before_value,
        after_value={"content": memory.content, "status": memory.status},
        actor="user",
    )
    remove_memory_vectors([memory.id])
    db.commit()
    return MemoryMutationResponse(memory_id=memory.id, status="deleted")


@router.delete("", response_model=StatusResponse)
async def clear_memories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StatusResponse:
    memory_ids = list(
        db.scalars(
            select(UserMemory.id).where(
                UserMemory.user_id == current_user.id,
                UserMemory.status == "active",
                UserMemory.visibility == "user_visible",
            )
        )
    )
    rows = db.execute(
        update(UserMemory)
        .where(UserMemory.id.in_(memory_ids))
        .values(status="deleted", updated_at=utcnow())
    )
    remove_memory_vectors(memory_ids)
    log_memory_operation(
        db,
        user_id=current_user.id,
        memory_id=None,
        action="delete",
        after_value={"deleted_count": int(rows.rowcount or 0)},
        reason="clear_visible_memories",
        actor="user",
    )
    db.commit()
    return StatusResponse(status="cleared")


@router.get("/document")
async def export_memory_document(
    download: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Response:
    memories = list(
        db.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == current_user.id,
                UserMemory.status == "active",
                UserMemory.visibility == "user_visible",
            )
            .order_by(desc(UserMemory.updated_at))
        )
    )
    content = build_memory_document(memories)
    headers = {}
    if download:
        filename = f"memories-{utcnow().strftime('%Y%m%d')}.md"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=content, media_type="text/markdown; charset=utf-8", headers=headers)
