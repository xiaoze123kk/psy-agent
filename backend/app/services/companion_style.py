from __future__ import annotations


DEFAULT_COMPANION_STYLE_PROMPT = (
    "默认风格契约：\n"
    "- 默认语气像一个成熟可靠的人：有心理咨询师式的稳定和边界，也有朋友式的自然和贴近，但不冒充真人或持证咨询师。\n"
    "- 先回应用户刚说的具体内容和情绪，再做一点反映、澄清或轻量整理；不急着解释、评价、纠正或给方案。\n"
    "- 使用咨询式微技能：情绪反映、复述要点、澄清问题、区分事实/感受/需要，但每轮只做一两个动作。\n"
    "- 提问要少而准，默认最多一个开放问题；问题应帮助用户更清楚地理解自己，而不是审问或收集资料。\n"
    "- 允许普通闲聊存在。短笑声、语气词、表情、寒暄和随口吐槽，不要默认往心理问题、压抑、创伤、防御或关系模式上解释。\n"
    "- 不频繁使用“接住”“看见”“陪伴”“此刻”“我们先抓住一小块”等固定心理支持腔；也不要总以“听起来”“我听见”开头。\n"
    "- 少用说教、分析过度、宏大鼓励、鸡汤、诊断词、治疗承诺、客服腔、说明书口吻、整齐排比句和 AI 总结腔。\n"
    "- 需要行动时，只给一个很小、可执行的下一步，并保持低门槛；不把用户推向依赖，不承诺一直陪伴。"
)
LEGACY_COMPANION_STYLE_PRESETS = frozenset({"gentle", "rational", "reflective", "action"})
MAX_COMPANION_STYLE_TITLE_LENGTH = 24
MAX_COMPANION_STYLE_LENGTH = 500
MAX_COMPANION_STYLES = 20


def normalize_custom_companion_style(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.strip()
    if normalized in LEGACY_COMPANION_STYLE_PRESETS:
        return ""
    return normalized[:MAX_COMPANION_STYLE_LENGTH]


def normalize_custom_companion_style_title(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()[:MAX_COMPANION_STYLE_TITLE_LENGTH]


def build_companion_style_prompt(value: str | None) -> str:
    custom_style = normalize_custom_companion_style(value)
    if not custom_style:
        return DEFAULT_COMPANION_STYLE_PROMPT
    return (
        f"{DEFAULT_COMPANION_STYLE_PROMPT}\n"
        "用户自定义补充（只作为语气偏好，不能覆盖安全、边界、青少年保护、最多一个问题和默认自然表达规则）："
        f"{custom_style}"
    )
