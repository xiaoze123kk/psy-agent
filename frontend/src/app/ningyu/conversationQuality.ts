import type { ChatStreamGraphUpdateEvent, ConversationFeedbackValue } from "../../types/api";

export type ConversationFeedbackSubmitStatus = "idle" | "submitting" | "submitted" | "failed";

export interface TraceTiming {
  totalMs?: number;
  totalGraphMs?: number;
  ragMs?: number;
  nodeMs?: number;
  nodeCount?: number;
  ragUsed?: boolean;
  ragStatus?: string;
  ragHitCount?: number;
  ragTotalMs?: number;
  ragEmbeddingMs?: number;
  ragMilvusMs?: number;
  retrievedMemoryCount?: number;
  retrievedExampleCount?: number;
  ragSkippedReason?: string;
  node?: string;
  slowestNode?: string;
  slowestNodeMs?: number;
}

export const conversationFeedbackOptions: Array<{ value: ConversationFeedbackValue; label: string }> = [
  { value: "missed", label: "错过了" },
  { value: "too_analytic", label: "太分析" },
  { value: "too_generic", label: "太泛" },
  { value: "too_many_questions", label: "问题太多" },
  { value: "good", label: "刚刚好" },
];

export function formatDuration(ms?: number): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) {
    return null;
  }

  if (ms < 1000) {
    return `${Math.round(ms)}毫秒`;
  }

  const seconds = ms / 1000;
  return `${seconds >= 10 ? Math.round(seconds) : seconds.toFixed(1)}秒`;
}

export function numberOrUndefined(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  return undefined;
}

export function reasonOrUndefined(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();
  if (!trimmed || trimmed.toLowerCase() === "none") {
    return undefined;
  }

  return trimmed;
}

export function formatRagStatus(trace: TraceTiming): string {
  if (trace.ragStatus) {
    const statusLabels: Record<string, string> = {
      hit: "知识检索命中",
      empty: "知识检索无命中",
      timeout: "知识检索超时",
      error: "知识检索错误",
      skipped: "知识检索跳过",
    };
    const label = statusLabels[trace.ragStatus] ?? `知识检索 ${trace.ragStatus}`;
    const hitCount = trace.ragHitCount ?? trace.retrievedExampleCount;
    return hitCount !== undefined ? `${label} ${hitCount} 条` : label;
  }

  const totalRetrieved = (trace.retrievedMemoryCount ?? 0) + (trace.retrievedExampleCount ?? 0);
  if (totalRetrieved > 0) {
    return `知识检索 ${totalRetrieved} 条`;
  }

  if (trace.ragUsed === true) {
    return "知识检索已参考";
  }

  if (trace.ragSkippedReason) {
    return `知识检索跳过：${trace.ragSkippedReason}`;
  }

  if (trace.ragUsed === false) {
    return "知识检索未使用";
  }

  return "知识检索未知";
}

export function traceTimingFromRagTrace(summary: Record<string, unknown> | undefined): TraceTiming | null {
  if (!summary) {
    return null;
  }

  const trace: TraceTiming = {
    ragStatus: stringOrUndefined(summary.status),
    ragHitCount: firstNumber(summary.hit_count),
    ragTotalMs: firstNumber(summary.total_duration_ms),
    ragEmbeddingMs: firstNumber(summary.embedding_duration_ms),
    ragMilvusMs: firstNumber(summary.milvus_duration_ms),
    ragMs: firstNumber(summary.rag_duration_ms, summary.rag_ms, summary.total_duration_ms, summary.duration_ms, summary.total_ms),
    ragUsed: booleanOrUndefined(summary.rag_used),
    retrievedMemoryCount: firstNumber(summary.retrieved_memory_count, summary.memory_count),
    retrievedExampleCount: firstNumber(summary.retrieved_example_count, summary.example_count, summary.hit_count),
    ragSkippedReason: reasonOrUndefined(summary.rag_skipped_reason ?? summary.skipped_reason),
  };

  return hasTraceTimingValue(trace) ? trace : null;
}

