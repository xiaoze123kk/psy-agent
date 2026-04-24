import json
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.chat import SendMessageRequest, StartThreadRequest
from app.services.graph_runtime import GraphRuntime

router = APIRouter(prefix="/chat", tags=["chat"])
graph_runtime = GraphRuntime()


def format_sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/threads")
async def create_thread(payload: StartThreadRequest) -> dict[str, str]:
    thread_id = str(uuid4())
    return {
        "thread_id": thread_id,
        "langgraph_thread_id": f"lg-{thread_id}",
        "mode": payload.mode,
        "title": payload.title or "new session",
    }


@router.post("/threads/{thread_id}/messages")
async def send_message(thread_id: str, payload: SendMessageRequest) -> dict[str, object]:
    assistant_message = await graph_runtime.invoke_turn(
        thread_id=thread_id,
        user_id=payload.user_id,
        content=payload.content,
        input_type=payload.input_type,
        user_mode=payload.user_mode,
    )
    return {
        "thread_id": thread_id,
        "assistant_message": assistant_message,
    }


@router.post("/threads/{thread_id}/stream")
async def stream_message(thread_id: str, payload: SendMessageRequest) -> StreamingResponse:
    async def event_generator():
        result = await graph_runtime.invoke_turn(
            thread_id=thread_id,
            user_id=payload.user_id,
            content=payload.content,
            input_type=payload.input_type,
            user_mode=payload.user_mode,
        )
        yield format_sse_event(
            "graph_update",
            {
                "node": "risk_classifier",
                "risk_level": result["risk_level"],
            },
        )
        for token in result["assistant_text"].split(" "):
            if token:
                yield format_sse_event("token", {"text": token + " "})
        yield format_sse_event("final", result)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
