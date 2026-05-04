from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.knowledge import (
    AskKnowledgeRequest,
    AskKnowledgeResponse,
    KnowledgeArticleResponse,
    KnowledgeGapListResponse,
    KnowledgeGapMutationResponse,
    KnowledgeQuizBankStatsResponse,
    KnowledgeQuizResultResponse,
    KnowledgeQuizSessionResponse,
    KnowledgeSearchResponse,
    ResolveKnowledgeGapRequest,
    StartKnowledgeQuizRequest,
    SubmitKnowledgeQuizRequest,
)
from app.services.knowledge_quiz_service import (
    get_knowledge_quiz_bank_stats,
    start_knowledge_quiz,
    submit_knowledge_quiz,
)
from app.services.knowledge_service import (
    article_to_detail,
    ask_knowledge,
    get_article,
    list_knowledge_gaps,
    resolve_knowledge_gap,
    search_articles,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    q: str = Query(default=""),
    category: str | None = None,
    audience: str | None = None,
    db: Session = Depends(get_db_session),
) -> KnowledgeSearchResponse:
    return search_articles(db, query=q, category=category, audience=audience)


@router.get("/articles/{article_id}", response_model=KnowledgeArticleResponse)
async def read_knowledge_article(
    article_id: str,
    db: Session = Depends(get_db_session),
) -> KnowledgeArticleResponse:
    article = get_article(db, article_id)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge article not found.")
    return article_to_detail(article)


@router.post("/ask", response_model=AskKnowledgeResponse)
async def ask_knowledge_endpoint(
    payload: AskKnowledgeRequest,
    db: Session = Depends(get_db_session),
) -> AskKnowledgeResponse:
    return await ask_knowledge(
        db,
        question=payload.question,
        use_my_context=payload.use_my_context,
        thread_id=payload.thread_id,
    )


@router.get("/gaps", response_model=KnowledgeGapListResponse)
async def read_knowledge_gaps(
    status_filter: str = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> KnowledgeGapListResponse:
    return list_knowledge_gaps(db, status_filter=status_filter, limit=limit)


@router.post("/gaps/{gap_id}/resolve", response_model=KnowledgeGapMutationResponse)
async def resolve_knowledge_gap_endpoint(
    gap_id: str,
    payload: ResolveKnowledgeGapRequest,
    db: Session = Depends(get_db_session),
) -> KnowledgeGapMutationResponse:
    try:
        return resolve_knowledge_gap(
            db,
            gap_id=gap_id,
            article_id=payload.article_id,
            reviewer_note=payload.reviewer_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/quiz/stats", response_model=KnowledgeQuizBankStatsResponse)
async def read_knowledge_quiz_stats() -> KnowledgeQuizBankStatsResponse:
    return get_knowledge_quiz_bank_stats()


@router.post("/quiz/start", response_model=KnowledgeQuizSessionResponse)
async def start_knowledge_quiz_endpoint(payload: StartKnowledgeQuizRequest) -> KnowledgeQuizSessionResponse:
    return start_knowledge_quiz(payload.mode)


@router.post("/quiz/submit", response_model=KnowledgeQuizResultResponse)
async def submit_knowledge_quiz_endpoint(payload: SubmitKnowledgeQuizRequest) -> KnowledgeQuizResultResponse:
    try:
        return submit_knowledge_quiz(payload.session_id, payload.answers)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
