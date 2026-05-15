# 后端风控体验改造设计

## 背景

当前后端已经有风险识别、控制平面、危机回复、RAG/工具/记忆门控和 `response_validator`。问题不在于没有安全边界，而在于可见体验过于硬切：用户一说到高风险词，系统容易从普通陪伴突然变成危机模板、强转介或公告式安全提示。这会削弱信任，也让心理陪伴角色显得割裂。

本设计只覆盖后端。知识库当前在项目中处于禁用状态，本轮不改知识库检索、知识 chunk 元数据和知识工具。

## 目标

1. 把风控从“关键词触发硬模板”改成“后台严格控制 + 前台连续陪伴”的策略系统。
2. 保留高风险安全边界：危险内容不外泄、不提供方法、不做诊断/用药、不强化依赖。
3. 高风险下仍允许安全范围内的上下文能力，尤其是记忆偏好和安全资源，而不是让系统失忆。
4. 将 `L2/L3` 首轮强转介后移；危机首轮不默认提心理咨询师、精神科、医院心理门诊。
5. 禁用“接住”等机械化高频词，避免鸡汤式劝活和公告式口吻。
6. 建立可测试、可审计、可逐步扩展的风险策略接口。

## 非目标

- 不启用知识库。
- 不调整数据库 schema。
- 不实现真人干预、报警、外呼或主动联系第三方。
- 不把所有安全判断交给模型自由发挥。
- 不删除现有 `risk_level`、`control_category`、`response_validator` 这些硬边界。

## 设计原则

- 风险处理硬，语言表达软。
- 高风险不是信息隔离，而是信息净化。
- 用户愿意继续对话是保护信号，但不能直接视为安全。
- 首轮目标不是讲道理，而是让用户继续回应、延后危险动作、靠近安全环境。
- 一轮最多一个问题，回复尽量短。
- 不复述具体危险方法，使用“那个东西”“那个位置”“这一步”等低刺激指代。
- 外部支持先从可信任现实人物开始，专业咨询建议放到用户稍微稳定之后。

## 风控分层

### 1. 风险识别层

保留 `L0/L1/L2/L3`，新增结构化策略字段：

- `risk_domain`: `self_harm`, `harm_other`, `victimization`, `clinical_red_flag`, `medical_request`, `dependency`, `sexual_boundary`, `prompt_attack`, `privacy`, `normal_support`
- `immediacy`: `none`, `vague`, `near_term`, `active`
- `risk_confidence`: `low`, `medium`, `high`
- `protective_signals`: 例如 `still_talking`, `mentions_trusted_person`, `denies_plan`, `asks_for_help`
- `risk_phase`: `first_contact`, `stabilizing`, `still_high`, `deescalating`, `post_crisis`

`risk_classifier` 继续负责基础分级和语义信号，`control_plane` 负责把风险信号转成上述策略字段。第一版可以通过 `recent_messages`、上一轮 `last_risk_level`、本轮文本和 `risk_reasons` 推导 `risk_phase`，不新增持久化字段。

### 2. 控制平面层

`control_plane` 输出不再只告诉后续节点走哪个 response node，还要输出 `risk_response_policy`：

```python
{
    "risk_domain": "self_harm",
    "immediacy": "near_term",
    "risk_phase": "first_contact",
    "allowed_moves": ["brief_validation", "time_box", "micro_safety_step", "one_low_friction_reply"],
    "forbidden_moves": ["diagnosis", "method_detail", "professional_referral_first_turn", "moralizing"],
    "tone": "low_pressure",
    "max_questions": 1,
    "max_chars": 220,
}
```

策略由后端生成，模型只能在策略内表达。这样可见回复更自然，但不会脱离安全边界。

### 3. 安全上下文层

高风险下不再只读取 `safety_summary`。新增 `safety_context_pack`，由记忆和会话摘要中安全可用的内容组成。

允许进入高风险上下文的内容：

