from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
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
