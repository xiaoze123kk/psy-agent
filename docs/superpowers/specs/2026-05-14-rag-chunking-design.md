# RAG Chunking 优化设计

## 目标

把心理咨询 RAG 语料从单纯的“单轮问答示例库”升级为“分层的咨询过程参考库”。新的设计既要保留单轮回复风格的精确匹配能力，也要补上多轮对话中的情绪递进、咨询师介入路径和整段咨询走向。同时，借全量重建索引的机会把现有 BGE-M3 embedding 用法调优，兼顾召回质量、索引吞吐和可恢复性。

## 当前状态

聊天主链路通过 `example_retriever` 从 Milvus 检索 counseling examples。当前导入链路会把每个 user-assistant pair 写成一个 `CounselingExampleChunk`，再对完整 `content` 做 embedding，运行时最多取 3 条安全示例放入 prompt。

这个策略适合局部风格参考，但容易割裂一段咨询对话。单个 pair 往往看不到前面的情绪铺垫、咨询师之前的反映方式，以及后续介入是否让对话发生变化。直接把 chunk 变长也不是好方案，因为会降低检索精度、增加 prompt 负担和复制泄露风险。因此优化方向应该是“分层”，而不是简单地做更大的 chunk。

当前 embedding provider 是本地 `BAAI/bge-m3`，维度为 1024。这个模型适合中文和多语义检索，第一版不换模型；但现在 query/document 编码路径不够显式，document max length 偏保守，`.env.local` 还会把设备覆盖到 CPU。既然新 chunk 会触发全量 re-embedding，需要同时优化 embedding 使用策略。

## 总体设计

新增并保留三类 counseling chunk：

- `turn_pair`：一条用户消息加一条咨询师回复。保留现有的精确回复风格参考能力。
- `process_segment`：语义上相对完整的多轮咨询过程片段，通常包含 3-5 个 user-assistant pair，相邻片段默认重叠 1 个 pair。它负责保留咨询师如何承接、澄清、反映、介入和收束。
- `session_sketch`：整段对话的高度脱敏地图。它不存完整原文，只描述用户核心困扰、情绪线、咨询师引导路径，以及结尾状态或未解决点。

第一版尽量复用现有数据库结构。`chunk_type`、原始会话 ID、pair 范围、阶段、情绪标签和介入标签先写入 `CounselingExampleChunk.metadata`。如果 Milvus 需要按 chunk 类型过滤，可以在重建 `counseling_examples_v1` collection 时增加必要的 scalar fields；否则先通过过采样和 Python 侧过滤降低迁移风险。

## Chunk 构造

### 单轮问答：`turn_pair`

`turn_pair` 基本沿用当前行为：

```text
片段类型：单轮问答
用户：...
咨询回应：...
```

建议 metadata：

```json
{
  "chunk_type": "turn_pair",
  "original_external_id": "case-123",
  "pair_start": 2,
  "pair_end": 2,
  "pair_count": 1,
  "overlap_pairs": 0,
  "parser": "messages"
}
```

### 咨询过程片段：`process_segment`

`process_segment` 使用 pair 级别切分，不使用字符 overlap。默认窗口为 3 个 pair，最大 5 个 pair，默认 overlap 为 1 个 pair。pair 级 overlap 能保留“用户表达 - 咨询回应”的完整角色边界，避免把咨询师回应从它所回应的用户消息中切开。

如果能识别语义边界，应优先按语义边界切分，而不是机械滑窗。边界包括主题变化、情绪强度变化、从探索进入介入、从介入进入总结或收束等。如果识别不到明显边界，再退回固定 pair window。

内容格式：

```text
片段类型：咨询过程片段
阶段：exploration
用户情绪线索：焦虑, 委屈
咨询师动作线索：共情反映 -> 澄清问题 -> 轻量建议
对话片段：
用户：...
咨询回应：...
用户：...
咨询回应：...
```

建议 metadata：

```json
{
  "chunk_type": "process_segment",
  "original_external_id": "case-123",
  "segment_index": 1,
  "pair_start": 2,
  "pair_end": 4,
  "pair_count": 3,
  "overlap_pairs": 1,
  "phase": "exploration",
  "emotion_tags": ["anxiety", "hurt"],
  "intervention_tags": ["reflection", "clarifying_question", "grounding"],
  "parser": "messages"
}
```

### 整段咨询地图：`session_sketch`

`session_sketch` 是整段咨询的地图。第一版应该用规则生成，不依赖 LLM。这样索引重建可重复、成本低，也避免 LLM 在导入阶段生成不稳定或带幻觉的总结。

内容格式：

```text
片段类型：整段咨询地图
主要困扰：工作压力和睡眠受影响
情绪起点：焦虑, 疲惫
情绪变化：从混乱倾诉转向能说出一个具体压力源
咨询师引导路径：共情承接 -> 澄清压力源 -> 稳定化建议
结尾状态：仍未解决, 但用户愿意继续描述
```

`session_sketch` 应尽量避免保留原始隐私细节。它的用途是帮助检索理解整段咨询方向，而不是给模型复制原文。

