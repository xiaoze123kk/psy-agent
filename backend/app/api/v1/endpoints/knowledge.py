from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas.knowledge import (
    AskKnowledgeRequest,
    AskKnowledgeResponse,
    KnowledgeArticleResponse,
    KnowledgeSearchResponse,
)
from app.services.knowledge_service import article_to_detail, ask_knowledge, get_article, search_articles

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
