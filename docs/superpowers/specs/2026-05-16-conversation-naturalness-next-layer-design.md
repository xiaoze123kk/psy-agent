# 对话自然度下一层优化设计

## 背景

当前后端已经完成了几轮关键改造：安全风控从硬编码关键词走向语义分层；高风险回复不再硬模板化；回复长度可以动态变化；结尾策略也从“每轮最多一个问题”改成“问题是可选动作”。这些改动之后，单轮对话已经开始像一个更自然的陪伴者。

下一层问题不再是“是否安全”或“是否温柔”，而是 agent 是否真的像一个有连续感、有注意力、有文化理解能力的人。用户会敏锐感受到这些细节：

- 它是不是顺着前几轮继续说，还是每轮重新开一个咨询流程。
- 它是不是把文学、人物、书名、隐喻当成真实话题，而不是只当成心理症状线索。
- 它是不是会根据用户纠正立刻改变，而不是道歉后继续旧模式。
- 它是不是每轮都用相似开头、相似结构、相似按钮。
- 它是不是把普通聊天过度解释成压抑、防御、创伤或深层模式。

本 spec 覆盖这 8 个痛点：

1. 多轮节奏感。
2. 减少固定开头。
3. 更会聊用户提到的东西。
4. 安全模式退出更自然。
5. 按钮文案更像用户会说的话。
6. 避免过度心理化。
7. 修正能力。
8. 对话动作多样化。

## 目标

1. 让 agent 保持多轮话题连续性，不把每轮都当成独立咨询片段。
2. 让文学、哲学、影视、人物、书名和隐喻成为可继续谈论的内容，而不是只被心理化解释。
3. 降低固定开头、固定结构和固定按钮带来的模板感。
4. 让用户纠正、拒绝、吐槽、说“不是这个意思”后，下一轮能明显改变策略。
5. 让普通闲聊优先被当作普通聊天，只有上下文确有风险或求助线索时才心理化。
6. 让安全模式退出时既不失忆，也不继续盘问。
7. 建立可测试的自然度 eval，覆盖连续性、文化锚点、纠偏和过度心理化。

## 非目标

- 不改变当前风险分层的安全底线。
- 不启用知识库；当前知识库仍按项目状态暂不纳入。
- 不做前端 UI 改造。
- 不让 agent 假装自己真正读过所有书或拥有真人经历。
- 不让 agent 进入不可控的长篇文学评论、学术讲座或百科输出。
- 不取消心理支持能力；只是减少不必要的心理化。

## 核心原则

### 1. 对话先是对话，再是干预

用户不是每句话都在“求干预”。很多时候用户是在分享联想、试探理解、寻找共鸣、表达一个比喻，或者只是想让对话继续流动。agent 应先识别对话动作，再决定是否需要心理支持动作。

### 2. 锚点是真实内容，不只是情绪证据

当用户提到《在轮下》、荣格、黑塞、某个角色、某句诗、某部电影，agent 应该把它们当作当前话题的一部分。它可以轻轻连接情绪，但不应把所有文化锚点都翻译成“你现在很压抑”。

### 3. 修正比道歉重要

用户说“不是这个意思”“你又机器了”“别一直问”“别心理分析”时，下一轮最重要的不是解释或道歉，而是马上改变对话动作。

### 4. 安全之后要会回到生活

高风险缓和后，agent 应保留温和关照，但优先回应用户当前话题。不能因为之前有风险，就把后续每个普通话题都拖回安全盘问。

## 方案比较

### 方案 A：继续靠大 prompt 增加自然度要求

做法是在核心提示词里继续加入“不要固定开头”“不要过度心理化”“要有连续感”等规则。

优点是改动小。

缺点是提示词会继续膨胀，模型很难稳定执行；eval 也很难定位失败原因。它容易变成“又加一堆禁令”，反而让回复更紧。

### 方案 B：完全交给模型自由发挥

做法是减少规则，让模型根据上下文自然聊天。

优点是可能更松弛。

缺点是安全边界、纠偏和一致性会变差；在心理陪伴产品里不可控。

