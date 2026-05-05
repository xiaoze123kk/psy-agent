from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import CounselingCorpusSource, CounselingExampleChunk, utcnow
from app.db.session import SessionLocal, init_db
from app.services.counseling_vector_service import COUNSELING_CORPUS_SOURCES
from app.services.vector_index_service import index_counseling_chunks


HIGH_RISK_TERMS = (
    "自杀",
    "自伤",
    "割腕",
    "上吊",
    "跳楼",
    "结束生命",
    "不想活",
    "寻死",
    "kill myself",
    "suicide",
    "self harm",
)

FORBIDDEN_ASSISTANT_PATTERNS = re.compile(
    "|".join(
        [
            r"确诊",
            r"诊断.{0,8}为",
            r"你得了",
            r"一定能好",
            r"保证.{0,6}(康复|治好)",
            r"包治",
            r"服用.{0,10}药",
            r"剂量",
            r"不用找医生",
            r"不用咨询",
            r"别去.?医院",
            r"只有我.{0,8}你",
            r"你离不开我",
        ]
    ),
    re.IGNORECASE,
)

PII_PATTERNS = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号]"),
    (re.compile(r"(?<!\d)\d{15}(\d{2}[\dXx])?(?!\d)"), "[身份证号]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱]"),
    (re.compile(r"(微信|vx|VX|qq|QQ)[:：]?\s*[A-Za-z0-9_-]{5,}"), r"\1：[账号]"),
]

MODE_CLUES = {
    "soothe": ("心慌", "睡不着", "焦虑", "紧张", "发抖", "喘不过气", "胸闷", "惊恐", "害怕"),
    "counseling": ("怎么办", "理一理", "分析", "复盘", "想想办法", "怎么处理", "做决定", "选择", "沟通"),
    "vent": ("委屈", "没人理解", "想哭", "难受", "压力好大", "压抑", "崩溃", "好累"),
}


@dataclass(frozen=True)
class ParsedExample:
    external_id: str
    chunk_index: int
    mode: str
    topic: str | None
    user_text: str
    assistant_text: str
    context_text: str | None
    content: str
    tags: list[str]
    metadata: dict[str, Any]


def _clean_text(text: object) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    for regex, replacement in PII_PATTERNS:
        cleaned = regex.sub(replacement, cleaned)
    return cleaned


def _contains_high_risk(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in HIGH_RISK_TERMS)


def _is_safe_example(user_text: str, assistant_text: str) -> bool:
    if _contains_high_risk(user_text) or _contains_high_risk(assistant_text):
        return False
    return not bool(FORBIDDEN_ASSISTANT_PATTERNS.search(assistant_text))


def _classify_mode(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text}\n{assistant_text}"
    scores = {
        mode: sum(1 for clue in clues if clue in haystack)
        for mode, clues in MODE_CLUES.items()
    }
    best_mode, best_score = max(scores.items(), key=lambda item: item[1])
    return best_mode if best_score > 0 else "counseling"


def _hash_external_id(*parts: str) -> str:
    digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def _content(context_text: str | None, user_text: str, assistant_text: str) -> str:
    parts = []
    if context_text:
        parts.append(f"上下文：{context_text}")
    parts.append(f"用户：{user_text}")
    parts.append(f"咨询回应：{assistant_text}")
    return "\n".join(parts)


def _topic_from_item(item: dict[str, Any]) -> str | None:
    for key in ("topic", "tag", "normalizedTag", "category", "label"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:80]
    return None


def _messages_from_item(item: dict[str, Any]) -> list[dict[str, str]]:
    raw_messages = (
        item.get("messages")
        or item.get("conversation")
        or item.get("conversations")
        or item.get("dialog")
        or item.get("dialogue")
    )
    messages: list[dict[str, str]] = []
    if isinstance(raw_messages, list):
        for raw in raw_messages:
            if isinstance(raw, dict):
                role = str(raw.get("role") or raw.get("from") or raw.get("speaker") or "").lower()
                content = _clean_text(raw.get("content") or raw.get("value") or raw.get("text") or raw.get("utterance"))
            elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                role = str(raw[0]).lower()
                content = _clean_text(raw[1])
            else:
                continue
            if role in {"human", "client", "user", "咨询者", "来访者"}:
                role = "user"
            elif role in {"gpt", "assistant", "counselor", "therapist", "心理咨询师", "咨询师"}:
                role = "assistant"
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
    return messages


