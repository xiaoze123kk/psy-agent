from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


KnowledgeScopeStatus = Literal["in_scope", "out_of_scope"]


@dataclass(frozen=True)
class ExpandedKnowledgeQuery:
    normalized: str
    strong_terms: tuple[str, ...]
    weak_terms: tuple[str, ...]

    @property
    def terms(self) -> tuple[str, ...]:
        return (*self.strong_terms, *self.weak_terms)


DISTRESS_TERMS: tuple[str, ...] = (
    "焦虑",
    "紧张",
    "害怕",
    "恐惧",
    "担心",
    "崩溃",
    "痛苦",
    "羞耻",
    "羞愧",
    "内疚",
    "自责",
    "失控",
    "控制不住",
    "戒不掉",
    "困扰",
    "难受",
    "低落",
    "孤独",
    "烦躁",
    "自卑",
    "睡不着",
    "失眠",
    "影响生活",
    "影响学习",
    "影响工作",
)

PSYCHOLOGY_TERMS: tuple[str, ...] = (
    "心理",
    "心理学",
    "心理健康",
    "情绪",
    "压力",
    "睡眠",
    "睡前",
    "脑子停不下来",
    "心慌",
    "恐慌",
    "惊恐",
    "抑郁",
    "抑郁症",
    "兴趣下降",
    "强迫",
    "强迫症",
    "双相",
    "躁郁",
    "躁狂",
    "轻躁狂",
    "饮食障碍",
    "厌食",
    "贪食",
    "暴食",
    "边缘型人格",
    "bpd",
    "创伤",
    "应激",
    "ptsd",
    "ocd",
    "adhd",
    "cbt",
    "dbt",
    "emdr",
    "act",
    "创伤后应激",
    "创伤后压力",
    "创伤后应激障碍",
    "解离",
    "闪回",
    "倦怠",
    "耗竭",
    "认知偏差",
    "边界感",
    "边界",
    "依恋",
    "自尊",
    "敏感",
    "内耗",
    "反刍",
    "拖延",
    "正念",
    "冥想",
    "咨询",
    "求助",
)

SEXUAL_KNOWLEDGE_TERMS: tuple[str, ...] = (
    "打飞机",
    "自慰",
    "手淫",
    "性行为",
    "性生活",
    "性姿势",
    "避孕",
    "阳痿",
    "早泄",
    "射精",
)

OUT_OF_SCOPE_TERMS: tuple[str, ...] = (
    "代码",
    "编程",
    "python",
    "javascript",
    "java",
    "数据库",
    "股票",
    "基金",
    "投资",
    "理财",
    "路线",
    "导航",
    "天气",
    "翻译",
    "英语怎么说",
    "数学",
    "物理",
    "化学",
    "历史",
    "新闻",
    "游戏",
    "电影",
    "笑话",
)

RELATIONSHIP_TERMS: tuple[str, ...] = (
    "父母",
    "家人",
    "妈妈",
    "爸爸",
    "同学",
    "朋友",
    "伴侣",
    "恋人",
    "对象",
    "室友",
    "同事",
    "老师",
    "老板",
)

RELATIONSHIP_PROBLEM_TERMS: tuple[str, ...] = (
    "吵架",
    "冷战",
    "沟通",
    "相处",
    "拒绝",
    "讨好",
    "分手",
    "排挤",
    "欺负",
    "依赖",
    "抛弃",
)

SUPPORT_REQUEST_TERMS: tuple[str, ...] = (
    "怎么办",
    "怎么缓解",
    "怎么调节",
    "怎么面对",
    "怎么处理",
    "怎么走出来",
)

INTERNAL_STATE_TERMS: tuple[str, ...] = (
    "心里",
    "脑子",
    "情绪",
    "状态",
    "感受",
    "累",
    "烦",
    "怕",
)

QUERY_STOP_PHRASES: tuple[str, ...] = (
    "是什么",
    "是啥",
    "什么意思",
    "啥意思",
    "怎么办",
    "怎么回事",
    "有用吗",
    "为什么",
    "如何",
    "怎么",
)

SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "创伤后应激障碍": ("ptsd", "pstd", "创伤后应激障碍", "创伤后应激", "创伤后压力", "创伤", "创上", "闪回", "噩梦"),
    "抑郁": ("抑郁", "抑欲", "抑豫", "抑郁症", "低落", "兴趣下降", "无望", "开心不起来"),
    "强迫": ("ocd", "ocb", "强迫症", "强迫障碍", "强迫", "强破", "反复检查"),
    "注意缺陷多动": ("adhd", "ahdh", "注意缺陷多动", "注意力缺陷", "多动", "注意力不集中"),
    "双相": ("双相", "躁郁", "躁狂", "轻躁狂", "心境障碍", "精力很高", "睡很少"),
    "饮食障碍": ("饮食障碍", "厌食", "贪食", "暴食", "爆食", "身体形象", "催吐", "过度运动"),
    "边缘型人格": ("bpd", "边缘型人格", "边缘型人格障碍", "情绪不稳定", "害怕被抛下", "空虚感", "解离", "解理"),
    "压力焦虑": ("压力", "鸭梨", "压力源", "焦虑", "焦绿", "焦滤", "交虑", "叫虑", "担心", "紧绷", "应对压力"),
    "认知行为疗法": ("cbt", "认知行为疗法", "认知行为治疗", "认知重评", "认知偏差", "自动想法"),
    "辩证行为疗法": ("dbt", "辩证行为疗法", "情绪调节", "痛苦耐受"),
    "眼动脱敏再加工": ("emdr", "眼动脱敏", "眼动脱敏再加工", "创伤治疗"),
    "失眠": ("睡不着", "睡不卓", "失眠", "失棉", "失绵", "睡前", "脑子停不下来", "入睡困难"),
    "惊恐": ("心慌", "惊恐", "惊孔", "恐慌", "恐荒", "惊恐发作", "身体警报", "呼吸"),
    "反刍": ("内耗", "内号", "反刍", "反处", "反厨", "反复想", "想太多", "复盘停不下来", "脑子停不下来"),
    "边界": ("边界感", "边界", "边届", "边介", "拒绝", "讨好", "关系边界"),
    "焦虑依恋": ("焦虑依恋", "依恋", "安全感", "关系焦虑"),
    "心理耗竭": ("耗竭", "倦怠", "心理耗竭", "burnout", "精力恢复不过来"),
}