### 方案 C：新增“对话动作策略层”

做法是在现有 `risk_response_policy` 和 prompt builder 之外，引入一层轻量的 `conversation_move_policy`。它不决定安全等级，而是决定本轮更像哪种对话动作：继续话题、回应文化锚点、陈述留白、轻邀请、纠偏、普通闲聊、微行动等。

优点是可解释、可测试、能和现有风控策略并行工作。

缺点是需要补策略字段、prompt 注入、validator/eval，不能只改一句话。

推荐采用方案 C。

## 设计概览

新增内部策略对象：

```json
{
  "conversation_move": "continue_thread | respond_to_anchor | reflective_pause | soft_invitation | correction_followup | ordinary_chat | post_risk_return | micro_step | clarify_once",
  "topic_anchor": {
    "type": "literary | philosophical | media | person | metaphor | daily_detail | relational | none",
    "value": "在轮下",
    "handling": "treat_as_topic | connect_lightly_to_emotion | avoid_psychologizing"
  },
  "style_variation": {
    "opening_mode": "direct | echo_anchor | short_reflection | no_preface",
    "structure_mode": "single_paragraph | two_beat | pause_then_invite | brief_answer",
    "avoid_reused_openings": true
  },
  "correction_state": {
    "user_corrected_previous_reply": false,
    "correction_type": "not_that_meaning | too_many_questions | too_ai_like | too_psychological | too_safety_focused | none"
  },
  "psychologizing_risk": "low | medium | high",
  "button_style": "user_voice | topic_continue | safety_micro_reply | none"
}
```

这不是用户可见字段，只用于 prompt、trace、validator 和 eval。

## 八个优化点

### 1. 多轮节奏感

现状风险：agent 单轮表现不错，但多轮里容易不断重新“共情-整理-提问”，缺少正在一起走一段话题的感觉。

设计：

- 从 `recent_messages` 派生 `thread_continuity`。
- 判断当前用户是在回答上一轮、延续一个锚点、切换话题，还是纠正 agent。
- 如果是延续话题，优先 `conversation_move=continue_thread`，不要重新开场。
- 如果用户只是短答“记得”“嗯”“是这个”，下一轮先接上，不要重新解释用户。

示例：

不推荐：

> 听起来你现在很压抑。你能说说这种感觉从什么时候开始的吗？

推荐：

> 对，就是《在轮下》那种被一整套东西推着走的感觉。你刚刚说“不然就会被碾死”，这句话其实已经把那种没有退路感说出来了。

### 2. 减少固定开头

现状风险：高频“听到你说”“我听见了”“这听起来”会让用户感到咨询话术。

设计：

- 增加 `opening_mode`。
- 最近两轮 assistant 如果已经使用同类开头，本轮禁止重复。
- 允许直接进入内容，不必每轮先声明理解。

开头类型：

| opening_mode | 示例 |
| --- | --- |
| `direct` | “《在轮下》这个比喻很重。” |
| `echo_anchor` | “奔跑、被碾死、没有停下来的资格。” |
| `short_reflection` | “这不是单纯累，是被推着走。” |
| `no_preface` | 直接回应上一句，不加开场白。 |

### 3. 更会聊用户提到的东西

现状风险：用户提到文化内容，agent 只把它当成情绪投射材料。

设计：

- 增加 `topic_anchor.type` 和 `topic_anchor.handling`。
- 对文学、哲学、影视、人物类锚点，允许 agent 做轻量内容回应。
- 如果没有把握，不假装深度知识；可以承认只抓住用户给出的线索。
- 回复优先使用用户锚点中的具体词，而不是泛化为“你的情绪”。

处理策略：

- `treat_as_topic`：把锚点当话题继续聊。
- `connect_lightly_to_emotion`：轻轻连到用户处境，不做深层分析。
- `avoid_psychologizing`：避免把锚点解释成症状或防御。

### 4. 安全模式退出更自然

现状风险：高风险缓和后，agent 可能继续安全盘问，或者完全失忆。

设计：

