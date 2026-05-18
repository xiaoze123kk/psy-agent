# RAG 系统

> 返回：[[00 后端项目亮点分模块索引]]
> 相关代码：`backend/app/graphs/nodes/rag_nodes.py`、`backend/app/services/counseling_vector_service.py`、`backend/app/services/counseling_reranker.py`、`backend/app/services/counseling_examples.py`、`backend/app/services/counseling_chunking.py`、`backend/app/services/knowledge_service.py`

## 它解决什么问题

RAG 在这个项目里有两类用途：

1. 知识库 RAG：用于心理健康知识内容。
2. 咨询语料 RAG：用于给回复生成提供咨询过程和语言风格参考。

最有特色的是咨询语料 RAG。它不是为了“查知识答案”，而是为了让模型参考更像真实咨询对话的回应方式。

## 咨询语料 chunk 设计

咨询语料不是简单按固定字数切片，而是按对话意义分层：

| chunk 类型 | 说明 | 用途 |
| --- | --- | --- |
| `turn_pair` | 单个 user-assistant 轮次 | 学局部回应方式、措辞和节奏 |
| `process_segment` | 3-5 轮咨询片段 | 学情绪变化和咨询师推进方式 |
| `session_sketch` | 整段咨询地图 | 学主题、情绪线、干预路径，不保存逐字原文 |

这个设计非常适合心理咨询场景，因为咨询不是知识问答，而是过程性互动。

## 检索链路

```text
example_retriever
  -> counseling_rag_allowed
  -> embedding query
  -> Milvus recall
  -> local/model rerank
  -> quota selection
  -> retrieved_counseling_examples
  -> prompt builder
```

## 安全 gating

RAG 有明确的安全边界：

- `risk_level` 是 `L2` / `L3` 时阻断咨询语料 RAG。
- Milvus 不可用时不会阻断聊天，而是返回 fallback。
- embedding 不可用时会跳过 RAG。
- reranker 失败时会退回确定性选择。
- retrieved examples 会被 validator 防复制，避免 RAG 原文泄露。

## rerank 亮点

`counseling_reranker.py` 支持：

- 本地 reranker worker。
- 超时控制。
- reranker disabled/unavailable fallback。
- scored_count、duration、reason trace。
- 按 query 类型做 chunk 配额选择。

这意味着 RAG 不是“搜到什么塞什么”，而是有召回、重排、配额、失败降级和 trace 的完整链路。

## 为什么是亮点

很多项目的 RAG 是知识检索。这个项目的咨询 RAG 更像“过程参考检索”：它检索的不是标准答案，而是咨询对话片段，用来改善回复的语气、节奏和干预路径。

## 对外讲法

> 这个 RAG 系统不只检索知识，还检索咨询过程样本。语料按 turn_pair、process_segment、session_sketch 三层建模，并且高风险时自动阻断，reranker 失败时降级，trace 中能看到每次召回和重排状态。

## 开发边界

- 不要把高风险场景接回普通咨询语料 RAG。
- 修改 chunk 类型或 Milvus scalar fields 后，要考虑重建 collection。
- 修改 rerank fallback 时，要保留 trace 字段，方便定位问题。

## 推荐验证

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_conversation_control_rag.py tests/test_counseling_reranker.py tests/test_counseling_milvus_plan.py -q
```
