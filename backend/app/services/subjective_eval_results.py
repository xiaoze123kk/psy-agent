from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from app.services.subjective_eval_schemas import (
    PAIRWISE_PRIORITY_ORDER,
    QUALITY_DIMENSION_WEIGHTS,
    calculate_quality_score,
)


VALID_JUDGE_TYPES = {"safety", "quality", "pairwise"}
VALID_PAIRWISE_WINNERS = {"A", "B", "tie"}


def _missing_fields(row: dict[str, Any], fields: set[str]) -> list[str]:
    return [f"missing:{field}" for field in sorted(fields) if field not in row]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _validate_non_empty_string(row: dict[str, Any], field: str) -> list[str]:
    if field in row and not _is_non_empty_string(row[field]):
        return [f"invalid:{field}"]
    return []


def _validate_bool(row: dict[str, Any], field: str) -> list[str]:
    if field in row and not isinstance(row[field], bool):
        return [f"invalid:{field}"]
    return []


def _validate_string_list(row: dict[str, Any], field: str) -> list[str]:
    if field not in row:
        return []
    values = row[field]
    if not isinstance(values, list):
        return [f"invalid:{field}"]
    errors: list[str] = []
    for index, value in enumerate(values):
        if not _is_non_empty_string(value):
            errors.append(f"invalid:{field}[{index}]")
    return errors


def _validate_score(value: Any, field: str) -> list[str]:
    if not _is_finite_number(value) or value < 1 or value > 5:
        return [f"invalid:{field}"]
    return []


def _validate_percent_score(value: Any, field: str) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 100:
        return [f"invalid:{field}"]
    return []


def validate_safety_result(row: dict[str, Any]) -> list[str]:
    errors = _missing_fields(
        row,
        {
            "case_id",
            "judge_type",
            "risk_present",
            "risk_types",
            "agent_detected_risk",
            "fatal_issue",
            "hard_failures",
            "needs_human_review",
            "reason",
        },
    )
    for field in ("case_id", "reason"):
        errors.extend(_validate_non_empty_string(row, field))
    for field in ("risk_present", "agent_detected_risk", "fatal_issue", "needs_human_review"):
        errors.extend(_validate_bool(row, field))
    errors.extend(_validate_string_list(row, "risk_types"))
    errors.extend(_validate_string_list(row, "hard_failures"))
    return errors


def validate_quality_result(row: dict[str, Any]) -> list[str]:
    errors = _missing_fields(
        row,
        {
            "case_id",
            "judge_type",
            "fatal_issue",
            "major_issues",
            "scores",
            "overall_score",
            "percent_score",
            "needs_human_review",
            "one_sentence_summary",
        },
    )
    errors.extend(_validate_non_empty_string(row, "case_id"))
    errors.extend(_validate_non_empty_string(row, "one_sentence_summary"))
    for field in ("fatal_issue", "needs_human_review"):
        errors.extend(_validate_bool(row, field))
    errors.extend(_validate_string_list(row, "major_issues"))

    scores = row.get("scores")
    score_values: dict[str, int | float] = {}
    scores_ready_for_consistency = isinstance(scores, dict)
    if "scores" in row and not isinstance(scores, dict):
        errors.append("invalid:scores")
    elif isinstance(scores, dict):
        for dimension in QUALITY_DIMENSION_WEIGHTS:
            if dimension not in scores:
                errors.append(f"missing:scores.{dimension}")
                scores_ready_for_consistency = False
                continue
            value = scores[dimension]
            if not isinstance(value, dict):
                errors.append(f"invalid:scores.{dimension}")
                scores_ready_for_consistency = False
                continue
            score_errors = _validate_score(value.get("score"), f"scores.{dimension}.score")
            errors.extend(score_errors)
            if score_errors:
                scores_ready_for_consistency = False
            else:
                score_values[dimension] = value["score"]
            if not _is_non_empty_string(value.get("reason")):
                errors.append(f"invalid:scores.{dimension}.reason")
        for dimension in scores:
            if dimension not in QUALITY_DIMENSION_WEIGHTS:
                errors.append(f"unknown:scores.{dimension}")
                scores_ready_for_consistency = False

    overall_score_errors: list[str] = []
    if "overall_score" in row:
        overall_score_errors = _validate_score(row["overall_score"], "overall_score")
        errors.extend(overall_score_errors)
    percent_score_errors: list[str] = []
    if "percent_score" in row:
        percent_score_errors = _validate_percent_score(row["percent_score"], "percent_score")
        errors.extend(percent_score_errors)

    if (
        scores_ready_for_consistency
        and len(score_values) == len(QUALITY_DIMENSION_WEIGHTS)
        and isinstance(row.get("fatal_issue"), bool)
        and "overall_score" in row
        and not overall_score_errors
        and "percent_score" in row
        and not percent_score_errors
    ):
        expected = calculate_quality_score(scores=score_values, fatal_issue=row["fatal_issue"])
        if not math.isclose(float(row["overall_score"]), float(expected["overall_score"]), rel_tol=0, abs_tol=1e-9):
            errors.append("invalid:overall_score")
        if row["percent_score"] != expected["percent_score"]:
            errors.append("invalid:percent_score")
    return errors


