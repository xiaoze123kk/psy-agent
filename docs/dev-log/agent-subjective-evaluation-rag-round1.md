# 开发日志：主观评测 Phase 2 RAG 第一轮复盘

## 日期

2026-05-22

## 背景 / 问题

用户要求在主观评测中开启 RAG，并完成真实 agent 输出后的 Codex 初评。第一轮评测已完成，但结果暴露出两个优先级最高的问题：一是部分危机、未成年人、医疗、依赖和隐私边界样本没有进入安全/边界路由；二是模型空回复或 validator 再生失败会直接形成 `failed_no_reply`。

## 关键结论

- 本轮 RAG 是开启状态；此前默认 60 秒检索超时过紧，评测时使用 `RAG_RETRIEVAL_TIMEOUT_SECONDS=180` 后可以完成本地 embedding + Milvus + rerank。
- 100 条主观样本中，86 条生成成功，14 条无回复；73 条使用 RAG。
- Codex 初评汇总显示：`missed_high_risk` 39、`missing_real_world_support` 28、`no_reply` 14、`missing_teen_trusted_adult` 9。
- 直接探针显示，`crisis_domestic_006`、`crisis_location_010`、`minor_sexual_004`、`medical_diagnosis_001`、`dependency_only_safe_006`、`privacy_id_001` 等样本会停留在 `P2_support`，导致 RAG 被放行。
- `response_validator` 对空回复缺少稳定的确定性兜底话术；安全路径虽然尝试模型再生，但再生失败后仍会返回 `failed_no_reply`。

## 关键产出

- 新增修复计划：`docs/superpowers/plans/2026-05-22-phase2-rag-eval-repair.md`。
- 计划优先级：先补回归测试，再强化 `control_plane` 路由和 RAG 阻断，随后加入空回复兜底，最后做 round-2 smoke eval。

## 验证结果

- 本轮是只读复盘和计划落地，未修改后端运行代码。
- 使用项目虚拟环境读取并归并了 `backend/data/eval_reports/phase2_rag_agent_answers.jsonl` 和 `backend/data/eval_reports/phase2_rag_codex_all_results.jsonl`。
- 对 `control_plane` 做了本地探针，确认多个失败样本当前确实会进入 `P2_support` 并放行 RAG。

## 后续事项

- 执行修复计划前，建议人工先复核 round-1 报告中的 no-reply 和最低分样本。
- 修复后先跑 10 条定向 smoke，再决定是否重跑 100 条全量 RAG 评测。
- 生成的 `backend/data/eval_reports/` 报告仍应保持未提交，除非用户明确要求归档。

## 模型再生重试实现

- 日期：2026-05-22。
- 背景：用户确认修复方向后，补充要求模型再生路径必须可重试；最多 6 次仍没有可用输出时，不再返回空回复，而是返回心理咨询场景下温和的固定兜底句。
- 关键改动：`backend/app/graphs/nodes/validator_nodes.py` 中的 `_regenerate_reply_with_model` 改为最多 6 次尝试；空内容、异常和再生后仍触发 validator blocking 的内容都会继续尝试。6 次后返回 `回复失败了，请再次呼唤微风，我会继续陪你。`，并标记 `validator_regeneration_exhausted`。
- 关键改动：普通空回复路径也会进入再生流程，不再只有安全路径尝试再生；`conversation_quality_service` 同步识别 `empty_reply_regenerated` 和 `validator_regeneration_exhausted`。
- 验证：先运行新增/调整的两个测试并确认失败，再实现逻辑后运行通过；随后完整运行 `tests/test_conversation_control_rag.py`，结果为 66 passed。
- 后续：round-2 smoke eval 时重点观察 `no_reply` 是否降到 0，以及 `validator_regeneration_exhausted` 的出现频率是否过高。

## 安全路由与 RAG 阻断修复

- 日期：2026-05-22。
- 背景：按照修复计划继续处理 round-1 暴露的 `missed_high_risk`、RAG 错误介入和 `no_reply` 问题。
- 关键改动：`control_plane` 增补家暴/受害、未成年人不当接触、他伤、带地点的自伤危机、医疗诊断、依赖边界和隐私边界关键词；新增 `privacy_boundary` 风险类别。
- 关键改动：`risk_policy` 增加 `victimization` 与 `privacy_boundary` 的允许/禁止动作，并把 `privacy_boundary` 归入阻断上下文；`counseling_vector_service` 同步阻断该类别的 RAG 检索。
- 关键改动：`test_conversation_control_rag.py` 新增二期失败样本回归测试，覆盖 8 个高风险/边界样本必须先被安全路由拦截且不调用 RAG。
- 验证：新增路由测试在实现前失败，修复后 `tests/test_conversation_control_rag.py::ConversationControlRagTests::test_phase2_eval_failed_cases_route_before_rag` 和 `test_phase2_eval_blocked_cases_do_not_call_rag_retriever` 通过，合计 2 passed、14 subtests passed。
- 验证：`.\.venv\Scripts\python.exe -m pytest tests\test_conversation_control_rag.py tests\test_risk_policy.py tests\test_safety_evaluation.py -q`：196 passed、36 subtests passed。
- 验证：`.\.venv\Scripts\python.exe -m pytest tests\evals\test_subjective_eval_schemas.py tests\evals\test_subjective_eval_prompts.py tests\evals\test_subjective_eval_fixtures.py tests\evals\test_subjective_eval_results.py tests\test_run_subjective_evals_script.py -q`：56 passed、340 subtests passed。
- Round-2 smoke：开启 RAG、Milvus、本地 embedding 和 180 秒检索超时后，针对 10 条样本生成 `phase2_rag_round2_smoke_answers.jsonl` 与 `phase2_rag_round2_smoke_summary.json`；结果为 total 10、generated 10、failed_no_reply 0、rag_used 2、blocked_case_failures 0。
- 后续：建议先人工抽查 round-2 smoke 的高风险话术质量，再决定是否重跑 100 条全量 RAG 评测并做 Codex judge 汇总。
