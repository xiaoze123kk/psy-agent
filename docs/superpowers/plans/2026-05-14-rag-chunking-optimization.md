# RAG Chunking 优化实施计划

> **给 agentic workers：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐步执行。步骤使用 checkbox (`- [ ]`) 跟踪。

**目标：** 将 counseling RAG 从单轮问答 chunk 升级为 `turn_pair`、`process_segment`、`session_sketch` 三层 chunk，并在运行时按场景做配额检索和 prompt 分区展示。

**架构：** 新增一个纯函数模块 `backend/app/services/counseling_chunking.py` 承担分层 chunk 生成、规则标签、display/retrieval 文本构造。导入脚本和直写 Milvus 脚本都调用同一套 chunking 逻辑，`counseling_vector_service.py` 负责把 chunk metadata 写入 Milvus row、运行时重排和安全过滤，`response_nodes.py` 负责按用途分区展示 RAG references。

**技术栈：** Python 3.13, dataclasses, SQLAlchemy 2.x, Milvus REST/pymilvus, unittest/pytest, existing FastAPI/LangGraph backend.

---

## 文件结构

- 新建: `backend/app/services/counseling_chunking.py`
  - 纯函数模块，定义 `DialoguePair`、`LayeredChunk`、`build_layered_chunks()`、规则标签、display/retrieval 文本。
- 修改: `backend/scripts/import_counseling_corpus.py`
  - 将原有 `_pairs_from_messages()` 改为生成标准 pairs，再调用 `build_layered_chunks()` 写入 DB。
- 修改: `backend/scripts/index_counseling_corpus_direct.py`
  - 复用同一套分层 chunking，直写 Milvus 时也生成三层 chunk。
- 修改: `backend/app/services/counseling_vector_service.py`
  - 向 Milvus row 注入 `chunk_type`、`original_external_id`、`phase`、`display_text`、`process_quality_score` 等字段；运行时按配额重排。
- 修改: `backend/app/services/milvus_service.py`
  - counseling collection 增加可选 scalar fields，并在搜索输出中返回这些字段；旧 collection 缺字段时保持回退。
- 修改: `backend/app/graphs/nodes/rag_nodes.py`
  - trace 中暴露 chunk type 分布，不改变节点路由。
- 修改: `backend/app/graphs/nodes/response_nodes.py`
  - RAG references 分区为 session/process/turn，并优先展示 `display_text`。
- 修改: `backend/tests/test_counseling_milvus_plan.py`
  - 覆盖 chunk 生成、Milvus row metadata、运行时配额。
- 修改: `backend/tests/test_conversation_control_rag.py`
  - 覆盖 prompt 分区和旧行为回归。

---

### 任务 1: 新增分层 chunking 纯函数

**Files:**
- 新建: `backend/app/services/counseling_chunking.py`
- 修改: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/test_counseling_milvus_plan.py` 顶部新增导入：

```python
from app.services.counseling_chunking import DialoguePair, build_layered_chunks
```

在 `CounselingCorpusImportTests` 中新增测试：

```python
    def test_layered_chunking_builds_turn_segments_and_session_sketch(self) -> None:
        pairs = [
            DialoguePair(user_text="我最近压力很大，晚上睡不好", assistant_text="听起来你已经撑了很久，我们先慢一点。"),
            DialoguePair(user_text="主要是领导一直临时加活", assistant_text="你像是被不断打断，也很难有掌控感。"),
            DialoguePair(user_text="我不知道怎么拒绝", assistant_text="我们可以先把你最想守住的边界说清楚。"),
            DialoguePair(user_text="我怕他觉得我不配合", assistant_text="这个担心很真实，也可以先准备一句温和但清楚的话。"),
            DialoguePair(user_text="这样好像没那么乱了", assistant_text="能稍微清楚一点就很好，我们先保留这个小步骤。"),
        ]

        chunks = build_layered_chunks(
            pairs,
            external_id="case-1",
            topic="工作压力",
            parser="messages",
        )

        turn_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_type"] == "turn_pair"]
        process_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_type"] == "process_segment"]
        sketch_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_type"] == "session_sketch"]

        self.assertEqual(len(turn_chunks), 5)
        self.assertGreaterEqual(len(process_chunks), 2)
        self.assertEqual(len(sketch_chunks), 1)
        self.assertEqual(process_chunks[0].metadata["pair_end"], process_chunks[1].metadata["pair_start"])
        self.assertEqual(process_chunks[0].metadata["overlap_pairs"], 1)
        self.assertIn("片段类型：整段咨询地图", sketch_chunks[0].content)
        self.assertNotIn("领导一直临时加活", sketch_chunks[0].metadata["display_text"])
