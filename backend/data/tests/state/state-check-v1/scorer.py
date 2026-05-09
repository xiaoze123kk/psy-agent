"""今日状态测试评分模块

compute(test, answers) -> dict
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCORE_DIR = Path(__file__).resolve().parent


def _load_score_data() -> dict:
    score_files = list(_SCORE_DIR.glob("*score*.json"))
    if not score_files:
        logger.error("No score file found in %s", _SCORE_DIR)
        return {}
    return json.loads(score_files[0].read_text(encoding="utf-8"))


def compute(test: dict, answers: dict[int, str]) -> dict:
    score_data = _load_score_data()
    scoring = score_data.get("scoring", {})
    option_scores = scoring.get("option_scores", {})
    total = 0
    for idx_str, opt_id in answers.items():
        idx = int(idx_str)
        scores_for_q = option_scores.get(str(idx), {})
        total += scores_for_q.get(opt_id, 0)

    thresholds = scoring.get("thresholds", [])
    for entry in thresholds:
        if total >= entry["min_total"]:
            return {
                "result_code": entry["result_code"],
                "result_label": entry["result_label"],
                "summary": entry["summary"],
                "risk_note": entry.get("risk_note", ""),
                "suggested_actions": entry.get("suggested_actions", []),
                "traits": entry.get("traits", []),
                "strengths": entry.get("strengths", []),
                "blind_spots": entry.get("blind_spots", []),
                "companion_style": entry.get("companion_style", ""),
            }

    default = score_data.get("default_result", {})
    return {
        "result_code": default.get("result_code", "burdened"),
        "result_label": default.get("result_label", ""),
        "summary": default.get("summary", ""),
        "risk_note": default.get("risk_note", ""),
        "suggested_actions": default.get("suggested_actions", []),
        "traits": default.get("traits", []),
        "strengths": default.get("strengths", []),
        "blind_spots": default.get("blind_spots", []),
        "companion_style": default.get("companion_style", ""),
    }
