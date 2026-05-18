# Frontend Conversation Quality Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the main frontend up to parity with the desktop chat lab for conversation-quality feedback and trace visibility.

**Architecture:** Keep backend behavior unchanged and add frontend-only contract, parsing, and presentation layers. Put pure feedback/trace helpers in a small `conversationQuality.ts` module, then wire `NingyuAppShell.tsx` to persist turn ids, submit feedback, and render compact trace summaries.

**Tech Stack:** Vite, React 19, TypeScript strict mode, existing CSS modules, existing `/api/v1/feedback` backend contract.

---

## File Structure

- Modify: `frontend/src/types/api.ts`
  - Add conversation feedback value types, light feedback request, quality summary response, graph trace fields, final trace field.
- Modify: `frontend/src/api/endpoints.ts`
  - Add semantic wrappers for conversation quality feedback and optional quality summary.
- Create: `frontend/src/app/ningyu/conversationQuality.ts`
  - Pure helpers for duration formatting, RAG status labels, trace extraction, graph update detail formatting, and feedback labels.
- Create: `frontend/src/app/ningyu/conversationQuality.contract.ts`
  - Typecheck-only contract examples that fail before helpers/types exist and pass after implementation.
- Modify: `frontend/src/app/ningyu/NingyuAppShell.tsx`
  - Store `turnId`, `assistantMessageId`, `trace`, feedback state, and trace-aware graph updates.
  - Submit conversation-quality feedback to backend.
  - Render `TraceLine` and five naturalness feedback choices.
- Modify: `frontend/src/app/ningyu/NingyuAppShell.css`
  - Style trace line and expanded feedback controls with low visual weight.

---

### Task 1: Add Types, API Wrappers, And Pure Trace Helpers

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Create: `frontend/src/app/ningyu/conversationQuality.ts`
- Create: `frontend/src/app/ningyu/conversationQuality.contract.ts`

- [ ] **Step 1: Write the failing contract file**

Create `frontend/src/app/ningyu/conversationQuality.contract.ts`:

```ts
import {
  conversationFeedbackOptions,
  formatDuration,
  graphUpdateDetail,
  traceTimingFromRagTrace,
  traceTimingFromSummary,
} from "./conversationQuality";
import type {
  ChatStreamFinalEvent,
  ChatStreamGraphUpdateEvent,
  ConversationFeedbackRequest,
  ConversationFeedbackValue,
  ConversationQualitySummary,
  FeedbackCreateRequest,
} from "../../types/api";

const feedback: ConversationFeedbackValue = "too_many_questions";

const request: ConversationFeedbackRequest = {
  thread_id: "thread-1",
  turn_id: "turn-1",
  feedback,
  optional_note: "短一点会更贴近",
};

const feedbackPayload: FeedbackCreateRequest = request;

const summary: ConversationQualitySummary = {
  total_turns: 1,
  limit: 200,
  thread_id: "thread-1",
  feedback_counts: { too_many_questions: 1 },
  next_turn_signal_counts: {},
  conversation_move_counts: {},
  voice_mode_counts: {},
  validator_severity_counts: {},
  validator_reason_counts: {},
  experience_reason_counts: {},
  negative_feedback_by_move: {},
  question_count_buckets: {},
};

const graphUpdate: ChatStreamGraphUpdateEvent = {
  node: "example_retriever",
  duration_ms: 235,
  rag_trace_summary: {
    status: "hit",
    hit_count: 3,
    total_duration_ms: 180,
  },
};

const finalEvent: ChatStreamFinalEvent = {
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
    total_graph_duration_ms: 420,
    slowest_node: { node_name: "dialogue_generation", duration_ms: 300 },
    rag: { trace: { status: "hit", hit_count: 3 } },
  },
};

const trace = traceTimingFromSummary(finalEvent.trace_summary);
const ragTrace = traceTimingFromRagTrace(graphUpdate.rag_trace_summary);
const detail = graphUpdateDetail(graphUpdate);

if (formatDuration(1200) !== "1.2s") throw new Error("duration formatting changed");
if (!trace?.slowestNode) throw new Error("slowest node missing");
if (ragTrace.ragStatus !== "hit") throw new Error("RAG trace missing");
if (!detail.includes("RAG")) throw new Error("graph update detail missing RAG status");
if (conversationFeedbackOptions.length !== 5) throw new Error("feedback option count changed");

void feedbackPayload;
void summary;
```

