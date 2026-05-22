from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.subjective_eval_prompts import (
    build_pairwise_judge_messages,
    build_quality_judge_messages,
    build_safety_judge_messages,
)
from app.services.subjective_eval_results import (
    build_eval_summary,
    render_markdown_report,
    validate_human_review_result,
    validate_judge_result,
)


DEFAULT_FIXTURE = BACKEND_ROOT / "tests/evals/fixtures_subjective_quality.json"
DEFAULT_PAIRWISE_FIXTURE = BACKEND_ROOT / "tests/evals/fixtures_pairwise_quality.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def validate_rows(rows: list[Any], *, source: Path) -> list[str]:
    errors: list[str] = []
    for line_number, row in enumerate(rows, start=1):
        for error in validate_judge_result(row):
            errors.append(f"{source}:{line_number} {error}")
    return errors


def validate_human_review_rows(rows: list[Any], *, source: Path, known_case_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for line_number, row in enumerate(rows, start=1):
        for error in validate_human_review_result(row, known_case_ids=known_case_ids):
            errors.append(f"{source}:{line_number} {error}")
    return errors


def _answer_for_case(case: dict[str, Any]) -> str:
    answer = str(case.get("agent_answer") or "").strip()
    if not answer:
        raise ValueError(f"Case {case.get('id')} is missing agent_answer.")
    return answer


def build_safety_requests(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for case in cases:
        requests.append(
            {
                "case_id": case["id"],
                "judge_type": "safety",
                "messages": build_safety_judge_messages(case, _answer_for_case(case)),
            }
        )
    return requests


def build_quality_requests(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for case in cases:
        requests.append(
            {
                "case_id": case["id"],
                "judge_type": "quality",
                "messages": build_quality_judge_messages(case, _answer_for_case(case)),
            }
        )
    return requests


def build_pairwise_requests(
    pairwise_cases: list[dict[str, Any]],
    *,
    subjective_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cases_by_id = {str(case["id"]): case for case in subjective_cases}
    requests: list[dict[str, Any]] = []
    for pairwise_case in pairwise_cases:
        source_case_id = str(pairwise_case["source_case_id"])
        source_case = cases_by_id.get(source_case_id)
        if source_case is None:
            raise ValueError(f"Unknown source_case_id: {source_case_id}")
        requests.append(
            {
                "case_id": pairwise_case["id"],
                "judge_type": "pairwise",
                "messages": build_pairwise_judge_messages(pairwise_case, source_case=source_case),
            }
        )
    return requests


def summarize_judge_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hard_failure_counts: Counter[str] = Counter()
    quality_scores: list[float] = []
    fatal_issue_count = 0
    human_review_count = 0

    for row in rows:
        if row.get("fatal_issue"):
            fatal_issue_count += 1
        if row.get("needs_human_review"):
            human_review_count += 1
        for failure in row.get("hard_failures", []) or []:
            hard_failure_counts[str(failure)] += 1
        if row.get("judge_type") == "quality" and row.get("overall_score") is not None:
            quality_scores.append(float(row["overall_score"]))

    quality_score_avg = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None
    return {
        "total_results": len(rows),
        "fatal_issue_count": fatal_issue_count,
        "human_review_count": human_review_count,
        "hard_failure_counts": dict(sorted(hard_failure_counts.items())),
        "quality_score_avg": quality_score_avg,
    }


def _case_list_from(path: Path) -> list[dict[str, Any]]:
    cases = load_json(path)
    if not isinstance(cases, list):
        raise ValueError(f"Expected {path} to contain a JSON list.")
    return cases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and summarize subjective Codex judge requests.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build-requests")
    build_parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--judge-type", choices=["safety", "quality", "both"], default="both")

    pairwise_parser = subparsers.add_parser("build-pairwise-requests")
    pairwise_parser.add_argument("--subjective-fixture", type=Path, default=DEFAULT_FIXTURE)
    pairwise_parser.add_argument("--pairwise-fixture", type=Path, default=DEFAULT_PAIRWISE_FIXTURE)
    pairwise_parser.add_argument("--output", type=Path, required=True)

    summarize_parser = subparsers.add_parser("summarize-results")
    summarize_parser.add_argument("--results", type=Path, required=True)
    summarize_parser.add_argument("--output", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate-results")
    validate_parser.add_argument("--results", type=Path, required=True)

    report_parser = subparsers.add_parser("summarize-report")
    report_parser.add_argument("--results", type=Path, required=True)
    report_parser.add_argument("--human-review", type=Path)
    report_parser.add_argument("--json-output", type=Path, required=True)
    report_parser.add_argument("--markdown-output", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command == "build-requests":
        cases = _case_list_from(args.fixture)
        requests: list[dict[str, Any]] = []
        if args.judge_type in {"safety", "both"}:
            requests.extend(build_safety_requests(cases))
        if args.judge_type in {"quality", "both"}:
            requests.extend(build_quality_requests(cases))
        write_jsonl(args.output, requests)
        print(json.dumps({"request_count": len(requests), "output": str(args.output)}, ensure_ascii=False))
        return 0

    if args.command == "build-pairwise-requests":
        subjective_cases = _case_list_from(args.subjective_fixture)
        pairwise_cases = _case_list_from(args.pairwise_fixture)
        requests = build_pairwise_requests(pairwise_cases, subjective_cases=subjective_cases)
        write_jsonl(args.output, requests)
        print(json.dumps({"request_count": len(requests), "output": str(args.output)}, ensure_ascii=False))
        return 0

    if args.command == "summarize-results":
        rows = read_jsonl(args.results)
        summary = summarize_judge_results(rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if args.command == "validate-results":
        rows = read_jsonl(args.results)
        errors = validate_rows(rows, source=args.results)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"valid": True, "result_count": len(rows)}, ensure_ascii=False))
        return 0

    if args.command == "summarize-report":
        rows = read_jsonl(args.results)
        errors = validate_rows(rows, source=args.results)
        human_reviews: list[Any] = []
        if args.human_review:
            human_reviews = read_jsonl(args.human_review)
            known_case_ids = {
                row["case_id"]
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("case_id"), str) and row["case_id"].strip()
            }
            errors.extend(
                validate_human_review_rows(
                    human_reviews,
                    source=args.human_review,
                    known_case_ids=known_case_ids,
                )
            )
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
            return 1

        summary = build_eval_summary(rows, human_reviews=human_reviews)
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        args.markdown_output.write_text(render_markdown_report(summary), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
