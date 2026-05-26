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

## 2026-05-26 聊天流 stream_failed 修复

### 背景/问题

- 主界面发送消息后助手消息显示 `stream_failed`，前端处理卡片显示“处理遇到问题”。
- 后端日志显示 `process_message_turn_stream` 在 `_prepare_turn_context()` 构建记忆索引时异常退出。
- 根因是 PostgreSQL `TIMESTAMPTZ` 返回的 `UserMemory.updated_at` 可能是 timezone-aware datetime，而项目当前 `utcnow()` 返回 timezone-naive datetime；`memory_service` 中做时间差计算时触发 `TypeError: can't subtract offset-naive and offset-aware datetimes`。

### 关键改动

- 在 `backend/app/services/memory_service.py` 中新增记忆服务局部的 UTC aware 时间差 helper。
- `build_memory_index()`、`retrieve_memories_for_turn()` 的记忆新鲜度计算改为统一转 UTC aware 后相减。
- 同步修复自动记忆整合 gate 中 `completed_at` 的同类时间差判断。
- 更新 `backend/tests/test_chat_endpoints.py` 的测试鉴权 helper，按现有 token_version 校验生成 access token。

### 验证结果

- TDD RED：新增 timezone-aware `updated_at` 测试先失败，复现 `can't subtract offset-naive and offset-aware datetimes`。
- 修复后：`backend/.venv/Scripts/python.exe -m pytest tests/test_memory_service.py tests/test_chat_endpoints.py -q` 通过，`30 passed`。
- 本地真实 SSE smoke：临时用户 + timezone-aware 记忆走 `POST /api/v1/chat/threads/{thread_id}/stream` 返回 `event: final`，未出现 `event: error` 或 `stream_failed`；验证后已清理临时用户数据。

### 后续事项

- 后续可统一把 `app.db.models.utcnow()` 迁移为 timezone-aware UTC，并集中评估数据库和测试夹具影响。

### 2026-05-26 发送入口与 RAG 超时预算修复

### 背景/问题

前端登录后在欢迎态输入内容时，输入框可用但发送逻辑要求必须已经选中会话或处于草稿会话，因此空首页态会直接返回 `false`，表现为“无法发送对话”。同时，后端本地启动脚本默认把 `RAG_RETRIEVAL_TIMEOUT_SECONDS` 设为 `120`，而当前 `.env.local` 中 `CHAT_TURN_TIMEOUT_SECONDS` 为 `90`，导致 RAG 还没超时，整轮聊天先触发 `graph_timeout_fallback`。

### 关键改动

- 新增 `frontend/src/app/ningyu/sendFlow.ts`，明确空首页态和草稿态都允许发送时自动创建线程。
- `NingyuAppShell` 的 `ensureThreadForSend()` 复用该规则，空首页态直接发送会先创建新对话再发送消息。
- `rag_nodes.example_retriever()` 新增有效 RAG 超时计算，确保 RAG 检索给主回复保留至少 30 秒预算。
- `scripts/start-backend.ps1` 默认设置 `CHAT_TURN_TIMEOUT_SECONDS=120`、`RAG_RETRIEVAL_TIMEOUT_SECONDS=30`，避免本地 RAG 慢路径拖垮主对话。

### 验证结果

- 新增前端单元测试先失败，确认缺少首页态直接发送规则。
- 新增后端测试先失败，确认 RAG 超时预算未被限制、启动脚本未设置聊天总超时。
- `npm run test:unit`：`3 passed`。
- `npm run check`：通过。
- `pytest tests/test_startup_script.py::test_start_backend_script_uses_uvicorn_on_backend_port tests/test_conversation_control_rag.py::ConversationControlRagTests::test_rag_timeout_keeps_response_budget_before_chat_timeout tests/test_conversation_control_rag.py::ConversationControlRagTests::test_rag_timeout_is_visible_and_does_not_block_generation_path -q`：`3 passed`。
- 重启后端后，前端真实发送“再测一次，应该不用等很久了。”，SSE 返回 `final`，`delivery_status=generated`；RAG 在 30 秒超时后降级，主回复继续生成。

### 后续事项

- 当前 RAG 仍会在本地慢路径触发 30 秒 timeout，后续可单独排查 reranker/embedding worker 为什么没有在热启动后快速返回。

### 2026-05-26 搜索结果外露与受伤陪伴体验修复

### 背景/问题

用户在聊天中说“武汉昨天下暴雨了，骑车摔了一跤，好疼啊”，助手首轮回复直接展示了 `web_search` 检索片段，并且没有接住“暴雨、摔倒、疼痛”的核心体验。排查后确认根因在后端工具层：`昨天` 命中当前事实查询正则后触发 web search 预取，模型无自然语言整理时又使用了检索兜底文案“我查到的搜索结果显示...”，导致搜索摘要进入陪伴对话。

### 关键改动

- 为个人受伤/疼痛/摔倒类支持对话增加搜索抑制规则；没有明确“查一下/是真的吗/新闻/天气预报”等查询意图时，不再预取 `web_search`。
- 在同类当前轮进入模型前移除 `web_search` 工具，避免模型因为“昨天”等时间词再次主动检索。
- 同步清理该类当前轮的工具提示，移除“必须调用 web_search”的矛盾指令。
- 调整事实查询兜底文案，不再使用“我查到的搜索结果显示”这类把检索过程暴露给用户的措辞。
- 新增回归测试覆盖暴雨骑车摔倒场景，要求不调用搜索、不向模型暴露 `web_search`，且回复保留暴雨和疼痛上下文。