TYPO_CORRECTIONS: dict[str, str] = {
    "pstd": "ptsd",
    "ocb": "ocd",
    "ahdh": "adhd",
    "创上": "创伤",
    "抑欲": "抑郁",
    "抑豫": "抑郁",
    "强破": "强迫",
    "爆食": "暴食",
    "解理": "解离",
    "鸭梨": "压力",
    "焦绿": "焦虑",
    "焦滤": "焦虑",
    "交虑": "焦虑",
    "叫虑": "焦虑",
    "睡不卓": "睡不着",
    "失棉": "失眠",
    "失绵": "失眠",
    "惊孔": "惊恐",
    "恐荒": "恐慌",
    "内号": "内耗",
    "反处": "反刍",
    "反厨": "反刍",
    "边届": "边界",
    "边介": "边界",
}


def normalize_knowledge_text(text: str) -> str:
    compact = " ".join(text.strip().lower().split())
    punctuation = "？！，。；：（）【】《》、“”‘’"
    translated = compact.translate({ord(char): " " for char in punctuation})
    return " ".join(translated.split())


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _ordered_unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _is_usable_term(term: str) -> bool:
    stripped = term.strip()
    if not stripped:
        return False
    if stripped.isascii():
        return len(stripped) >= 2
    return len(stripped) >= 2


def _without_stop_phrases(text: str) -> str:
    cleaned = text
    for phrase in QUERY_STOP_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    return " ".join(cleaned.split())


def expand_knowledge_query(query: str) -> ExpandedKnowledgeQuery:
    normalized = normalize_knowledge_text(apply_known_typo_corrections(query)[0])
    strong_terms: list[str] = []
    weak_terms: list[str] = []

    cleaned_query = _without_stop_phrases(normalized)
    if _is_usable_term(cleaned_query) and cleaned_query != normalized:
        strong_terms.append(cleaned_query)

    for token in re.findall(r"[a-z0-9]{2,}", normalized):
        strong_terms.append(token)

    for aliases in SYNONYM_GROUPS.values():
        if any(alias in normalized for alias in aliases):
            strong_terms.extend(aliases)

    for term in PSYCHOLOGY_TERMS:
        if term in normalized:
            strong_terms.append(term)

    for term in RELATIONSHIP_TERMS + RELATIONSHIP_PROBLEM_TERMS:
        if term in normalized:
            strong_terms.append(term)

    for term in DISTRESS_TERMS + INTERNAL_STATE_TERMS:
        if term in normalized and _is_usable_term(term):
            weak_terms.append(term)

    return ExpandedKnowledgeQuery(
        normalized=normalized,
        strong_terms=_ordered_unique([term for term in strong_terms if _is_usable_term(term)]),
        weak_terms=_ordered_unique([term for term in weak_terms if _is_usable_term(term)]),
    )


def classify_knowledge_scope(question: str) -> KnowledgeScopeStatus:
    normalized = normalize_knowledge_text(apply_known_typo_corrections(question)[0])
    if not normalized:
        return "out_of_scope"

    if contains_any(normalized, DISTRESS_TERMS):
        return "in_scope"
    if contains_any(normalized, PSYCHOLOGY_TERMS):
        return "in_scope"
    if contains_any(normalized, RELATIONSHIP_TERMS) and contains_any(normalized, RELATIONSHIP_PROBLEM_TERMS):
        return "in_scope"
    if contains_any(normalized, SUPPORT_REQUEST_TERMS) and contains_any(normalized, INTERNAL_STATE_TERMS):
        return "in_scope"
    if contains_any(normalized, SEXUAL_KNOWLEDGE_TERMS):
        return "out_of_scope"
    if contains_any(normalized, OUT_OF_SCOPE_TERMS):
        return "out_of_scope"
    return "out_of_scope"


def apply_known_typo_corrections(question: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    corrected = normalize_knowledge_text(question)
    replacements: list[tuple[str, str]] = []
    for alias, canonical in TYPO_CORRECTIONS.items():
        normalized_alias = normalize_knowledge_text(alias)
        if not normalized_alias or normalized_alias == canonical:
            continue
        if normalized_alias not in corrected:
            continue
        corrected = corrected.replace(normalized_alias, canonical)
        replacements.append((alias, canonical))
    return corrected, tuple(replacements)
