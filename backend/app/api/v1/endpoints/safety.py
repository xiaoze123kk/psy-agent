from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/safety", tags=["safety"])


class CrisisEventRequest(BaseModel):
    thread_id: str
    message_id: str | None = None
    risk_level: str
    detected_signals: list[str] = []
    action_taken: list[str] = []


@router.get("/resources")
async def safety_resources(region: str = "CN", audience: str = "all") -> dict[str, object]:
    return {
        "region": region,
        "audience": audience,
        "items": [
            {
                "resource_type": "trusted_adult",
                "title": "Contact a trusted adult",
                "description": "Reach out to someone you trust right now.",
            }
        ],
    }


@router.post("/crisis-events")
async def create_crisis_event(payload: CrisisEventRequest) -> dict[str, str]:
    return {
        "event_id": "demo-crisis-event",
        "thread_id": payload.thread_id,
        "status": "recorded",
    }
