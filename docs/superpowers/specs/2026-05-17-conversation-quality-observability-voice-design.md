# 对话质量观测闭环与宁语声线优化设计

## 背景

前几期对话模块已经完成了几层关键改造：风险回复不再只靠硬模板；`conversation_move_policy` 能区分延续话题、普通闲聊、纠偏、风险后回流和文化锚点；文化锚点也从单个 `anchor_value` 升级为结构化 `anchor_evidence`，能更稳地避免胡编作品细节。

现在的问题不再是“宁语是否足够温柔”，而是它是否能稳定地像同一个会聊天的人：能看见自己上一轮有没有没接住，能知道用户一句话里到底有几条线，能在用户纠正后短时间内真的换一种聊法，也能保持一套不僵硬但稳定的声线。

如果继续只加 prompt 禁令，系统会越来越像一个规则堆叠出来的咨询机器人。第五期应该把优化重点从“补一条回复规则”推进到“建立可观测、可回放、可校准的对话质量闭环”。

## 目标

1. 建立对话质量观测闭环，让每轮对话的策略、回复形状、validator 警告、修复情况和用户后续反应可被追踪。
2. 支持多意图 / 多锚点理解，能区分主线、次线、不要展开的线，以及本轮只应轻触的线。
3. 定义“宁语声线契约”，让回复在句长、停顿、提问频率、分析深度、幽默边界和结尾方式上更稳定。
4. 增强用户纠正后的短期学习：用户说“不是这个意思”“别分析”“别一直问”后，后续几轮要降低同类误判。
5. 为桌面前端预留轻反馈入口，让真实使用中的“没接住 / 太分析 / 太泛 / 刚刚好”能回流到后端质量数据。
6. 保持现有风险安全底线，不让自然度优化覆盖 `risk_response_policy`、危机处理和边界策略。

## 非目标

- 不引入外部联网搜索。
- 不在本期建设完整文化知识库或作品百科库。
- 不重做全部记忆系统；本期只补短期对话适配和质量标记。
- 不重构桌面前端整体 UI；只定义轻反馈 API 和最小交互契约。
- 不让 agent 固定成僵硬人设；“声线契约”是表达边界，不是角色扮演剧本。
- 不用用户原文做长期质量统计，避免把敏感文本沉淀到分析数据里。

## 当前问题诊断

### 1. 质量判断缺少运行时证据

现在 validator 和 eval 已经能抓到部分负例，但多数判断仍发生在开发测试里。真实对话中，系统很难回答这些问题：

- 哪些 `conversation_move` 最容易触发修复？
- 哪些文化锚点最容易被浅层复读？
- 哪类用户纠正之后，agent 仍然继续旧策略？
- 哪些回复结尾让用户更可能继续说，哪些让用户沉默？
- 按钮文案是否真的被点击，还是只是看起来合理？

没有这些观测，后续优化会越来越依赖主观抽样。

### 2. 单意图策略不够表达真实用户输入

用户经常一句话同时包含多条线，例如：

> 我不是想聊《德米安》本身，就是觉得那个“找自己”的说法有点像我，但你别又开始分析我。

这句话至少包含：

- 文化锚点：《德米安》
- 用户线索：找自己
- 明确边界：不是聊作品本身
- 纠正 / 预防：不要开始分析我

当前策略层可以识别一部分锚点和纠正，但缺少“主线 / 次线 / 禁止展开线”的统一表达。

### 3. 声线稳定性仍靠 prompt 经验

宁语现在已经比早期自然，但仍可能在不同场景中摇摆：一轮像咨询师，一轮像百科，一轮像客服，一轮又像测试助手。真正的陪伴感需要一套可执行的表达契约：

- 什么情况下只接一句，不总结。
- 什么情况下可以问问题，最多问几个。
- 什么情况下允许一点轻幽默。
- 什么情况下要避免“听起来你……”这类咨询腔。
- 什么情况下宁可留白，也不要强行给建议。

### 4. 用户纠正后的改变还不够持久

已有 `correction_followup` 可以影响下一轮，但真实体验里，用户纠正通常代表一种短期偏好：

- “别分析”可能意味着接下来几轮都要降低分析深度。
- “别一直问”可能意味着接下来几轮都要减少问句。
- “不是这个意思”可能意味着要重新选择主线，而不是只道歉一次。

本期需要把纠正从“单轮事件”升级为“短期适配状态”。

## 方案比较

### 方案 A：继续补 prompt 禁令

做法是在 prompt 里继续加入“不许太分析”“不要重复开头”“用户纠正后要改变”等规则。

优点是改动小。

缺点是 prompt 会继续膨胀，而且无法知道真实运行中到底哪类场景失败最多。它更像靠提醒维持自然度，不能形成优化闭环。

