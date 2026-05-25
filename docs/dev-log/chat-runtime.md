# 聊天运行时迭代日志

## 2026-05-13 桌面前端对话验证问题

### 背景

为验证真实对话模块，临时在桌面创建了轻量前端：

- 桌面前端：`C:\Users\24313\Desktop\ningyu-chat-lab`
- 后端地址：`http://localhost:8000`
- 数据库：本地 PostgreSQL，`postgresql+psycopg://postgres:123456@127.0.0.1:5432/psychology_agent`
- 向量检索：本地 Milvus + local embedding

### 现象

- 登录页偶发显示“无法连接后端，请确认服务已在对应地址启动。”
- 对话页可以发出用户消息，但助手卡在“正在生成回复...”。
- 历史 turn 中多次出现 `graph_timeout_fallback`。
- 前端 trace 可见类似：
  - `端到端 54s · 图 0ms · intent_classifier 0ms · 1 节点`
  - 或发送后长期停留在 `准备发送` / `服务端处理中` / `正在生成回复...`

### 已确认事实

- 后端进程曾多次不再监听 `127.0.0.1:8000`，此时健康检查返回无法连接。
- 后端重新启动后，`GET /health` 可以返回 `{"status":"ok"}`。
- 最近失败 turn 在 PostgreSQL 中记录为：
  - `turn_status = completed`
  - `delivery_status = failed_no_reply`
  - `failure_reason = graph_timeout_fallback`
  - trace 只落了 `delivery_result`，没有完整图节点 trace。
- 运行时配置中 RAG 是开启的：
  - `milvus_enabled=True`
  - `counseling_rag_enabled=True`
  - `embedding_provider=local`
  - `local_embedding_device=cuda`
- Milvus 可达，RAG 能真实检索到结果；一次手动检索耗时约 `16.2s`，返回 3 条 `smilechat` 命中。

### 当前判断

问题不是桌面前端单点渲染错误。主要风险在后端聊天运行时：

- 后端进程常驻不稳定，会导致前端显示无法连接。
- RAG / local embedding 首次或慢路径耗时过高，容易吃掉单轮 `CHAT_TURN_TIMEOUT_SECONDS=25` 的预算。
- 可选检索层不应阻塞主对话回复；检索慢时应降级为无 RAG 继续生成。
- 失败 fallback 的 trace 太少，无法直接展示卡在哪个图节点，后续需要补更细的诊断记录。

### 后续修复项

1. 给 `example_retriever` 或 `retrieve_counseling_examples` 增加短超时和安全降级：超时后返回空示例，`rag_skipped_reason=rag_timeout`，继续生成回复。
2. 将 RAG/embedding 耗时纳入 trace，确保前端能看到慢在检索、模型还是保存阶段。
3. 增加后端启动/守护方式，避免临时 `uvicorn` 进程退出后桌面前端失联。
4. 桌面前端在 stream 中断、后端断连、fallback 时展示明确错误态和重试入口。
5. 可选：启动时预热本地 embedding，或给首轮检索使用更长但独立的冷启动预算。

### 2026-05-13 本轮迭代记录

- 已把桌面前端接入真实 `streamMessage` 的 RAG trace 展示：可显示 `RAG 命中/超时/跳过`、命中条数、RAG 总耗时、embedding 耗时、Milvus 耗时和跳过原因。
- 已在后端把 `rag_trace_summary` 纳入 LangGraph `AgentState`、流式 `graph_update` 和最终 `trace_summary`，避免历史消息只剩 `rag_timeout` 原因、丢失细分耗时。
- 已把 `/chat/threads/{thread_id}/stream` 改回真正 SSE 流式返回，不再等整轮对话跑完后才 replay；这样 RAG 冷启动时前端能先看到 accepted / heartbeat / 节点进度。
- 已确认本地 CPU embedding 冷启动一次约 `40.1s`，Milvus 搜索约 `4.5s`，总检索约 `44.7s`；因此默认 `RAG_RETRIEVAL_TIMEOUT_SECONDS` 提到 `60`，默认 `CHAT_TURN_TIMEOUT_SECONDS` 提到 `120`。
- Milvus 当前在线：`psych-agent-milvus-standalone` healthy，端口 `19530` 可用。
### 2026-05-14 RAG 性能与稳定性修复

- 定位到 RAG 慢的主要原因不是前端：本地 BGE-M3 embedding 冷启动会占 20s+，但模型热起来后不同中文 query 可降到约 `0.3s-0.5s`。
- `EmbeddingClient` 增加 query LRU 缓存，重复 query 直接复用向量；当前默认 `EMBEDDING_QUERY_CACHE_SIZE=128`。
- Windows + Python 3.13 下本地 embedding 不再默认塞进 API 进程；新增 `local_embedding_worker` 子进程隔离，避免 FlagEmbedding/CUDA/torch 异常把 uvicorn 一起带崩。
- 修复 worker 管道中文输入：父进程用 ASCII escaped JSON 发送文本，避免隐藏子进程 stdin 编码导致中文 query 在 tokenizer 里报 `TextEncodeInput`。
- 单条运行时 query 改走 BGE-M3 `encode_queries()`；批量语料索引仍走 `encode()`。
- `companion` RAG 的 Milvus 检索顺序改为先 `any`，命中足够时不再连续查 `vent/soothe/counseling` 三个窄 mode。
- Python 3.13 + Windows 启动时禁用 `platform._wmi`，避免 SQLAlchemy import 期间卡在 WMI 查询。
- 已重新拉起 Docker Desktop 和 Milvus 三件套：`psych-agent-milvus-etcd`、`psych-agent-milvus-minio`、`psych-agent-milvus-standalone`，Milvus 19530 可用。
- 实测桌面前端真实 SSE 链路：
  - 冷 worker 首轮中文 RAG：`embedding 22.1s`、`Milvus 1.1s`、`RAG 总 23.2s`，命中 3 条 `smilechat`。
  - 热 worker 中文 RAG：`embedding 512ms`、`Milvus 1.66s`、`RAG 总 2.18s`，命中 3 条。
  - 开启后台预热后首轮中文 RAG：`embedding 426ms`、`Milvus 1.05s`、`RAG 总 1.50s`，命中 3 条。
- 当前桌面验证后端以 `LOCAL_EMBEDDING_USE_WORKER=1`、`LOCAL_EMBEDDING_WARM_ON_STARTUP=1` 启动；`.env.local` 未直接改动。
