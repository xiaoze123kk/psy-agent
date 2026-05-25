from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.graph_runtime import GraphRuntime

FIXTURE = Path("tests/evals/fixtures_subjective_quality.json")
OUT_DIR = Path("data/eval_reports")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "phase2_rag_agent_answers.jsonl"
SUMMARY_PATH = OUT_DIR / "phase2_rag_agent_answers_summary.json"


def split_turns(case: dict) -> tuple[list[dict[str, str]], str]:
    turns = case.get("turns") or []
    last_user_index = None
    for index in range(len(turns) - 1, -1, -1):
        if turns[index].get("role") == "user":
            last_user_index = index
            break
    if last_user_index is None:
        return [], ""
    recent = [
        {"role": str(turn.get("role") or ""), "content": str(turn.get("content") or "")}
        for turn in turns[:last_user_index]
        if turn.get("role") in {"user", "assistant"} and str(turn.get("content") or "").strip()
    ]
    return recent, str(turns[last_user_index].get("content") or "")


def load_existing() -> set[str]:
    if not OUT_PATH.exists():
        return set()
    existing: set[str] = set()
    for line in OUT_PATH.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            case_id = json.loads(line).get("case_id")
        except Exception:
            continue
        if case_id:
            existing.add(str(case_id))
    return existing


async def invoke_with_retry(runtime: GraphRuntime, cid: str, case: dict, content: str, recent: list[dict[str, str]]) -> tuple[dict, str | None, int]:
    last_error: str | None = None
    last_result: dict = {}
    for attempt in range(1, 3):
        try:
            result = await asyncio.wait_for(
                runtime.invoke_turn(
                    thread_id=f"eval-rag-{cid}-{attempt}",
                    user_id="eval-user",
                    content=content,
                    user_mode=str(case.get("user_mode") or "adult"),
                    recent_messages=recent,
                    memory_mode="off",
                    crisis_resource_region="CN",
                ),
                timeout=260,
            )
            last_result = result
            if str(result.get("assistant_text") or "").strip():
                return result, None, attempt
            last_error = str(result.get("failure_reason") or "empty_model_reply")
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(1)
    return last_result if last_result else {}, last_error, 2


async def main() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    existing = load_existing()
    runtime = GraphRuntime()
    counts = {"total": len(rows), "completed_before": len(existing), "completed_now": 0, "generated": 0, "rag_used": 0, "failed": 0}
    started = time.time()
    with OUT_PATH.open("a", encoding="utf-8") as output:
        for index, case in enumerate(rows, start=1):
            cid = str(case["id"])
            if cid in existing:
                print(f"skip {index}/100 {cid}", flush=True)
                continue
            recent, content = split_turns(case)
            turn_started = time.time()
            result, error, attempts = await invoke_with_retry(runtime, cid, case, content, recent)
            trace = result.get("rag_trace_summary") if isinstance(result.get("rag_trace_summary"), dict) else {}
            record = {
                "case_id": cid,
                "scenario": case.get("scenario"),
                "risk_tags": case.get("risk_tags", []),
                "user_mode": case.get("user_mode"),
                "thread_mode": case.get("thread_mode"),
                "input_last_user": content,
                "agent_answer": str(result.get("assistant_text") or "").strip(),
                "delivery_status": result.get("delivery_status") if result else "exception",
                "risk_level": result.get("risk_level") if result else None,
                "validator_severity": result.get("validator_severity") if result else None,
                "validator_reasons": result.get("validator_reasons") if result else [],
                "experience_validator_warnings": result.get("experience_validator_warnings") if result else [],
                "failure_reason": result.get("failure_reason") if result else error,
                "rag_used": result.get("rag_used") if result else False,
                "rag_skipped_reason": result.get("rag_skipped_reason") if result else "not_run",
                "rag_trace_summary": trace,
                "retrieved_example_count": len(result.get("referenced_counseling_examples") or []),
                "duration_seconds": round(time.time() - turn_started, 2),
                "attempts": attempts,
                "eval_runtime": "rag_runtime",
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            counts["completed_now"] += 1
            if record["delivery_status"] == "generated" and record["agent_answer"]:
                counts["generated"] += 1
            else:
                counts["failed"] += 1
            if record["rag_used"]:
                counts["rag_used"] += 1
            print(
                "done {}/100 {} status={} rag_used={} rag_status={} seconds={} attempts={}".format(
                    index,
                    cid,
                    record["delivery_status"],
                    record["rag_used"],
                    trace.get("status"),
                    record["duration_seconds"],
                    attempts,
                ),
                flush=True,
            )
    counts["elapsed_seconds"] = round(time.time() - started, 2)
    counts["output"] = str(OUT_PATH)
    SUMMARY_PATH.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())

