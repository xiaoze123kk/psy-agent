"""MBTI 16型人格测试评分模块

compute(test, answers) -> dict
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SCORE_DIR = Path(__file__).resolve().parent

_SIXTEEN_TYPE_RESULTS = {
    "INFJ": {
        "result_code": "INFJ-like",
        "result_label": "洞察型陪伴者",
        "summary": "你对他人的情绪很敏感，容易想得很深，擅长洞察他人的需求。珍惜你的同理心和创造力，但也请记得照顾好自己的边界，学会在付出与自我之间找到平衡。",
        "traits": ["对他人的情绪很敏感", "容易想得很深", "压力下会过度消耗自己", "重视深层联结", "很有同理心"],
        "strengths": ["善于洞察他人需求", "忠诚且有耐心", "富有创造力"],
        "blind_spots": ["容易忽略自己的需求", "过度反省", "难以拒绝别人"],
        "companion_style": "先接住情绪，再轻轻拓宽视角",
    },
    "ESTP": {
        "result_code": "ESTP-like",
        "result_label": "适应型行动者",
        "summary": "你务实灵活，擅长临场应变，喜欢动手解决问题。你的行动力是你最大的优势，试着在快速行动的同时也偶尔停下来感受一下内在的情绪节奏。",
        "traits": ["务实灵活", "擅长临场应变", "喜欢动手解决问题", "能量来得快去得也快", "注重当下效果"],
        "strengths": ["行动力强", "危机时很靠谱", "善于抓住机会"],
        "blind_spots": ["容易忽略深层情绪", "有时显得不耐烦", "容易厌倦重复"],
        "companion_style": "给具体可执行的很小步骤，别讲大道理",
    },
    "INFP": {
        "result_code": "INFP-like",
        "result_label": "理想型调和者",
        "summary": "你内心世界丰富，追求意义和真实，对美和情感很敏感。你的深度共情和创造力是珍贵的礼物，记得把理想落地为小步骤，让梦想也能在日常中生长。",
        "traits": ["内心世界丰富", "追求意义和真实", "对美和情感很敏感", "灵活包容", "有时沉浸在想象中"],
        "strengths": ["深度共情", "创造性表达", "尊重个体差异"],
        "blind_spots": ["容易拖延", "有时过度理想化", "对批评很敏感"],
        "companion_style": "先肯定感受的正当性，再一起找到意义",
    },
    "ENTJ": {
        "result_code": "ENTJ-like",
        "result_label": "策略型推动者",
        "summary": "你目标导向，喜欢掌控和规划，有很强的意志力。你的领导力和抗压能力令人佩服，但也请允许自己偶尔卸下盔甲，承认疲惫并不可耻。",
        "traits": ["目标导向", "喜欢掌控和规划", "有很强的意志力", "注重效率和成果", "不习惯表达脆弱"],
        "strengths": ["有领导力", "抗压能力强", "善于统筹资源"],
        "blind_spots": ["容易忽略自己和他人的情感", "太想掌控", "累到崩溃才停下来"],
        "companion_style": "先承认压力已经很大了，再一起拆成小目标",
    },
}

_TRAD_DIM_ORDER = ["E-I", "S-N", "T-F", "J-P"]

_TRAD_DIM_POSITIVE = {"E-I": "E", "S-N": "S", "T-F": "T", "J-P": "J"}
_TRAD_DIM_NEGATIVE = {"E-I": "I", "S-N": "N", "T-F": "F", "J-P": "P"}


def _load_score_data() -> dict:
    score_files = list(_SCORE_DIR.glob("*_score_*.json"))
    if not score_files:
        logger.error("No score file found in %s", _SCORE_DIR)
        return {}
    return json.loads(score_files[0].read_text(encoding="utf-8"))


def _parse_content(content: str) -> dict[str, str]:
    """解析富文本 content 字段，提取问题正文、选项A、选项B。"""
    result = {"question": "", "option_a": "", "option_b": ""}

    question_match = re.search(r"【问题】\s*(.+?)(?:\n|$)", content)
    if question_match:
        result["question"] = question_match.group(1).strip()

    a_match = re.search(r"\bA\.\s*(.+?)(?:\n|$)", content)
    if a_match:
        result["option_a"] = a_match.group(1).strip()

    b_match = re.search(r"\bB\.\s*(.+?)(?:\n|$)", content)
    if b_match:
        result["option_b"] = b_match.group(1).strip()

    return result


def _parse_normalized(normalized: str) -> dict[str, int]:
    """从 normalized 字符串提取 A/B 计分规则。

    认知堆叠格式: "A=1（1分），另一选项计0分" 或 "B=1（1分），另一选项计0分"
    传统维度格式: "A → E（计1分），B → I（计0分）"，A 始终得 1 分。
    """
    if not normalized:
        return {"A": 0, "B": 0}
    if "A=1" in normalized:
        return {"A": 1, "B": 0}
    if "B=1" in normalized:
        return {"A": 0, "B": 1}
    return {"A": 1, "B": 0}


def _score_items(score_items: list, answers: dict[int | str, str]) -> int:
    """根据 score items（含 1-based index）和用户答案计算总分。"""
    total = 0
    for item in score_items:
        idx_1based = item["index"]
        idx_0based = idx_1based - 1
        answer = answers.get(idx_0based)
        if answer is None:
            answer = answers.get(str(idx_0based))
        if answer is None:
            continue
        normalized = item.get("scoring", {}).get("normalized", "")
        scoring = _parse_normalized(normalized)
        total += scoring.get(answer, 0)
    return total


def _build_generic_result(type_code: str) -> dict:
    """当 score JSON 和 _SIXTEEN_TYPE_RESULTS 均无对应类型时，构建通用结果。"""
    return {
        "result_code": type_code,
        "result_label": f"{type_code} 类型",
        "summary": f"你的认知功能组合与 {type_code} 类型最为接近。",
        "suggested_actions": [],
        "traits": [],
        "strengths": [],
        "blind_spots": [],
        "companion_style": "",
        "sixteen_type_code": type_code,
        "sixteen_type_label": f"{type_code} 类型",
    }


def compute(test: dict, answers: dict[int | str, str]) -> dict:
    score_data = _load_score_data()
    if not score_data:
        return _build_generic_result("UNKN")

    scoring_rules = score_data.get("scoring", {})
    trad_dims = scoring_rules.get("traditional_dimensions", {})
    dim_scores: dict[str, int] = {}
    for dim_key in _TRAD_DIM_ORDER:
        dim_data = trad_dims.get(dim_key, {})
        items = dim_data.get("items", [])
        dim_scores[dim_key] = _score_items(items, answers)

    code_parts = []
    for dim_key in _TRAD_DIM_ORDER:
        score = dim_scores.get(dim_key, 0)
        if score >= 2:
            code_parts.append(_TRAD_DIM_POSITIVE[dim_key])
        else:
            code_parts.append(_TRAD_DIM_NEGATIVE[dim_key])
    traditional_code = "".join(code_parts)

    cross_rules = scoring_rules.get("cross_validation_rules", {})
    dim_confidences: dict[str, str] = {}
    for dim_key in _TRAD_DIM_ORDER:
        score = dim_scores.get(dim_key, 0)
        if score == 4 or score == 0:
            dim_confidences[dim_key] = "高"
        elif score == 3 or score == 1:
            dim_confidences[dim_key] = "中"
        else:
            dim_confidences[dim_key] = "边界模糊"

    cog_stacks = scoring_rules.get("cognitive_stacks", {})
    type_scores: dict[str, int] = {}
    for type_key, type_data in cog_stacks.items():
        items = type_data.get("items", [])
        type_scores[type_key] = _score_items(items, answers)

    best_type = max(type_scores, key=type_scores.get) if type_scores else ""
    best_score = type_scores.get(best_type, 0)

    if best_score >= 4:
        type_confidence = "高匹配"
    elif best_score >= 3:
        type_confidence = "中等匹配"
    else:
        type_confidence = "低匹配"

    result_interp = score_data.get("results", {})
    type_interp = result_interp.get(best_type, {})
    interp_summary = type_interp.get(type_confidence, "")

    has_valid_interp = bool(interp_summary and "请根据知识库" not in interp_summary)

    fallback = _SIXTEEN_TYPE_RESULTS.get(best_type)
    if not fallback:
        fallback = _SIXTEEN_TYPE_RESULTS.get(traditional_code)

    if fallback:
        summary = interp_summary if has_valid_interp else fallback["summary"]
        return {
            "result_code": fallback["result_code"],
            "result_label": fallback["result_label"],
            "summary": summary,
            "suggested_actions": fallback.get("suggested_actions", []),
            "traits": fallback["traits"],
            "strengths": fallback["strengths"],
            "blind_spots": fallback["blind_spots"],
            "companion_style": fallback["companion_style"],
            "sixteen_type_code": best_type,
            "sixteen_type_label": fallback["result_label"],
        }

    if has_valid_interp:
        return {
            "result_code": best_type,
            "result_label": f"{best_type} 类型",
            "summary": interp_summary,
            "suggested_actions": [],
            "traits": [],
            "strengths": [],
            "blind_spots": [],
            "companion_style": "",
            "sixteen_type_code": best_type,
            "sixteen_type_label": f"{best_type} 类型",
        }

    return _build_generic_result(best_type)
