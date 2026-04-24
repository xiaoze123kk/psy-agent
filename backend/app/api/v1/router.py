from fastapi import APIRouter

from app.api.v1.endpoints import auth, chat, knowledge, memory, mood, onboarding, safety, tests, voice

api_router = APIRouter()


@api_router.get("")
async def api_root() -> dict[str, str]:
    return {"message": "Counseling Agent API v1"}


api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(chat.router)
api_router.include_router(memory.router)
api_router.include_router(mood.router)
api_router.include_router(knowledge.router)
api_router.include_router(tests.router)
api_router.include_router(safety.router)
api_router.include_router(voice.router)