- 用户不喜欢的表达方式，例如不想被命令、不想一上来听热线。
- 过去有效的稳定方式，例如短句、呼吸、陪一分钟、先整理身体感受。
- 可信任现实关系线索，例如姐姐、室友、老师、朋友，但不暴露联系方式。
- 用户称呼和语气偏好。
- 概括性安全连续性，例如“此前在夜间孤独时风险升高”。

过滤内容：

- 具体工具、地点、方法和可操作细节。
- 详细创伤复述。
- 手机号、地址、邮箱、身份证等个人标识。
- 可能诱发复现的描述。

`memory_service.retrieve_memories_for_turn()` 在 `L2/L3` 下改为安全白名单检索，而不是只允许 `safety_summary`。第一版白名单建议为 `safety_summary`, `support_strategy`, `preference`, `correction`, 少量 `relationship`。

### 4. 工具层

知识库不纳入本轮。

`ToolGate` 改成能力模式：

- `normal_context`: L0/L1 常规工具能力。
- `safety_context`: L2/L3 安全工具能力。
- `blocked_context`: prompt attack、危险方法、诊断用药等强限制场景。

高风险下允许：

- `search_memories` 的安全上下文模式，只返回安全摘要和偏好提示，不返回原文私密内容。
- `get_safety_resources`。
- `get_current_time`。
- `summarize_session`。
- 安全模式 web search，若保留现有 `web_search`，必须由后端生成查询，不带用户原话，只查可信支持资源，并过滤结果。

高风险下禁止：

- 用用户原话自由 web search。
- 搜索危险方法、剂量、地点、工具。
- 天气等与稳定无明显关系的工具。
- 普通可见记忆全文检索。

### 5. 回复策略层

`crisis_response`, `boundary_response`, `clinical_red_flag_response` 不再写整段固定模板，而是调用 `risk_response_policy` 生成短回复。第一版可以仍用受控模板片段组合，后续再切到模型生成。

不同 domain 的策略：

| domain | 主要目标 | 禁止点 |
| --- | --- | --- |
| `self_harm` | 降低强度、延后动作、保持回应、引入现实陪伴 | 方法复述、首轮强转介、鸡汤劝活 |
| `harm_other` | 降低冲动、远离目标对象/现场、回到愤怒背后的受伤感 | 认同报复、攻击建议、羞辱用户 |
| `victimization` | 关注现实安全、鼓励去有人处、低压求助 | 质疑受害者、要求证明 |
| `clinical_red_flag` | 稳定身体和现实感、避免确认妄想、建议可信现实支持 | 诊断、确认被监视/被控制为真 |
| `medical_request` | 不给药物和剂量，帮助整理症状和就医问题 | 药名剂量、停药建议、替代医生 |
| `dependency` | 陪伴但不成为唯一支撑，温和扩展支持网络 | “只有我懂你”、永远陪伴承诺 |
| `sexual_boundary` | 不进入性化互动，回到情绪或关系困扰 | 羞辱、调情、继续性化 |
| `prompt_attack` | 不泄露规则，回到用户真实需要 | 暴露系统提示、扮演越权角色 |

`L2/L3 self_harm` 首轮结构：

1. 一句情绪确认。
2. 把目标缩到“这一分钟”。
3. 一个微安全动作，用指代而非复述方法。
4. 一个低门槛回应方式。

示例风格：

> 你现在已经痛到很难再撑了。我们先不讲以后，也不分析原因，只先把这一分钟过掉。你能不能先让那个东西离你远一点，或者从那个位置退一步？回我一个字也可以。

### 6. 体验 validator

保留现有内容安全 validator，并新增体验安全检查。

内容安全继续拦：

- 自伤/伤人方法。
- 诊断和确诊。
- 药物、剂量、处方、停药。
- 妄想确认。
- 诱导依赖。
- 治疗保证。
- 未验证资源号码。
- RAG/示例原文复制。

体验安全新增拦：

