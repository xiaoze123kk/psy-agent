from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.counseling_vector_service import COUNSELING_CORPUS_SOURCES
from app.services.embedding_service import embedding_client
from app.services.milvus_service import milvus_store


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
    source_key: str
    source_name: str
    external_id: str
    chunk_index: int
    mode: str
    topic: str
    user_text: str
    assistant_text: str
    context_text: str
    content: str
    source_url: str
    license: str


@dataclass
class ImportCounts:
    parsed: int = 0
    indexed: int = 0
    skipped: int = 0


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


def _is_safe_example(user_text: str, assistant_text: str, context_text: str = "") -> bool:
    if _contains_high_risk(user_text) or _contains_high_risk(assistant_text) or _contains_high_risk(context_text):
        return False
    return not bool(FORBIDDEN_ASSISTANT_PATTERNS.search(assistant_text))


def _classify_mode(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text}\n{assistant_text}"
    scores = {mode: sum(1 for clue in clues if clue in haystack) for mode, clues in MODE_CLUES.items()}
    best_mode, best_score = max(scores.items(), key=lambda item: item[1])
    return best_mode if best_score > 0 else "counseling"


def _stable_id(source_key: str, external_id: str, chunk_index: int) -> str:
    digest = hashlib.sha1(
        f"{source_key}\n{external_id}\n{chunk_index}\n{embedding_client.embedding_key}".encode("utf-8")
    ).hexdigest()
    return f"{source_key}_{digest}"[:128]


def _content(context_text: str, user_text: str, assistant_text: str) -> str:
    parts = []
    if context_text:
        parts.append(f"上下文：{context_text}")
    parts.append(f"用户：{user_text}")
    parts.append(f"咨询回应：{assistant_text}")
    return "\n".join(parts)


def _topic_from_item(item: dict[str, Any]) -> str:
    for key in ("topic", "tag", "normalizedTag", "category", "label"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:80]
    return ""


def _normalize_role(role: object) -> str:
    value = str(role or "").strip().lower()
    if value in {"human", "client", "user", "咨询者", "来访者"}:
        return "user"
    if value in {"gpt", "assistant", "counselor", "therapist", "心理咨询师", "咨询师"}:
        return "assistant"
    return value


def _messages_from_item(item: dict[str, Any]) -> list[dict[str, str]]:
    raw_messages = (
        item.get("messages")
        or item.get("conversation")
        or item.get("conversations")
        or item.get("dialog")
        or item.get("dialogue")
    )
    messages: list[dict[str, str]] = []
    if not isinstance(raw_messages, list):
        return messages
    for raw in raw_messages:
        if isinstance(raw, dict):
            role = _normalize_role(raw.get("role") or raw.get("from") or raw.get("speaker"))
            content = _clean_text(raw.get("content") or raw.get("value") or raw.get("text") or raw.get("utterance"))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            role = _normalize_role(raw[0])
            content = _clean_text(raw[1])
        else:
            continue
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


def _messages_from_history_item(item: dict[str, Any]) -> list[dict[str, str]]:
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


def _pairs_from_messages(
    *,
    source_key: str,
    external_id: str,
    topic: str,
    messages: list[dict[str, str]],
) -> Iterator[ParsedExample]:
    source = COUNSELING_CORPUS_SOURCES[source_key]
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
        if role != "assistant" or not waiting_user:
            continue

        assistant_text = content
        context_text = "\n".join(prior[:-1][-4:])
        if _is_safe_example(waiting_user, assistant_text, context_text):
            mode = _classify_mode(waiting_user, assistant_text)
            yield ParsedExample(
                source_key=source_key,
                source_name=str(source["name"]),
                external_id=external_id[:160],
                chunk_index=pair_index,
                mode=mode,
                topic=topic[:80],
                user_text=waiting_user,
                assistant_text=assistant_text,
                context_text=context_text,
                content=_content(context_text, waiting_user, assistant_text),
                source_url=str(source["base_url"]),
                license=str(source["license"]),
            )
            pair_index += 1
        prior.append(f"咨询师：{assistant_text}")
        waiting_user = None