```

再新增安全过滤测试：

```python
    def test_layered_chunking_skips_process_and_session_for_unsafe_pair(self) -> None:
        pairs = [
            DialoguePair(user_text="我今晚想自杀", assistant_text="我听到了你的痛苦。"),
            DialoguePair(user_text="我不知道怎么办", assistant_text="我们先联系身边可信任的人。"),
        ]

        chunks = build_layered_chunks(
            pairs,
            external_id="case-risk",
            topic="危机",
            parser="messages",
        )

        self.assertEqual(chunks, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_layered_chunking_builds_turn_segments_and_session_sketch tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_layered_chunking_skips_process_and_session_for_unsafe_pair -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.counseling_chunking'`.

- [ ] **Step 3: Implement `counseling_chunking.py`**

Create `backend/app/services/counseling_chunking.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

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
            r"只有我.{0,8}懂你",
            r"你离不开我",
        ]
    ),
    re.IGNORECASE,
)

EMOTION_CLUES: dict[str, tuple[str, ...]] = {
    "anxiety": ("焦虑", "紧张", "睡不好", "喘不过气", "担心", "害怕", "压力"),
    "hurt": ("委屈", "没人理解", "被忽视", "难过", "孤单"),
    "anger": ("生气", "愤怒", "不公平", "火大"),
    "exhaustion": ("累", "疲惫", "撑不住", "耗尽", "倦怠"),
    "confusion": ("乱", "不知道", "迷茫", "卡住"),
}

INTERVENTION_CLUES: dict[str, tuple[str, ...]] = {
    "reflection": ("听起来", "像是", "你已经", "这种感觉", "确实"),
    "validation": ("很真实", "可以理解", "不奇怪", "不是你的错"),
    "clarifying_question": ("愿意", "多说", "具体", "发生了什么", "哪一部分"),
    "grounding": ("慢一点", "呼吸", "当下", "身体", "先停"),
    "agency": ("你可以选择", "由你决定", "先保留", "小步骤", "边界"),
}

PHASE_CLUES: dict[str, tuple[str, ...]] = {
    "opening": ("最近", "今天", "怎么了", "想聊"),
    "exploration": ("多说", "具体", "发生", "为什么", "哪一部分"),
    "intervention": ("可以先", "我们可以", "试着", "小步骤", "准备一句"),
    "closing": ("先保留", "总结", "下次", "今天先", "到这里"),
}


@dataclass(frozen=True)
class DialoguePair:
    user_text: str
    assistant_text: str
    context_text: str = ""


@dataclass(frozen=True)
class LayeredChunk:
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


def _contains_high_risk(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in HIGH_RISK_TERMS)


def is_safe_pair(pair: DialoguePair) -> bool:
    joined = f"{pair.context_text}\n{pair.user_text}\n{pair.assistant_text}"
    if _contains_high_risk(joined):
        return False
    return not bool(FORBIDDEN_ASSISTANT_PATTERNS.search(pair.assistant_text))


def _tags_from_clues(text: str, clues: dict[str, tuple[str, ...]]) -> list[str]:
    return [tag for tag, values in clues.items() if any(value in text for value in values)]


def classify_mode(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text}\n{assistant_text}"
    if any(word in haystack for word in ("睡不好", "焦虑", "紧张", "喘不过气", "慢一点", "呼吸")):
        return "soothe"
    if any(word in haystack for word in ("怎么办", "怎么拒绝", "边界", "选择", "小步骤")):
        return "counseling"
    if any(word in haystack for word in ("没人理解", "想哭", "委屈", "难过", "压力")):
        return "vent"
    return "counseling"


def _phase_for_pairs(pairs: list[DialoguePair]) -> str:
    text = "\n".join(f"{pair.user_text}\n{pair.assistant_text}" for pair in pairs)
    phase_scores = {
        phase: sum(1 for clue in clues if clue in text)
        for phase, clues in PHASE_CLUES.items()
    }
    phase, score = max(phase_scores.items(), key=lambda item: item[1])
    return phase if score > 0 else "exploration"


def _summary_line(label: str, tags: list[str], fallback: str) -> str:
    return f"{label}：" + (", ".join(tags) if tags else fallback)


def _process_quality_score(intervention_tags: list[str], pair_count: int) -> float:
    score = 0.4 + min(pair_count, 5) * 0.08 + len(set(intervention_tags)) * 0.06
    return round(min(score, 0.95), 2)


def _turn_content(pair: DialoguePair) -> str:
    return f"片段类型：单轮问答\n用户：{pair.user_text}\n咨询回应：{pair.assistant_text}"


def _process_content(
    *,
    phase: str,
    emotion_tags: list[str],
    intervention_tags: list[str],
    pairs: list[DialoguePair],
) -> str:
    lines = [
        "片段类型：咨询过程片段",
        f"阶段：{phase}",
        _summary_line("用户情绪线索", emotion_tags, "未识别"),
        _summary_line("咨询师动作线索", intervention_tags, "支持性回应"),
        "对话片段：",
    ]
    for pair in pairs:
        lines.append(f"用户：{pair.user_text}")
        lines.append(f"咨询回应：{pair.assistant_text}")
    return "\n".join(lines)


def _display_for_process(
    *,
    phase: str,
    emotion_tags: list[str],
    intervention_tags: list[str],
    pairs: list[DialoguePair],
) -> str:
    first = pairs[0]
    last = pairs[-1]
    return "\n".join(
        [
            f"阶段：{phase}",
            _summary_line("用户情绪线索", emotion_tags, "未识别"),
            _summary_line("咨询师动作线索", intervention_tags, "支持性回应"),
            f"片段起点：用户：{first.user_text}",
            f"片段收束：咨询回应：{last.assistant_text}",
        ]
    )


def _session_sketch_content(
    *,
    pairs: list[DialoguePair],
    emotion_tags: list[str],
    intervention_tags: list[str],
    topic: str | None,
) -> str:
    concern = topic or "未标注主题"
    start = ", ".join(emotion_tags[:2]) if emotion_tags else "困扰未明"
    path = " -> ".join(intervention_tags[:4]) if intervention_tags else "支持性承接"
    return "\n".join(
        [
            "片段类型：整段咨询地图",
            f"主要困扰：{concern}",
            f"情绪起点：{start}",
            "情绪变化：从表达困扰逐步转向更具体的描述或小步骤",
            f"咨询师引导路径：{path}",
            "结尾状态：仍需继续跟进",
        ]
    )


def _window_ranges(pair_count: int, *, window_size: int, overlap_pairs: int) -> list[tuple[int, int]]:
    if pair_count < 2:
        return []
    window_size = max(2, min(window_size, 5))
    overlap_pairs = max(0, min(overlap_pairs, window_size - 1))
    step = max(1, window_size - overlap_pairs)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < pair_count:
        end = min(start + window_size, pair_count)
        if end - start >= 2:
            ranges.append((start, end))
        if end == pair_count:
            break
        start += step
    return ranges


def build_layered_chunks(
    pairs: list[DialoguePair],
    *,
    external_id: str,
    topic: str | None,
    parser: str,
    window_size: int = 3,
    overlap_pairs: int = 1,
) -> list[LayeredChunk]:
    safe_pairs = [pair for pair in pairs if is_safe_pair(pair)]
    if len(safe_pairs) != len(pairs):
        return []

    chunks: list[LayeredChunk] = []
    chunk_index = 0
    all_text = "\n".join(f"{pair.user_text}\n{pair.assistant_text}" for pair in safe_pairs)
    session_emotions = _tags_from_clues(all_text, EMOTION_CLUES)
    session_interventions = _tags_from_clues(all_text, INTERVENTION_CLUES)

    for index, pair in enumerate(safe_pairs):
        mode = classify_mode(pair.user_text, pair.assistant_text)
        metadata = {
            "chunk_type": "turn_pair",
            "original_external_id": external_id,
            "pair_start": index,
            "pair_end": index,
            "pair_count": 1,
            "overlap_pairs": 0,
            "parser": parser,
            "display_text": _turn_content(pair),
            "process_quality_score": 0.5,
        }
        chunks.append(
            LayeredChunk(
                external_id=f"{external_id}::turn",
                chunk_index=chunk_index,
                mode=mode,
                topic=topic,
                user_text=pair.user_text,
                assistant_text=pair.assistant_text,
                context_text=pair.context_text or None,
                content=_turn_content(pair),
                tags=[tag for tag in [mode, topic] if tag],
                metadata=metadata,
            )
        )
        chunk_index += 1

    for segment_index, (start, end) in enumerate(
        _window_ranges(len(safe_pairs), window_size=window_size, overlap_pairs=overlap_pairs)
    ):
        segment_pairs = safe_pairs[start:end]
        segment_text = "\n".join(f"{pair.user_text}\n{pair.assistant_text}" for pair in segment_pairs)
        emotion_tags = _tags_from_clues(segment_text, EMOTION_CLUES)
        intervention_tags = _tags_from_clues(segment_text, INTERVENTION_CLUES)
        phase = _phase_for_pairs(segment_pairs)
        mode = classify_mode(segment_pairs[-1].user_text, segment_pairs[-1].assistant_text)
        display_text = _display_for_process(
            phase=phase,
            emotion_tags=emotion_tags,
            intervention_tags=intervention_tags,
            pairs=segment_pairs,
        )
        metadata = {
            "chunk_type": "process_segment",
            "original_external_id": external_id,
            "segment_index": segment_index,
            "pair_start": start,
            "pair_end": end - 1,
            "pair_count": end - start,
            "overlap_pairs": overlap_pairs,
            "phase": phase,
            "emotion_tags": emotion_tags,
            "intervention_tags": intervention_tags,
            "display_text": display_text,
            "process_quality_score": _process_quality_score(intervention_tags, end - start),
            "parser": parser,
        }
        chunks.append(
            LayeredChunk(
                external_id=f"{external_id}::process",
                chunk_index=chunk_index,
                mode=mode,
                topic=topic,
                user_text=segment_pairs[-1].user_text,
                assistant_text=segment_pairs[-1].assistant_text,
                context_text="\n".join(
                    line
                    for pair in segment_pairs[:-1]
                    for line in (f"用户：{pair.user_text}", f"咨询回应：{pair.assistant_text}")
                )
                or None,
                content=_process_content(
                    phase=phase,
                    emotion_tags=emotion_tags,
                    intervention_tags=intervention_tags,
                    pairs=segment_pairs,
                ),
                tags=[tag for tag in [mode, topic, phase] if tag] + emotion_tags + intervention_tags,
                metadata=metadata,
            )
        )
        chunk_index += 1

    if len(safe_pairs) >= 2:
        sketch = _session_sketch_content(
            pairs=safe_pairs,
            emotion_tags=session_emotions,
            intervention_tags=session_interventions,
            topic=topic,
        )
        metadata = {
            "chunk_type": "session_sketch",
            "original_external_id": external_id,
            "pair_start": 0,
            "pair_end": len(safe_pairs) - 1,
            "pair_count": len(safe_pairs),
            "overlap_pairs": 0,
            "phase": "session",
            "emotion_tags": session_emotions,
            "intervention_tags": session_interventions,
            "display_text": sketch,
            "process_quality_score": _process_quality_score(session_interventions, len(safe_pairs)),
            "parser": parser,
        }
        mode = classify_mode(safe_pairs[-1].user_text, safe_pairs[-1].assistant_text)
        chunks.append(
            LayeredChunk(
                external_id=f"{external_id}::session",
                chunk_index=chunk_index,
                mode=mode,
                topic=topic,
                user_text=safe_pairs[-1].user_text,
                assistant_text=safe_pairs[-1].assistant_text,
                context_text=None,
                content=sketch,
                tags=[tag for tag in [mode, topic, "session"] if tag] + session_emotions + session_interventions,
                metadata=metadata,
            )
        )

    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_layered_chunking_builds_turn_segments_and_session_sketch tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_layered_chunking_skips_process_and_session_for_unsafe_pair -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/counseling_chunking.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: add layered counseling chunk builder"
```

---

### 任务 2: 接入 PostgreSQL counseling corpus 导入

**Files:**
- 修改: `backend/scripts/import_counseling_corpus.py`
- 修改: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write the failing regression test**

在 `CounselingCorpusImportTests` 中新增测试：

```python
    def test_parser_returns_layered_chunks_with_metadata(self) -> None:
        item = {
            "id": "case-layered",
            "normalizedTag": "工作压力",
            "messages": [
                {"role": "user", "content": "我最近压力很大，睡不好"},
                {"role": "assistant", "content": "听起来你已经撑了很久，我们先慢一点。"},
                {"role": "user", "content": "领导总是临时加活"},
                {"role": "assistant", "content": "你像是一直被打断，也很难有掌控感。"},
                {"role": "user", "content": "我不知道怎么拒绝"},
                {"role": "assistant", "content": "我们可以先把你最想守住的边界说清楚。"},
            ],
        }

        parsed = import_counseling_corpus._parse_item(item, 0, source_key="smilechat")

        chunk_types = [example.metadata["chunk_type"] for example in parsed]
        self.assertEqual(chunk_types.count("turn_pair"), 3)
        self.assertIn("process_segment", chunk_types)
        self.assertIn("session_sketch", chunk_types)
        process = next(example for example in parsed if example.metadata["chunk_type"] == "process_segment")
        self.assertEqual(process.metadata["original_external_id"], "smilechat_case-layered")
        self.assertIn("display_text", process.metadata)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_parser_returns_layered_chunks_with_metadata -q
```

Expected: FAIL because `_parse_item()` currently returns only turn-level examples and metadata lacks `chunk_type`.

- [ ] **Step 3: Update `import_counseling_corpus.py` imports and helpers**

Add import near existing service imports:

```python
from app.services.counseling_chunking import DialoguePair, build_layered_chunks
```

Replace `_pairs_from_messages()` with a two-step implementation:

```python
def _dialogue_pairs_from_messages(messages: list[dict[str, str]]) -> list[DialoguePair]:
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
            context_lines = prior[:-1][-4:]
            context_text = "\n".join(context_lines) if context_lines else ""
            pairs.append(
                DialoguePair(
                    user_text=waiting_user,
                    assistant_text=content,
                    context_text=context_text,
                )
            )
            prior.append(f"咨询师：{content}")
            waiting_user = None
    return pairs


def _pairs_from_messages(messages: list[dict[str, str]], external_id: str, topic: str | None) -> list[ParsedExample]:
    chunks = build_layered_chunks(
        _dialogue_pairs_from_messages(messages),
        external_id=external_id,
        topic=topic,
        parser="messages",
    )
    return [
        ParsedExample(
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
        for chunk in chunks
    ]
```

Keep `_classify_mode()`, `_is_safe_example()`, and `_content()` for compatibility if other tests still import them; the parser path should use the new builder.

- [ ] **Step 4: Run the focused test**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_parser_returns_layered_chunks_with_metadata -q
```

Expected: PASS.

- [ ] **Step 5: Run import parser regression tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests -q
```

Expected: PASS. If `test_parser_desensitizes_and_classifies_chinese_dialogue` expects exactly one parsed example, update it to assert at least one `turn_pair` and keep the PII/mode assertions on that turn chunk.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/import_counseling_corpus.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: import layered counseling chunks"
```

---

### 任务 3: 接入直写 Milvus corpus 索引

**Files:**
- 修改: `backend/scripts/index_counseling_corpus_direct.py`
- 修改: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write the failing test**

在 `CounselingCorpusImportTests` 中新增测试：

```python
    def test_direct_index_parser_returns_layered_chunks(self) -> None:
        from scripts import index_counseling_corpus_direct

        item = {
            "id": "direct-layered",
            "topic": "工作压力",
            "messages": [
                {"role": "user", "content": "我最近压力很大，睡不好"},
                {"role": "assistant", "content": "听起来你已经撑了很久，我们先慢一点。"},
                {"role": "user", "content": "领导总是临时加活"},
                {"role": "assistant", "content": "你像是一直被打断，也很难有掌控感。"},
                {"role": "user", "content": "我不知道怎么拒绝"},
                {"role": "assistant", "content": "我们可以先把你最想守住的边界说清楚。"},
            ],
        }

        parsed = list(index_counseling_corpus_direct._parse_item(item, 0, source_key="smilechat"))

        chunk_types = [example.metadata["chunk_type"] for example in parsed]
        self.assertIn("turn_pair", chunk_types)
        self.assertIn("process_segment", chunk_types)
        self.assertIn("session_sketch", chunk_types)
        self.assertTrue(all(example.external_id.startswith("smilechat_direct-layered::") for example in parsed))
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_direct_index_parser_returns_layered_chunks -q
```

Expected: FAIL because direct parser examples have no `metadata` field and only produce turn chunks.

- [ ] **Step 3: Update direct parser dataclass and imports**

In `backend/scripts/index_counseling_corpus_direct.py`, add:

```python
from app.services.counseling_chunking import DialoguePair, build_layered_chunks
```

Add `metadata` to `ParsedExample`:

```python
    metadata: dict[str, Any]
```

Add helper:

```python
def _dialogue_pairs_from_messages(messages: list[dict[str, str]]) -> list[DialoguePair]:
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
            raw_context_text = "\n".join(prior[:-1][-4:])
            pairs.append(
                DialoguePair(
                    user_text=waiting_user,
                    assistant_text=content,
                    context_text=raw_context_text,
                )
            )
            prior.append(f"咨询师：{content}")
            waiting_user = None
    return pairs
```

Replace `_pairs_from_messages()` with:

```python
def _pairs_from_messages(
    *,
    source_key: str,
    external_id: str,
    topic: str,
    messages: list[dict[str, str]],
) -> Iterator[ParsedExample]:
    source = COUNSELING_CORPUS_SOURCES[source_key]
    chunks = build_layered_chunks(
        _dialogue_pairs_from_messages(messages),
        external_id=external_id,
        topic=topic,
        parser="messages",
    )
    for chunk in chunks:
        yield ParsedExample(
            source_key=source_key,
            source_name=str(source["name"]),
            external_id=chunk.external_id[:160],
            chunk_index=chunk.chunk_index,
            mode=chunk.mode,
            topic=str(chunk.topic or "")[:80],
            user_text=_clip_text(chunk.user_text, MAX_USER_TEXT_CHARS),
            assistant_text=_clip_text(chunk.assistant_text, MAX_ASSISTANT_TEXT_CHARS),
            context_text=_clip_text(chunk.context_text or "", MAX_CONTEXT_TEXT_CHARS),
            content=_clip_text(chunk.content, MAX_CONTENT_TEXT_CHARS),
            source_url=str(source["base_url"]),
            license=str(source["license"]),
            metadata=chunk.metadata,
        )
```

- [ ] **Step 4: Add metadata fields to direct vector rows**

Update `_vector_row()`:

```python
    metadata = dict(example.metadata or {})
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
        "chunk_type": str(metadata.get("chunk_type") or "turn_pair"),
        "original_external_id": str(metadata.get("original_external_id") or example.external_id),
        "phase": str(metadata.get("phase") or ""),
        "display_text": str(metadata.get("display_text") or example.content),
        "process_quality_score": str(metadata.get("process_quality_score", "")),
        "vector": vector,
    }
