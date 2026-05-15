from __future__ import annotations

import json
import sys
from typing import Any


PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr

from app.core.config import settings  # noqa: E402


def _emit(payload: dict[str, Any]) -> None:
    PROTOCOL_STDOUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
    PROTOCOL_STDOUT.flush()


def _resolve_device() -> str:
    configured = (settings.local_embedding_device or "auto").strip().lower()
    if configured != "auto":
        return configured
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load_model(device: str) -> tuple[Any, Any] | None:
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except Exception as exc:
        _emit({"ok": False, "error": f"transformers unavailable: {exc}"})
        return None

    kwargs: dict[str, Any] = {}
    if settings.local_embedding_cache_dir:
        kwargs["cache_dir"] = settings.local_embedding_cache_dir

    try:
        tokenizer = AutoTokenizer.from_pretrained(settings.counseling_rerank_model, **kwargs)
        model = AutoModelForSequenceClassification.from_pretrained(settings.counseling_rerank_model, **kwargs)
        model.to(device)
        model.eval()
    except Exception as exc:
        _emit({"ok": False, "error": f"model load failed: {exc}"})
        return None
    return tokenizer, model


def _score_documents(tokenizer: Any, model: Any, device: str, query: str, documents: list[str]) -> list[float]:
    import torch

    scores: list[float] = []
    batch_size = max(settings.counseling_rerank_batch_size, 1)
    max_length = max(settings.counseling_rerank_max_length, 1)

    with torch.no_grad():
        for index in range(0, len(documents), batch_size):
            batch_documents = documents[index : index + batch_size]
            inputs = tokenizer(
                [query] * len(batch_documents),
                batch_documents,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            logits = model(**inputs).logits
            if logits.ndim == 2 and logits.shape[-1] > 1:
                logits = logits[:, -1]
            else:
                logits = logits.reshape(-1)
            scores.extend(torch.sigmoid(logits).detach().cpu().tolist())
    return [float(score) for score in scores]


def main() -> int:
    device = _resolve_device()
    loaded = _load_model(device)
    if loaded is None:
        return 1
    tokenizer, model = loaded

    for raw_line in sys.stdin:
        documents: list[str] = []
        try:
            request = json.loads(raw_line)
            query = str(request.get("query") or "").strip()
            documents = [str(document).strip() for document in request.get("documents", []) if str(document).strip()]
            if not query or not documents:
                _emit({"ok": False, "error": "query and documents are required"})
                continue
            scores = _score_documents(tokenizer, model, device, query, documents)
            _emit({"ok": True, "scores": scores})
        except Exception as exc:
            _emit(
                {
                    "ok": False,
                    "error": str(exc),
                    "document_count": len(documents),
                    "document_preview": [document[:80] for document in documents[:2]],
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
