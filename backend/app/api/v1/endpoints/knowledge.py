from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class AskKnowledgeRequest(BaseModel):
    question: str
    use_my_context: bool = True


@router.get("/search")
async def search_knowledge(q: str) -> dict[str, list[dict[str, str]]]:
    return {
        "items": [
            {
                "article_id": "demo-article-1",
                "title": f"About {q}",
                "summary_30s": "Knowledge retrieval scaffold response.",
            }
        ]
    }


@router.post("/ask")
async def ask_knowledge(payload: AskKnowledgeRequest) -> dict[str, object]:
    return {
        "answer": f"Scaffold answer for: {payload.question}",
        "related_articles": [],
    }