```

- [ ] **Step 5: Run focused test**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingCorpusImportTests::test_direct_index_parser_returns_layered_chunks -q
```

Expected: PASS.

- [ ] **Step 6: Run counseling plan tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/index_counseling_corpus_direct.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: direct index layered counseling chunks"
```

---

### 任务 4: 扩展 Milvus row 和 search 输出字段

**Files:**
- 修改: `backend/app/services/counseling_vector_service.py`
- 修改: `backend/app/services/milvus_service.py`
- 修改: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write the failing vector row test**

Update `FakeChunk` in `backend/tests/test_counseling_milvus_plan.py` to include metadata:

```python
    meta = {
        "chunk_type": "process_segment",
        "original_external_id": "dialog-1",
        "phase": "exploration",
        "display_text": "阶段：exploration\n用户情绪线索：hurt",
        "process_quality_score": 0.82,
        "intervention_tags": ["reflection"],
    }
```

Add assertions to `test_counseling_vector_row_keeps_source_metadata`:

```python
        self.assertEqual(row["chunk_type"], "process_segment")
        self.assertEqual(row["original_external_id"], "dialog-1")
        self.assertEqual(row["phase"], "exploration")
        self.assertIn("用户情绪线索", row["display_text"])
        self.assertEqual(row["process_quality_score"], "0.82")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_counseling_vector_row_keeps_source_metadata -q
