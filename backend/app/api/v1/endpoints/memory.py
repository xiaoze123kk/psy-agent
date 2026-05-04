from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User, UserMemory, utcnow
from app.db.session import get_db_session
from app.schemas.memory import (
    ListMemoriesResponse,
    MemoryItemResponse,
    MemoryMutationResponse,
    StatusResponse,
    UpdateMemoryRequest,
)


router = APIRouter(prefix="/memories", tags=["memory"])

MEMORY_TYPE_LABELS = {
    "session_summary": "对话摘要",
    "preference": "陪伴偏好",
    "recurring_trigger": "触发点",
    "support_strategy": "支持方式",
    "state": "长期状态",
    "relationship": "关系记忆",
    "safety_summary": "安全摘要",
}

MEMORY_TYPE_ORDER = [
    "session_summary",
    "preference",
    "recurring_trigger",
    "support_strategy",
    "state",
    "relationship",
    "safety_summary",
]


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ListMemoriesResponse:
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
    return ListMemoriesResponse(
        items=[
            MemoryItemResponse(
                memory_id=memory.id,
                memory_type=memory.memory_type,
                content=memory.content,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
            )
            for memory in memories
        ]
    )


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

    memory.content = payload.content
    memory.updated_at = utcnow()
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

    memory.status = "deleted"
    memory.updated_at = utcnow()
    db.commit()
    return MemoryMutationResponse(memory_id=memory.id, status="deleted")


@router.delete("", response_model=StatusResponse)
async def clear_memories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StatusResponse:
    db.execute(
        update(UserMemory)
        .where(
            UserMemory.user_id == current_user.id,
            UserMemory.status == "active",
            UserMemory.visibility == "user_visible",
        )
        .values(status="deleted", updated_at=utcnow())
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
