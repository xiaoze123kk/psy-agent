# Graph trace 与质量追踪

> 返回：[[00 后端项目亮点分模块索引]]
> 相关代码：`backend/app/services/graph_trace_service.py`、`backend/app/services/conversation_quality_service.py`、`backend/app/services/graph_runtime.py`

## 它解决什么问题

当用户说“为什么这一轮回复这么奇怪”，或者开发者调试 RAG/风控/校验时，不能只看最终文本。需要知道：

- 哪个节点运行了。
- 每个节点输出了什么。
- RAG 有没有用。
- 为什么 RAG 被跳过。
- validator 有没有 warning/block。
- 记忆有没有写入。
- 最终 delivery_status 是什么。

## trace 类型

项目里有几类重要追踪：

| trace | 说明 |
| --- | --- |
| graph trace | LangGraph 每个节点的更新记录。 |
| trace summary | 给前端/API 使用的压缩摘要。 |
| RAG trace | 检索是否命中、召回数量、rerank 状态、耗时。 |
| quality trace | 对话质量评估，包括用户信号、validator 结果、是否重写。 |
| memory decisions | 记忆写入或跳过原因。 |

## 工作链路

```text
GraphRuntime
  -> record node update
  -> build trace summary
  -> chat_service persist_turn_traces
  -> conversation_turn_traces
```

同时，validator 和 response result 会生成 conversation quality trace，用来描述本轮回复质量和修复状态。

## 为什么是亮点

agent 产品最怕“黑箱”。这个项目把每轮对话中关键中间状态都留了下来，便于定位：

- 是风险分级错了？
- 是 control plane 走错路了？
- 是 RAG 没召回？
- 是 prompt 没接住 conversation move policy？
- 是 validator 修复失败？

这对迭代心理咨询 agent 很重要，因为体验问题往往不是单点 bug，而是链路里某个策略影响了后续节点。

## 对外讲法

> 每轮对话保存 graph trace、RAG trace、validator reasons、quality trace 和 memory decisions。这样可以解释一次回复为什么这样生成，也方便定位策略链路中的问题。

## 开发边界

- 新增节点输出时，要考虑是否进入 trace summary。
- 新增 validator reason 时，要确认前端/trace 能显示。
- 不要把敏感完整上下文无过滤暴露到 graph update。

## 推荐验证

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_graph_runtime_streaming.py tests/test_conversation_quality_trace.py -q
```