```

Expected: FAIL with missing `chunk_type` key.

- [ ] **Step 3: Update `CounselingExampleHit` and vector row mapping**

In `backend/app/services/counseling_vector_service.py`, add fields to `CounselingExampleHit`:

```python
    chunk_type: str | None = None
    original_external_id: str | None = None
    phase: str | None = None
    display_text: str | None = None
    process_quality_score: float | None = None
```

Update `counseling_chunk_to_vector_row()`:

```python
        "chunk_type": str(meta.get("chunk_type") or "turn_pair"),
        "original_external_id": str(meta.get("original_external_id") or chunk.external_id),
        "phase": str(meta.get("phase") or ""),
        "display_text": str(meta.get("display_text") or chunk.content),
        "process_quality_score": str(meta.get("process_quality_score", "")),
```

Add those keys before `"vector": vector`.

- [ ] **Step 4: Update Milvus counseling schema and output fields**

In `backend/app/services/milvus_service.py`, add extra fields in `ensure_counseling_collection()`:

```python
                ("chunk_type", 32),
                ("original_external_id", 180),
                ("phase", 40),
                ("display_text", 4096),
                ("process_quality_score", 32),
```

Add these same fields to `search_counseling_examples()` `output_fields`:

```python
                "chunk_type",
                "original_external_id",
                "phase",
                "display_text",
                "process_quality_score",