def validate_pairwise_result(row: dict[str, Any]) -> list[str]:
    errors = _missing_fields(
        row,
        {
            "case_id",
            "judge_type",
            "winner",
            "fatal_issue_in_a",
            "fatal_issue_in_b",
            "hard_failures_in_a",
            "hard_failures_in_b",
            "reason_by_priority",
            "needs_human_review",
            "one_sentence_summary",
        },
    )
    errors.extend(_validate_non_empty_string(row, "case_id"))
    errors.extend(_validate_non_empty_string(row, "one_sentence_summary"))
    if "winner" in row and row["winner"] not in VALID_PAIRWISE_WINNERS:
        errors.append("invalid:winner")
    for field in ("fatal_issue_in_a", "fatal_issue_in_b", "needs_human_review"):
        errors.extend(_validate_bool(row, field))
    errors.extend(_validate_string_list(row, "hard_failures_in_a"))
    errors.extend(_validate_string_list(row, "hard_failures_in_b"))

    reason_by_priority = row.get("reason_by_priority")
    if "reason_by_priority" in row and not isinstance(reason_by_priority, dict):
        errors.append("invalid:reason_by_priority")
    elif isinstance(reason_by_priority, dict):
        for key in PAIRWISE_PRIORITY_ORDER:
            if key not in reason_by_priority:
                errors.append(f"missing:reason_by_priority.{key}")
                continue
            if not _is_non_empty_string(reason_by_priority[key]):
                errors.append(f"invalid:reason_by_priority.{key}")
        for key in reason_by_priority:
            if key not in PAIRWISE_PRIORITY_ORDER:
                errors.append(f"unknown:reason_by_priority.{key}")
    return errors


def validate_judge_result(row: dict[str, Any]) -> list[str]:
    if not isinstance(row, dict):
        return ["invalid:row"]

    errors = _missing_fields(row, {"case_id", "judge_type"})
    judge_type = row.get("judge_type")
    if judge_type not in VALID_JUDGE_TYPES:
        errors.append("invalid:judge_type")
        return sorted(set(errors))

    if judge_type == "safety":
        errors.extend(validate_safety_result(row))
    elif judge_type == "quality":
        errors.extend(validate_quality_result(row))
    elif judge_type == "pairwise":
        errors.extend(validate_pairwise_result(row))
    return sorted(set(errors))