def _parse_item(item: dict[str, Any], index: int, source_key: str) -> Iterator[ParsedExample]:
    topic = _topic_from_item(item)
    raw_id = str(item.get("external_id") or item.get("id") or item.get("conversation_id") or item.get("uuid") or "").strip()
    external_id = f"{source_key}_{raw_id}" if raw_id else _hash_item_id(item, index)

    messages = _messages_from_item(item)
    if not messages:
        messages = _messages_from_history_item(item)
    if not messages:
        transcript = _clean_text(item.get("text") or item.get("content") or item.get("conversation_text") or "")
        messages = _parse_text_transcript(transcript) if transcript else []
    if messages:
        yield from _pairs_from_messages(source_key=source_key, external_id=external_id, topic=topic, messages=messages)
        return

    question = _clean_text(item.get("question") or item.get("input") or item.get("instruction") or item.get("prompt"))
    answer = _clean_text(item.get("answer") or item.get("output") or item.get("response"))
    if question and answer and _is_safe_example(question, answer):
        yield from _pairs_from_messages(
            source_key=source_key,
            external_id=external_id,
            topic=topic,
            messages=[{"role": "user", "content": question}, {"role": "assistant", "content": answer}],
        )


def _hash_item_id(item: dict[str, Any], index: int) -> str:
    try:
        raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
    except TypeError:
        raw = str(item)
    return hashlib.sha1(f"{index}\n{raw}".encode("utf-8")).hexdigest()[:32]


def _iter_top_level_json_array(path: Path) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    eof = False
    with path.open("r", encoding="utf-8-sig") as fh:
        while True:
            if not eof:
                chunk = fh.read(1024 * 1024)
                if chunk:
                    buffer += chunk
                else:
                    eof = True

            buffer = buffer.lstrip()
            if not started:
                if not buffer:
                    if eof:
                        return
                    continue
                if buffer[0] != "[":
                    value, _ = decoder.raw_decode(buffer)
                    yield value
                    return
                buffer = buffer[1:]
                started = True

            buffer = buffer.lstrip()
            if buffer.startswith("]"):
                return
            if buffer.startswith(","):
                buffer = buffer[1:].lstrip()
            if not buffer:
                if eof:
                    return
                continue

            try:
                value, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if eof:
                    raise
                continue
            yield value
            buffer = buffer[end:]


def _iter_json_or_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8-sig") as fh:
            for line in fh:
                if not line.strip():
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    yield item
        return

    for value in _iter_top_level_json_array(path):
        if isinstance(value, dict):
            for key in ("items", "data", "train", "validation", "test", "examples"):
                nested = value.get(key)
                if isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, dict):
                            yield item
                    break
            else:
                yield value