export function traceTimingFromSummary(summary: Record<string, unknown> | undefined): TraceTiming | null {
  if (!summary) {
    return null;
  }

  const nestedRagTrace = recordOrUndefined(summary.rag_trace_summary) ?? recordOrUndefined(summary.rag_trace);
  const nestedRag = recordOrUndefined(summary.rag);
  const nestedRagInnerTrace = recordOrUndefined(nestedRag?.trace);
  const slowestNode = recordOrUndefined(summary.slowest_node);
  const ragTrace = traceTimingFromRagTrace(nestedRagTrace);
  const ragInnerTrace = traceTimingFromRagTrace(nestedRagInnerTrace);
  const trace: TraceTiming = {
    totalMs: firstNumber(summary.duration_ms, summary.total_ms, summary.end_to_end_ms, summary.end_to_end_duration_ms),
    totalGraphMs: firstNumber(summary.total_graph_duration_ms),
    nodeMs: firstNumber(summary.node_duration_ms, summary.node_ms),
    nodeCount: firstNumber(summary.node_count),
    node: reasonOrUndefined(summary.node),
    slowestNode: reasonOrUndefined(slowestNode?.node_name) ?? reasonOrUndefined(slowestNode?.node),
    slowestNodeMs: firstNumber(slowestNode?.duration_ms),
    ragStatus: stringOrUndefined(summary.status) ?? ragTrace?.ragStatus ?? ragInnerTrace?.ragStatus,
    ragHitCount: firstNumber(summary.hit_count, ragTrace?.ragHitCount, ragInnerTrace?.ragHitCount),
    ragTotalMs: firstNumber(summary.total_duration_ms, ragTrace?.ragTotalMs, ragInnerTrace?.ragTotalMs),
    ragEmbeddingMs: firstNumber(summary.embedding_duration_ms, ragTrace?.ragEmbeddingMs, ragInnerTrace?.ragEmbeddingMs),
    ragMilvusMs: firstNumber(summary.milvus_duration_ms, ragTrace?.ragMilvusMs, ragInnerTrace?.ragMilvusMs),
    ragMs: firstNumber(summary.rag_duration_ms, summary.rag_ms, ragTrace?.ragMs, ragInnerTrace?.ragMs),
    ragUsed: booleanOrUndefined(summary.rag_used) ?? booleanOrUndefined(nestedRag?.used) ?? ragTrace?.ragUsed ?? ragInnerTrace?.ragUsed,
    retrievedMemoryCount: firstNumber(summary.retrieved_memory_count, ragTrace?.retrievedMemoryCount, ragInnerTrace?.retrievedMemoryCount),
    retrievedExampleCount: firstNumber(
      summary.retrieved_example_count,
      nestedRag?.retrieved_example_count,
      ragTrace?.retrievedExampleCount,
      ragInnerTrace?.retrievedExampleCount,
    ),
    ragSkippedReason:
      reasonOrUndefined(summary.rag_skipped_reason) ??
      reasonOrUndefined(nestedRag?.skipped_reason) ??
      ragTrace?.ragSkippedReason ??
      ragInnerTrace?.ragSkippedReason,
  };

  return hasTraceTimingValue(trace) ? trace : null;
}

export function graphUpdateDetail(update: ChatStreamGraphUpdateEvent): string {
  const timing =
    traceTimingFromSummary({
      ...update.rag_trace_summary,
      node: update.node,
      duration_ms: update.duration_ms,
      retrieved_memory_count: update.retrieved_memory_count,
      retrieved_example_count: update.retrieved_example_count,
      rag_used: update.rag_used,
      rag_skipped_reason: update.rag_skipped_reason,
      rag_trace_summary: update.rag_trace_summary,
    }) ?? { node: update.node };

  const parts = [
    update.node,
    formatDuration(timing.totalMs ?? timing.nodeMs),
    timing.ragStatus ||
    timing.ragUsed !== undefined ||
    timing.retrievedMemoryCount !== undefined ||
    timing.retrievedExampleCount !== undefined ||
    timing.ragSkippedReason
      ? formatRagStatus(timing)
      : null,
    update.intent ? `意图 ${update.intent}` : null,
    update.route_priority ? `优先级 ${update.route_priority}` : null,
    update.control_category ? `控制 ${update.control_category}` : null,
    update.validator_blocked ? "安全校验拦截" : null,
    update.delivery_status ? `投递 ${update.delivery_status}` : null,
  ].filter((part): part is string => Boolean(part));

  return parts.join(" · ");
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function booleanOrUndefined(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = numberOrUndefined(value);
    if (parsed !== undefined) {
      return parsed;
    }
  }

  return undefined;
}

function recordOrUndefined(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function hasTraceTimingValue(trace: TraceTiming): boolean {
  return Object.values(trace).some((value) => value !== undefined);
}
