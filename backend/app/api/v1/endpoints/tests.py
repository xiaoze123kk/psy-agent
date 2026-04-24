from fastapi import APIRouter

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("")
async def list_tests() -> dict[str, list[dict[str, object]]]:
    return {
        "items": [
            {
                "test_id": "demo-test-1",
                "code": "sixteen_type",
                "title": "16 type exploration",
                "estimated_minutes": 10,
            },
            {
                "test_id": "demo-test-2",
                "code": "anime_match",
                "title": "Anime personality match",
                "estimated_minutes": 5,
            },
        ]
    }


@router.post("/{test_id}/attempts")
async def start_attempt(test_id: str) -> dict[str, object]:
    return {
        "attempt_id": "demo-attempt",
        "test_id": test_id,
        "questions": [],
    }


@router.post("/attempts/{attempt_id}/complete")
async def complete_attempt(attempt_id: str) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "result_code": "INFJ_like",
        "result_title": "Insightful companion",
        "summary": "Scaffold result payload.",
    }
