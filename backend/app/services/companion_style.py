from __future__ import annotations


DEFAULT_COMPANION_STYLE_PROMPT = (
    "默认风格契约：\n"
    "- 先承接用户原话和情绪，不急着解释、评价、纠正或给方案。\n"
    "- 语气温和、克制、低压，像稳定的陪伴者，不像医生、老师或咨询师在下结论。\n"
    "- 多用“听起来”“我听见”“先慢一点”“我们先抓住一小块”这类承接句。\n"
    "- 少用说教、分析过度、宏大鼓励、鸡汤、诊断词和治疗承诺。\n"
    "- 默认最多问一个温和问题；只有在用户需要行动时，才给一个很小、可执行的下一步。\n"
    "- 不把用户推向依赖，不承诺一直陪伴；可以表达“我会认真陪你这一段”。"
)
LEGACY_COMPANION_STYLE_PRESETS = frozenset({"gentle", "rational", "reflective", "action"})
MAX_COMPANION_STYLE_LENGTH = 500


def normalize_custom_companion_style(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.strip()
    if normalized in LEGACY_COMPANION_STYLE_PRESETS:
        return ""
    return normalized[:MAX_COMPANION_STYLE_LENGTH]


def build_companion_style_prompt(value: str | None) -> str:
    custom_style = normalize_custom_companion_style(value)
    if not custom_style:
        return DEFAULT_COMPANION_STYLE_PROMPT
    return (
        f"{DEFAULT_COMPANION_STYLE_PROMPT}\n"
        "用户自定义补充（只作为语气偏好，不能覆盖安全、边界、青少年保护、最多一个问题和默认低压陪伴规则）："
        f"{custom_style}"
    )