### 方案 B：先做前端反馈，再人工看样本

做法是在桌面前端加入反馈按钮，把用户反馈记录下来，后续人工查看。

优点是真实、有价值。

缺点是如果后端没有结构化质量 trace，反馈只能告诉我们“用户不满意”，不能告诉我们是哪条策略、哪种 move、哪类回复形状出了问题。

### 方案 C：质量观测骨架 + 多线策略 + 声线契约

做法是在现有 `conversation_move_policy`、validator、trace 和 prompt builder 上加一层轻量质量观测与表达契约：

- 每轮生成 `conversation_quality_trace`。
- 策略层输出 `intent_lanes` 表达多意图 / 多锚点。
- prompt 注入“宁语声线契约”，按场景限制句长、问句、分析深度和结尾。
- 用户纠正写入短期 `adaptation_state`。
- 前端反馈接入同一套质量 trace。

优点是可解释、可测试、能持续校准，而且符合当前后端架构。

缺点是要跨 `conversation_move_policy`、`dialogue_prompt_builder`、validator、trace、测试和轻反馈 API，不能用单点补丁完成。

推荐采用方案 C。

## 核心设计

### 1. 新增 `conversation_quality_trace`

`conversation_quality_trace` 是面向调试、eval 和后续分析的内部结构，不直接暴露给模型，也不展示给用户。

示例：

```json
{
  "turn_shape": {
    "assistant_length_bucket": "short | medium | long",
    "question_count": 0,
    "opening_pattern": "direct | validation_preface | anchor_echo | safety_check | unknown",
    "closing_pattern": "pause | invitation | action_button | safety_micro_step | none"
  },
  "policy_snapshot": {
    "conversation_move": "respond_to_anchor",
    "risk_level": "L0",
    "topic_anchor_type": "literary",
    "cultural_response_mode": "echo_user_clue",
    "voice_mode": "anchored_companion"
  },
  "validator_snapshot": {
    "severity": "passed",
    "experience_reasons": [],
    "regeneration_attempted": false
  },
  "user_signal": {
    "explicit_feedback": "none | missed | too_analytic | too_generic | good",
    "next_turn_signal": "continued | corrected | stopped | unknown"
  }
}
```

隐私原则：

- 默认不写入用户原文和 assistant 原文。
- 锚点只保存类型、短标签和策略字段；敏感文本保留在已有对话存储边界内，不复制到质量 trace。
- 如果需要调试原文，只通过现有 graph trace 权限路径查看，不新增长期分析副本。

### 2. 新增 `intent_lanes`

`intent_lanes` 用来表达用户一句话里的多条线。它不是替代 `conversation_move`，而是给 `conversation_move` 更细的依据。

示例：

```json
{
  "primary_lane": "self_reference",
  "intent_lanes": [
    {
      "id": "lane_1",
      "kind": "cultural_anchor",
      "anchor_type": "literary",
      "anchor_value": "德米安",
      "priority": "secondary",
      "handling": "do_not_expand_work_detail"
    },
    {
      "id": "lane_2",
      "kind": "self_reference",
      "user_clues": ["找自己", "有点像我"],
      "priority": "primary",
      "handling": "respond_to_user_clue"
    },
    {
      "id": "lane_3",
      "kind": "boundary",
      "user_clues": ["别又开始分析我"],
      "priority": "blocking_style_constraint",
      "handling": "lower_analysis_depth"
    }
  ]
}
```

基本规则：

- `primary` 是本轮主要回应对象。
- `secondary` 可以轻触，但不能抢主线。
- `blocking_style_constraint` 是表达约束，优先级高于普通内容线。
- `do_not_expand_work_detail` 禁止把文化锚点扩写成作品解析。
- 当 `intent_lanes` 与旧字段冲突时，旧字段用于兼容，prompt 优先听 `intent_lanes`。

### 3. 新增 `ningyu_voice_contract`

声线契约是一组内部表达参数，用来让 prompt builder 给模型更具体的写法要求。

示例：

```json
{
  "voice_mode": "anchored_companion | quiet_presence | ordinary_chat | safety_gentle | correction_repair",
  "analysis_depth": "none | light | moderate",
  "question_budget": 0,
  "sentence_budget": "1-2 | 2-4 | 4-6",
  "opening_preference": "direct | echo_user_words | no_preface",
  "closing_preference": "pause | soft_invitation | micro_action | no_question",
  "humor_allowed": false,
  "avoid_patterns": ["听起来你", "这说明你", "你可能是在"]
}
```

建议初始声线模式：

