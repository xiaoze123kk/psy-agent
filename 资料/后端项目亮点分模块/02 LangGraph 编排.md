# LangGraph 编排

> 返回：[[00 后端项目亮点分模块索引]]
> 相关代码：`backend/app/graphs/main_graph.py`、`backend/app/graphs/routing.py`、`backend/app/graphs/state.py`、`backend/app/services/graph_runtime.py`

## 它解决什么问题

心理咨询 agent 不能把所有逻辑塞进一个 prompt。不同阶段有不同职责：

- 输入要清洗。
- 风险要优先判断。
- 控制面要决定能不能走普通支持。
- RAG 要在合适场景才启用。
- 回复生成要按场景分流。
- 输出要被校验。
- 最后要总结和决定是否写记忆。

这些由 `main_graph.py` 编成一张主图。

## 主图结构

```text
normalize_input
  -> load_user_profile
  -> risk_classifier
  -> control_plane
  -> intent_classifier / crisis_response / boundary_response / clarification_response
  -> example_retriever
  -> response node
  -> response_validator
  -> summarize_turn
  -> memory_candidate_extract
  -> write_memory / skip_memory
```

节点图见：

![[langgraph-main-graph.svg]]

也可以看总图笔记：[[项目模块讲解与LangGraph节点图]]。

## 节点分层

| 阶段 | 节点 | 作用 |
| --- | --- | --- |
| 输入 | `normalize_input`、`load_user_profile` | 规范输入、加载用户画像。 |
| 风险 | `risk_classifier` | 输出风险等级、风险域、原因码和风险策略。 |
| 控制 | `control_plane` | 决定危机、红旗、边界、澄清或普通支持。 |
| RAG | `intent_classifier`、`example_retriever` | 判断意图并检索咨询语料参考。 |
| 回复 | `*_response` | 按场景生成 assistant 文本和按钮。 |
| 校验 | `response_validator` | 安全和体验出口闸门。 |
| 记忆 | `summarize_turn`、`memory_candidate_extract`、`write_memory`、`skip_memory` | 摘要本轮、提取记忆候选、写入或跳过。 |

## 为什么是亮点

主图把“心理安全优先”和“普通聊天体验”分层了。不是所有请求都进入同一个模型 prompt，而是先经过风险和控制面：

- 高风险直接去 `crisis_response`。
- 临床红旗去 `clinical_red_flag_response`。
- 边界/系统保护去 `boundary_response`。
- 信息不足去 `clarification_response`。
- 普通支持才进入意图识别和 RAG。

这种分流降低了模型在高风险场景乱发挥的概率，也让每个节点能专注自己的职责。

## 开发边界

- 修改节点顺序时，要同步改 `routing.py` 和 GraphRuntime 流式 trace。
- 新增 AgentState 字段时，要检查 prompt builder、trace summary、测试。
- 新增 response 节点时，要接入 validator 和 memory 后处理。

## 推荐验证

```powershell
cd E:\心理咨询agent\backend
.\.venv\Scripts\python.exe -m pytest tests/test_graph_runtime_streaming.py tests/test_conversation_control_rag.py -q
```
