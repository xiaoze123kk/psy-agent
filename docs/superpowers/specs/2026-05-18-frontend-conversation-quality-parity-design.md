# Main 前端对话质量闭环对齐设计

## 背景

当前 `main` 分支后端已经具备对话自然度治理的核心能力：流式回复会产出 `trace_summary`、`conversation_quality_trace`、RAG trace、validator 信息，后端 `/api/v1/feedback` 也支持 `thread_id + turn_id + feedback` 形式的轻反馈。桌面项目 `C:/Users/24313/Desktop/ningyu-chat-lab` 把这些能力做成了一个较轻的对话调试台，因此在调自然度时更直接、更顺手。

`main` 分支前端的优势是产品壳更完整，有首页、线程列表、安全入口、心情 check-in、周总结等正式体验。但它没有完整接入桌面版的对话质量反馈和 trace 展示。结果是：同样接后端时，main 前端未必真的生成更差的回复，但用户更难发现、标记、校正“没接住 / 太分析 / 太泛 / 问太多”这些自然度问题，长期闭环也更弱。

## 现状证据

### 桌面版已有能力

- `C:/Users/24313/Desktop/ningyu-chat-lab/src/types.ts`
  - 定义 `ConversationFeedbackValue = "missed" | "too_analytic" | "too_generic" | "too_many_questions" | "good"`。
  - `ChatStreamGraphUpdateEvent` 包含 `duration_ms`、`rag_trace_summary`。
  - `ChatStreamFinalEvent` 包含 `trace_summary`。
- `C:/Users/24313/Desktop/ningyu-chat-lab/src/api.ts`
  - `submitConversationQualityFeedback()` 调用 `/api/v1/feedback`。
  - `getConversationQualitySummary()` 调用 `/api/v1/feedback/conversation-quality/summary`。
- `C:/Users/24313/Desktop/ningyu-chat-lab/src/App.tsx`
  - 在流式 `graph_update` 中累计节点耗时、RAG 命中和慢节点。
  - 在 `final` 中读取 `trace_summary`。
  - 在 assistant 消息旁提供自然度反馈按钮，并把反馈提交给后端。

### main 前端缺口

- `frontend/src/types/api.ts`
  - `ChatStreamGraphUpdateEvent` 缺少 `duration_ms`、`rag_trace_summary`、`retrieved_example_count`。
  - `ChatStreamFinalEvent` 缺少 `trace_summary`。
  - `FeedbackCreateRequest` 只描述旧式 `target_type + rating`，没有轻反馈字段 `thread_id`、`turn_id`、`feedback`、`optional_note`。
- `frontend/src/app/ningyu/NingyuAppShell.tsx`
  - `MessageFeedback = "helpful" | "not_helpful"` 只存在前端本地 state。
  - `handleMessageFeedback()` 只更新本地 `messageFeedback`，没有调用 `api.submitFeedback()`。
  - `handleSend()` 收到了 `accepted.turn_id` 和 `final`，但没有把 turn id、trace、RAG 诊断整理成可复用 UI 状态。
- `frontend/src/api/tokenStore.ts` 和桌面版 token key 不一致：
  - main 使用 `warp_te.access_token` / `warp_te.refresh_token`。
  - 桌面版使用 `ningyu_chat_lab_access_token` / `ningyu_chat_lab_refresh_token`。
  - 这会导致两边可能使用不同账号、不同线程、不同记忆上下文，从而放大“体感差异”。

## 目标

1. 让 `main` 前端接入桌面版已经验证过的对话质量轻反馈，不再只做本地“有帮助 / 不适合”状态。
2. 让 `main` 前端能读取并展示关键 trace：端到端耗时、图节点耗时、慢节点、RAG 命中、RAG 跳过原因。
3. 保留 `main` 的正式产品体验，不把桌面调试台整页搬进去。
4. 让反馈能回流到后端 `conversation_quality_trace`，从而继续影响后续 compact context 和自然度治理。
5. 明确 token / 登录态差异，避免误把不同账号上下文造成的差异理解为“前端自然度差”。

