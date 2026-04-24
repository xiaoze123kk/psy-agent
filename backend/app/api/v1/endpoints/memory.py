from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/memories", tags=["memory"])


class UpdateMemoryRequest(BaseModel):
    content: str


@router.get("")
async def list_memories() -> dict[str, list[dict[str, str]]]:
    return {
        "items": [
            {
                "memory_id": "demo-memory-1",
                "memory_type": "preference",
                "content": "Prefers gentle responses.",
            }
        ]
    }


@router.patch("/{memory_id}")
async def update_memory(memory_id: str, payload: UpdateMemoryRequest) -> dict[str, str]:
    return {
        "memory_id": memory_id,
        "content": payload.content,
        "status": "updated",
    }


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, str]:
    return {"memory_id": memory_id, "status": "deleted"}


@router.delete("")
async def clear_memories() -> dict[str, str]:
    return {"status": "cleared"}
