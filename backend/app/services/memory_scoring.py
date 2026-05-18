from __future__ import annotations

import re
from difflib import SequenceMatcher


def clean_text(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").replace("\r", "\n").split())
    if limit is not None and len(text) > limit:
        return text[: max(limit - 1, 0)] + "…"
    return text


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    ascii_words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    cjk_chars = {char for char in lowered if "\u4e00" <= char <= "\u9fff"}
    return ascii_words | cjk_chars


def term_similarity(query: str, document: str) -> float:
    query_terms = tokenize(query)
    if not query_terms:
        return 0.0
    doc_terms = tokenize(document)
    if not doc_terms:
        return 0.0
    return len(query_terms & doc_terms) / max(len(query_terms), 1)


def content_similarity(left: str, right: str) -> float:
    left_text = clean_text(left).lower()
    right_text = clean_text(right).lower()
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def should_compare_memory_content(existing_content: object, candidate_content: object) -> bool:
    left = clean_text(existing_content)
    right = clean_text(candidate_content)
    if not left or not right:
        return False
    if left == right:
        return True

    shorter_length = min(len(left), len(right))
    longer_length = max(len(left), len(right))
    if shorter_length / longer_length < 0.45:
        return False
    if shorter_length < 12:
        return True
    return bool(tokenize(left) & tokenize(right))
