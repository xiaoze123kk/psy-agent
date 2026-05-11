import type {
  ChatStreamGraphUpdateEvent,
  ChatTraceSummary,
  ChatTraceStep,
  DeliveryStatus,
  MemoryReference,
  RiskLevel,
} from "../types/api";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object");
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function normalizeRisk(value: unknown): RiskLevel | undefined {
  return value === "L0" || value === "L1" || value === "L2" || value === "L3" ? value : undefined;
}

function normalizeDelivery(value: unknown): DeliveryStatus | undefined {
  return value === "generated" || value === "failed_no_reply" || value === "safety_fallback" ? value : undefined;
}

function normalizeMemoryRefs(value: unknown): MemoryReference[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => isRecord(item))
    .map((item) => ({
      memory_id: String(item.memory_id ?? ""),
      memory_type: String(item.memory_type ?? ""),
      content: String(item.content ?? "").trim(),
    }))
    .filter((item) => Boolean(item.memory_id && item.content));
}

function normalizeStep(value: unknown, fallbackSequence = 0): ChatTraceStep | null {
  if (!isRecord(value)) return null;
  const nodeName = asString(value.node_name) ?? asString(value.node) ?? "";
  if (!nodeName) return null;
  return {
    sequence: asNumber(value.sequence) ?? fallbackSequence,
    trace_type: asString(value.trace_type) ?? "graph_node",
    node_name: nodeName,
    status: asString(value.status) ?? "completed",
    duration_ms: asNumber(value.duration_ms) ?? 0,
    reason_codes: asStringList(value.reason_codes),
    error_code: asString(value.error_code) ?? null,
    output_summary: isRecord(value.output_summary) ? value.output_summary : {},
  };
}

export function normalizeTraceSummary(value: unknown): ChatTraceSummary | null {
  if (!isRecord(value)) return null;
  const mode = isRecord(value.mode) ? value.mode : {};
  const memory = isRecord(value.memory) ? value.memory : {};
  const rag = isRecord(value.rag) ? value.rag : {};
  const validator = isRecord(value.validator) ? value.validator : {};
  const fallback = isRecord(value.fallback) ? value.fallback : {};
  const steps = Array.isArray(value.steps)
    ? value.steps.map((step, index) => normalizeStep(step, index)).filter((step): step is ChatTraceStep => Boolean(step))
    : [];

  return {
    node_count: asNumber(value.node_count) ?? steps.length,
    failed_nodes: asStringList(value.failed_nodes),
    slowest_node: isRecord(value.slowest_node)
      ? {
          node_name: asString(value.slowest_node.node_name) ?? "",
          duration_ms: asNumber(value.slowest_node.duration_ms) ?? 0,
        }
      : null,
    total_graph_duration_ms: asNumber(value.total_graph_duration_ms),
    delivery_status: normalizeDelivery(value.delivery_status) ?? asString(value.delivery_status),
    failure_reason: asString(value.failure_reason) ?? null,
    validator_blocked: asBoolean(value.validator_blocked),
    mode: {
      intent: asString(mode.intent),
      control_category: asString(mode.control_category),
      route_priority: asString(mode.route_priority),
      risk_level: normalizeRisk(mode.risk_level) ?? asString(mode.risk_level),
    },
    memory: {
      memory_mode: asString(memory.memory_mode) ?? null,
      retrieved_count: asNumber(memory.retrieved_count),
      referenced_count: asNumber(memory.referenced_count),
      referenced_memories: normalizeMemoryRefs(memory.referenced_memories),
      should_write: asBoolean(memory.should_write),
      write_decision_count: asNumber(memory.write_decision_count),
      write_decisions: Array.isArray(memory.write_decisions)
        ? memory.write_decisions.filter((item): item is Record<string, unknown> => isRecord(item))
        : [],
      job_id: asString(memory.job_id),
      job_status: asString(memory.job_status),
    },
    rag: {
      used: asBoolean(rag.used),
      skipped_reason: asString(rag.skipped_reason),
      retrieved_example_count: asNumber(rag.retrieved_example_count),
      example_ids: asStringList(rag.example_ids),
      example_source_keys: asStringList(rag.example_source_keys),
    },
    validator: {
      checked: asBoolean(validator.checked),
      blocked: asBoolean(validator.blocked),
      reasons: asStringList(validator.reasons),
      delivery_status: normalizeDelivery(validator.delivery_status) ?? asString(validator.delivery_status),
    },
    fallback: {
      triggered: asBoolean(fallback.triggered),
      reason: asString(fallback.reason) ?? null,
      retryable: asBoolean(fallback.retryable),
    },
    steps,
  };
}

