from __future__ import annotations

from app.graphs.nodes.common import AgentState, excerpt, has_any_text
from app.services.session_digest_service import fallback_session_summary, update_session_digest_with_llm


async def summarize_turn(state: AgentState) -> AgentState:
    existing_digest = state.get("session_digest") if isinstance(state.get("session_digest"), dict) else {}
    if state.get("delivery_status") == "failed_no_reply":
        return {"session_summary": "", "session_digest": existing_digest}

    existing_summary = str(state.get("session_summary") or "").strip()
    fallback_summary = existing_summary or fallback_session_summary(state)
    session_digest = await update_session_digest_with_llm(state)
    if session_digest:
        return {
            "session_summary": str(session_digest.get("summary_200chars") or fallback_summary),
            "session_digest": session_digest,
        }
    return {"session_summary": fallback_summary, "session_digest": existing_digest}


async def memory_candidate_extract(state: AgentState) -> AgentState:
    if state.get("delivery_status") == "failed_no_reply":
        return {"memory_candidates": [], "memory_policy_reason": "failed_no_reply"}
    if state.get("memory_mode") == "off":
        return {"memory_candidates": [], "memory_policy_reason": "memory_mode_off"}
    memory_policy = state.get("memory_policy", "write_safe_summary")
    if memory_policy == "skip_sensitive":
        return {"memory_candidates": [], "memory_policy_reason": "skip_sensitive"}
    summary = state.get("session_summary", "")
    if not summary:
        return {"memory_candidates": [], "memory_policy_reason": "empty_summary"}
    existing_candidates = [
        dict(candidate)
        for candidate in (state.get("memory_candidates") or [])
        if isinstance(candidate, dict) and str(candidate.get("content") or "").strip()
    ]
    if existing_candidates:
        return {
            "memory_candidates": existing_candidates[:8],
            "memory_policy_reason": "tool_provided",
        }
    if memory_policy == "crisis_audit_only":
        return {
            "memory_candidates": [
                {
                    "memory_type": "safety_summary",
                    "title": "安全摘要",
                    "summary": summary,
                    "content": summary,
                    "importance": 5,
                    "visibility": "internal_safety",
                    "tags": ["安全"],
                }
            ],
            "memory_policy_reason": "crisis_audit_only",
        }
    candidates = [
        {
            "memory_type": "session_summary",
            "title": "本轮对话摘要",
            "summary": summary,
            "content": summary,
            "importance": 3,
            "tags": ["摘要"],
        }
    ]
    if state.get("memory_mode") != "long_term":
        return {"memory_candidates": candidates, "memory_policy_reason": "summary_only"}

    text = state.get("normalized_text", "")
    compact_text = excerpt(text, 90)
    digest = state.get("session_digest") if isinstance(state.get("session_digest"), dict) else {}

    def _digest_text(*keys: str) -> str:
        parts: list[str] = []
        for key in keys:
            value = digest.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, list):
                parts.extend(str(item).strip() for item in value if str(item).strip())
        return "；".join(part for part in parts if part)

    digest_summary = _digest_text("summary_200chars")
    digest_themes = _digest_text("key_themes")
    digest_arc = _digest_text("emotional_arc")
    digest_effective = _digest_text("effective_interventions")
    digest_unresolved = _digest_text("unresolved_threads")
    digest_changes = _digest_text("significant_changes")

    if digest_summary and digest_summary != summary:
        candidates.append(
            {
                "memory_type": "state",
                "title": "近期状态",
                "summary": f"会话全景中的近期状态线索：{excerpt(digest_summary, 80)}",
                "content": f"会话全景中的近期状态线索：{excerpt(digest_summary, 80)}",
                "importance": 3,
                "tags": ["状态"],
            }
        )
    elif digest_themes or digest_arc:
        candidates.append(
            {
                "memory_type": "state",
                "title": "近期状态",
                "summary": f"会话全景中的状态线索：{excerpt(digest_themes or digest_arc, 80)}",
                "content": f"会话全景中的状态线索：{excerpt(digest_themes or digest_arc, 80)}",
                "importance": 3,
                "tags": ["状态"],
            }
        )

    if digest_effective:
        candidates.append(
            {
                "memory_type": "support_strategy",
                "title": "有效支持方式",
                "summary": f"会话全景记录的有效支持方式：{excerpt(digest_effective, 80)}",
                "content": f"会话全景记录的有效支持方式：{excerpt(digest_effective, 80)}",
                "importance": 4,
                "tags": ["支持方式"],
            }
        )

    if digest_unresolved:
        candidates.append(
            {
                "memory_type": "recurring_trigger",
                "title": "反复触发点",
                "summary": f"会话全景记录的未展开线索：{excerpt(digest_unresolved, 80)}",
                "content": f"会话全景记录的未展开线索：{excerpt(digest_unresolved, 80)}",
                "importance": 4,
                "tags": ["触发点"],
            }
        )

    if digest_changes:
        candidates.append(
            {
                "memory_type": "session_summary",
                "title": "本轮对话摘要",
                "summary": f"{summary}；会话全景补充：{excerpt(digest_changes, 80)}",
                "content": f"{summary}；会话全景补充：{excerpt(digest_changes, 80)}",
                "importance": 3,
                "tags": ["摘要"],
            }
        )

    if has_any_text(
        text,
        (
            "不要一上来",
            "别一上来",
            "不要直接",
            "别直接",
            "别急着",
            "先别",
            "先听我",
            "听我说",
            "别分析",
            "不要分析",
            "别下结论",
            "不是这个意思",
            "不喜欢你这样",
        ),
    ):
        candidates.append(
            {
                "memory_type": "correction",
                "title": "纠错偏好",
                "summary": f"用户明确纠正陪伴方式：{compact_text}",
                "content": f"用户明确纠正陪伴方式：{compact_text}",
                "importance": 5,
                "tags": ["纠错", "支持方式"],
            }
        )

    if has_any_text(text, ("喜欢", "希望", "更想", "更希望", "不要", "别", "少一点", "直接", "温柔", "安慰", "分析", "提问", "先听", "先陪")):
        candidates.append(
            {
                "memory_type": "preference",
                "title": "陪伴偏好",
                "summary": f"用户表达了陪伴偏好：{compact_text}",
                "content": f"用户表达了陪伴偏好：{compact_text}",
                "importance": 4,
                "tags": ["支持方式"],
            }
        )
    if has_any_text(text, ("经常", "总是", "每次", "一到", "睡前", "考试", "开会", "触发", "反复", "又开始")):
        candidates.append(
            {
                "memory_type": "recurring_trigger",
                "title": "反复触发点",
                "summary": f"用户提到可能反复出现的困扰或触发点：{compact_text}",
                "content": f"用户提到可能反复出现的困扰或触发点：{compact_text}",
                "importance": 4,
                "tags": ["触发点"],
            }
        )
    if has_any_text(text, ("呼吸", "练习", "有用", "有效", "帮助", "适合", "先陪", "先听", "梳理", "grounding", "稳定")):
        candidates.append(
            {
                "memory_type": "support_strategy",
                "title": "有效支持方式",
                "summary": f"用户提到可能有帮助的支持方式：{compact_text}",
                "content": f"用户提到可能有帮助的支持方式：{compact_text}",
                "importance": 4,
                "tags": ["支持方式"],
            }
        )
    if has_any_text(text, ("朋友", "家人", "妈妈", "爸爸", "同学", "老师", "伴侣", "恋人", "室友", "关系")):
        candidates.append(
            {
                "memory_type": "relationship",
                "title": "关系主题",
                "summary": f"用户提到重要关系或关系困扰：{compact_text}",
                "content": f"用户提到重要关系或关系困扰：{compact_text}",
                "importance": 3,
                "tags": ["关系"],
            }
        )
    if has_any_text(text, ("最近", "这两周", "长期", "一直", "睡眠", "失眠", "焦虑", "低落", "疲惫", "压力", "情绪")):
        candidates.append(
            {
                "memory_type": "state",
                "title": "近期状态",
                "summary": f"用户提到近期状态线索：{compact_text}",
                "content": f"用户提到近期状态线索：{compact_text}",
                "importance": 3,
                "tags": ["状态"],
            }
        )
    if has_any_text(text, ("我叫", "可以叫我", "我是", "我在读", "我是大学生", "我工作")):
        candidates.append(
            {
                "memory_type": "profile",
                "title": "基础画像线索",
                "summary": f"用户提供了基础画像线索：{compact_text}",
                "content": f"用户提供了基础画像线索：{compact_text}",
                "importance": 3,
                "tags": ["画像"],
            }
        )
    return {"memory_candidates": candidates[:8], "memory_policy_reason": "long_term_structured"}


async def write_memory(state: AgentState) -> AgentState:
    tags = list(state.get("audit_tags", []))
    tags.append("memory_written")
    return {
        "should_write_memory": True,
        "audit_tags": tags,
    }


async def skip_memory(state: AgentState) -> AgentState:
    tags = list(state.get("audit_tags", []))
    tags.append("memory_skipped")
    return {
        "should_write_memory": False,
        "audit_tags": tags,
    }