## 非目标

- 不改后端 prompt、LangGraph 节点或自然度策略。
- 不重做 main 前端整体 UI。
- 不迁移桌面版项目到仓库内。
- 不编辑 `frontend/dist/`、`node_modules/` 或桌面项目生成文件。
- 不默认把 trace 暴露成面向普通用户的复杂调试面板；正式体验中应保持轻量、可折叠、低打扰。

## 设计原则

### 1. 反馈是产品能力，不是临时调试按钮

main 前端的 assistant 消息旁应提供对自然度有诊断价值的反馈项：

- `没接住` -> `missed`
- `太分析了` -> `too_analytic`
- `太泛了` -> `too_generic`
- `问太多` -> `too_many_questions`
- `刚刚好` -> `good`

这些反馈必须提交到 `/api/v1/feedback`，并携带当前 `thread_id` 和该轮 `turn_id`。提交状态需要有三种 UI 状态：提交中、已记录、记录失败。

### 2. trace 只展示对判断自然度有帮助的摘要

主消息气泡不应塞满内部字段。建议在 assistant 消息底部展示一行短 trace，例如：

```text
端到端 2.1s · 图 1.6s · RAG 命中 3条 · 最慢 dialogue_generation 1.2s
```

如果 trace 不存在，不显示该行。RAG 被跳过时显示短原因，例如：

```text
RAG 跳过：disabled
```

### 3. GraphUpdateTrail 保持“轻处理线索”，不要变成后端日志墙

main 现有 `GraphUpdateTrail` 可以继续保留，但应增加对以下字段的理解：

- `duration_ms`
- `rag_trace_summary.status`
- `rag_trace_summary.hit_count`
- `rag_trace_summary.total_duration_ms`
- `rag_skipped_reason`
- `retrieved_example_count`

显示内容应是用户可读的状态摘要，而不是原始 JSON。

### 4. turn id 是反馈闭环的关键字段

流式 `accepted` 和 `final` 都可能携带 `turn_id`。前端需要把它保存到 assistant 消息对象上：

- `accepted.turn_id` 先写入临时 assistant 消息。
- `final.turn_id` 覆盖或补齐。
- 历史消息加载时从 `message.metadata.turn_id` 读取。
- 若没有 `turn_id`，反馈按钮不显示或禁用。

### 5. token key 差异先标明，不做静默迁移

token key 关系到登录态、安全边界和用户数据归属。本期只在 spec 中明确差异，实施时可选择：

- 保持 main 独立 token key，只在调试说明里提示两边可能不是同一个账号。
- 增加一次性兼容读取：main 没有 token 时可读取桌面版 token key。

推荐第一阶段不做自动迁移，避免把桌面 lab 登录态静默带入正式前端。

## 数据契约

### 前端新增类型

`frontend/src/types/api.ts` 应补齐轻反馈和 trace 字段。

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

`FeedbackCreateRequest` 应扩展为同时支持旧反馈和轻反馈：

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

流式事件补齐：

```ts
export interface ChatStreamGraphUpdateEvent {
  node: string;
  status?: string;
  risk_level?: RiskLevel;
  intent?: string;
  route_priority?: string;
  control_category?: string;
  retrieved_memory_count?: number;
  retrieved_example_count?: number;
  rag_used?: boolean;
  rag_skipped_reason?: string;
  rag_trace_summary?: Record<string, unknown>;
  validator_blocked?: boolean;
  delivery_status?: DeliveryStatus;
  duration_ms?: number;
}

export interface ChatStreamFinalEvent {
  thread_id: string;
  message_id: string;
  assistant_message_id: string | null;
  client_message_id?: string | null;
  turn_id?: string | null;
  turn_status: TurnStatus;
  assistant_text: string;
  risk_level: RiskLevel;
  intent: string;
  suggested_actions: string[];
  session_summary: string;
  should_write_memory: boolean;
  referenced_memories: MemoryReference[];
  delivery_status: DeliveryStatus;
  failure_reason?: string | null;
  retryable: boolean;
  memory_job_id?: string | null;
  memory_job_status?: MemoryJobStatus;
  risk_reasons?: string[];
  memory_candidates?: unknown[];
  trace_summary?: Record<string, unknown>;
}
```

