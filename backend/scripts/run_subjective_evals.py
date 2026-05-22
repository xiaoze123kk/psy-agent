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
    build_quality_judge_messages,
    build_safety_judge_messages,
)


DEFAULT_FIXTURE = Path("tests/evals/fixtures_subjective_quality.json")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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

    summarize_parser = subparsers.add_parser("summarize-results")
    summarize_parser.add_argument("--results", type=Path, required=True)
    summarize_parser.add_argument("--output", type=Path, required=True)

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

    if args.command == "summarize-results":
        rows = read_jsonl(args.results)
        summary = summarize_judge_results(rows)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
