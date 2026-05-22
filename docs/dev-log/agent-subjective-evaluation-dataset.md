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