- “接住”。
- `L2/L3` 首轮出现“心理咨询师”“精神科”“医院心理门诊”“尽快就医”等强转介。
- “珍惜生命”“世界还有很多美好”“想想你的家人”等鸡汤或道德劝说。
- 危机首轮超过字符上限。
- 一轮多个问题。
- 复述具体危险工具/地点/动作。

安全路径体验违规时，validator 替换为低压安全 fallback；普通路径违规时继续 `failed_no_reply` 或重试。

## 数据流

1. `chat_service._preclassify_risk_level()` 继续预分类，但需要返回更完整的控制结果，供记忆和工具准备使用。
2. `_prepare_turn_context()` 根据预分类结果构建 `safety_context_pack`。
3. `GraphRuntime` 将 `safety_context_pack` 和 `risk_phase` 放入 `AgentState`。
4. `risk_classifier` 和 `control_plane` 在图内重新确认策略字段。
5. response node 调用策略生成器生成回复和按钮。
6. `response_validator` 做内容安全和体验安全双重校验。
7. `_persist_turn_result()` 记录策略字段、validator 结果、工具门控和安全上下文摘要。

## 按钮策略

按钮是干预的一部分，不只是快捷回复。

`L1`:

- 我想慢慢说
- 先帮我稳一下
- 我不知道原因

`L2`:

- 我还在
- 先陪我一分钟
- 我先不动
- 我说不出来

`L3`:

- 我还在
- 我退开一点了
- 我身边有人
- 请继续跟我说

`dependency`:

- 我怕没人懂
- 我不知道能找谁
- 我还想说一点

`clinical_red_flag`:

- 我现在有点害怕
- 先帮我稳住
- 我能找谁

## 审计与可观测性

每轮 assistant metadata 增加：

- `risk_domain`
- `immediacy`
- `risk_confidence`
- `risk_phase`
- `risk_response_policy`
- `safety_context_summary`
- `tool_gate_mode`
- `validator_reasons`
- `experience_validator_reasons`

这些字段只记录概括和策略，不记录高风险可操作细节。

## 测试策略

新增后端测试覆盖：

1. `L2` 首轮不出现强转介、不出现“接住”、不出现鸡汤劝活。
2. `L3` 提到工具/地点时，回复不复述具体方法，但包含微安全动作和低门槛回应。
3. 用户说“别让我找别人/别提热线”时，不反复强推外部帮助，先回到当下稳定。
4. `harm_other` 不提供报复建议，能引导远离目标对象或现场。
5. `clinical_red_flag` 不确认妄想为真，不做诊断。
6. `medical_request` 不给药物剂量或停药建议。
7. `dependency` 不强化“只有我”，不承诺永远陪伴。
8. 高风险检索使用 `safety_context_pack`，不泄露普通记忆全文。
9. 高风险 `ToolGate` 允许安全工具，禁止自由 web search 和普通记忆全文检索。
10. 风险从 `L3` 缓和后进入 `deescalating`，不会立刻恢复普通模式。
11. 语音入口复用同一后端策略字段。
12. 现有安全分类测试继续通过。

## 参考原则

- NIMH “Ask, Be There, Keep Them Safe, Help Them Connect, Follow Up”: https://www.nimh.nih.gov/health/publications/5-action-steps-for-helping-someone-in-emotional-pain
- 988 Lifeline Safety Assessment: https://988lifeline.org/professionals/best-practices/
- SAMHSA Safety Plan: https://www.samhsa.gov/resource/988/safety-plan
- WHO Suicide Prevention: https://www.who.int/health-topics/suicide

这些资料提供安全结构，不直接决定产品话术。本项目要把结构翻译成自然、低压、中文心理陪伴风格。

## 验收标准

- 高风险回复不再像硬切模板，但仍不泄露危险内容。
- `L2/L3` 首轮不强推专业咨询。
- 高风险下 agent 仍能使用安全过滤后的用户偏好和支持线索。
- validator 同时覆盖内容安全和体验安全。
- 所有新增策略字段有单元测试或集成测试覆盖。
- 现有聊天、记忆、工具、语音安全回归测试保持通过。
