# 开发日志：Agent 主观评测集设计

## 日期

2026-05-22

## 背景 / 问题

项目已有自动化评测设计和 42 条对话质量 fixture，但用户希望新增一套更贴近心理咨询 agent 主观体验的评测集，并明确由 Codex / 大模型先打分，后续再人工审核。

这类评测不能只看“聊得暖不暖”，需要先过安全边界，再评价咨询陪伴质量，最后用 A/B 对比支持 agent 版本迭代。

## 关键改动

- 新增设计文档：`docs/superpowers/specs/2026-05-22-agent-subjective-evaluation-dataset-design.md`。
- 明确采用“安全闸门 + 主观质量 + A/B 版本对比”的三层评测结构。
- 设计 Codex judge 的 Safety Judge、Quality Judge、Pairwise Judge 结构化 JSON 输出。
- 规划 50 条 gold set 校准，再扩展到 200 条分层样本。
- 明确高风险样本、Codex 分歧样本和 A/B 顺序交换不一致样本必须进入人工复核。

## 验证结果

- 本次只新增方案文档，未修改后端、前端或数据库代码。
- 已检查当前工作区存在多处既有未提交改动，本次文档新增与这些改动无关。

## 后续事项

- 用户确认设计后，进入实施计划阶段。
- 下一步应定义主观评测 fixture schema、Codex judge prompt 和 50 条 gold set。
- 后续接入统一 eval 报告时，需要记录 Codex 与人工复核的一致率、人工推翻率和 A/B 胜率。

## 实施记录

- 新增 `backend/app/services/subjective_eval_schemas.py`，负责主观评测 schema、风险标签词表、质量维度权重、hard failure 分数上限、A/B 优先级和人工复核路由。
- 新增 `backend/app/services/subjective_eval_prompts.py`，负责 Safety Judge、Quality Judge、Pairwise Judge 的 Codex 请求提示词，并加入被评测数据隔离规则，避免回答内容中的提示注入影响评委指令。
- 新增 `backend/tests/evals/fixtures_subjective_quality.json`，包含 50 条 gold set，覆盖日常情绪支持、关系议题、轻中度困扰、危机、未成年人、医疗边界、依赖边界、隐私边界和多轮升级。
- 新增 `backend/tests/evals/fixtures_pairwise_quality.json`，包含 6 条 A/B 对比样本，覆盖低价值感、危机方法、依赖、用药、风险后话题转移和隐私边界。
- 新增 `backend/scripts/run_subjective_evals.py`，用于生成 Codex judge 请求 JSONL，并汇总 Codex 返回的 JSONL 结果。
- 语义校准：`crisis_third_party_005` 的用户内容是“朋友说他不想活了”，风险标签从 `harm_to_others` 改为 `suicide_ideation`，避免把第三方自杀意念误计为他伤风险。

## 本轮验证

- `.\.venv\Scripts\python.exe -m pytest tests\evals\test_subjective_eval_schemas.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\evals\test_subjective_eval_prompts.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\evals\test_subjective_eval_fixtures.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests\test_run_subjective_evals_script.py -q`
- smoke：`run_subjective_evals.py build-requests` 使用临时 2 条带 `agent_answer` 样本生成 4 条 safety/quality 请求，验证后删除临时产物。
- smoke：`run_subjective_evals.py build-pairwise-requests` 使用默认 6 条 A/B fixture 生成 6 条 pairwise 请求，验证后删除临时产物。

## 使用方式

先把待评测 agent 输出补到主观 fixture 或同结构文件的 `agent_answer` 字段，然后生成 Safety/Quality 请求包：

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe scripts\run_subjective_evals.py build-requests --fixture data\eval_reports\subjective_answers.json --output data\eval_reports\subjective_requests.jsonl --judge-type both
```

生成 A/B 请求包：

```powershell
.\.venv\Scripts\python.exe scripts\run_subjective_evals.py build-pairwise-requests --output data\eval_reports\pairwise_requests.jsonl
```

Codex 按请求 JSONL 逐条返回 JSON 后，保存为 `subjective_results.jsonl`，再生成汇总：

```powershell
.\.venv\Scripts\python.exe scripts\run_subjective_evals.py summarize-results --results data\eval_reports\subjective_results.jsonl --output data\eval_reports\subjective_summary.json
```

## 后续事项

- 接入实际 agent 批量回答导出，把 50 条 gold set 自动补齐 `agent_answer`。
- 建立人工复核表，记录 Codex 与人工审核的一致率、人工推翻率、hard failure 误报/漏报和 A/B 胜率。
- 如果后续扩展 risk tag，需要同步更新 `RISK_TAGS`、fixture 和快照测试。
