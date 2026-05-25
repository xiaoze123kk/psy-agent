import type {
  ChatStreamFinalEvent,
  ChatStreamGraphUpdateEvent,
  ConversationFeedbackRequest,
  ConversationQualitySummary,
  FeedbackCreateRequest,
} from "../../types/api";
import {
  conversationFeedbackOptions,
  formatDuration,
  formatRagStatus,
  graphUpdateDetail,
  traceTimingFromRagTrace,
  traceTimingFromSummary,
} from "./conversationQuality";

const assertType = <T>(value: T): T => value;

const conversationFeedback = assertType<ConversationFeedbackRequest>({
  thread_id: "thread-1",
  turn_id: "turn-1",
  feedback: "good",
  optional_note: null,
});

const feedbackPayload: FeedbackCreateRequest = conversationFeedback;

assertType<ConversationQualitySummary>({
  total_turns: 3,
  limit: 200,
  thread_id: "thread-1",
  feedback_counts: { good: 2, missed: 1 },
  next_turn_signal_counts: {},
  conversation_move_counts: {},
  voice_mode_counts: {},
  validator_severity_counts: {},
  validator_reason_counts: {},
  experience_reason_counts: {},
  negative_feedback_by_move: {},
  question_count_buckets: {},
});

const graphUpdate = assertType<ChatStreamGraphUpdateEvent>({
  node: "example_retriever",
  duration_ms: 1234,
  retrieved_example_count: 2,
  rag_trace_summary: {
    status: "hit",
    hit_count: 3,
    total_duration_ms: 456,
  },
});

const finalEvent = assertType<ChatStreamFinalEvent>({
  thread_id: "thread-1",
  message_id: "message-1",
  assistant_message_id: "assistant-1",
  turn_id: "turn-1",
  turn_status: "completed",
  assistant_text: "我在。",
  risk_level: "L0",
  intent: "support",
  suggested_actions: [],
  session_summary: "",
  should_write_memory: false,
  referenced_memories: [],
  delivery_status: "generated",
  retryable: false,
  trace_summary: {
    node_count: 2,
    total_graph_duration_ms: 2048,
    slowest_node: { node_name: "dialogue_generation", duration_ms: 1500 },
    rag: {
      used: true,
      trace: {
        status: "hit",
        hit_count: 3,
        total_duration_ms: 456,
      },
      retrieved_example_count: 3,
    },
  },
});

const assertEqual = (actual: unknown, expected: unknown) => {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, received ${String(actual)}`);
  }
};

const ragTrace = traceTimingFromRagTrace(graphUpdate.rag_trace_summary);
const finalTrace = traceTimingFromSummary(finalEvent.trace_summary);

assertEqual(conversationFeedbackOptions.length, 5);
assertEqual(formatDuration(1234), "1.2秒");
assertEqual(formatDuration(undefined), null);
assertEqual(formatRagStatus({ ragStatus: "hit", ragHitCount: 3 }), "知识检索命中 3 条");
assertEqual(graphUpdateDetail(graphUpdate), "example_retriever · 1.2秒 · 知识检索命中 3 条");
assertEqual(ragTrace?.ragStatus, "hit");
assertEqual(ragTrace?.ragHitCount, 3);
assertEqual(finalTrace?.totalGraphMs, 2048);
assertEqual(finalTrace?.slowestNode, "dialogue_generation");
assertEqual(finalTrace?.retrievedExampleCount, 3);

void feedbackPayload;
