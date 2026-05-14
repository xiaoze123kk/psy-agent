from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
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
from app.services.counseling_chunking import DialoguePair, LayeredChunk, build_layered_chunks
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


def _parsed_from_layered_chunk(chunk: LayeredChunk) -> ParsedExample:
    return ParsedExample(
        external_id=chunk.external_id,
        chunk_index=chunk.chunk_index,
        mode=chunk.mode,
        topic=chunk.topic,
        user_text=chunk.user_text,
        assistant_text=chunk.assistant_text,
        context_text=chunk.context_text,
        content=chunk.content,
        tags=chunk.tags,
        metadata=chunk.metadata,
    )


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
    pairs: list[DialoguePair] = []
    prior: list[str] = []
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
                pairs.append(
                    DialoguePair(
                        user_text=waiting_user,
                        assistant_text=assistant_text,
                        context_text=context_text or "",
                    )
                )
            prior.append(f"咨询师：{assistant_text}")
            waiting_user = None
    chunks = build_layered_chunks(pairs, external_id=external_id, topic=topic, parser="messages")
    return [_parsed_from_layered_chunk(chunk) for chunk in chunks]


def _parse_smilechat_flat_array(items: list[dict[str, Any]], external_id: str, topic: str | None) -> list[ParsedExample]:
    """Handle SMILECHAT format: flat array of {role: client/counselor, content: ...} objects."""
    messages: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").lower()
        content = _clean_text(item.get("content") or "")
        if role == "client":
            messages.append({"role": "user", "content": content})
        elif role == "counselor":
            messages.append({"role": "assistant", "content": content})
    return _pairs_from_messages(messages, external_id, topic)


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


def _parse_item(item: dict[str, Any], index: int, source_key: str = "") -> list[ParsedExample]:
    topic = _topic_from_item(item)
    raw_id = str(item.get("id") or item.get("conversation_id") or item.get("uuid") or "").strip()
    if raw_id:
        external_id = f"{source_key}_{raw_id}" if source_key else raw_id
    else:
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
        chunks = build_layered_chunks(
            [DialoguePair(user_text=question, assistant_text=answer)],
            external_id=external_id,
            topic=topic,
            parser="qa",
        )
        return [_parsed_from_layered_chunk(chunk) for chunk in chunks]
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


# ─── Large JSON streaming parse (for 800MB+ files) ───

def _stream_json_array(file_path: Path) -> list[dict[str, Any]]:
    """Stream items from a top-level JSON array using ijson for memory efficiency."""
    try:
        import ijson
    except ImportError:
        raise ImportError("ijson is required for streaming large JSON files. Install with: pip install ijson")

    items: list[dict[str, Any]] = []
    with open(file_path, "rb") as fh:
        for item in ijson.items(fh, "item"):
            if isinstance(item, dict):
                items.append(item)
    return items


# ─── SMILECHAT multi-file directory support ───

