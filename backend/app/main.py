import asyncio
import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.services.memory_job_service import start_memory_job_worker, stop_memory_job_worker


logger = logging.getLogger(__name__)


async def _warm_local_embedding() -> None:
    from app.services.embedding_service import embedding_client

    started_at = perf_counter()
    try:
        warmed = await embedding_client.warmup()
    except Exception as exc:  # pragma: no cover - startup resilience
        logger.warning("Local embedding warmup failed: %s", exc)
        return

    duration_ms = int((perf_counter() - started_at) * 1000)
    if warmed:
        logger.info(
            "Local embedding warmup completed in %sms on %s.",
            duration_ms,
            embedding_client.resolved_local_device,
        )
    else:
        logger.warning("Local embedding warmup returned no vector after %sms.", duration_ms)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        version="0.3.0",
        description="Sprint 1 backend for the counseling agent.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"] if not settings.cookie_secure else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup() -> None:
        init_db()
        start_memory_job_worker()
        if settings.knowledge_warm_index_on_startup:
            from app.services.knowledge_service import warm_knowledge_search_index

            with SessionLocal() as db:
                warm_knowledge_search_index(db)
        if (
            settings.counseling_rag_enabled
            and settings.milvus_enabled
            and settings.local_embedding_warm_on_startup
            and settings.embedding_provider.strip().lower() == "local"
        ):
            app.state.embedding_warmup_task = asyncio.create_task(_warm_local_embedding())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        task = getattr(app.state, "embedding_warmup_task", None)
        if task and not task.done():
            task.cancel()
        from app.services.embedding_service import embedding_client

        await embedding_client.aclose()
        await stop_memory_job_worker()

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
