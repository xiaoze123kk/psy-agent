from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import ConversationThread, RiskEvent, User, generate_uuid
from app.db.session import SessionLocal, get_db_session
from app.schemas.voice import VoiceSessionCreateRequest, VoiceSessionResponse
from app.services.graph_runtime import GraphRuntime
from app.services.voice_service import build_ws_url, create_voice_session, end_voice_session, get_voice_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])
graph_runtime = GraphRuntime()


@router.post("/sessions", response_model=VoiceSessionResponse)
async def create_session(
    payload: VoiceSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> VoiceSessionResponse:
    thread_id = payload.thread_id
    if thread_id is None:
        thread = ConversationThread(
            user_id=current_user.id,
            langgraph_thread_id=generate_uuid(),
            mode=payload.mode,
            title="语音会话",
        )
        db.add(thread)
        db.commit()
        db.refresh(thread)
        thread_id = thread.id

    voice_session = create_voice_session(
        db,
        user_id=current_user.id,
        thread_id=thread_id,
        mode=payload.mode,
        save_transcript=payload.save_transcript,
    )

    return VoiceSessionResponse(
        voice_session_id=voice_session.id,
        thread_id=thread_id,
        ws_url=build_ws_url(voice_session.id),
    )


@router.websocket("/sessions/{voice_session_id}/ws")
async def voice_session_ws(websocket: WebSocket, voice_session_id: str) -> None:
    await websocket.accept()

    # Use a dedicated DB session for the lifetime of this WebSocket connection.
    db = SessionLocal()
    user: User | None = None

    try:
        voice_session = get_voice_session(db, voice_session_id)
        if voice_session is None:
            await websocket.send_json({"type": "error", "error_code": "not_found", "message": "语音会话不存在"})
            await websocket.close()
            return

        user = db.get(User, voice_session.user_id)
        if user is None:
            await websocket.send_json({"type": "error", "error_code": "unauthorized", "message": "用户不存在"})
            await websocket.close()
            return

        thread = db.get(ConversationThread, voice_session.thread_id)
        if thread is None:
            await websocket.send_json({"type": "error", "error_code": "not_found", "message": "对话线程不存在"})
            await websocket.close()
            return

        await websocket.send_json({
            "type": "session_ready",
            "voice_session_id": voice_session.id,
            "thread_id": thread.id,
        })
        await websocket.send_json({"type": "listening", "message": "请说出你想说的话"})

        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "user_text":
                user_text = (msg.get("text") or "").strip()
                if not user_text:
                    continue

                client_event_id = msg.get("client_event_id", "")

                # Notify client that processing has started
                await websocket.send_json({
                    "type": "processing",
                    "client_event_id": client_event_id,
                })

                # Invoke the full LangGraph pipeline (risk + intent + response)
                user_mode = user.profile.user_mode if user.profile else "adult"
                companion_style = user.settings.companion_style if user.settings else "gentle"
                memory_mode = user.settings.memory_mode if user.settings else "summary_only"

                result = await graph_runtime.invoke_turn(
                    thread_id=thread.id,
                    user_id=user.id,
                    content=user_text,
                    input_type="voice",
                    user_mode=user_mode,
                    memory_mode=memory_mode,
                    companion_style=companion_style,
                    nickname=user.profile.nickname if user.profile else None,
                )

                risk_level = str(result.get("risk_level", "L0"))
                assistant_text = str(result.get("assistant_text", ""))
                suggested_actions = list(result.get("suggested_actions", []))

                # If L2/L3, send safety escalation FIRST before assistant text
                if risk_level in {"L2", "L3"}:
                    await websocket.send_json({
                        "type": "safety_escalation",
                        "risk_level": risk_level,
                        "message": "我很在意你的安全。我们先暂停普通聊天，优先确认你现在是否安全。",
                    })
                    # Record risk event
                    risk_event = RiskEvent(
                        user_id=user.id,
                        thread_id=thread.id,
                        risk_level=risk_level,
                        trigger_text=user_text[:500],
                        safety_action_taken=["show_sos", "crisis_response"],
                    )
                    db.add(risk_event)
                    db.commit()

                # Stream assistant text as deltas (simulate token-by-token)
                chunk_size = 12
                for i in range(0, len(assistant_text), chunk_size):
                    chunk = assistant_text[i : i + chunk_size]
                    await websocket.send_json({
                        "type": "assistant_delta",
                        "text": chunk,
                    })

                # Send the final message
                await websocket.send_json({
                    "type": "assistant_final",
                    "text": assistant_text,
                    "risk_level": risk_level,
                    "suggested_actions": suggested_actions,
                })

                # Go back to listening for the next turn
                await websocket.send_json({"type": "listening", "message": "请说出你想说的话"})

            elif msg_type == "end_session":
                await websocket.send_json({
                    "type": "session_ended",
                    "voice_session_id": voice_session_id,
                })
                end_voice_session(db, session_id=voice_session_id, status="ended")
                await websocket.close()
                return

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected: %s", voice_session_id)
    except Exception:
        logger.exception("Voice WebSocket error for session %s", voice_session_id)
        try:
            await websocket.send_json({
                "type": "error",
                "error_code": "internal_error",
                "message": "语音服务暂时不可用，请切换到文字对话。",
            })
        except Exception:
            pass
    finally:
        try:
            end_voice_session(db, session_id=voice_session_id, status="error" if user is None else "ended")
        except Exception:
            pass
        db.close()