def _parse_text_transcript(text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    pattern = re.compile(r"(用户|来访者|咨询者|心理咨询师|咨询师|assistant|user)[:：]\s*", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    for index, match in enumerate(matches):
        role_label = match.group(1).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = _clean_text(text[start:end])
        if not content:
            continue
        role = "assistant" if role_label in {"心理咨询师", "咨询师", "assistant"} else "user"
        messages.append({"role": role, "content": content})
    return messages


def _pairs_from_messages(messages: list[dict[str, str]], external_id: str, topic: str | None) -> list[ParsedExample]:
    parsed: list[ParsedExample] = []
    prior: list[str] = []
    pair_index = 0
    waiting_user: str | None = None
    for message in messages:
        role = message["role"]
        content = message["content"]
        if role == "user":
            waiting_user = content
            prior.append(f"用户：{content}")
            continue
        if role == "assistant" and waiting_user:
            assistant_text = content
            context_lines = prior[:-1][-4:]
            context_text = "\n".join(context_lines) if context_lines else None
            if _is_safe_example(waiting_user, assistant_text):
                mode = _classify_mode(waiting_user, assistant_text)
                parsed.append(
                    ParsedExample(
                        external_id=external_id,
                        chunk_index=pair_index,
                        mode=mode,
                        topic=topic,
                        user_text=waiting_user,
                        assistant_text=assistant_text,
                        context_text=context_text,
                        content=_content(context_text, waiting_user, assistant_text),
                        tags=[tag for tag in [mode, topic] if tag],
                        metadata={"parser": "messages"},
                    )
                )
                pair_index += 1
            prior.append(f"咨询师：{assistant_text}")
            waiting_user = None
    return parsed


def _parse_history_item(item: dict[str, Any], external_id: str, topic: str | None) -> list[ParsedExample]:
    history = item.get("history")
    input_text = _clean_text(item.get("input") or item.get("question") or item.get("instruction") or item.get("prompt"))
    output_text = _clean_text(item.get("output") or item.get("answer") or item.get("response"))
    messages: list[dict[str, str]] = []

    if isinstance(history, list):
        for turn in history:
            if isinstance(turn, (list, tuple)) and len(turn) >= 2:
                user_text = _clean_text(turn[0])
                assistant_text = _clean_text(turn[1])
                if user_text:
                    messages.append({"role": "user", "content": user_text})
                if assistant_text:
                    messages.append({"role": "assistant", "content": assistant_text})

    if input_text:
        messages.append({"role": "user", "content": input_text})
    if output_text:
        messages.append({"role": "assistant", "content": output_text})

    return _pairs_from_messages(messages, external_id, topic)


def _parse_item(item: dict[str, Any], index: int) -> list[ParsedExample]:
    topic = _topic_from_item(item)
    external_id = str(item.get("id") or item.get("conversation_id") or item.get("uuid") or "").strip()
    if not external_id:
        external_id = _hash_external_id(json.dumps(item, ensure_ascii=False, sort_keys=True), str(index))

    messages = _messages_from_item(item)
    if messages:
        return _pairs_from_messages(messages, external_id, topic)

    parsed = _parse_history_item(item, external_id, topic)
    if parsed:
        return parsed

    transcript = _clean_text(item.get("text") or item.get("content") or item.get("conversation_text") or "")
    if transcript:
        messages = _parse_text_transcript(transcript)
        if messages:
            return _pairs_from_messages(messages, external_id, topic)

    question = _clean_text(item.get("question") or item.get("input") or item.get("instruction") or item.get("prompt"))
    answer = _clean_text(item.get("answer") or item.get("output") or item.get("response"))
    if question and answer and _is_safe_example(question, answer):
        mode = _classify_mode(question, answer)
        return [
            ParsedExample(
                external_id=external_id,
                chunk_index=0,
                mode=mode,
                topic=topic,
                user_text=question,
                assistant_text=answer,
                context_text=None,
                content=_content(None, question, answer),
                tags=[tag for tag in [mode, topic] if tag],
                metadata={"parser": "qa"},
            )
        ]
    return []


def _iter_nested_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("items", "data", "train", "validation", "test", "examples"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _load_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        items = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                items.append(parsed)
        return items

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return _iter_nested_items(data)


def _source_payload(source_key: str) -> dict[str, Any]:
    try:
        return COUNSELING_CORPUS_SOURCES[source_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported counseling source: {source_key}") from exc


def import_examples(
    *,
    source_key: str,
    items: list[dict[str, Any]],
    publish_reviewed: bool,
    dry_run: bool,
    limit: int | None,
) -> dict[str, int]:
    payload = _source_payload(source_key)
    parsed_examples: list[ParsedExample] = []
    for index, item in enumerate(items):
        parsed_examples.extend(_parse_item(item, index))
        if limit and len(parsed_examples) >= limit:
            parsed_examples = parsed_examples[:limit]
            break

    status = "published" if publish_reviewed else "draft"
    counts = {"parsed": len(parsed_examples), "created": 0, "updated": 0, "skipped": 0}
    if dry_run:
        counts["created"] = len(parsed_examples)
        return counts

    with SessionLocal() as db:
        source = db.scalar(select(CounselingCorpusSource).where(CounselingCorpusSource.source_key == source_key))
        if source is None:
            source = CounselingCorpusSource(**payload)
            db.add(source)
            db.flush()
        else:
            for key, value in payload.items():
                if getattr(source, key) != value:
                    setattr(source, key, value)
        source.retrieved_at = utcnow()

        for example in parsed_examples:
            existing = db.scalar(
                select(CounselingExampleChunk).where(
                    CounselingExampleChunk.source_id == source.id,
                    CounselingExampleChunk.external_id == example.external_id,
                    CounselingExampleChunk.chunk_index == example.chunk_index,
                )
            )
            row_payload = {
                "source_id": source.id,
                "external_id": example.external_id,
                "chunk_index": example.chunk_index,
                "mode": example.mode,
                "topic": example.topic,
                "user_text": example.user_text,
                "assistant_text": example.assistant_text,
                "context_text": example.context_text,
                "content": example.content,
                "tags": example.tags,
                "meta": example.metadata,
                "source_url": source.base_url,
                "license": source.license,
                "status": status,
            }
            if existing is None:
                db.add(CounselingExampleChunk(**row_payload))
                counts["created"] += 1
                continue
            for key, value in row_payload.items():
                setattr(existing, key, value)
            counts["updated"] += 1
        db.commit()
    return counts


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import Chinese counseling dialogue corpora into PostgreSQL and optional Milvus.")
    parser.add_argument("--source", required=True, choices=sorted(COUNSELING_CORPUS_SOURCES.keys()))
    parser.add_argument("--input-json", type=Path, required=True, help="Local JSON/JSONL file downloaded from the source.")
    parser.add_argument("--limit", type=int, help="Limit parsed examples for trial imports.")
    parser.add_argument("--publish-reviewed", action="store_true", help="Mark imported safe examples as published and indexable.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-index", action="store_true", help="Skip Milvus indexing after import.")
    args = parser.parse_args()

    init_db()
    items = _load_items(args.input_json)
    counts = import_examples(
        source_key=args.source,
        items=items,
        publish_reviewed=args.publish_reviewed,
        dry_run=args.dry_run,
        limit=args.limit,
    )

    index_counts = {"indexed": 0, "skipped": 0}
    if args.publish_reviewed and not args.dry_run and not args.no_index:
        with SessionLocal() as db:
            result = await index_counseling_chunks(db, source_key=args.source, limit=args.limit)
            index_counts = {"indexed": result.indexed, "skipped": result.skipped}

    print(json.dumps({**counts, "milvus": index_counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