export function mergeTraceGraphUpdate(summary: ChatTraceSummary | null | undefined, update: ChatStreamGraphUpdateEvent): ChatTraceSummary {
  const current: ChatTraceSummary = normalizeTraceSummary(summary) ?? { steps: [] };
  const steps = current.steps ?? [];
  const step: ChatTraceStep = {
    sequence: steps.length,
    trace_type: "graph_update",
    node_name: update.node,
    status: update.status ?? "completed",
    duration_ms: update.duration_ms ?? 0,
    reason_codes: update.validator_reasons ?? [],
    output_summary: {
      risk_level: update.risk_level,
      intent: update.intent,
      control_category: update.control_category,
      route_priority: update.route_priority,
      retrieved_memory_count: update.retrieved_memory_count,
      retrieved_example_count: update.retrieved_example_count,
      rag_used: update.rag_used,
      rag_skipped_reason: update.rag_skipped_reason,
      validator_blocked: update.validator_blocked,
      validator_reasons: update.validator_reasons,
      delivery_status: update.delivery_status,
      failure_reason: update.failure_reason,
      should_write_memory: update.should_write_memory,
    },
  };

  return normalizeTraceSummary({
    ...current,
    node_count: Math.max(current.node_count ?? 0, steps.length + 1),
    delivery_status: update.delivery_status ?? current.delivery_status,
    failure_reason: update.failure_reason ?? current.failure_reason,
    mode: {
      ...current.mode,
      intent: update.intent ?? current.mode?.intent,
      control_category: update.control_category ?? current.mode?.control_category,
      route_priority: update.route_priority ?? current.mode?.route_priority,
      risk_level: update.risk_level ?? current.mode?.risk_level,
    },
    memory: {
      ...current.memory,
      retrieved_count: update.retrieved_memory_count ?? current.memory?.retrieved_count,
      should_write: update.should_write_memory ?? current.memory?.should_write,
      write_decision_count: update.memory_write_decision_count ?? current.memory?.write_decision_count,
    },
    rag: {
      ...current.rag,
      used: update.rag_used ?? current.rag?.used,
      skipped_reason: update.rag_skipped_reason ?? current.rag?.skipped_reason,
      retrieved_example_count: update.retrieved_example_count ?? current.rag?.retrieved_example_count,
    },
    validator: {
      ...current.validator,
      checked: update.node === "response_validator" || current.validator?.checked,
      blocked: update.validator_blocked ?? current.validator?.blocked,
      reasons: update.validator_reasons ?? current.validator?.reasons,
      delivery_status: update.delivery_status ?? current.validator?.delivery_status,
    },
    fallback: {
      ...current.fallback,
      triggered: update.delivery_status ? update.delivery_status !== "generated" : current.fallback?.triggered,
      reason: update.failure_reason ?? current.fallback?.reason,
      retryable: update.retryable ?? current.fallback?.retryable,
    },
    steps: [...steps, step],
  }) as ChatTraceSummary;
}

export function mergeTraceSummary(
  liveSummary: ChatTraceSummary | null | undefined,
  finalSummary: ChatTraceSummary | null | undefined,
): ChatTraceSummary | null {
  const finalTrace = normalizeTraceSummary(finalSummary);
  const liveTrace = normalizeTraceSummary(liveSummary);
  if (!finalTrace) return liveTrace;
  if ((finalTrace.steps?.length ?? 0) > 0) return finalTrace;
  return normalizeTraceSummary({ ...finalTrace, steps: liveTrace?.steps ?? [] });
}