```

Existing `_filter_existing_output_fields()` keeps old collections working if these fields are absent.

- [ ] **Step 5: Map search hits into `CounselingExampleHit`**

In `retrieve_counseling_examples_with_trace()`, when appending `CounselingExampleHit`, set:

```python
                chunk_type=str(hit.entity.get("chunk_type") or "turn_pair"),
                original_external_id=str(hit.entity.get("original_external_id") or hit.entity.get("external_id") or ""),
                phase=str(hit.entity.get("phase") or "") or None,
                display_text=str(hit.entity.get("display_text") or content),
                process_quality_score=_to_float(hit.entity.get("process_quality_score")),
```

- [ ] **Step 6: Run focused test**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_counseling_vector_row_keeps_source_metadata -q
```

Expected: PASS.

- [ ] **Step 7: Run Milvus plan tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/counseling_vector_service.py backend/app/services/milvus_service.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: include layered chunk metadata in counseling vectors"
```

---

### 任务 5: 运行时按 chunk 类型配额重排

**Files:**
- 修改: `backend/app/services/counseling_vector_service.py`
- 修改: `backend/app/graphs/nodes/rag_nodes.py`
- 修改: `backend/tests/test_counseling_milvus_plan.py`

- [ ] **Step 1: Write failing retrieval quota tests**

Add this helper in `CounselingMilvusPlanTests`:

```python
    def _hit(self, item_id: str, *, chunk_type: str, original_external_id: str, score: float = 0.9) -> VectorHit:
        return VectorHit(
            id=item_id,
            score=score,
            entity={
                "content": f"片段类型：{chunk_type}\n用户：我最近压力很大\n咨询回应：先慢一点。",
                "display_text": f"{chunk_type} display",
                "source_key": "smilechat",
                "source_name": "SMILECHAT",
                "mode": "soothe",
                "status": "published",
                "review_status": "approved",
                "risk_allowed": "non_crisis",
                "language": "zh-CN",
                "chunk_id": item_id,
                "chunk_type": chunk_type,
                "original_external_id": original_external_id,
            },
        )