- 复用现有 `risk_phase=deescalating/post_crisis`，新增 `conversation_move=post_risk_return`。
- 当前轮无新风险表达时，先回应当前话题。
- 只保留一句低压关照，不主动重复计划、工具、身边有人等安全问题。
- 如果用户明确说“不想一直聊安全”，下一轮必须切换出安全盘问。

示例：

> 刚才那阵我还记得，但这会儿你想聊荣格，我们就先从荣格这里走。这个话题本身也许比反复确认安全更能让你喘一口气。

### 5. 按钮文案更像用户会说的话

现状风险：按钮像流程选项，而不是用户下一句会说的话。

设计：

- 根据 `button_style` 生成按钮。
- 普通对话优先 `user_voice` 或 `topic_continue`。
- 高风险才使用 `safety_micro_reply`。
- 按钮避免“继续陪我”过度泛化；要贴近当前话题。

示例：

文学/隐喻场景：

- “这个比喻很准”
- “我想继续说这个”
- “先停在这句话上”

普通闲聊：

- “就随便聊聊”
- “这个挺有意思”
- “换个轻一点的”

安全缓和：

- “我还在”
- “先慢一点”
- “别继续盘问”

### 6. 避免过度心理化

现状风险：短笑、随口吐槽、文学联想、日常细节被解释成压抑、创伤、防御。

设计：

- 增加 `psychologizing_risk`。
- 当输入短、轻、日常、玩笑、文化讨论或用户未显露求助意图时，优先 `ordinary_chat`。
- validator/eval 增加 `over_psychologizing`。
- 对“呵呵”“哈哈”“记得吗”“今天看到一朵花”这类输入，不自动套深层解释。

普通聊天优先规则：

```text
如果没有明确痛苦、风险、求助、反复模式或用户请求分析：
先当作普通人类聊天处理。
```

### 7. 修正能力

现状风险：用户纠正后，agent 道歉但策略没变。

设计：

- 识别纠正类型：
  - `not_that_meaning`
  - `too_many_questions`
  - `too_ai_like`
  - `too_psychological`
  - `too_safety_focused`
- 下一轮注入 `correction_followup` 策略。
- 回复必须体现行为变化，而不是解释为什么刚才那样说。

示例：

用户：

> 不是这个意思，你又在心理分析了。

推荐：

> 好，那我先把分析放下。你刚才说的重点更像是《在轮下》那种处境感，不是要我判断你怎么了。

### 8. 对话动作多样化

现状风险：主要动作是共情、整理、提问、小步骤，久了会单调。

设计：

引入对话动作库：

| move | 作用 |
| --- | --- |
| `continue_thread` | 顺着上一轮话题往下走 |
| `respond_to_anchor` | 回应书名、人物、隐喻、日常细节 |
| `reflective_pause` | 不推进，只停留 |
| `soft_invitation` | 轻邀请，不压迫 |
| `correction_followup` | 根据用户纠正改变策略 |
| `ordinary_chat` | 普通聊天，不心理化 |
| `post_risk_return` | 风险后自然回到当前话题 |
| `micro_step` | 高风险或失控时的小动作 |
| `clarify_once` | 只澄清一个必要点 |

## 后端数据流

1. `control_plane` 或独立策略服务读取：
   - `risk_level`
   - `risk_response_policy`
   - `recent_messages`
   - `normalized_text`
   - `semantic_risk`
   - `user_context_pack`

2. 生成 `conversation_move_policy`。

3. `dialogue_prompt_builder` 注入：
   - 本轮对话动作。
   - 话题锚点处理方式。
   - 开头变化要求。
   - 是否避免心理化。
   - 是否根据用户纠正调整。
   - 按钮风格。

4. response node 仍由模型生成自然语言。

5. `response_validator` 增加体验检查：
   - 固定开头重复。
   - 文化锚点被忽略。
   - 用户纠正后仍旧策略。
   - 普通聊天过度心理化。
   - 安全缓和后继续盘问。
   - 按钮不像用户会说的话。

6. trace 记录策略字段，方便调试。

## Prompt 设计原则