### 前端消息模型

`NingyuAppShell.tsx` 内部 `Message` 需要增加：

```ts
type ConversationFeedbackSubmitStatus = "idle" | "submitting" | "submitted" | "failed";

interface TraceTiming {
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

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  riskLevel?: string | null;
  suggestedActions?: string[];
  metadata?: Record<string, unknown>;
  isStreaming?: boolean;
  deliveryStatus?: string;
  intent?: string;
  sessionSummary?: string;
  turnStatus?: string;
  failureReason?: string | null;
  turnId?: string | null;
  assistantMessageId?: string | null;
  trace?: TraceTiming | null;
  feedbackState?: {
    value: ConversationFeedbackValue;
    status: ConversationFeedbackSubmitStatus;
  };
}
```

## API 设计

### 复用现有 `submitFeedback`

`frontend/src/api/endpoints.ts` 已有：

```ts
submitFeedback(payload: FeedbackCreateRequest): Promise<FeedbackResponse>
```

实施时不需要新增 API 方法，也可以为了语义清晰增加一个轻包装：

```ts
submitConversationQualityFeedback(payload: ConversationFeedbackRequest): Promise<FeedbackResponse> {
  return this.submitFeedback(payload);
}
```

如果新增包装，桌面版迁移过来的调用点更清楚；如果不新增，直接调用 `api.submitFeedback({ thread_id, turn_id, feedback })` 也符合后端契约。

### 可选摘要接口

后端已有：

```text
GET /api/v1/feedback/conversation-quality/summary?thread_id=<thread_id>
```

第一阶段不一定要做 UI。建议先只补类型和 API 方法，后续再做调试抽屉或质量摘要面板。

## UI 设计

### Assistant 消息反馈区

替换当前 `有帮助 / 不适合`：

```text
没接住  太分析了  太泛了  问太多  刚刚好   记录中/已记录/未记录
```

规则：

- 只在 assistant 消息完成后显示。
- 消息没有 `turnId` 时不显示反馈按钮。
- 提交中禁用按钮。
- 已提交后禁用按钮，避免重复写入。
- 提交失败时保留已选项并显示 `未记录`，允许用户再次点击。

### TraceLine

放在 assistant 消息底部、建议动作上方或下方均可，但视觉权重应低于正文。

显示规则：

- `trace` 为空：不渲染。
- `endToEndMs` 存在：显示 `端到端 <duration>`。
- `totalGraphMs` 存在：显示 `图 <duration>`。
- `ragStatus` 存在：显示 `RAG 命中/无命中/跳过/超时/错误`。
- `ragHitCount` 存在：追加 `<n>条`。
- `slowestNode + slowestNodeMs` 存在：显示 `最慢 <node> <duration>`。

### GraphUpdateTrail

当前 main 已有 GraphUpdateTrail。增强规则：

- `graph_update.duration_ms` 存在时，节点行追加耗时。
- `example_retriever` 或带 `rag_trace_summary` 的节点显示 RAG 状态。
- 保持最多最近 5 条，不无限增长。

## 实施边界

### 需要修改的 main 文件

- `frontend/src/types/api.ts`
  - 增加 conversation quality feedback 类型。
  - 扩展 `FeedbackCreateRequest`。
  - 补齐 stream graph/final trace 字段。
- `frontend/src/api/endpoints.ts`
  - 可选新增 `submitConversationQualityFeedback()`。
  - 可选新增 `getConversationQualitySummary()`。
