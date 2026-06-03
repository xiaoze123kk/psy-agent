# 2026-05-26 “想死想死”情绪隐喻边界修复

## 背景/问题

用户指出“想死想死的感觉”可能是在自嘲或描述情绪压力，不应默认假设用户真正想去死，也不需要立刻进入 L2。排查发现单轮 `risk_classifier` 已能把“想死想死的一种感觉”识别为 `emotional_metaphor` 并停在 L1；真正误升级发生在下一轮 `control_plane`：它把近期用户消息拼入 `detection_text` 后，用原始自伤词表继承近期上下文，导致低风险隐喻在后续“没事，就是一种情绪而已”这类澄清轮里被重新推到 `P0_immediate_safety` / L2。

## 关键改动

- 在 `control_nodes` 中新增近期用户上下文的语义复核：只有近期用户消息本身被 `classify_risk_text()` 判断为 L2/L3，且不是 `idiom_or_slang`、`emotional_metaphor` 等低风险表达时，才继承为高风险自伤上下文。
- 原始 L3 自伤信号优先基于当前轮文本判断，避免上一轮低风险“想死想死”与当前轮“现在/今天”等普通时间词拼接成伪近端风险。
- 新增回归测试覆盖：上一轮是“唉，就是想死想死的一种感觉”，下一轮澄清“没事，就是一种情绪而已。”时，不应进入 L2、P0 或触发 safety check。

## 验证结果

- 先运行新增单测确认失败：原逻辑会把该场景误判为 L2。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_safety_evaluation.py -k emotional_metaphor_context_is_not_inherited_as_l2 -q`：`1 passed, 113 deselected`。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_safety_evaluation.py tests/test_risk_policy.py -q`：`129 passed, 22 subtests passed`。

## 后续事项

- 后续可继续补充更多中文自嘲/夸张表达样本，例如“笑死/累死/烦死/社死”和“想死了但不是那个意思”，进一步校准 L0/L1 与 L2 边界。