## 检索文本与展示文本分离

需要区分两种文本：

- `retrieval_text`：用于 embedding。它可以包含 chunk 类型、阶段、主题、情绪标签、介入标签、简短摘要和必要对话文本。
- `display_text`：用于 prompt 展示。它必须短、结构化、少细节。`process_segment` 只展示理解流程所需的代表性行，`session_sketch` 只展示摘要字段。

第一版可以把 `retrieval_text` 写入 `content` 用于向量化，把 `display_text` 写入 metadata。运行时格式化 RAG references 时优先使用 metadata 里的 `display_text`，避免把过长的检索文本直接塞进 prompt。

## Embedding 使用策略

第一版继续使用 `BAAI/bge-m3`，不更换 embedding 模型。BGE-M3 对中文、多语言和较长文本检索都比较稳，且本地部署更适合心理咨询语料的隐私要求。优化重点是把现有模型用好，而不是引入模型迁移风险。

### Query 和 Document 显式分离

运行时用户输入应走 query embedding，索引时的 `retrieval_text` 应走 document embedding。代码层面需要避免通过“单条文本还是批量文本”隐式判断编码路径，建议新增或明确：

- `embed_query(text)`：用于用户 query，内部走 BGE-M3 query 编码路径。
- `embed_documents(texts)`：用于索引 chunk/retrieval_text，内部走 document 编码路径。

这样可以让 query 和 document 的 max length、日志、批量策略独立演进。

### Max Length 分层

当前 `LOCAL_EMBEDDING_MAX_LENGTH=1024` 对单轮 chunk 足够，但对 `process_segment` 和 `session_sketch` 可能偏短。建议拆成两个配置：

```text
LOCAL_EMBEDDING_QUERY_MAX_LENGTH=512
LOCAL_EMBEDDING_DOCUMENT_MAX_LENGTH=2048
```

第一版 document max length 先用 2048，不直接拉到 4096，以控制 CPU/GPU 压力。后续如果 process chunk 截断仍明显，再结合评测上调。

### 设备和吞吐

重建索引建议优先使用 `LOCAL_EMBEDDING_DEVICE=auto` 或 `cuda`。如果没有 CUDA，CPU 仍可用，但需要降低 batch size。建议规则：

- CUDA：`LOCAL_EMBEDDING_BATCH_SIZE=32` 起步，失败时降级。
- CPU：`LOCAL_EMBEDDING_BATCH_SIZE=4-8` 起步。
- API 实时检索继续支持 worker 模式，避免模型加载或推理阻塞主进程。

索引脚本应在日志中输出 provider、model、device、batch size、query/document max length、embedding index version、indexed/skipped 计数，方便判断慢在模型、Milvus 还是数据清洗。

### Embedding Key 版本化

当前 `embedding_key` 只包含 provider、model 和 dim。chunking、`retrieval_text` 结构、query/document 策略和 max length 改变后，新旧向量语义并不等价，不能混在同一批索引里。

新增配置：

```text
EMBEDDING_INDEX_VERSION=rag-layered-v1
```

新的 key 应类似：

```text
local:BAAI/bge-m3:1024:rag-layered-v1
```

如果配置为空，可回退到旧 key，保证兼容；但分层 RAG 重建时应设置版本，避免旧单轮 chunk 向量和新分层 chunk 向量混用。

### 暂不引入 Reranker / Sparse / ColBERT

BGE-M3 支持 sparse 和 multi-vector 能力，也可以接 reranker，但第一版不纳入实现范围。先完成 dense embedding + 分层 chunk + 配额重排 + index version。等有质量评测结果后，再决定是否追加 rerank 或 hybrid retrieval。

## 运行时检索策略

运行时不要盲目取 top-k，而是按 chunk 类型配额重排。

默认支持类对话：

```text
1 条 process_segment
2 条 turn_pair
```

复杂咨询或延续前文场景，例如用户说“继续”“还是”“刚才”“前面那个”等：

```text
1 条 session_sketch
1 条 process_segment
1 条 turn_pair
```

短安抚场景：

```text
0-1 条 process_segment
2-3 条 turn_pair
```

如果 Milvus 暂时不能按 `chunk_type` 过滤，就先检索过采样结果，再在 Python 侧根据 metadata 或内容标记做配额选择。重排还需要做多样性控制：

- 同一个 `original_external_id` 默认最多保留 1-2 条。
- 按当前场景保留不同 chunk 类型的组合。
- 在最终选择前剔除不安全、未授权、低质量 chunk。

## 邻居扩展

不要为了避免上下文断裂而把所有 chunk 都做长。如果命中了一个高度相关的 `turn_pair`，retriever 可以根据 metadata 找到它所属的 `process_segment`，或者找同一 `original_external_id` 的相邻 pair 作为补充上下文。这样 embedding 仍然精准，生成时也能恢复局部上下文。

第一版可以只在 Milvus 返回结果中做这种归并。后续如果需要更完整，可以从 PostgreSQL 按 `original_external_id` 和 pair 范围补查邻居。

## 质量与安全

