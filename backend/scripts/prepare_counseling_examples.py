"""
从 PsyQA 等开源心理咨询语料中筛选高质量 few-shot 示例，
用于注入到对话生成 prompt 中，提升模型回复的专业性和共情感。

用法：
    python scripts/prepare_counseling_examples.py                    # 自动下载 PsyQA
    python scripts/prepare_counseling_examples.py --input-json data/psyqa_local.json  # 使用本地文件
    python scripts/prepare_counseling_examples.py --input-json data/custom.json --output data/my_examples.py  # 自定义路径
    python scripts/prepare_counseling_examples.py --dry-run          # 仅预览不写文件
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.deepseek_client import deepseek_client

# --- 文件名映射 ---
# HuggingFace PsyQA 数据集的典型文件结构
PSYQA_SPLITS = ["train", "validation", "test"]

# --- 安全过滤规则 ---

# 用户问题中不得包含的高风险关键词（自杀/自伤/暴力）
HIGH_RISK_QUESTION_TERMS = (
    "自杀", "自伤", "割腕", "上吊", "跳楼", "吃安眠药",
    "结束生命", "不想活", "寻死", "遗书",
    "kill myself", "suicide", "self harm",
)

# 咨询师回答中不得包含的禁止语言
FORBIDDEN_ASSISTANT_PATTERNS = [
    # 诊断性语言
    r"你这是.{0,6}(症|障碍|问题)",
    r"确诊",
    r"你得了",
    r"临床诊断",
    # 治疗承诺
    r"一定能好",
    r"保证.{0,4}康复",
    r"按我说的做",
    r"包治",
    # 药物建议
    r"去买.{0,6}药",
    r"服用.{0,6}药",
    r"处方",
    r"剂量",
    # 替代专业帮助
    r"不用找医生",
    r"不用咨询",
    r"别去.?医院",
    # 诱导依赖
    r"只有我.{0,4}你",
    r"你离不开我",
    r"别找别人",
    # 宗教/灵修暗示
    r"因果报应",
    r"前世.{0,4}债",
]
FORBIDDEN_REGEX = re.compile("|".join(FORBIDDEN_ASSISTANT_PATTERNS), re.IGNORECASE)

# 回答中鼓励出现的共情句式（分值越高越好）
EMPATHY_PATTERNS = [
    (r"听起来.{1,20}(不容易|很难|辛苦|累)", 3),
    (r"(我能|我可以).{1,10}(感受|理解|体会)", 3),
    (r"这(确实|的确|真的).{1,10}(不容易|困难|辛苦)", 2),
    (r"你不是.{1,8}(一个人|孤单|独自)", 2),
    (r"(说出来|表达).{1,10}(勇气|不容易|力量)", 2),
    (r"(先|不妨|可以).{1,8}(慢慢|不急|放慢)", 1),
    (r"(你觉得|你感觉|你想到).{1,15}(吗|呢)?", 1),
    (r"我.{1,6}(陪|在|一起).{1,6}你", 1),
]
EMPATHY_REGEX = [(re.compile(p, re.IGNORECASE), w) for p, w in EMPATHY_PATTERNS]

# 回答中减分的句式
NEGATIVE_PATTERNS = [
    (r"你应该.{1,15}(做|想|去|改变)", 2),
    (r"你(必须|一定)要", 2),
    (r"这(很|太).{1,8}(简单|容易)", 1),
    (r"你就是.{1,8}(问题|毛病|不对)", 2),
    (r"我建议你(吃药|去医院|看医生)", 3),
]
NEGATIVE_REGEX = [(re.compile(p, re.IGNORECASE), w) for p, w in NEGATIVE_PATTERNS]

# --- 模式分类关键词 ---
# 基于 PsyQA 的 strategy 标注字段做初步分类
# PsyQA 的 description 字段对应的是咨询策略
STRATEGY_TO_MODE: dict[str, str] = {
    "question": "counseling",        # 开放式提问 → 疏导
    "restructuring": "counseling",   # 认知重构 → 疏导
    "interpretation": "counseling",  # 解释 → 疏导
    "information": "counseling",     # 信息提供 → 疏导
    "support": "vent",               # 支持性回应 → 倾诉共情
    "approval": "vent",              # 肯定/认可 → 倾诉共情
    "reassurance": "vent",           # 安抚/再保证 → 倾诉共情
    "self-disclosure": "vent",       # 自我暴露 → 倾诉共情
    "comforting": "vent",            # 安抚 → 情绪安抚
    "emotional_release": "vent",     # 情绪宣泄 → 倾诉共情
    "direct_guidance": "counseling", # 直接指导 → 疏导
    "normalizing": "soothe",         # 正常化 → 安抚
    "grounding": "soothe",           # 接地技术 → 安抚
    "breathing": "soothe",           # 呼吸练习 → 安抚
    "summary": "counseling",         # 总结 → 疏导
    "paraphrase": "vent",            # 复述/反射 → 倾诉
    "reflection": "counseling",      # 情感反映 → 疏导
    "confrontation": "counseling",   # 面质 → 疏导
    "exploration": "counseling",     # 探索 → 疏导
    "validation": "vent",            # 确认/验证感受 → 倾诉共情
}

# 用户问题内容关键词辅助分类（当没有 strategy 标注时使用）
QUESTION_MODE_CLUES: dict[str, list[str]] = {
    "vent": [
        "想哭", "委屈", "没人理解", "憋", "难受",
        "压力好大", "很压抑", "崩溃", "撑不住", "好累",
        "不开心", "难过", "心里堵", "说出来", "倾诉",
    ],
    "soothe": [
        "心慌", "睡不着", "紧张", "焦虑", "发抖",
        "喘不过气", "胸闷", "坐立不安", "害怕",
        "惊恐", "头晕", "出汗", "控制不住",
    ],
    "counseling": [
        "怎么办", "理一理", "分析", "复盘", "想想办法",
        "解决", "帮我看看", "不知道怎么办", "怎么处理",
        "做决定", "选择", "要不要", "怎么沟通",
    ],
}


def load_psyqa_dataset(input_json: Optional[Path] = None) -> list[dict[str, Any]]:
    """加载 PsyQA 数据集，优先使用本地 JSON，fallback 到 HuggingFace datasets 库。"""
    if input_json is not None:
        print(f"从本地 JSON 加载: {input_json}")
        data = json.loads(input_json.read_text(encoding="utf-8-sig"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # 支持 {"train": [...], "validation": [...], ...} 格式
            items: list[dict] = []
            for key, val in data.items():
                if isinstance(val, list):
                    items.extend(val)
            return items
        return []

    try:
        from datasets import load_dataset as hf_load_dataset
        print("尝试从 HuggingFace 加载 PsyQA 数据集...")
        dataset = hf_load_dataset("qwyd/PsyQA", trust_remote_code=True)
        items: list[dict] = []
        for split in PSYQA_SPLITS:
            if split in dataset:
                items.extend(dataset[split])
        print(f"从 HuggingFace 加载了 {len(items)} 条记录")
        return items
    except ImportError:
        print("HuggingFace datasets 库未安装，请运行: pip install datasets")
        print("或者使用 --input-json 指定本地 PsyQA JSON 文件")
        raise
    except Exception as e:
        print(f"HuggingFace 加载失败: {e}")
        print("请尝试从 ModelScope 下载后使用 --input-json 加载")
        raise


def is_safe_question(question: str) -> bool:
    """检查用户问题是否安全（不含高风险内容）"""
    lowered = question.lower()
    for term in HIGH_RISK_QUESTION_TERMS:
        if term in lowered:
            return False
    return True


def is_safe_answer(answer: str) -> bool:
    """检查咨询师回答是否安全（不含禁止语言）"""
    return not bool(FORBIDDEN_REGEX.search(answer))


def count_chinese_chars(text: str) -> int:
    """统计中文字符数"""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def quality_score(question: str, answer: str) -> tuple[int, dict[str, int]]:
    """计算 QA 对的综合质量分数。返回 (总分, 明细)"""
    score = 0
    detail: dict[str, int] = {}

    q_chars = count_chinese_chars(question)
    a_chars = count_chinese_chars(answer)

    # 问题长度：10-150 中文字
    if 10 <= q_chars <= 150:
        score += 2
        detail["q_length"] = 2
    elif 5 <= q_chars < 10:
        score += 1
        detail["q_length"] = 1
    else:
        detail["q_length"] = 0

    # 回答长度：80-400 中文字（适中，不敷衍不说教）
    if 120 <= a_chars <= 350:
        score += 5
        detail["a_length"] = 5
    elif 80 <= a_chars <= 400:
        score += 3
        detail["a_length"] = 3
    elif 50 <= a_chars < 80:
        score += 1
        detail["a_length"] = 1
    else:
        detail["a_length"] = 0

    # 共情句式加分
    empathy_total = 0
    for regex, weight in EMPATHY_REGEX:
        if regex.search(answer):
            empathy_total += weight
    score += empathy_total
    detail["empathy"] = empathy_total

    # 减分项
    penalty = 0
    for regex, weight in NEGATIVE_REGEX:
        if regex.search(answer):
            penalty += weight
    score -= penalty
    detail["penalty"] = penalty

    # 安全分 (安全通过不加分，不通过直接 -50)
    if not is_safe_answer(answer):
        score -= 50
        detail["safe"] = -50
    else:
        detail["safe"] = 0

    # 问题安全分
    if not is_safe_question(question):
        score -= 50
        detail["q_safe"] = -50
    else:
        detail["q_safe"] = 0

    return score, detail


def classify_by_strategy(description: str) -> Optional[str]:
    """根据 PsyQA 的策略标注字段分类对话模式"""
    if not description:
        return None
    lowered = description.lower().strip()
    for keyword, mode in STRATEGY_TO_MODE.items():
        if keyword in lowered:
            return mode
    return None


def classify_by_question_content(question: str) -> Optional[str]:
    """根据用户问题内容关键词分类对话模式"""
    lowered = question.lower()
    scores: dict[str, int] = {}
    for mode, keywords in QUESTION_MODE_CLUES.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score > 0:
            scores[mode] = score
    if not scores:
        return None
    return max(scores, key=lambda m: scores[m])


def classify_mode(question: str, description: str) -> str:
    """综合策略标注和问题内容分类对话模式"""
    mode = classify_by_strategy(description)
    if mode:
        return mode
    return classify_by_question_content(question) or "vent"


async def classify_with_llm(
    question: str,
    answer: str,
    existing_mode: str,
) -> str:
    """使用 DeepSeek 复核/修正模式分类"""
    if not deepseek_client.is_configured:
        return existing_mode

    prompt = (
        "你是心理咨询对话标注员。请根据用户问题和咨询师回应，将对话归类为以下三种模式之一：\n"
        "- vent: 用户以倾诉为主，咨询师以共情、接住情绪为主，不给建议\n"
        "- soothe: 用户有明显的情绪/身体反应（焦虑、心慌、紧张），咨询师先安抚稳定\n"
        "- counseling: 用户想理清事情、做决策，咨询师做结构化梳理\n"
        f"\n现有分类: {existing_mode}\n"
        f"用户问题: {question}\n"
        f"咨询师回答: {answer}\n"
        "请只输出一个词: vent / soothe / counseling"
    )

    try:
        reply = await deepseek_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=16,
        )
    except Exception:
        return existing_mode

    if not reply:
        return existing_mode

    reply_lower = reply.strip().lower()
    if "soothe" in reply_lower:
        return "soothe"
    if "counseling" in reply_lower:
        return "counseling"
    if "vent" in reply_lower:
        return "vent"
    return existing_mode


async def prepare_examples(
    input_json: Optional[Path] = None,
    *,
    min_per_mode: int = 3,
    max_per_mode: int = 8,
    total_samples: int = 200,
    use_llm: bool = True,
    dry_run: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """主流程：加载、筛选、分类、输出"""
    raw_items = load_psyqa_dataset(input_json)
    print(f"加载了 {len(raw_items)} 条原始记录")

    # 标准化字段名：PsyQA 字段可能是 question / description / answer
    candidates: list[dict[str, Any]] = []
    for item in raw_items:
        question = str(item.get("question") or item.get("text") or "").strip()
        description = str(item.get("description") or item.get("strategy") or "").strip()
        answer = str(
            item.get("answer")
            or item.get("answers")
            or item.get("response")
            or item.get("output")
            or ""
        ).strip()

        if not question or not answer:
            continue

        score, _ = quality_score(question, answer)
        if score < 2:  # 最低 2 分以上
            continue

        candidates.append({
            "question": question,
            "description": description,
            "answer": answer,
            "score": score,
        })

    # 按分数降序排列
    candidates.sort(key=lambda x: x["score"], reverse=True)
    print(f"通过质量筛选: {len(candidates)} 条")

    # 按模式分组
    mode_groups: dict[str, list[dict[str, Any]]] = {
        "vent": [],
        "soothe": [],
        "counseling": [],
    }

    # 先用规则分类，取前 total_samples 条
    for item in candidates[:total_samples]:
        mode = classify_mode(item["question"], item["description"])
        item["mode"] = mode
        mode_groups[mode].append(item)

    print(f"规则分类结果: vent={len(mode_groups['vent'])}, "
          f"soothe={len(mode_groups['soothe'])}, "
          f"counseling={len(mode_groups['counseling'])}")

    # 用 LLM 复核高分示例（每个模式取 top candidates）
    if use_llm and deepseek_client.is_configured:
        print("使用 LLM 复核模式分类...")
        for mode in ("vent", "soothe", "counseling"):
            top_candidates = mode_groups[mode][:max_per_mode * 2]
            if not top_candidates:
                continue
            for i, item in enumerate(top_candidates):
                new_mode = await classify_with_llm(
                    item["question"], item["answer"], item["mode"]
                )
                if new_mode != item["mode"]:
                    # 从原组移除，加入新组
                    mode_groups[item["mode"]].remove(item)
                    item["mode"] = new_mode
                    mode_groups[new_mode].append(item)
            # 重新按分数排序
            mode_groups[mode].sort(key=lambda x: x["score"], reverse=True)

    # 输出
    result: dict[str, list[dict[str, str]]] = {}
    for mode in ("vent", "soothe", "counseling"):
        selected = mode_groups[mode][:max_per_mode]
        result[mode] = [
            {"user": item["question"], "assistant": item["answer"]}
            for item in selected
        ]
        print(f"\n=== {mode} ({len(result[mode])} 条) ===")
        for i, ex in enumerate(result[mode][:min_per_mode], 1):
            print(f"  [{i}] 用户: {ex['user'][:60]}...")
            print(f"      咨询师: {ex['assistant'][:80]}...")

    # 检查是否达到最低数量
    for mode, min_count in [("vent", min_per_mode), ("soothe", min_per_mode), ("counseling", min_per_mode)]:
        if len(result[mode]) < min_count:
            print(f"\n警告: {mode} 模式仅有 {len(result[mode])} 条示例，少于最低要求 {min_count} 条")

    return result


def generate_module_file(examples: dict[str, list[dict[str, str]]], output_path: Path) -> None:
    """生成 counseling_examples.py 模块文件"""
    content = [
        '# Auto-generated by scripts/prepare_counseling_examples.py',
        '# 来源: PsyQA (CC BY 4.0) — https://huggingface.co/datasets/qwyd/PsyQA',
        '# 每条示例已通过安全过滤和质量筛选',
        '#',
        '# PsyQA 论文: Improving Psychological Counseling with Large Language Models',
        '# A Structured Multi-Strategy Dataset for Mental Health Support (ACL 2021 Findings)',
        '',
        '"""心理咨询对话 few-shot 示例字典，供 nodes.py 注入 prompt 使用"""',
        '',
        'from __future__ import annotations',
        '',
        '',
        'COUNSELING_EXAMPLES: dict[str, list[dict[str, str]]] = {',
    ]
    for mode, items in examples.items():
        content.append(f'    "{mode}": [')
        for item in items:
            content.append('        {')
            content.append(f'            "user": {json.dumps(item["user"], ensure_ascii=False)},')
            content.append(f'            "assistant": {json.dumps(item["assistant"], ensure_ascii=False)},')
            content.append('        },')
        content.append('    ],')
    content.append('}')
    content.append('')

    output_path.write_text("\n".join(content), encoding="utf-8")
    print(f"\n已生成 {output_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 PsyQA 筛选 few-shot 心理咨询对话示例"
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        help="本地 PsyQA JSON 文件路径（如不指定则从 HuggingFace 下载）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "app" / "services" / "counseling_examples.py",
        help="输出文件路径",
    )
    parser.add_argument(
        "--min-per-mode",
        type=int,
        default=3,
        help="每种模式最少需要的示例数 (默认 3)",
    )
    parser.add_argument(
        "--max-per-mode",
        type=int,
        default=8,
        help="每种模式最多保留的示例数 (默认 8)",
    )
    parser.add_argument(
        "--total-samples",
        type=int,
        default=200,
        help="用于分类筛选的总样本数 (默认 200)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="不使用 LLM 复核分类",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览不写文件",
    )
    args = parser.parse_args()

    examples = await prepare_examples(
        input_json=args.input_json,
        min_per_mode=args.min_per_mode,
        max_per_mode=args.max_per_mode,
        total_samples=args.total_samples,
        use_llm=not args.no_llm,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        generate_module_file(examples, args.output)
        print(f"\n请在启动服务前确认 {args.output} 中的示例内容。")
        print("如果 HuggingFace 不可用，可以先用 --dry-run 预览，再用 --input-json 加载本地文件。")

    print("\n完成。")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
