from __future__ import annotations

from typing import Any

from app.services.compact_context_service import build_compact_context_pack


def _compact_text(value: object, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _compact_list(value: object, *, limit: int = 5, item_limit: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _compact_text(item, limit=item_limit)
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _message_metadata(message: object) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {}
    metadata = message.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _latest_compact_pack(recent_messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(recent_messages or []):
        if not isinstance(message, dict) or str(message.get("role") or "") != "assistant":
            continue
        pack = _message_metadata(message).get("compact_context_pack")
        if isinstance(pack, dict) and pack:
            return pack
    return {}


def _focus_lines(focus: object) -> list[str]:
    return _compact_list(focus, limit=6, item_limit=80)


def apply_manual_compact_hint(pack: dict[str, Any], focus: list[str]) -> dict[str, Any]:
    if not isinstance(pack, dict):
        return {}
    hinted = dict(pack)
    event = dict(hinted.get("event") or {})
    trigger = dict(event.get("trigger") or {})
    reasons = [
        str(reason)
        for reason in trigger.get("reason", [])
        if str(reason or "").strip()
    ] if isinstance(trigger.get("reason"), list) else []
    if "manual_hint" not in reasons:
        reasons.append("manual_hint")
    trigger["reason"] = reasons
    event["trigger"] = trigger
    if focus:
        event["hint"] = {"focus": focus}
    hinted["event"] = event
    return hinted


def compact_prompt_view(pack: dict[str, Any]) -> str:
    if not isinstance(pack, dict) or not pack:
        return "当前没有可用的 compact 状态。"
    compact_state = pack.get("state")
    if not isinstance(compact_state, dict) or not compact_state:
        return "当前 compact 状态为空。"

    lines: list[str] = []
    summary = _compact_text(compact_state.get("summary_for_prompt"), limit=220)
    if summary:
        lines.append(f"短期连续性：{summary}")

    active_threads = compact_state.get("active_threads")
    if isinstance(active_threads, list):
        for thread in active_threads[:3]:
            if not isinstance(thread, dict):
                continue
            topic = _compact_text(thread.get("topic"), limit=80)
            hint = _compact_text(thread.get("next_move_hint"), limit=100)
            if topic and hint:
                lines.append(f"当前活跃话题：{topic}；下一步：{hint}")
            elif topic:
                lines.append(f"当前活跃话题：{topic}")

    stale_threads = compact_state.get("stale_threads")
    if isinstance(stale_threads, list):
        for thread in stale_threads[:3]:
            if not isinstance(thread, dict):
                continue
            topic = _compact_text(thread.get("topic"), limit=80)
            reuse_policy = _compact_text(thread.get("reuse_policy"), limit=120)
            if topic and reuse_policy:
                lines.append(f"旧锚点降权：{topic}；{reuse_policy}")
            elif topic:
                lines.append(f"旧锚点降权：{topic}；除非用户主动提起，否则不要复用。")

    boundaries = _compact_list(compact_state.get("user_boundaries"), limit=4)
    if boundaries:
        lines.append(f"用户边界：{'、'.join(boundaries)}")

    preferences = _compact_list(compact_state.get("interaction_preferences"), limit=4)
    if preferences:
        lines.append(f"互动偏好：{'、'.join(preferences)}")

    time_policy = compact_state.get("time_context_policy")
    if isinstance(time_policy, dict):
        timezone_name = _compact_text(time_policy.get("timezone"), limit=40)
        if timezone_name:
            lines.append(f"时间策略：{timezone_name}；当前时间由运行时提供。")

    quality_signals = compact_state.get("quality_signals")
    if isinstance(quality_signals, dict):
        quality_lines: list[str] = []
        for key, label in (
            ("recent_repetition_risk", "重复风险"),
            ("recent_over_questioning_risk", "追问过密风险"),
            ("stale_anchor_misuse_risk", "旧锚点误用风险"),
            ("context_break_risk", "上下文断裂风险"),
            ("user_correction_signal", "用户纠正"),
            ("topic_drift_risk", "跑题风险"),
        ):
            value = _compact_text(quality_signals.get(key), limit=24)
            if value:
                quality_lines.append(f"{label}={value}")
        if quality_lines:
            lines.append(f"质量提醒：{'；'.join(quality_lines)}")

    hint = ((pack.get("event") or {}).get("hint") or {}) if isinstance(pack.get("event"), dict) else {}
    focus = _focus_lines(hint.get("focus") if isinstance(hint, dict) else None)
    if focus:
        lines.append(f"手动 compact hint：{'、'.join(focus)}")

    if not lines:
        return "当前 compact 状态没有可渲染内容。"
    return "当前会话压缩状态（调试预览，不要直接复述）：\n" + "\n".join(f"- {line}" for line in lines)


def _compact_metrics(pack: dict[str, Any]) -> dict[str, Any]:
    event = pack.get("event") if isinstance(pack.get("event"), dict) else {}
    compact_state = pack.get("state") if isinstance(pack.get("state"), dict) else {}
    stale_threads = compact_state.get("stale_threads") if isinstance(compact_state, dict) else []
    memory_candidates = pack.get("memory_candidates") if isinstance(pack.get("memory_candidates"), list) else []
    trigger = event.get("trigger") if isinstance(event, dict) else {}
    return {
        "message_count": trigger.get("message_count") if isinstance(trigger, dict) else None,
        "usage_ratio": trigger.get("usage_ratio") if isinstance(trigger, dict) else None,
        "stale_thread_count": len(stale_threads) if isinstance(stale_threads, list) else 0,
        "memory_candidate_count": len(memory_candidates),
    }


def build_compact_debug_view(
    *,
    recent_messages: list[dict[str, Any]],
    session_digest: dict[str, Any] | None,
    risk_level: str,
) -> dict[str, Any]:
    pack = _latest_compact_pack(recent_messages)
    if not pack:
        pack = build_compact_context_pack(
            recent_messages=recent_messages,
            session_digest=session_digest or {},
            risk_level=risk_level,
        )
    event = pack.get("event") if isinstance(pack.get("event"), dict) else {}
    compact_state = pack.get("state") if isinstance(pack.get("state"), dict) else {}
    return {
        "has_compact": bool(pack),
        "latest_event": event,
        "state": compact_state,
        "metrics": _compact_metrics(pack),
        "prompt_view": compact_prompt_view(pack),
    }


def build_manual_compact_preview(
    *,
    recent_messages: list[dict[str, Any]],
    session_digest: dict[str, Any] | None,
    risk_level: str,
    focus: list[str] | None = None,
    max_recent_messages: int = 10,
    created_at: str = "",
) -> dict[str, Any]:
    focus_lines = _focus_lines(focus or [])
    pack = build_compact_context_pack(
        recent_messages=recent_messages,
        session_digest=session_digest or {},
        risk_level=risk_level,
        max_recent_messages=max_recent_messages,
        created_at=created_at,
    )
    pack = apply_manual_compact_hint(pack, focus_lines)
    return {
        "persisted": False,
        "pack": pack,
        "prompt_diff": {
            "without_compact": "未注入 compact 状态；仅依赖最近原文窗口、长期记忆和运行时上下文。",
            "with_compact": compact_prompt_view(pack),
        },
    }
