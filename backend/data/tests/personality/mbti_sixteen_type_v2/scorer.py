import json
from pathlib import Path
from typing import Dict


def _load_score_data() -> dict:
    score_path = Path(__file__).resolve().parent / "mbti_sixteen_type_v2_score.json"
    with open(score_path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute(test: dict, answers: dict[int, str]) -> dict:
    score_data = _load_score_data()
    scoring = score_data["scoring"]
    question_mapping = scoring["question_mapping"]
    dimensions_def = scoring["dimensions"]
    clarity_levels = scoring["clarity_levels"]
    results = score_data["results"]

    dim_order = ["EI", "SN", "TF", "JP"]
    dim_scores = {d: {"pole_a": 0, "pole_b": 0} for d in dim_order}

    for qi_str, mapping in question_mapping.items():
        qi = int(qi_str)
        answer = answers.get(qi)
        if answer is None:
            continue
        dim = mapping["dimension"]
        pole_a_letter = mapping["A"]
        pole_b_letter = mapping["B"]
        if answer == "A":
            dim_scores[dim]["pole_a"] += 1
        elif answer == "B":
            dim_scores[dim]["pole_b"] += 1

    type_code = ""
    dimension_results = {}

    for dim in dim_order:
        scores = dim_scores[dim]
        pole_a_label = dimensions_def[dim]["pole_a"]
        pole_b_label = dimensions_def[dim]["pole_b"]
        diff = scores["pole_a"] - scores["pole_b"]

        if diff > 0:
            preferred_pole = pole_a_label
            preferred_label = dimensions_def[dim]["pole_a_label"]
            non_preferred_label = dimensions_def[dim]["pole_b_label"]
        elif diff < 0:
            preferred_pole = pole_b_label
            preferred_label = dimensions_def[dim]["pole_b_label"]
            non_preferred_label = dimensions_def[dim]["pole_a_label"]
        else:
            preferred_pole = pole_a_label
            preferred_label = dimensions_def[dim]["pole_a_label"]
            non_preferred_label = dimensions_def[dim]["pole_b_label"]

        clarity = abs(diff) * 2

        clarity_level = clarity_levels[-1]["level"]
        clarity_desc = clarity_levels[-1]["description"]
        for cl in clarity_levels:
            if cl["min"] <= clarity <= cl["max"]:
                clarity_level = cl["level"]
                clarity_desc = cl["description"]
                break

        type_code += preferred_pole

        dimension_results[dim] = {
            "dimension_label": dimensions_def[dim]["label"],
            "pole_a": {
                "letter": pole_a_label,
                "label": dimensions_def[dim]["pole_a_label"],
                "score": scores["pole_a"],
            },
            "pole_b": {
                "letter": pole_b_label,
                "label": dimensions_def[dim]["pole_b_label"],
                "score": scores["pole_b"],
            },
            "preferred_pole": preferred_pole,
            "preferred_label": preferred_label,
            "non_preferred_label": non_preferred_label,
            "clarity": clarity,
            "clarity_level": clarity_level,
            "clarity_description": clarity_desc,
        }

    type_info = results.get(type_code, {})
    if type_code[1] == "N":
        type_group_code = "N" + type_code[2]
    else:
        type_group_code = "S" + type_code[3]
    type_group_info = scoring.get("type_groups", {}).get(type_group_code, {})

    return {
        "result_code": type_code,
        "result_label": type_info.get("result_label", type_code),
        "summary": type_info.get("summary", ""),
        "suggested_actions": type_info.get("suggested_actions", []),
        "traits": type_info.get("traits", []),
        "strengths": type_info.get("strengths", []),
        "blind_spots": type_info.get("blind_spots", []),
        "companion_style": type_info.get("companion_style", ""),
        "risk_note": type_info.get("risk_note", ""),
        "sixteen_type_code": type_code,
        "sixteen_type_label": type_info.get("sixteen_type_label", ""),
        "dimension_scores": dimension_results,
        "type_group": {
            "code": type_group_code,
            "label": type_group_info.get("label", ""),
            "description": type_group_info.get("description", ""),
        },
    }