- [ ] **Step 2: Run typecheck and verify RED**

Run:

```powershell
cd frontend
npm run check
```

Expected: FAIL because `conversationQuality.ts` and the new exported API types do not exist yet.

- [ ] **Step 3: Implement types and API wrappers**

In `frontend/src/types/api.ts`, add:

```ts
export type ConversationFeedbackValue =
  | "missed"
  | "too_analytic"
  | "too_generic"
  | "too_many_questions"
  | "good";

export interface ConversationFeedbackRequest {
  thread_id: string;
  turn_id: string;
  feedback: ConversationFeedbackValue;
  optional_note?: string;
}

export interface ConversationQualitySummary {
  total_turns: number;
  limit: number;
  thread_id: string | null;
  feedback_counts: Record<string, number>;
  next_turn_signal_counts: Record<string, number>;
  conversation_move_counts: Record<string, number>;
  voice_mode_counts: Record<string, number>;
  validator_severity_counts: Record<string, number>;
  validator_reason_counts: Record<string, number>;
  experience_reason_counts: Record<string, number>;
  negative_feedback_by_move: Record<string, number>;
  question_count_buckets: Record<string, number>;
}
```

Extend `FeedbackCreateRequest`:

```ts
export interface FeedbackCreateRequest {
  target_type?: "assistant_message" | "knowledge_answer" | "test_result";
  target_id?: string;
  rating?: number;
  tags?: string[];
  note?: string | null;
  thread_id?: string;
  turn_id?: string;
  feedback?: ConversationFeedbackValue;
  optional_note?: string;
}
```

Extend `ChatStreamGraphUpdateEvent` with:

```ts
retrieved_example_count?: number;
rag_trace_summary?: Record<string, unknown>;
duration_ms?: number;
```

Extend `ChatStreamFinalEvent` with:

```ts
trace_summary?: Record<string, unknown>;
```

In `frontend/src/api/endpoints.ts`, import the new types and add:

```ts
submitConversationQualityFeedback(payload: ConversationFeedbackRequest): Promise<FeedbackResponse> {
  return this.submitFeedback(payload);
}

getConversationQualitySummary(threadId?: string): Promise<ConversationQualitySummary> {
  const query = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : "";
  return this.client.get<ConversationQualitySummary>(`/api/v1/feedback/conversation-quality/summary${query}`);
}
```

- [ ] **Step 4: Implement pure helpers**

Create `frontend/src/app/ningyu/conversationQuality.ts`:

```ts
import type { ChatStreamGraphUpdateEvent, ConversationFeedbackValue } from "../../types/api";

export type ConversationFeedbackSubmitStatus = "idle" | "submitting" | "submitted" | "failed";

export interface TraceTiming {
  endToEndMs?: number;
  totalGraphMs?: number;
  lastNode?: string;
  lastNodeMs?: number;
  slowestNode?: string;
  slowestNodeMs?: number;
  nodeCount?: number;
  ragStatus?: string;
  ragHitCount?: number;
  ragTotalMs?: number;
  ragEmbeddingMs?: number;
  ragMilvusMs?: number;
  ragSkippedReason?: string;
}

export const conversationFeedbackOptions: Array<{ value: ConversationFeedbackValue; label: string }> = [
  { value: "missed", label: "没接住" },
  { value: "too_analytic", label: "太分析了" },
  { value: "too_generic", label: "太泛了" },
  { value: "too_many_questions", label: "问太多" },
  { value: "good", label: "刚刚好" },
];

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
}

export function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function reasonOrUndefined(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (!trimmed || trimmed.toLowerCase() === "none") return undefined;
  return trimmed;
}

export function formatRagStatus(status: string): string {
  if (status === "hit") return "命中";
  if (status === "empty") return "无命中";
  if (status === "timeout") return "超时";
  if (status === "error") return "错误";
  if (status === "skipped") return "跳过";
  return status;
}

export function traceTimingFromRagTrace(trace: unknown): TraceTiming {
  if (!trace || typeof trace !== "object") return {};
  const source = trace as Record<string, unknown>;
  return {
    ragStatus: typeof source.status === "string" ? source.status : undefined,
    ragHitCount: numberOrUndefined(source.hit_count),
    ragTotalMs: numberOrUndefined(source.total_duration_ms),
    ragEmbeddingMs: numberOrUndefined(source.embedding_duration_ms),
    ragMilvusMs: numberOrUndefined(source.milvus_duration_ms),
    ragSkippedReason: reasonOrUndefined(source.skipped_reason),
  };
}

export function traceTimingFromSummary(summary: unknown): TraceTiming | null {
  if (!summary || typeof summary !== "object") return null;
  const source = summary as Record<string, unknown>;
  const slowest = source.slowest_node && typeof source.slowest_node === "object" ? (source.slowest_node as Record<string, unknown>) : null;
  const rag = source.rag && typeof source.rag === "object" ? (source.rag as Record<string, unknown>) : null;
  const ragTrace = rag?.trace && typeof rag.trace === "object" ? (rag.trace as Record<string, unknown>) : null;
  const trace: TraceTiming = {
    totalGraphMs: numberOrUndefined(source.total_graph_duration_ms),
    nodeCount: numberOrUndefined(source.node_count),
    slowestNode: typeof slowest?.node_name === "string" ? slowest.node_name : typeof slowest?.node === "string" ? slowest.node : undefined,
    slowestNodeMs: slowest ? numberOrUndefined(slowest.duration_ms) : undefined,
    ...traceTimingFromRagTrace(ragTrace),
    ragSkippedReason: reasonOrUndefined(rag?.skipped_reason),
  };
  return Object.values(trace).some((value) => value !== undefined) ? trace : null;
}

export function graphUpdateDetail(update: ChatStreamGraphUpdateEvent): string {
  const ragTrace = traceTimingFromRagTrace(update.rag_trace_summary);
  if (ragTrace.ragStatus) {
    const parts = [`RAG ${formatRagStatus(ragTrace.ragStatus)}`];
    if (ragTrace.ragHitCount !== undefined) parts.push(`${ragTrace.ragHitCount}条`);
    if (ragTrace.ragTotalMs !== undefined) parts.push(formatDuration(ragTrace.ragTotalMs));
    if (ragTrace.ragSkippedReason) parts.push(ragTrace.ragSkippedReason);
    return parts.join(" · ");
  }

  const details = [
    update.intent ? `意图：${update.intent}` : null,
    update.route_priority ? `优先级：${update.route_priority}` : null,
    update.control_category ? `控制：${update.control_category}` : null,
    typeof update.retrieved_memory_count === "number" ? `记忆：${update.retrieved_memory_count}` : null,
    typeof update.retrieved_example_count === "number" ? `示例：${update.retrieved_example_count}` : null,
    typeof update.rag_used === "boolean" ? `知识：${update.rag_used ? "已参考" : "未使用"}` : null,
    update.rag_skipped_reason ? `RAG：${update.rag_skipped_reason}` : null,
    update.validator_blocked ? "已被安全校验拦截" : null,
    update.delivery_status ? `投递：${update.delivery_status}` : null,
  ].filter(Boolean);

  if (update.duration_ms !== undefined) details.push(`耗时：${formatDuration(update.duration_ms)}`);
  return details.join(" · ") || "正在整理这一步的上下文";
}
```

- [ ] **Step 5: Run typecheck and verify GREEN**

Run:

```powershell
cd frontend
npm run check
```

Expected: PASS.

---