export function hasTraceContent(summary: ChatTraceSummary | null | undefined): boolean {
  const trace = normalizeTraceSummary(summary);
  return Boolean(trace && ((trace.node_count ?? 0) > 0 || (trace.steps?.length ?? 0) > 0 || trace.delivery_status));
}

export function traceNodeLabel(node?: string | null): string {
  const labels: Record<string, string> = {
    accepted: "接收请求",
    risk_classifier: "风险识别",
    load_user_profile: "读取设置",
    control_plane: "模式分流",
    intent_classifier: "理解意图",
    memory_retrieval: "读取记忆",
    example_retriever: "检索参考",
    companion_response: "陪伴式回复",
    soothing_response: "安抚式回复",
    counseling_response: "咨询式回复",
    crisis_response: "危机支持",
    clinical_red_flag_response: "安全提醒",
    boundary_response: "边界回复",
    response_validator: "回复校验",
    summarize_turn: "整理摘要",
    memory_candidate_extract: "提取记忆候选",
    write_memory: "写入记忆",
    summary_memory_node: "摘要记忆",
    saving_record: "保存记录",
    delivery_result: "投递结果",
  };
  return node ? labels[node] ?? "处理步骤" : "处理步骤";
}

export function traceModeText(summary: ChatTraceSummary | null | undefined): string {
  const trace = normalizeTraceSummary(summary);
  const mode = trace?.mode;
  if (mode?.route_priority === "P0_immediate_safety") return "安全优先模式";
  if (mode?.route_priority === "P1_clinical_red_flag") return "安全提醒模式";
  if (mode?.control_category === "abusive_to_assistant") return "边界回复模式";
  if (mode?.intent === "soothe") return "安抚陪伴模式";
  if (mode?.intent === "counseling") return "咨询支持模式";
  if (mode?.intent === "vent") return "倾诉陪伴模式";
  return "日常陪伴模式";
}

export function traceMemoryText(summary: ChatTraceSummary | null | undefined, fallbackRefs: MemoryReference[] = []): string {
  const trace = normalizeTraceSummary(summary);
  const memory = trace?.memory;
  const count = memory?.referenced_count ?? memory?.referenced_memories?.length ?? fallbackRefs.length ?? 0;
  const retrieved = memory?.retrieved_count ?? count;
  if (count > 0) return `引用了 ${count} 条记忆`;
  if (retrieved > 0) return `读取了 ${retrieved} 条记忆`;
  if (memory?.memory_mode === "off") return "记忆已关闭";
  return "未使用长期记忆";
}

export function traceRagText(summary: ChatTraceSummary | null | undefined): string {
  const rag = normalizeTraceSummary(summary)?.rag;
  if (rag?.used) return `参考了 ${rag.retrieved_example_count ?? 0} 条案例`;
  if (rag?.skipped_reason) return "未启用案例参考";
  return "未使用案例参考";
}

export function traceValidatorText(summary: ChatTraceSummary | null | undefined): string {
  const validator = normalizeTraceSummary(summary)?.validator;
  if (validator?.blocked) return "校验后降级";
  if (validator?.checked) return "已通过校验";
  return "未触发校验";
}

export function traceFallbackText(summary: ChatTraceSummary | null | undefined): string {
  const trace = normalizeTraceSummary(summary);
  if (!trace?.fallback?.triggered) return "";
  if (trace.delivery_status === "safety_fallback") return "触发安全降级";
  if (trace.delivery_status === "failed_no_reply") return "未生成可用回复";
  return "触发降级";
}

export function traceHeadline(summary: ChatTraceSummary | null | undefined, fallbackRefs: MemoryReference[] = []): string {
  const trace = normalizeTraceSummary(summary);
  const parts = [traceModeText(trace), traceMemoryText(trace, fallbackRefs), traceValidatorText(trace)];
  const fallback = traceFallbackText(trace);
  if (fallback) parts.push(fallback);
  return parts.join(" · ");
}

export function traceMemoryRefs(summary: ChatTraceSummary | null | undefined, fallbackRefs: MemoryReference[] = []): MemoryReference[] {
  const refs = normalizeTraceSummary(summary)?.memory?.referenced_memories ?? [];
  return refs.length ? refs : fallbackRefs;
}