def _load_smilechat_items(smilechat_data_dir: Path) -> list[dict[str, Any]]:
    """Load SMILECHAT data from a directory of individual JSON files.

    Each file contains a flat JSON array of turn objects with {role, content, annotation}.
    We wrap each file as a single conversation for the importer.
    """
    items: list[dict[str, Any]] = []
    json_files = sorted(smilechat_data_dir.glob("*.json"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
    for idx, json_file in enumerate(json_files):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        # Wrap the flat turn array as a conversation item
        items.append({
            "external_id": f"smilechat_{json_file.stem}",
            "file_index": idx,
            "_smilechat_turns": data,
        })
    return items


def _parse_smilechat_item(item: dict[str, Any]) -> list[ParsedExample]:
    """Parse a SMILECHAT conversation (flat turn array stored in _smilechat_turns)."""
    turns = item.get("_smilechat_turns")
    if not isinstance(turns, list):
        return []
    external_id = str(item.get("external_id") or "")
    return _parse_smilechat_flat_array(turns, external_id, topic=None)


# ─── Database batch insert ───

INSERT_BATCH_SIZE = 500


def _upsert_examples_batch(
    db: SessionLocal,
    source: CounselingCorpusSource,
    parsed_examples: list[ParsedExample],
    status: str,
    counts: dict[str, int],
) -> None:
    """Write a batch of parsed examples to DB. Deduplicates within the batch."""
    # Deduplicate within batch by (external_id, chunk_index)
    seen: set[tuple[str, int]] = set()
    unique_examples: list[ParsedExample] = []
    for ex in parsed_examples:
        key = (ex.external_id, ex.chunk_index)
        if key not in seen:
            seen.add(key)
            unique_examples.append(ex)

    for example in unique_examples:
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
        else:
            for key, value in row_payload.items():
                setattr(existing, key, value)
            counts["updated"] += 1
    db.commit()


def _source_payload(source_key: str) -> dict[str, Any]:
    try:
        return COUNSELING_CORPUS_SOURCES[source_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported counseling source: {source_key}") from exc


def import_examples_batched(
    *,
    source_key: str,
    items: list[dict[str, Any]],
    is_smilechat: bool,
    publish_reviewed: bool,
    dry_run: bool,
    limit: int | None,
) -> dict[str, int]:
    payload = _source_payload(source_key)
    status = "published" if publish_reviewed else "draft"
    total_parsed = 0
    counts = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}

    if dry_run:
        # Preview first N items only
        preview_total = 0
        for index, item in enumerate(items):
            if is_smilechat:
                parsed = _parse_smilechat_item(item)
            else:
                parsed = _parse_item(item, index, source_key)
            preview_total += len(parsed)
            if limit and preview_total >= limit:
                break
        counts["parsed"] = min(preview_total, limit) if limit else preview_total
        counts["created"] = counts["parsed"]
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
        db.commit()

        batch: list[ParsedExample] = []
        for index, item in enumerate(items):
            if is_smilechat:
                parsed = _parse_smilechat_item(item)
            else:
                parsed = _parse_item(item, index, source_key)
            batch.extend(parsed)
            total_parsed += len(parsed)

            # Flush batch when enough accumulated
            while len(batch) >= INSERT_BATCH_SIZE:
                chunk = batch[:INSERT_BATCH_SIZE]
                batch = batch[INSERT_BATCH_SIZE:]
                _upsert_examples_batch(db, source, chunk, status, counts)

            if limit and total_parsed >= limit:
                # Trim excess and flush remainder
                excess = total_parsed - limit
                if excess > 0:
                    batch = batch[: len(batch) - excess]
                    total_parsed = limit
                if batch:
                    _upsert_examples_batch(db, source, batch, status, counts)
                batch = []

            if (index + 1) % 5000 == 0:
                print(f"  处理进度: {index + 1}/{len(items)} 条对话, 已解析 {total_parsed} 个片段...")

        # Final flush
        if batch:
            _upsert_examples_batch(db, source, batch, status, counts)

    counts["parsed"] = total_parsed
    return counts


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

    file_size = path.stat().st_size
    if file_size > 100_000_000:  # > 100MB
        print(f"  检测到大文件 ({file_size / 1_000_000:.0f}MB)，使用流式解析...")
        return _stream_json_array(path)

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return _iter_nested_items(data)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import Chinese counseling dialogue corpora into PostgreSQL and optional Milvus.")
    parser.add_argument("--source", required=True, choices=sorted(COUNSELING_CORPUS_SOURCES.keys()))
    parser.add_argument("--input-json", type=Path, help="Local JSON/JSONL file downloaded from the source.")
    parser.add_argument("--input-dir", type=Path, help="Directory containing SMILECHAT JSON files (data/ directory).")
    parser.add_argument("--limit", type=int, help="Limit parsed examples for trial imports.")
    parser.add_argument("--publish-reviewed", action="store_true", help="Mark imported safe examples as published and indexable.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-index", action="store_true", help="Skip Milvus indexing after import.")
    args = parser.parse_args()

    if not args.input_json and not args.input_dir:
        parser.error("必须指定 --input-json 或 --input-dir")
    if args.input_dir and args.source != "smilechat":
        parser.error("--input-dir 目前仅支持 SMILECHAT (--source smilechat)")

    init_db()

    is_smilechat = args.source == "smilechat" and args.input_dir is not None
    if is_smilechat:
        print(f"从目录加载 SMILECHAT 数据: {args.input_dir}")
        items = _load_smilechat_items(args.input_dir)
        print(f"  发现 {len(items)} 个对话文件")
    else:
        items = _load_items(args.input_json)
        print(f"  解析到 {len(items)} 条原始记录")

    counts = import_examples_batched(
        source_key=args.source,
        items=items,
        is_smilechat=is_smilechat,
        publish_reviewed=args.publish_reviewed,
        dry_run=args.dry_run,
        limit=args.limit,
    )

    index_counts = {"indexed": 0, "skipped": 0}
    if args.publish_reviewed and not args.dry_run and not args.no_index:
        print("  开始向量化索引到 Milvus...")
        with SessionLocal() as db:
            result = await index_counseling_chunks(db, source_key=args.source, limit=args.limit)
            index_counts = {"indexed": result.indexed, "skipped": result.skipped}

    print(json.dumps({**counts, "milvus": index_counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