- `frontend/src/app/ningyu/NingyuAppShell.tsx`
  - 扩展 `Message` 状态。
  - 在 stream accepted/final/history load 中保存 `turnId`、`assistantMessageId`、`trace`。
  - 替换反馈按钮并提交后端。
  - 增加 `TraceLine` 和 trace parsing helpers。
  - 增强 `GraphUpdateTrail` 的 RAG/耗时摘要。
- `frontend/src/app/ningyu/NingyuAppShell.css`
  - 调整反馈按钮和 trace line 的低权重样式。
- 可选新增 `frontend/src/app/ningyu/conversationQuality.ts`
  - 如果 `NingyuAppShell.tsx` 继续膨胀，把 trace parsing、feedback labels、formatDuration 抽出去。
- 可选新增 `frontend/src/app/ningyu/conversationQuality.test.ts`
  - 如果前端测试环境可用，测试 trace parsing 和 feedback payload。

### 不应修改

- 不修改 `backend/` 的对话生成逻辑。
- 不修改 `database/`。
- 不修改桌面项目文件。
- 不修改构建产物或缓存目录。

## 验收标准

1. 在 main 前端发送一条消息后，assistant 回复完成时可以看到自然度反馈按钮。
2. 点击 `太分析了` 会向 `/api/v1/feedback` 发送：

```json
{
  "thread_id": "<active-thread-id>",
  "turn_id": "<turn-id>",
  "feedback": "too_analytic"
}
```

3. 提交成功后 UI 显示 `已记录`，刷新历史消息后该轮 trace 中的显式反馈可由后端摘要接口统计到。
4. 如果流式 final 带 `trace_summary`，assistant 消息显示简短 trace line。
5. 如果 graph update 带 `duration_ms` 或 `rag_trace_summary`，GraphUpdateTrail 能展示耗时或 RAG 状态。
6. 没有 `turn_id` 的历史 assistant 消息不显示反馈按钮，避免提交无效反馈。
7. `npm run check` 通过。
8. 本地浏览器 smoke：
   - 登录 main 前端。
   - 新建或打开线程。
   - 发送一条普通对话。
   - 观察流式回复、trace line、反馈按钮。
   - 点击一个反馈项，确认 Network 中 `/api/v1/feedback` 返回 200。

## 风险与缓解

### 风险：正式界面被调试信息压重

缓解：trace line 只显示一行摘要，样式低权重；未来可加“开发模式”开关。

### 风险：重复提交反馈

缓解：前端提交成功后禁用按钮；后端目前允许多条 feedback，前端先避免误点重复写入。

### 风险：历史消息缺少 turn_id

缓解：无 turn id 不显示反馈按钮；后续如有必要再做后端历史 metadata 补齐。

### 风险：main 与桌面版账号上下文不同导致误判

缓解：本期不做 token 自动迁移；测试时明确使用同一个账号登录两边，并使用同一后端地址。

### 风险：`NingyuAppShell.tsx` 继续变大

缓解：如果实现时新增逻辑超过约 120 行，优先抽到 `conversationQuality.ts`。

## 推荐实施顺序

1. 先补 `frontend/src/types/api.ts` 的数据契约。
2. 再补 API 轻包装。
3. 抽出 trace parsing helpers，并用桌面版逻辑作为参考。
4. 改 `handleSend()` 和 `mapMessageItem()`，保证 turn id 与 trace 能进入消息模型。
5. 替换反馈 UI，并打通 `api.submitFeedback()`。
6. 增强 GraphUpdateTrail。
7. 跑 `npm run check`。
8. 用浏览器和 Network 面板 smoke 一轮真实反馈提交。

## 后续可选增强

- 在右侧状态区增加“本线程对话质量摘要”，读取 `/api/v1/feedback/conversation-quality/summary`。
- 增加开发模式开关，只在开发模式显示慢节点、RAG 细节。
- 为 feedback 增加 optional note，但默认不要求用户输入，避免打断聊天。
- 做一次同账号同线程对照测试，比较 main 前端和桌面版在同一后端下的体感差异。
