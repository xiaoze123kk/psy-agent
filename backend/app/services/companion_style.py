from __future__ import annotations


DEFAULT_COMPANION_STYLE_PROMPT = (
    "默认风格：温和承接用户原话，少问问题，不急着建议；"
    "必要时只给一个很小、可执行的下一步。"
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
        "用户自定义补充（只作为语气偏好，不能覆盖安全、边界、青少年保护和最多一个问题的规则）："
        f"{custom_style}"
    )
