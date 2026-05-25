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


def _resolve_use_fp16(device: str) -> bool:
    configured = (settings.local_embedding_use_fp16 or "auto").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    return device.startswith("cuda")


def _max_length_for_kind(kind: str) -> int:
    if kind == "query":
        return max(settings.local_embedding_query_max_length, 1)
    if kind == "document":
        return max(settings.local_embedding_document_max_length, 1)
    return max(settings.local_embedding_max_length, 1)


def _coerce_vectors(raw_vectors: Any, *, expected_count: int) -> list[list[float]] | None:
    if hasattr(raw_vectors, "tolist"):
        raw_vectors = raw_vectors.tolist()
    if expected_count == 1 and isinstance(raw_vectors, (list, tuple)) and raw_vectors:
        first_value = raw_vectors[0]
        if not isinstance(first_value, (list, tuple)) and not hasattr(first_value, "tolist"):
            raw_vectors = [raw_vectors]
    if not isinstance(raw_vectors, list) or len(raw_vectors) != expected_count:
        return None

    vectors: list[list[float]] = []
    for raw_vector in raw_vectors:
        if hasattr(raw_vector, "tolist"):
            raw_vector = raw_vector.tolist()
        if not isinstance(raw_vector, (list, tuple)):
            return None
        vector = [float(value) for value in raw_vector]
        if len(vector) != settings.embedding_dim:
            return None
        vectors.append(vector)
    return vectors


def main() -> int:
    try:
        from FlagEmbedding import BGEM3FlagModel
    except Exception as exc:
        _emit({"ok": False, "error": f"FlagEmbedding unavailable: {exc}"})
        return 1

    device = _resolve_device()
    kwargs: dict[str, Any] = {
        "use_fp16": _resolve_use_fp16(device),
        "devices": device,
    }
    if settings.local_embedding_cache_dir:
        kwargs["cache_dir"] = settings.local_embedding_cache_dir

    try:
        model = BGEM3FlagModel(settings.embedding_model, **kwargs)
    except Exception as exc:
        _emit({"ok": False, "error": f"model load failed: {exc}"})
        return 1

    for raw_line in sys.stdin:
        texts: list[str] = []
        try:
            request = json.loads(raw_line)
            kind = str(request.get("kind") or "document").strip().lower()
            if kind not in {"query", "document"}:
                kind = "document"
            texts = [str(text).strip() for text in request.get("texts", []) if str(text).strip()]
            encode_input: str | list[str] = texts[0] if len(texts) == 1 else texts
            encode_kwargs = {
                "batch_size": max(settings.local_embedding_batch_size, 1),
                "max_length": _max_length_for_kind(kind),
                "return_dense": True,
                "return_sparse": False,
                "return_colbert_vecs": False,
            }
            if kind == "query" and hasattr(model, "encode_queries"):
                output = model.encode_queries(encode_input, **encode_kwargs)
            else:
                output = model.encode(encode_input, **encode_kwargs)
            dense_vectors = output.get("dense_vecs") if isinstance(output, dict) else output
            vectors = _coerce_vectors(dense_vectors, expected_count=len(texts))
            if vectors is None:
                _emit({"ok": False, "error": "invalid embedding vectors"})
            else:
                _emit({"ok": True, "vectors": vectors})
        except Exception as exc:
            _emit(
                {
                    "ok": False,
                    "error": str(exc),
                    "text_count": len(texts),
                    "text_preview": [text[:80] for text in texts[:2]],
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
