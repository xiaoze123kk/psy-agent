from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import SessionLocal, init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        version="0.3.0",
        description="Sprint 1 backend for the counseling agent.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup() -> None:
        init_db()
        if settings.knowledge_warm_index_on_startup:
            from app.services.knowledge_service import warm_knowledge_search_index

            with SessionLocal() as db:
                warm_knowledge_search_index(db)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