| voice_mode | 使用场景 | 写法 |
| --- | --- | --- |
| `anchored_companion` | 用户给出文化、隐喻、具体画面 | 先接锚点和用户线索，轻连感受，不百科 |
| `quiet_presence` | 用户表达重、短、疲惫，未请求方案 | 少说，允许留白，不急着提问 |
| `ordinary_chat` | 日常、玩笑、轻闲聊 | 像普通聊天，不心理化 |
| `safety_gentle` | L2 或风险缓和 | 保留安全底线，但不用强模板 |
| `correction_repair` | 用户纠正 agent | 直接改变行为，少解释 |

### 4. 新增短期 `adaptation_state`

`adaptation_state` 记录用户近期明确纠正或偏好的冷却状态，只影响当前线程的接下来几轮，不默认写入长期记忆。

示例：

```json
{
  "avoid_analysis_turns": 3,
  "avoid_questions_turns": 2,
  "avoid_safety_check_turns": 1,
  "prefer_direct_anchor_response_turns": 3,
  "last_correction_type": "too_psychological",
  "last_updated_turn_id": "..."
}
```

衰减规则：

- 每完成一轮回复，对应计数减 1。
- 新的用户纠正可以刷新或叠加相关计数。
- L2/L3 风险明确出现时，安全策略仍然优先，但 prompt 要尽量低压。
- 用户明确要求“可以分析一下”时，`avoid_analysis_turns` 可提前清零。

### 5. 轻反馈 API 契约

桌面前端可以在回复旁提供极轻反馈。反馈不需要一开始做成完整评价系统，只需要能标记最常见问题。

后端建议新增或扩展一个反馈入口：

```json
{
  "thread_id": "...",
  "turn_id": "...",
  "feedback": "missed | too_analytic | too_generic | too_many_questions | good",
  "optional_note": "string"
}
```

反馈写入质量 trace 或独立质量表时，应关联：

- `turn_id`
- `conversation_move`
- `voice_mode`
- `validator_severity`
- `experience_validator_reasons`
- `response_shape`

桌面前端最小交互建议：

- 默认不打扰用户。
- 可以把反馈藏在回复 hover / 更多菜单里。
- 文案贴近日常感：`没接住`、`太分析了`、`太泛了`、`刚刚好`。
- 不在本期做复杂统计面板。

## 后端数据流

1. `control_nodes` 继续生成风险策略和 `conversation_move_policy`。
2. `conversation_move_policy` 在现有字段基础上补充：
   - `intent_lanes`
   - `ningyu_voice_contract`
   - `adaptation_state_delta`
3. `dialogue_prompt_builder` 注入：
   - 本轮主线和次线
   - 不要展开的线
   - 声线契约
   - 短期纠正适配要求
4. response node 生成回复。
5. `response_validator` 继续做内容安全和体验检查，并新增声线相关 reason。
6. validator 后生成 `conversation_quality_trace`：
   - 回复形状
   - 策略快照
   - validator 快照
   - 反馈占位
7. 如果下一轮用户出现纠正、继续、停止等信号，可回填上一轮的 `next_turn_signal`。
8. 前端反馈 API 可异步补写 `explicit_feedback`。

## Prompt 注入设计

prompt 不应把内部 JSON 原样暴露，而应转成简短自然的执行指令。

示例：

```text
本轮主线：回应用户说“找自己”和“有点像我”的线索。
可轻触的线：用户提到《德米安》，但用户说不是想聊作品本身。
不要展开：不要补作品情节、人物细节或作者意图；不要把用户直接心理分析。
宁语声线：anchored_companion；2-4 句；最多 0 个问题；开头直接接用户词；结尾可以留白。
短期适配：用户刚提醒“别分析”，本轮降低分析深度，只回应他给出的线索。
```

这类 prompt block 要替代一部分泛化禁令，避免继续堆叠“不要做 X”的长列表。

## Validator 设计

新增或细化体验 reason：

| reason | 含义 | 严重度 |
| --- | --- | --- |
| `missed_primary_lane` | 回复没有回应本轮主线 | warning |
| `expanded_forbidden_lane` | 展开了用户要求不要展开的线 | warning，用户明确拒绝后可 blocking |
| `violated_voice_contract` | 问句数、分析深度或长度明显违背声线契约 | warning |
| `failed_short_term_adaptation` | 用户纠正后的冷却期内仍重复同类问题 | blocking 或 warning |
| `feedback_negative_quality` | 用户显式反馈没接住、太分析、太泛 | trace only，不直接阻断 |

现有 reason 继续保留：

- `over_psychologizing`
- `ignored_topic_anchor`
- `fabricated_cultural_claim`
- `overconfident_cultural_claim`
- `shallow_anchor_echo`
- `missed_user_cultural_clue`
- `generic_buttons`
- `failed_user_correction`