### Task 2: Wire Turn IDs, Trace Parsing, And Feedback Submission

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.tsx`

- [ ] **Step 1: Import helper module and update message shape**

Import from `./conversationQuality`:

```ts
import {
  conversationFeedbackOptions,
  formatDuration,
  formatRagStatus,
  graphUpdateDetail,
  traceTimingFromRagTrace,
  traceTimingFromSummary,
  type ConversationFeedbackSubmitStatus,
  type TraceTiming,
} from "./conversationQuality";
```

Import `ConversationFeedbackValue` from `../../types/api`.

Extend `Message` with:

```ts
turnId?: string | null;
assistantMessageId?: string | null;
trace?: TraceTiming | null;
feedbackState?: {
  value: ConversationFeedbackValue;
  status: ConversationFeedbackSubmitStatus;
};
```

- [ ] **Step 2: Replace local feedback type and state**

Remove:

```ts
type MessageFeedback = "helpful" | "not_helpful";
const [messageFeedback, setMessageFeedback] = useState<Record<string, MessageFeedback>>({});
```

Messages should now own their own `feedbackState`.

- [ ] **Step 3: Preserve turn ids and trace from history**

Update `mapMessageItem()`:

```ts
function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function mapMessageItem(message: MessageItem): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    timestamp: formatMessageTime(message.created_at),
    riskLevel: message.risk_level,
    suggestedActions: extractSuggestedActions(message.metadata),
    metadata: message.metadata,
    turnId: stringOrNull(message.metadata.turn_id),
    assistantMessageId:
      stringOrNull(message.metadata.assistant_message_id) ?? (message.role === "assistant" ? message.id : null),
    deliveryStatus:
      typeof message.metadata.delivery_status === "string" ? message.metadata.delivery_status : undefined,
    trace: traceTimingFromSummary(message.metadata.trace_summary),
  };
}
```

- [ ] **Step 4: Preserve turn ids and trace during streaming**

In `accepted`, set `turnId`. In `graph_update`, use `graphUpdateDetail(update)` and update `trace` with node/RAG timing. In `final`, set `turnId`, `assistantMessageId`, and `traceTimingFromSummary(final.trace_summary)`.

The graph update state update must keep only five recent updates:

```ts
setGraphUpdates((current) => [...current.slice(-4), mapGraphUpdate(update)]);
```

- [ ] **Step 5: Submit conversation quality feedback**

Add:

```ts
const updateMessage = (messageId: string, update: (message: Message) => Message) => {
  setMessages((current) => current.map((message) => (message.id === messageId ? update(message) : message)));
};

const handleMessageFeedback = async (message: Message, feedback: ConversationFeedbackValue) => {
  if (!activeThreadId || !message.turnId || message.role !== "assistant") return;
  if (message.feedbackState?.status === "submitting" || message.feedbackState?.status === "submitted") return;

  updateMessage(message.id, (current) => ({
    ...current,
    feedbackState: { value: feedback, status: "submitting" },
  }));

  try {
    await api.submitConversationQualityFeedback({
      thread_id: activeThreadId,
      turn_id: message.turnId,
      feedback,
    });
    updateMessage(message.id, (current) => ({
      ...current,
      feedbackState: { value: feedback, status: "submitted" },
    }));
  } catch {
    updateMessage(message.id, (current) => ({
      ...current,
      feedbackState: { value: feedback, status: "failed" },
    }));
  }
};
```

- [ ] **Step 6: Run typecheck**

Run:

```powershell
cd frontend
npm run check
```

Expected: PASS.

---

### Task 3: Render Feedback Choices, Trace Line, And Styles

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.tsx`
- Modify: `frontend/src/app/ningyu/NingyuAppShell.css`

- [ ] **Step 1: Update `ChatMessage` props**

Change props from `(feedback, onFeedback)` to:

```ts
onFeedback: (message: Message, feedback: ConversationFeedbackValue) => void;
```

Call:

```tsx
<ChatMessage key={message.id} message={message} isNight={isNight} onFeedback={onMessageFeedback} />
```

- [ ] **Step 2: Add `TraceLine` component**

Add:

```tsx
function TraceLine({ trace }: { trace: TraceTiming }) {
  const parts = [
    trace.endToEndMs !== undefined ? `端到端 ${formatDuration(trace.endToEndMs)}` : null,
    trace.totalGraphMs !== undefined ? `图 ${formatDuration(trace.totalGraphMs)}` : null,
    trace.ragStatus ? `RAG ${formatRagStatus(trace.ragStatus)}${trace.ragHitCount !== undefined ? ` ${trace.ragHitCount}条` : ""}` : null,
    trace.ragSkippedReason ? `RAG原因 ${trace.ragSkippedReason}` : null,
    trace.slowestNode && trace.slowestNodeMs !== undefined ? `最慢 ${trace.slowestNode} ${formatDuration(trace.slowestNodeMs)}` : null,
  ].filter(Boolean);

  if (parts.length === 0) return null;
  return <div className="ningyu-trace-line">{parts.join(" · ")}</div>;
}
```

Render inside assistant message bubble after body:

```tsx
{message.trace ? <TraceLine trace={message.trace} /> : null}
```

- [ ] **Step 3: Replace feedback controls**

Only render if assistant message is complete and has `turnId`:

```tsx
{isAssistant && !message.isStreaming && message.turnId ? (
  <div className={`ningyu-message-feedback ${message.feedbackState?.status ? `is-${message.feedbackState.status}` : ""}`} aria-label="回复反馈">
    {conversationFeedbackOptions.map((option) => {
      const selected = message.feedbackState?.value === option.value;
      const disabled = message.feedbackState?.status === "submitting" || message.feedbackState?.status === "submitted";
      return (
        <button
          key={option.value}
          className={selected ? "is-selected" : ""}
          type="button"
          onClick={() => onFeedback(message, option.value)}
          disabled={disabled}
          aria-pressed={selected}
        >
          {option.label}
        </button>
      );
    })}
    {message.feedbackState?.status ? (
      <span aria-live="polite">
        {message.feedbackState.status === "submitting"
          ? "记录中"
          : message.feedbackState.status === "submitted"
            ? "已记录"
            : "未记录"}
      </span>
    ) : null}
  </div>
) : null}
```

- [ ] **Step 4: Style trace and feedback controls**

Add to `NingyuAppShell.css` near existing message feedback styles:

```css
.ningyu-trace-line {
  margin-top: 10px;
  color: rgba(15, 118, 110, 0.48);
  font-size: 11px;
  line-height: 1.45;
}

.ningyu-shell.is-night .ningyu-trace-line {
  color: #64748b;
}

.ningyu-message-feedback button:disabled {
  cursor: default;
  opacity: 0.72;
}

.ningyu-message-feedback.is-failed span {
  color: #b91c1c;
}

.ningyu-shell.is-night .ningyu-message-feedback.is-failed span {
  color: #fca5a5;
}
```

- [ ] **Step 5: Run typecheck and build**

Run:

```powershell
cd frontend
npm run check
npm run build
```

Expected: both PASS.

---

### Task 4: Browser Smoke And Final Review

**Files:**
- No code files unless verification reveals a defect.

- [ ] **Step 1: Start or reuse local services**

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5175
```

- [ ] **Step 2: Browser smoke**

Open `http://127.0.0.1:5175/`.

Verify:

- Login or existing session loads.
- Open or create a conversation.
- Send a normal message.
- Assistant reply streams.
- Completed assistant message shows five feedback choices.
- Trace line appears when backend provides `trace_summary`.
- Clicking a feedback choice calls `/api/v1/feedback` with `thread_id`, `turn_id`, and `feedback`.

- [ ] **Step 3: Final verification commands**

Run:

```powershell
cd frontend
npm run check
npm run build
```

Expected: both PASS.

- [ ] **Step 4: Review changed files**

Run:

```powershell
git diff -- frontend/src/types/api.ts frontend/src/api/endpoints.ts frontend/src/app/ningyu/NingyuAppShell.tsx frontend/src/app/ningyu/NingyuAppShell.css frontend/src/app/ningyu/conversationQuality.ts frontend/src/app/ningyu/conversationQuality.contract.ts
```

Expected:

- No backend or database changes.
- No desktop project changes.
- No generated files.
- Spec requirements covered.
