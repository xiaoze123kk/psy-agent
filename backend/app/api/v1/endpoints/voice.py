from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/sessions")
async def create_voice_session(thread_id: str) -> dict[str, str]:
    voice_session_id = "demo-voice-session"
    return {
        "voice_session_id": voice_session_id,
        "thread_id": thread_id,
        "ws_url": f"/api/v1/voice/sessions/{voice_session_id}/ws",
    }


@router.websocket("/sessions/{voice_session_id}/ws")
async def voice_session_ws(websocket: WebSocket, voice_session_id: str) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "session_ready", "voice_session_id": voice_session_id})
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "end_session":
                await websocket.send_json({"type": "session_ended", "voice_session_id": voice_session_id})
                await websocket.close()
                return
            await websocket.send_json({"type": "echo", "payload": message})
    except WebSocketDisconnect:
        return