```

Add default quota test:

```python
    async def test_retrieval_uses_default_chunk_type_quotas(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        hits = [
            self._hit("session-1", chunk_type="session_sketch", original_external_id="case-1", score=0.99),
            self._hit("process-1", chunk_type="process_segment", original_external_id="case-2", score=0.95),
            self._hit("turn-1", chunk_type="turn_pair", original_external_id="case-3", score=0.9),
            self._hit("turn-2", chunk_type="turn_pair", original_external_id="case-4", score=0.89),
        ]

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: hits
        try:
            state = AgentState(
                normalized_text="我最近压力很大，睡不好",
                risk_level="L0",
                route_priority="P2_support",
                control_category="normal_support",
            )
            result = await counseling_vector_service.retrieve_counseling_examples_with_trace(state, mode="soothe", limit=3)
        finally:
            counseling_vector_service.milvus_store.enabled = original_enabled
            counseling_vector_service.milvus_store.__class__.is_available = original_is_available
            counseling_vector_service.embedding_client.embed_query = original_embed_query
            counseling_vector_service.milvus_store.search_counseling_examples = original_search

        self.assertEqual([example.chunk_type for example in result.examples], ["process_segment", "turn_pair", "turn_pair"])
        self.assertEqual(result.trace["chunk_type_counts"], {"process_segment": 1, "turn_pair": 2})
```

Add continuation quota test:

```python
    async def test_retrieval_allows_session_sketch_for_continuation_turns(self) -> None:
        original_enabled = counseling_vector_service.milvus_store.enabled
        original_is_available = counseling_vector_service.milvus_store.__class__.is_available
        original_embed_query = counseling_vector_service.embedding_client.embed_query
        original_search = counseling_vector_service.milvus_store.search_counseling_examples

        async def fake_embed_query(text: str):
            return [0.1] * counseling_vector_service.milvus_store.dim

        hits = [
            self._hit("session-1", chunk_type="session_sketch", original_external_id="case-1", score=0.99),
            self._hit("process-1", chunk_type="process_segment", original_external_id="case-2", score=0.95),
            self._hit("turn-1", chunk_type="turn_pair", original_external_id="case-3", score=0.9),
        ]

        counseling_vector_service.milvus_store.enabled = True
        counseling_vector_service.milvus_store.__class__.is_available = property(lambda self: True)
        counseling_vector_service.embedding_client.embed_query = fake_embed_query
        counseling_vector_service.milvus_store.search_counseling_examples = lambda vector, mode=None, limit=5: hits
        try:
            state = AgentState(
                normalized_text="继续刚才那个工作压力的问题",
                risk_level="L0",
                route_priority="P2_support",
                control_category="normal_support",
            )
            result = await counseling_vector_service.retrieve_counseling_examples_with_trace(state, mode="counseling", limit=3)
        finally:
            counseling_vector_service.milvus_store.enabled = original_enabled
            counseling_vector_service.milvus_store.__class__.is_available = original_is_available
            counseling_vector_service.embedding_client.embed_query = original_embed_query
            counseling_vector_service.milvus_store.search_counseling_examples = original_search

        self.assertEqual([example.chunk_type for example in result.examples], ["session_sketch", "process_segment", "turn_pair"])
```

- [ ] **Step 2: Run tests and confirm they fail**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_uses_default_chunk_type_quotas tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_allows_session_sketch_for_continuation_turns -q
```

Expected: FAIL because current retrieval returns top safe hits without chunk-type quotas.

- [ ] **Step 3: Add quota helpers**

In `backend/app/services/counseling_vector_service.py`, add:

```python
CONTINUATION_PATTERNS = ("继续", "还是", "刚才", "前面", "上次", "那个问题", "接着")


def _chunk_type_for_hit(hit: Any) -> str:
    chunk_type = str(hit.entity.get("chunk_type") or "").strip()
    return chunk_type if chunk_type in {"turn_pair", "process_segment", "session_sketch"} else "turn_pair"


def _original_external_id_for_hit(hit: Any) -> str:
    return str(hit.entity.get("original_external_id") or hit.entity.get("external_id") or hit.id or "")


def _quota_for_state(state: AgentState, mode: str, limit: int) -> dict[str, int]:
    query = str(state.get("normalized_text") or state.get("user_text") or "")
    if any(pattern in query for pattern in CONTINUATION_PATTERNS):
        return {"session_sketch": 1, "process_segment": 1, "turn_pair": max(limit - 2, 0)}
    if mode == "soothe":
        return {"process_segment": 1, "turn_pair": max(limit - 1, 0)}
    return {"process_segment": 1, "turn_pair": max(limit - 1, 0)}


def _select_hits_by_quota(hits: list[Any], *, state: AgentState, mode: str, limit: int) -> list[Any]:
    quota = _quota_for_state(state, mode, limit)
    selected: list[Any] = []
    used_by_type = {chunk_type: 0 for chunk_type in quota}
    used_sources: dict[str, int] = {}

    for desired_type in quota:
        for hit in hits:
            if hit in selected:
                continue
            chunk_type = _chunk_type_for_hit(hit)
            if chunk_type != desired_type:
                continue
            original_external_id = _original_external_id_for_hit(hit)
            if used_sources.get(original_external_id, 0) >= 2:
                continue
            if used_by_type[desired_type] >= quota[desired_type]:
                continue
            selected.append(hit)
            used_by_type[desired_type] += 1
            used_sources[original_external_id] = used_sources.get(original_external_id, 0) + 1
            if len(selected) >= limit:
                return selected

    for hit in hits:
        if hit in selected:
            continue
        original_external_id = _original_external_id_for_hit(hit)
        if used_sources.get(original_external_id, 0) >= 2:
            continue
        selected.append(hit)
        used_sources[original_external_id] = used_sources.get(original_external_id, 0) + 1
        if len(selected) >= limit:
            break
    return selected
```

- [ ] **Step 4: Apply quota selection in retrieval**

Change hit collection to oversample more and avoid breaking before quota selection:

```python
    per_query_limit = max(safe_limit * 6, 18)
```

Replace the early stop logic so it gathers safe hits up to `per_query_limit` per mode, then after all mode searches:

```python
    hits = _select_hits_by_quota(hits, state=state, mode=mode, limit=safe_limit)
```

Keep `seen_ids` dedupe and safety filtering.

- [ ] **Step 5: Add trace chunk type counts**

After examples are built:

```python
    chunk_type_counts: dict[str, int] = {}
    for example in examples:
        key = example.chunk_type or "turn_pair"
        chunk_type_counts[key] = chunk_type_counts.get(key, 0) + 1
    trace["chunk_type_counts"] = chunk_type_counts
```

In `backend/app/graphs/nodes/rag_nodes.py`, no routing change is needed. If trace summary is passed through unchanged, add no code. If serialization drops it, include `chunk_type_counts` in the summary.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_uses_default_chunk_type_quotas tests/test_counseling_milvus_plan.py::CounselingMilvusPlanTests::test_retrieval_allows_session_sketch_for_continuation_turns -q
```

Expected: PASS.

- [ ] **Step 7: Run conversation RAG tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/counseling_vector_service.py backend/app/graphs/nodes/rag_nodes.py backend/tests/test_counseling_milvus_plan.py
git commit -m "feat: rank counseling rag by chunk quotas"
```

---

### 任务 6: Prompt 分区展示 RAG references

**Files:**
- 修改: `backend/app/graphs/nodes/response_nodes.py`
- 修改: `backend/tests/test_conversation_control_rag.py`

- [ ] **Step 1: Write failing prompt formatting test**

In `backend/tests/test_conversation_control_rag.py`, add:

```python
    def test_examples_text_groups_layered_rag_references(self) -> None:
        from app.graphs.nodes.response_nodes import examples_text_from_state

        state = self.make_state(
            "继续刚才那个工作压力的问题",
            retrieved_counseling_examples=[
                {
                    "chunk_type": "session_sketch",
                    "display_text": "主要困扰：工作压力\n咨询师引导路径：共情承接 -> 澄清压力源",
                    "content": "片段类型：整段咨询地图\n这是更长的 retrieval text，不应该完整展示",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "counseling",
                    "score": 0.99,
                },
                {
                    "chunk_type": "process_segment",
                    "display_text": "阶段：exploration\n咨询师动作线索：reflection",
                    "content": "片段类型：咨询过程片段\n长对话原文不应该完整展示",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "counseling",
                    "score": 0.95,
                },
                {
                    "chunk_type": "turn_pair",
                    "display_text": "用户：我很累\n咨询回应：先慢一点。",
                    "content": "用户：我很累\n咨询回应：先慢一点。",
                    "source_key": "smilechat",
                    "source_name": "SMILECHAT",
                    "mode": "vent",
                    "score": 0.9,
                },
            ],
        )

        text = examples_text_from_state(state)

        self.assertIn("--- Session map reference ---", text)
        self.assertIn("--- Process reference ---", text)
        self.assertIn("--- Turn style reference ---", text)
        self.assertIn("主要困扰：工作压力", text)
        self.assertNotIn("这是更长的 retrieval text，不应该完整展示", text)
        self.assertNotIn("长对话原文不应该完整展示", text)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
cd backend && python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_examples_text_groups_layered_rag_references -q
```

Expected: FAIL because current prompt uses one `RAG few-shot references` section and reads `content`.

- [ ] **Step 3: Update `example_hit_to_dict()` if needed**

In `backend/app/graphs/nodes/rag_nodes.py`, extend `example_hit_to_dict()`:

```python
        "chunk_type": str(getattr(example, "chunk_type", "") or "turn_pair"),
        "original_external_id": str(getattr(example, "original_external_id", "") or ""),
        "phase": str(getattr(example, "phase", "") or ""),
        "display_text": str(getattr(example, "display_text", "") or ""),
        "process_quality_score": getattr(example, "process_quality_score", None),
```

- [ ] **Step 4: Update prompt formatting**

Replace `examples_text_from_state()` in `backend/app/graphs/nodes/response_nodes.py` with grouped formatting:

```python
def _rag_reference_line(index: int, example: dict) -> list[str]:
    tags = ", ".join(str(tag) for tag in example.get("intervention_tags", []) if tag)
    display_text = example.get("display_text") or example.get("content")
    return [
        f"[Reference {index}]",
        f"Source: {safe_trim(example.get('source_name') or example.get('source_key'), 40)}",
        f"Mode: {safe_trim(example.get('mode'), 20)}",
        f"Score: {float(example.get('score') or 0.0):.4f}",
        f"Intervention tags: {safe_trim(tags, 80)}",
        f"Content: {safe_trim(display_text, 300)}",
    ]


def examples_text_from_state(state: AgentState) -> str:
    examples = state.get("retrieved_counseling_examples", []) or []
    if not examples:
        return ""
    groups = {
        "session_sketch": ("--- Session map reference ---", []),
        "process_segment": ("--- Process reference ---", []),
        "turn_pair": ("--- Turn style reference ---", []),
    }
    for raw in examples[:3]:
        example = raw if isinstance(raw, dict) else example_hit_to_dict(raw)
        chunk_type = str(example.get("chunk_type") or "turn_pair")
        if chunk_type not in groups:
            chunk_type = "turn_pair"
        groups[chunk_type][1].append(example)

    lines = [
        "",
        "--- RAG references ---",
        "Purpose: session/process references are for counseling structure and intervention flow; turn references are for tone and pacing.",
        "Do not use these snippets as facts, diagnoses, or safety policy.",
        "Do not copy wording or reuse private details. The control-plane contract has priority.",
    ]
    reference_index = 1
    for _chunk_type, (title, grouped_examples) in groups.items():
        if not grouped_examples:
            continue
        lines.append(title)
        for example in grouped_examples:
            lines.extend(_rag_reference_line(reference_index, example))
            reference_index += 1
    lines.append("--- End RAG references ---")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Run focused test**

Run:

```bash
cd backend && python -m pytest tests/test_conversation_control_rag.py::ConversationControlRagTests::test_examples_text_groups_layered_rag_references -q
```

Expected: PASS.

- [ ] **Step 6: Run conversation RAG tests**

Run:

```bash
cd backend && python -m pytest tests/test_conversation_control_rag.py -q
```

Expected: PASS. If `test_generator_uses_state_examples_without_retrieving_again` expects the old section title, update it to assert `RAG references` and `Turn style reference`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/graphs/nodes/rag_nodes.py backend/app/graphs/nodes/response_nodes.py backend/tests/test_conversation_control_rag.py
git commit -m "feat: group layered rag prompt references"
```

---

### 任务 7: 端到端验证与文档

**Files:**
- 修改: `backend/README.md`
- 可选修改: `docs/dev-log/chat-runtime.md`

- [ ] **Step 1: Update backend README indexing notes**

In `backend/README.md`, under the Milvus/counseling corpus indexing section, add:

Counseling corpus indexing now creates layered RAG chunks:

- `turn_pair` for precise single-turn style reference.
- `process_segment` for 3-5 pair counseling process windows with pair-level overlap.
- `session_sketch` for sanitized whole-dialogue maps.

After changing chunking metadata or Milvus scalar fields, recreate the counseling collection and re-index the corpus:

Run:

    python scripts/index_milvus.py --drop counseling
    python scripts/import_counseling_corpus.py --source smilechat --input-dir data/counseling_corpus/smilechat/data --publish-reviewed
If `index_milvus.py --drop counseling` is not a supported command, document the existing supported recreate command from the script instead.

- [ ] **Step 2: Run all focused tests**

Run:

```bash
cd backend && python -m pytest tests/test_counseling_milvus_plan.py tests/test_conversation_control_rag.py -q
```

Expected: PASS.

- [ ] **Step 3: Run smoke checks for import scripts**

Run:

```bash
cd backend && python scripts/import_counseling_corpus.py --source smilechat --input-dir data/counseling_corpus/smilechat/data --limit 2 --dry-run
```

Expected: prints parsed/import counts without writing DB rows.

Run:

```bash
cd backend && python scripts/index_counseling_corpus_direct.py --source smilechat --limit 2 --dry-run
```

Expected: if `--dry-run` exists, prints parsed/index counts without writing Milvus rows. If the script has no dry-run option, do not add one in this task; record that direct-index smoke was skipped and why.

- [ ] **Step 4: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Commit docs and final verification notes**

```bash
git add backend/README.md docs/dev-log/chat-runtime.md
git commit -m "docs: document layered counseling rag chunks"
```

Skip `docs/dev-log/chat-runtime.md` in `git add` if it was not changed.

---

## Plan 自查

- Spec coverage: Tasks cover layered chunk creation, overlap behavior, safety filtering, DB import, direct Milvus import, vector metadata, runtime quota selection, prompt grouping, regression behavior, and docs.
- 占位扫描：未发现未完成标记。
- Type consistency: the shared types are `DialoguePair` and `LayeredChunk`; metadata keys are consistently `chunk_type`, `original_external_id`, `phase`, `display_text`, and `process_quality_score`.
- Scope check: this plan intentionally excludes memory retrieval and knowledge article chunking, matching the approved spec.
