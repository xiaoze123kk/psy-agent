from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


HIGH_RISK_TERMS = (
    "自杀",
    "自残",
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
            r"保证.{0,8}(康复|治好)",
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
    all_text = _joined_pairs(safe_pairs)
    session_emotions = _tags_from_clues(all_text, EMOTION_CLUES)
    session_interventions = _tags_from_clues(all_text, INTERVENTION_CLUES)

    for pair_index, pair in enumerate(safe_pairs):
        content = _turn_content(pair)
        mode = classify_mode(pair.user_text, pair.assistant_text)
        metadata = {
            "chunk_type": "turn_pair",
            "original_external_id": external_id,
            "pair_start": pair_index,
            "pair_end": pair_index,
            "pair_count": 1,
            "overlap_pairs": 0,
            "parser": parser,
            "display_text": content,
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
                content=content,
                tags=[tag for tag in [mode, topic] if tag],
                metadata=metadata,
            )
        )
        chunk_index += 1

    for segment_index, (start, end) in enumerate(
        _window_ranges(len(safe_pairs), window_size=window_size, overlap_pairs=overlap_pairs)
    ):
        segment_pairs = safe_pairs[start:end]
        segment_text = _joined_pairs(segment_pairs)
        emotion_tags = _tags_from_clues(segment_text, EMOTION_CLUES)
        intervention_tags = _tags_from_clues(segment_text, INTERVENTION_CLUES)
        phase = _phase_for_pairs(segment_pairs)
        mode = classify_mode(segment_pairs[-1].user_text, segment_pairs[-1].assistant_text)
        display_text = _process_display(
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
                context_text=_context_for_process(segment_pairs),
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
        sketch_content = _session_sketch_content(
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
            "phase": "whole_session",
            "emotion_tags": session_emotions,
            "intervention_tags": session_interventions,
            "display_text": sketch_content,
            "process_quality_score": _process_quality_score(session_interventions, len(safe_pairs)),
            "parser": parser,
        }
        chunks.append(
            LayeredChunk(
                external_id=f"{external_id}::session",
                chunk_index=chunk_index,
                mode=classify_mode(safe_pairs[-1].user_text, safe_pairs[-1].assistant_text),
                topic=topic,
                user_text="",
                assistant_text="",
                context_text=None,
                content=sketch_content,
                tags=[tag for tag in [topic, "whole_session"] if tag] + session_emotions + session_interventions,
                metadata=metadata,
            )
        )

    return chunks


def is_safe_pair(pair: DialoguePair) -> bool:
    joined = f"{pair.context_text}\n{pair.user_text}\n{pair.assistant_text}"
    if _contains_high_risk(joined):
        return False
    return not bool(FORBIDDEN_ASSISTANT_PATTERNS.search(pair.assistant_text))


def classify_mode(user_text: str, assistant_text: str) -> str:
    haystack = f"{user_text}\n{assistant_text}"
    if any(word in haystack for word in ("睡不好", "焦虑", "紧张", "喘不过气", "慢一点", "呼吸")):
        return "soothe"
    if any(word in haystack for word in ("怎么办", "怎么拒绝", "边界", "选择", "小步骤")):
        return "counseling"
    if any(word in haystack for word in ("没人理解", "想哭", "委屈", "难过", "压力")):
        return "vent"
    return "counseling"


def _contains_high_risk(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in HIGH_RISK_TERMS)


def _tags_from_clues(text: str, clues: dict[str, tuple[str, ...]]) -> list[str]:
    return [tag for tag, values in clues.items() if any(value in text for value in values)]


def _joined_pairs(pairs: list[DialoguePair]) -> str:
    return "\n".join(f"{pair.user_text}\n{pair.assistant_text}" for pair in pairs)


def _phase_for_pairs(pairs: list[DialoguePair]) -> str:
    text = _joined_pairs(pairs)
    phase_scores = {phase: sum(1 for clue in clues if clue in text) for phase, clues in PHASE_CLUES.items()}
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


def _process_display(
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


def _context_for_process(pairs: list[DialoguePair]) -> str | None:
    context = "\n".join(
        line
        for pair in pairs[:-1]
        for line in (f"用户：{pair.user_text}", f"咨询回应：{pair.assistant_text}")
    )
    return context or None


def _session_sketch_content(
    *,
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
