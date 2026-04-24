from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/moods", tags=["mood"])


class MoodLogRequest(BaseModel):
    mood_score: int = Field(ge=1, le=5)
    anxiety_score: int | None = Field(default=None, ge=1, le=5)
    energy_score: int | None = Field(default=None, ge=1, le=5)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    mood_tags: list[str] = []
    note: str | None = None


@router.post("")
async def create_mood_log(payload: MoodLogRequest) -> dict[str, object]:
    return {
        "log_id": "demo-log-id",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "mood_score": payload.mood_score,
    }


@router.get("/trends")
async def get_mood_trend(range: str = "7d") -> dict[str, object]:
    return {
        "range": range,
        "avg_mood_score": 3.2,
        "top_tags": ["anxious", "tired"],
        "daily": [],
        "summary": "Trend endpoint scaffold.",
    }