### 验证结果

- `backend/.venv/Scripts/python.exe -m pytest tests/test_tooling.py -q`：`56 passed`。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_tooling_integration.py tests/test_chat_endpoints.py -q`：`5 passed, 63 warnings`，warnings 为既有 `datetime.utcnow()` 弃用提示。

### 后续事项

- 后续可以把更多“身体不适/意外受伤/情绪急需承接”的中文表达纳入工具抑制词表，并结合真实对话样本继续校准。

### 2026-05-26 流式草稿外露修复

### 背景/问题

修复搜索兜底后，前端仍会在同一轮回复中短暂显示搜索/草稿内容，然后在 `final` 事件到达后替换为最终的宁语回复。排查发现，后端 `GraphRuntime.stream_turn()` 会透传 LangGraph `custom` 模式里的 `assistant_token`，这些 token 来自回复节点的未校验草稿；后续 `response_validator` 可能再重写答案，导致用户看到“先错后改”的闪烁体验。

### 关键改动

- `GraphRuntime.stream_turn()` 不再向 SSE 客户端透传 `custom` assistant token。
- 未经 `response_validator` 的回复草稿只保留在后端图内部，前端只通过最终 `final` 事件展示持久化后的助手正文。
- 更新流式运行时回归测试，要求 `graph_result` 之前不再出现 `token` 事件。
- 顺手修正 `test_chat_idempotency.py` 的测试 token 构造，补齐 `token_version`，避免当前认证逻辑下测试请求返回 401。

### 验证结果

- `backend/.venv/Scripts/python.exe -m pytest tests/test_graph_runtime_streaming.py tests/test_chat_endpoints.py -q`：`7 passed, 21 warnings`。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_chat_idempotency.py -q`：`15 passed, 241 warnings`。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_response_node_streaming.py -q`：`2 passed`。

### 后续事项

- 若以后要恢复“逐字出现”的体验，需要把可见流式输出放到 `response_validator` 之后，或者设计一个明确的“最终文本流”事件，不能再复用未校验草稿 token。

### 2026-05-26 最新事件搜索触发修复

### 背景/问题

用户询问“华为新半导体定律，你说一下呗”时，宁语未稳定检索到 2026 年 5 月 25 日华为发表“韬（τ）定律”的最新事件；用户随后纠正“涛定律好像，说错了”时，系统又没有把上一轮“华为/半导体”上下文带入检索。根因是当前事实预取只覆盖“新闻/最新/日期/昨天”等显式触发词，未覆盖“发布/发表/定律/半导体/芯片”这类新概念询问；同时短纠错句只用当前文本搜索，丢失上一轮主题。

### 关键改动

- 扩展当前事实预取触发词，覆盖“发布/发表/定律/半导体/芯片”等科技新闻和新概念问法。
- 新增短纠错轮查询构造：当前轮包含“说错了/好像/应该是”等纠错信号时，会合并上一条用户消息作为搜索上下文。
- 将“华为新半导体定律/涛定律/陶定律/韬定律”相关上下文规范成更容易命中的查询 `华为发表韬τ定律`。
- 收窄个人支持场景的搜索抑制规则，避免单独的“我”误伤“我说错了，是涛定律”这类事实纠错句。

### 验证结果

- 新增回归测试先失败，确认原逻辑无法导入查询构造 helper，且缺少华为半导体新定律触发。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_tooling.py -q`：`60 passed`。
- 本地 `search_service.search_web("华为发表韬τ定律")` 可返回澎湃新闻、EET China 等包含“华为正式发表半导体领域新定律/韬（τ）定律”的结果。

### 后续事项

- 后续可抽象更通用的新概念查询改写器，减少对单个热点事件的定制规则。

### 2026-05-26 搜索依据转陪伴式回复修复

### 背景/问题

最新事件搜索已经能命中“华为发表韬（τ）定律”，但当模型回复缺少日期或误判“没找到”时，后端会用 `_fallback_answer_from_prefetched_web()` 覆盖为“公开资料里能核对到...可参考来源...”格式。这仍然把搜索摘要和来源标题直接暴露在宁语气泡里，不符合心理陪伴场景：工具结果应该只作为内部依据，最终回复必须结合上下文重新组织。

### 关键改动

- 将预取搜索兜底从“搜索摘要格式”改为“自然事实整理格式”，不再输出“公开资料里能核对到”“可参考来源”、URL 或来源标题。
- 对“华为韬（τ）定律”场景增加陪伴式整理：先确认用户问的是什么，再用一句话说明关键信息，最后提供可继续拆解的温和方向。
- 新增回归断言，确保华为半导体新定律回复不会包含搜索摘要痕迹、域名或相对时间标签。

### 验证结果

- `backend/.venv/Scripts/python.exe -m pytest tests/test_tooling.py -q`：`60 passed`。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_graph_runtime_streaming.py tests/test_chat_endpoints.py tests/test_chat_idempotency.py tests/test_response_node_streaming.py -q`：`24 passed, 262 warnings`。

### 后续事项

- 后续如果要支持更多事实类场景，可把“事实依据 -> 陪伴式表达”的模板抽为小型策略层，而不是继续在单个 fallback 里堆规则。
