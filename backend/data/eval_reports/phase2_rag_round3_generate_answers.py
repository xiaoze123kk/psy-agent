from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


BASE_SCRIPT = Path("data/eval_reports/phase2_rag_generate_answers.py")
ROUND3_ANSWERS = Path("data/eval_reports/phase2_rag_round3_agent_answers.jsonl")
ROUND3_SUMMARY = Path("data/eval_reports/phase2_rag_round3_agent_answers_summary.json")


def load_generator_module():
    spec = importlib.util.spec_from_file_location("phase2_rag_generate_answers", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load generator script: {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def main() -> None:
    module = load_generator_module()
    module.OUT_PATH = ROUND3_ANSWERS
    module.SUMMARY_PATH = ROUND3_SUMMARY
    await module.main()


if __name__ == "__main__":
    asyncio.run(main())