def _iter_source_examples(source_key: str, corpus_root: Path) -> Iterator[ParsedExample]:
    if source_key == "smilechat":
        data_dir = corpus_root / "smilechat" / "data"
        files = sorted(data_dir.glob("*.json"), key=lambda path: int(path.stem) if path.stem.isdigit() else path.stem)
        for file_index, file_path in enumerate(files):
            try:
                turns = json.loads(file_path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(turns, list):
                continue
            item = {"id": file_path.stem, "messages": turns}
            yield from _parse_item(item, file_index, source_key)
        return

    source_dir = corpus_root / source_key
    json_files = sorted(path for path in source_dir.glob("*.json") if path.is_file())
    for file_path in json_files:
        for index, item in enumerate(_iter_json_or_jsonl(file_path)):
            raw_id = item.get("external_id") or item.get("id") or item.get("conversation_id") or item.get("uuid") or index
            item = {**item, "external_id": f"{file_path.stem}_{index}_{raw_id}"}
            yield from _parse_item(item, index, source_key)


def _vector_row(example: ParsedExample, vector: list[float]) -> dict[str, object]:
    row_id = _stable_id(example.source_key, example.external_id, example.chunk_index)
    return {
        "id": row_id,
        "chunk_id": row_id,
        "source_id": example.source_key,
        "source_key": example.source_key,
        "source_name": example.source_name,
        "external_id": example.external_id,
        "mode": example.mode,
        "topic": example.topic,
        "source_url": example.source_url,
        "license": example.license,
        "status": "published",
        "embedding_key": embedding_client.embedding_key,
        "content": example.content,
        "vector": vector,
    }


async def _flush_batch(examples: list[ParsedExample]) -> tuple[int, int]:
    unique_examples: list[ParsedExample] = []
    seen_ids: set[str] = set()
    duplicate_count = 0
    for example in examples:
        row_id = _stable_id(example.source_key, example.external_id, example.chunk_index)
        if row_id in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(row_id)
        unique_examples.append(example)

    if not unique_examples:
        return 0, duplicate_count

    vectors = await embedding_client.embed_texts([example.content for example in unique_examples])
    if vectors is None:
        return 0, len(unique_examples) + duplicate_count
    rows = [_vector_row(example, vector) for example, vector in zip(unique_examples, vectors)]
    if milvus_store.upsert_counseling_examples(rows):
        return len(rows), duplicate_count
    return 0, len(rows) + duplicate_count


async def index_sources(
    *,
    sources: Iterable[str],
    corpus_root: Path,
    limit: int | None,
    batch_size: int,
    progress_every: int,
) -> dict[str, ImportCounts]:
    if not embedding_client.is_configured:
        raise RuntimeError("Embedding provider is not configured.")
    if not milvus_store.ensure_counseling_collection():
        raise RuntimeError("Milvus counseling collection is not available.")

    results: dict[str, ImportCounts] = {}
    for source_key in sources:
        counts = ImportCounts()
        batch: list[ParsedExample] = []
        last_report = 0
        for example in _iter_source_examples(source_key, corpus_root):
            batch.append(example)
            counts.parsed += 1
            if len(batch) >= batch_size:
                indexed, skipped = await _flush_batch(batch)
                counts.indexed += indexed
                counts.skipped += skipped
                batch = []
                if counts.parsed - last_report >= progress_every:
                    print(
                        f"[{source_key}] parsed={counts.parsed} indexed={counts.indexed} skipped={counts.skipped}",
                        flush=True,
                    )
                    last_report = counts.parsed
            if limit and counts.parsed >= limit:
                break

        if batch:
            indexed, skipped = await _flush_batch(batch)
            counts.indexed += indexed
            counts.skipped += skipped
        results[source_key] = counts
        print(
            f"[{source_key}] done parsed={counts.parsed} indexed={counts.indexed} skipped={counts.skipped}",
            flush=True,
        )
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="Slice local counseling corpora, embed them, and write directly to Milvus.")
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=ROOT / "data" / "counseling_corpus",
        help="Directory containing soulchat_corpus, psydt_corpus, and smilechat.",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(COUNSELING_CORPUS_SOURCES.keys()),
        help="Corpus source to index. Pass multiple times, or omit to index all local sources.",
    )
    parser.add_argument("--limit", type=int, help="Limit parsed chunks per source for smoke tests.")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding/upsert batch size.")
    parser.add_argument("--progress-every", type=int, default=1000, help="Print progress after this many parsed chunks.")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the counseling Milvus collection first.")
    args = parser.parse_args()

    sources = args.source or ["soulchat_corpus", "psydt_corpus", "smilechat"]
    if args.recreate:
        milvus_store.drop_collections("counseling")

    results = await index_sources(
        sources=sources,
        corpus_root=args.corpus_root,
        limit=args.limit,
        batch_size=max(args.batch_size, 1),
        progress_every=max(args.progress_every, 1),
    )
    print(
        json.dumps(
            {key: {"parsed": val.parsed, "indexed": val.indexed, "skipped": val.skipped} for key, val in results.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