prompt 不应继续堆大量禁令，而应给出本轮“应该做什么”。

示例注入：

```text
本轮对话动作：respond_to_anchor
用户锚点：在轮下 / 文学隐喻
处理方式：把它当作真实话题继续聊，轻轻连接用户处境，不要立刻心理分析。
开头方式：direct，避免“听起来/我听见/我理解”开头。
结尾方式：reflective_pause，不用问句收尾。
按钮风格：topic_continue，像用户下一句会说的话。
```

## Validator 设计

新增体验 reason：

- `reused_formulaic_opening`
- `ignored_topic_anchor`
- `over_psychologizing`
- `failed_user_correction`
- `post_risk_over_safety_check`
- `generic_buttons`
- `conversation_restart`

建议严重度：

- `failed_user_correction`：blocking。
- `post_risk_over_safety_check`：blocking 或 high warning，取决于风险等级。
- `over_psychologizing`：普通场景 warning，用户明确拒绝心理分析后 blocking。
- `ignored_topic_anchor`：warning。
- `generic_buttons`：warning。
- `reused_formulaic_opening`：warning。

## Eval 设计

新增质量用例类型：

1. 文学锚点连续对话：
   - 用户提《在轮下》《德米安》《荣格》。
   - 正例应回应内容和隐喻。
   - 负例是只做心理化提问。

2. 普通闲聊不心理化：
   - “呵呵”“今天看到一朵花”“吃了个难吃包子”。
   - 正例轻松自然。
   - 负例是创伤、防御、压抑解释。

3. 用户纠偏：
   - 用户说“不是这个意思”“别一直问”“你太像机器”。
   - 正例下一轮行为改变。
   - 负例只是道歉后继续旧策略。

4. 风险后回流：
   - 前一轮 L2，后一轮问文学/日常话题。
   - 正例回应当前话题并轻轻保留关照。
   - 负例继续安全盘问。

5. 按钮自然度：
   - 正例按钮像用户下一句。
   - 负例按钮像流程选项或内部策略。

## 验收标准

- 截图里的《在轮下》场景，agent 能至少连续 3 轮顺着文学隐喻走，不每轮重启咨询流程。
- 用户提到文化/文学锚点时，回复里能看见锚点本身，而不只是泛化情绪。
- 普通闲聊不会默认进入深层心理分析。
- 用户纠正后，下一轮策略明显改变。
- 安全缓和后的普通话题不再被持续安全盘问。
- 按钮文案贴近当前语境，不再大量出现泛化按钮。
- 相关 validator/eval 能抓到负例。

## 实施顺序

1. 先补 eval：文化锚点、普通闲聊、纠偏、风险后回流、按钮自然度。
2. 新增 `conversation_move_policy` 生成逻辑。
3. 注入 prompt block。
4. 扩展 validator 体验 reason。
5. 调整按钮生成策略。
6. 跑现有安全/风控/自然度回归。

## 风险与缓解

### 风险 1：过度自由导致安全回退

缓解：`conversation_move_policy` 不能覆盖 `risk_response_policy`。当 L2/L3 明确存在时，安全策略仍优先。

### 风险 2：文化锚点回应变成胡编知识

缓解：prompt 要求“不确定时只回应用户给出的线索，不假装知道更多”。eval 增加 `fabricated_cultural_claim`。

### 风险 3：为了避免心理化而变得太轻浮

缓解：普通聊天优先不等于轻浮。若用户表达痛苦，仍需贴近痛苦，只是不抢着诊断和深挖。

### 风险 4：策略字段过多导致 prompt 变重

缓解：只注入本轮最相关的 3-5 条策略，不把完整 JSON 暴露给模型。

## 推荐切分

第一期优先做三件事：

1. 多轮节奏与文化锚点：解决“会不会真的聊天”。
2. 用户纠偏：解决“会不会听反馈”。
3. 普通聊天不心理化：解决“会不会过度咨询化”。

按钮自然度和固定开头可以作为同一批的轻量 validator/eval 跟进。安全模式退出已经有基础策略，可在第一期里补强回流 eval。