validator 不应因为所有 warning 都重试。建议：

- 内容安全和明确违背用户纠正的 blocking reason 才触发重生成。
- 声线轻微偏差只记录 warning。
- 用户显式负反馈只作为后续分析数据，不 retroactively 改写已发送回复。

## Eval 设计

新增 fixture 类型：

### 1. 多线输入

用户：

> 我不是想聊《德米安》本身，就是觉得那个“找自己”的说法有点像我，但你别又开始分析我。

正例：

- 主线回应“找自己”和“有点像我”。
- 轻触《德米安》，不讲作品情节。
- 不做心理分析。
- 不提问或只留下非常轻的一句邀请。

负例：

- 大段介绍《德米安》。
- 说用户在投射、压抑、逃避。
- 忽略“别分析我”。

### 2. 声线契约

用户：

> 嗯，就停在这儿吧。

正例：

- 1-2 句。
- 不问问题。
- 允许安静收住。

负例：

- 继续总结、分析、提行动建议。
- 追问“你愿意说说为什么吗”。

### 3. 用户纠正冷却

用户先说：

> 别一直问我问题。

下一轮用户：

> 我只是觉得今天有点空。

正例：

- 不以问句结尾。
- 接住“空”的感受或画面。
- 不解释刚才为什么问。

负例：

- 继续问“这种空从什么时候开始”。

### 4. 轻反馈回流

给定某轮反馈：

```json
{"feedback": "too_analytic"}
```

下一轮策略应：

- 增加短期 `avoid_analysis_turns`。
- 降低 `analysis_depth`。
- 在质量 trace 中关联这条反馈。

### 5. 质量 trace 完整性

每轮对话应至少生成：

- `turn_shape`
- `policy_snapshot`
- `validator_snapshot`
- `user_signal`

且不包含用户完整原文。

## 验收标准

1. 多线输入场景中，策略层能产出主线、次线和禁止展开线。
2. prompt 中能看到声线契约的自然语言指令，但不会把内部 JSON 字段暴露给用户。
3. 用户明确“别分析 / 别问 / 不是这个意思”后，后续 2-3 轮能看到对应短期适配。
4. 每轮回复生成质量 trace，包含策略、回复形状、validator 和反馈占位。
5. 质量 trace 不复制用户完整原文，不新增敏感文本长期分析副本。
6. 桌面前端可以通过最小 API 提交 `没接住 / 太分析 / 太泛 / 刚刚好` 类反馈。
7. 相关 eval 能抓住以下负例：
   - 忽略主线
   - 展开禁止线
   - 违反声线契约
   - 纠正后仍旧策略
   - 质量 trace 缺字段或含原文

## 实施顺序

1. 先补纯函数测试和 eval fixtures：多线输入、声线契约、纠正冷却、质量 trace。
2. 扩展 `conversation_move_policy`，新增 `intent_lanes` 和 `ningyu_voice_contract`。
3. 增加短期 `adaptation_state` 的生成、衰减和 prompt 注入。
4. 扩展 `dialogue_prompt_builder`，把多线策略和声线契约转成自然语言指令。
5. 扩展 validator 体验 reason。
6. 增加 `conversation_quality_trace` 构建与 graph trace 汇总。
7. 增加轻反馈 API 契约和后端存储入口。
8. 补一批跨模块回归测试，确保风险策略仍优先。

## 风险与缓解

### 风险 1：trace 变成隐私负担

缓解：质量 trace 默认不保存完整用户原文和 assistant 原文，只保存策略标签、长度桶、问句数、reason 和反馈枚举。

### 风险 2：声线契约过强导致回复变僵

缓解：声线契约只控制边界，不写固定句式。validator 只抓明显违背，不因为轻微风格差异频繁重生成。

### 风险 3：多线策略过度复杂

缓解：初始只支持三类优先级：`primary`、`secondary`、`blocking_style_constraint`。不做任意复杂意图图。

### 风险 4：用户反馈被当成绝对真理

缓解：单次反馈只影响短期适配和质量统计，不自动改长期画像。只有多次一致反馈才考虑进入长期偏好记忆。

### 风险 5：自然度优化压过安全

缓解：`risk_response_policy` 仍然高于声线契约和多线策略。L2/L3 明确存在时，安全底线优先，但表达方式尽量遵守低压和不模板化。

## 后续方向

可信文化知识卡片可以作为第六期或之后的独立专项：先在低风险、常见、版权和来源清晰的范围内建设小型知识卡，而不是在本期混入。第五期应先把“怎么知道自己聊得好不好”和“怎么稳定地像宁语”这两个底座打稳。