现有 PII 清洗和高风险过滤必须保留。新增过程类质量信号：

- `quality_score`：一般示例质量。
- `safety_score`：安全适配度。
- `process_quality_score`：片段是否展示了有价值的咨询推进，而不是模板化建议、诊断、过度保证或边界风险。

第一版可以使用规则评分：

- 惩罚：直接诊断、药物剂量、绝对保证、依赖性表达、建议密度过高。
- 奖励：共情反映、情绪确认、温和澄清、稳定化、征求同意、强调用户自主性。

低质量 chunk 应该不进入默认召回，或者只以 draft/review 状态保留。

## Prompt 使用方式

RAG references 在 prompt 中应按用途分区：

```text
--- Session map reference ---
...

--- Process reference ---
...

--- Turn style reference ---
...
```

提示词中应明确：

- `session_sketch` 和 `process_segment` 只用于学习结构和引导方式。
- `turn_pair` 可以参考语气、节奏和回复方式。
- RAG 内容不是当前用户事实依据。
- 不要复制任何 RAG 原文、细节或私密内容。
- control-plane 的安全策略优先级高于 RAG。

现有 copy-leak validator 必须继续保留。由于 process references 可能更长，应重点检查长片段复制泄露。

## 数据流

1. 将源语料解析为标准 user-assistant pairs。
2. 在创建任何 chunk 前进行 PII 清洗和不安全内容过滤。
3. 创建 `turn_pair` chunks。
4. 用确定性规则识别语义边界。
5. 创建带 pair-level overlap 的 `process_segment` chunks。
6. 对至少包含两个安全 pair 的对话创建一个脱敏 `session_sketch`。
7. 将 chunk 和 metadata 写入 PostgreSQL。
8. 使用 document embedding 对 `retrieval_text` 做向量化，并用带版本的 `embedding_key` 写入 Milvus。
9. 运行时使用 query embedding 检索过采样池，做安全过滤、chunk 类型配额、多样性重排，再用 `display_text` 格式化 prompt references。

## 错误处理与回滚

- 如果某段对话的过程切分失败，保留 `turn_pair`，跳过该对话的 `process_segment` 和 `session_sketch`。
- 如果 `session_sketch` 为空或不安全，跳过它。
- 如果 Milvus 缺少必要 scalar field，检索退回到过采样加 Python 过滤。
- 如果 GPU 不可用，embedding 自动回退到 CPU，但索引日志必须暴露实际 device 和 batch size。
- 如果 embedding index version 未配置，继续使用旧 key 格式；分层 RAG 正式重建时应显式配置版本。
- 现有 `turn_pair` 行为仍由同一个 RAG feature flag 控制，不能被新策略破坏。
- PostgreSQL 仍是内容真源，Milvus 只是可重建索引；回滚或重建应通过重新生成 counseling collection 完成。

## 测试策略

实现前先补测试：

- 解析测试：一个 5-pair 对话会生成 5 个 `turn_pair`、至少 2 个有 overlap 的 `process_segment`、1 个 `session_sketch`。
- overlap 测试：相邻 `process_segment` 共享配置指定的 pair-level overlap，且不会切断 user-assistant pair。
- 安全测试：高风险或不安全内容不仅阻止单轮 chunk，也阻止 process/session chunk。
- 检索配额测试：默认检索返回 process 和 turn 的混合结果，而不是 3 条同类型 chunk。
- 延续场景测试：用户输入包含延续信号时允许召回 1 条 `session_sketch`。
- Prompt 格式测试：process/session references 分区展示，并使用 `display_text`，不是完整 `retrieval_text`。
- Embedding key 测试：设置 `EMBEDDING_INDEX_VERSION` 后 key 包含版本，未设置时保持兼容。
- Query/document 测试：query embedding 和 document embedding 使用各自 max length 与编码路径。
- 索引 smoke 测试：输出 provider、model、device、batch size、document max length 和 indexed/skipped。
- 回归测试：当索引里只有 `turn_pair` 时，运行时仍能按旧行为返回安全示例。

## 非目标

- 本轮不修改 memory retrieval 系统。
- 本轮不重设计 knowledge article chunking。
- 本轮不更换 `BAAI/bge-m3` embedding 模型。
- 第一版不引入 reranker、sparse retrieval 或 ColBERT multi-vector retrieval。
- 第一版不在导入阶段加入 LLM 生成式 enrichment。
- 不把完整原始咨询 transcript 放入 prompt-facing 的 `session_sketch`。
- 不移除现有 RAG 安全门控和 copy-leak 校验。

## 实现决定

第一版直接给 Milvus counseling collection 增加 `chunk_type`、`original_external_id`、`phase`、`display_text`、`process_quality_score` 等 scalar fields。旧 collection 通过重建索引处理；运行时仍保留字段缺失时的 Python 侧回退。

第一版不换 embedding 模型，继续使用 `BAAI/bge-m3`。实现计划需要补充 embedding 子任务：显式 query/document embedding、query/document max length 配置、`EMBEDDING_INDEX_VERSION`、索引日志和重建 smoke check。