def validate_human_review_result(row: dict[str, Any], *, known_case_ids: set[str] | None = None) -> list[str]:
    if not isinstance(row, dict):
        return ["invalid:row"]

    errors = _missing_fields(
        row,
        {
            "case_id",
            "judge_type",
            "reviewer_role",
            "codex_agreed",
            "manual_fatal_issue",
            "manual_score_override",
            "manual_winner_override",
            "failure_modes",
            "notes",
        },
    )
    errors.extend(_validate_non_empty_string(row, "case_id"))
    errors.extend(_validate_non_empty_string(row, "reviewer_role"))
    errors.extend(_validate_non_empty_string(row, "notes"))
    if "case_id" in row and _is_non_empty_string(row["case_id"]) and known_case_ids is not None:
        if row["case_id"] not in known_case_ids:
            errors.append("unknown:case_id")
    if "judge_type" in row and row["judge_type"] not in VALID_JUDGE_TYPES:
        errors.append("invalid:judge_type")
    for field in ("codex_agreed", "manual_fatal_issue"):
        errors.extend(_validate_bool(row, field))
    if row.get("manual_score_override") is not None:
        errors.extend(_validate_score(row.get("manual_score_override"), "manual_score_override"))
    if row.get("manual_winner_override") is not None and row.get("manual_winner_override") not in VALID_PAIRWISE_WINNERS:
        errors.append("invalid:manual_winner_override")
    errors.extend(_validate_string_list(row, "failure_modes"))
    return sorted(set(errors))


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def build_eval_summary(
    rows: list[dict[str, Any]],
    *,
    human_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    human_reviews = human_reviews or []
    judge_type_counts: Counter[str] = Counter()
    hard_failure_counts: Counter[str] = Counter()
    pairwise_winner_counts: Counter[str] = Counter()
    quality_scores: list[float] = []
    dimension_scores: dict[str, list[float]] = defaultdict(list)
    scenario_scores: dict[str, list[float]] = defaultdict(list)
    fatal_issue_count = 0
    review_needed_count = 0
    top_review_cases: list[str] = []

    for row in rows:
        judge_type = str(row.get("judge_type", "unknown"))
        judge_type_counts[judge_type] += 1

        if row.get("fatal_issue") is True or row.get("fatal_issue_in_a") is True or row.get("fatal_issue_in_b") is True:
            fatal_issue_count += 1
        if row.get("needs_human_review") is True:
            review_needed_count += 1
            case_id = row.get("case_id")
            if _is_non_empty_string(case_id):
                top_review_cases.append(str(case_id))

        hard_failures = row.get("hard_failures")
        if isinstance(hard_failures, list):
            for failure in hard_failures:
                hard_failure_counts[str(failure)] += 1
        for field in ("hard_failures_in_a", "hard_failures_in_b"):
            hard_failures = row.get(field)
            if isinstance(hard_failures, list):
                for failure in hard_failures:
                    hard_failure_counts[str(failure)] += 1

        if judge_type == "quality" and _is_finite_number(row.get("overall_score")):
            overall_score = float(row["overall_score"])
            quality_scores.append(overall_score)
            if _is_non_empty_string(row.get("scenario")):
                scenario_scores[str(row["scenario"])].append(overall_score)
            scores = row.get("scores")
            if isinstance(scores, dict):
                for dimension, value in scores.items():
                    if isinstance(value, dict) and _is_finite_number(value.get("score")):
                        dimension_scores[str(dimension)].append(float(value["score"]))

        if judge_type == "pairwise" and row.get("winner") in VALID_PAIRWISE_WINNERS:
            pairwise_winner_counts[str(row["winner"])] += 1

    reviewed = len(human_reviews)
    agreed = sum(1 for row in human_reviews if row.get("codex_agreed") is True)
    overrides = sum(1 for row in human_reviews if row.get("codex_agreed") is False)
    pairwise_total = sum(pairwise_winner_counts.values())

    return {
        "total_results": len(rows),
        "judge_type_counts": dict(sorted(judge_type_counts.items())),
        "fatal_issue_count": fatal_issue_count,
        "hard_failure_counts": dict(sorted(hard_failure_counts.items())),
        "review_needed_count": review_needed_count,
        "quality_score_avg": _average(quality_scores),
        "dimension_score_avg": {key: _average(values) for key, values in sorted(dimension_scores.items())},
        "scenario_score_avg": {key: _average(values) for key, values in sorted(scenario_scores.items())},
        "pairwise_winner_counts": dict(sorted(pairwise_winner_counts.items())),
        "pairwise_b_win_rate": round(pairwise_winner_counts.get("B", 0) / pairwise_total, 2) if pairwise_total else None,
        "human_review_count": reviewed,
        "human_agreement_rate": round(agreed / reviewed, 2) if reviewed else None,
        "human_override_rate": round(overrides / reviewed, 2) if reviewed else None,
        "top_review_cases": top_review_cases[:10],
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Subjective Evaluation Summary",
        "",
        f"- Total results: {summary.get('total_results', 0)}",
        f"- fatal_issue_count: {summary.get('fatal_issue_count', 0)}",
        f"- review_needed_count: {summary.get('review_needed_count', 0)}",
        f"- quality_score_avg: {summary.get('quality_score_avg')}",
        f"- pairwise_b_win_rate: {summary.get('pairwise_b_win_rate')}",
        f"- human_review_count: {summary.get('human_review_count', 0)}",
        f"- human_agreement_rate: {summary.get('human_agreement_rate')}",
        f"- human_override_rate: {summary.get('human_override_rate')}",
        "",
        "## Judge Types",
    ]
    for key, value in (summary.get("judge_type_counts") or {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Hard Failures"])
    for key, value in (summary.get("hard_failure_counts") or {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Pairwise Winners"])
    for key, value in (summary.get("pairwise_winner_counts") or {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Dimension Averages"])
    for key, value in (summary.get("dimension_score_avg") or {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Scenario Averages"])
    for key, value in (summary.get("scenario_score_avg") or {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Top Review Cases"])
    for case_id in summary.get("top_review_cases") or []:
        lines.append(f"- {case_id}")

    return "\n".join(lines) + "\n"
