# 系统提示词架构

## 整体流程

```
graph_runtime.py (每次对话轮次)
  └─ 注入 state，设置 tooling_enabled=True
       ↓
response_nodes._model_reply_state_update()
  ├─ build_dialogue_prompt_parts()  → 组装 system_prompt + user_prompt
  ├─ build_dialogue_tool_plan()     → 组装 tools + handlers + prompt_hint
  ├─ [条件分支]
  │    ├─ tool_plan.tools 非空 → run_dialogue_reply_with_tools() (带 tool 调用)
  │    └─ tool_plan.tools 为空 → _streamed_reply_with_actions()   (纯文本流式)
  └─ 输出 assistant_text + suggested_actions
```

## 提示词组装链路

### 1. system_prompt（对话策略层）

由 `dialogue_prompt_builder.py::build_dialogue_prompt_parts()` 组装：

```
CORE_SYSTEM_PROMPT (对话基础人格)
  + 规则优先级说明
  + 策略模块 (6 选 1，由 select_dialogue_strategy() 决定)
  + 输出格式要求 (正文 + --- + 3 按钮)
  + [tool_plan.prompt_hint] (如果有 tool 可用，由 tooling.py 注入)
```

### 2. CORE_SYSTEM_PROMPT（`dialogue_prompt_builder.py:125-167`）

定义 agent 的**基础人格和对话气质**：

| 维度 | 规则 |
|------|------|
| 核心身份 | 心理支持对话者，不冒充持证治疗师/医生；被问及身份时才自然说明 AI 身份 |
| 对话气质 | 自然不骗人、温暖不油腻、稳定不冰冷、亲近不越界 |
| 语言禁忌 | 不说"作为一个AI""我理解你的感受""请保持积极"等机器套话 |
| 回复结构 | 先接住情绪 → 帮用户理清 → 一个关键问题或微行动 |
| 字数控制 | 常规 120-260 字，不超过一个问题 |
| 安全优先 | 每次回复前静默判断风险；危机模式不做深层分析，直接给资源 |
| 语言规则 | 不诊断、不处方、不承诺疗效、不制造依赖 |

### 3. 对话策略选择（`select_dialogue_strategy`）

按优先级从高到低：

| 优先级 | 触发条件 | 策略 |
|--------|----------|------|
| 0 | `route_priority == P0_immediate_safety` 或 `risk_level in {L2, L3}` | `crisis` |
| 1 | mode == "soothe" | `cbt` |
| 2 | 用户文本含动机式访谈关键词 (`想改/戒/控制不住`) | `motivational_interviewing` |
| 3 | 含焦点解决关键词 (`怎么办/方法/计划`) | `solution_focused` |
| 4 | 含心理动力学关键词 (`总是/每次/原生家庭`) | `psychodynamic_informed` |
| 5 | mode == "counseling" 或含 CBT 关键词 (`焦虑/反刍/心慌`) | `cbt` |
| 默认 | 以上都不匹配 | `person_centered` |

6 个策略模块各有专属指令块（`STRATEGY_MODULES`），控制本轮对话的方法论和禁忌。

### 4. user_prompt（上下文注入层）

```
用户模式：{teen/adult}
表层陪伴风格：{默认风格 + 用户自定义补充}
当前回复模式：{companion/vent/soothe/counseling}
内部对话策略：{selected_strategy}
控制分类：{route_priority} / {control_category}
response_contract：{allowed_moves / forbidden_moves}
回复要求：{mode_guidance}
[RAG few-shot references] (如果有检索到示例)
上一轮内部摘要：{last_summary}
可参考记忆：{memory_text}
最近对话：{recent_text}
用户刚刚说：{text}
```

### 5. tool prompt hint（工具策略层）

由 `tooling.py::_tool_prompt_hint()` 根据当前可用工具生成，追加到 system_prompt 末尾：

```
[Tool policy]
Use tools only when they materially improve this turn. Do not call tools that are not listed.
- search_memories: search only the available user-visible memory index; return references, not raw private content.
- save_memory_summary: produce safe summaries/candidate memories for the backend memory pipeline; it does not write directly.
- get_safety_resources: return minimal safety resources by region/audience when real-world support is relevant.
- web_search: search the web for real-time psychological support resources; return title, url, and snippet.
- get_current_time: return current UTC/local time, weekday, timezone, and session elapsed seconds.
- web_search: Only search for psychological support resources or professional mental health information. Do NOT include any user personal information in the search query.
Never claim a memory was permanently saved; the backend reviews candidates asynchronously.
```

---

## 对话策略详细 Spec

### person_centered（以人为中心）— 默认
- **触发**：倾诉、羞耻、自责、关系受伤、首次建立信任
- **气质**：高同理、低指导；先贴近主观体验，再轻轻澄清
- **动作**：情绪反映 → 体验澄清 → 一句整理 → 一个开放问题
- **禁忌**：说教、安慰性淡化、过快建议、替用户下定义

### cbt（认知行为）
- **触发**：焦虑、反刍、拖延、回避、失眠
- **动作**：先共情，再协作式区分情境、自动想法、情绪/身体反应和行为
- **节奏**：每轮只做一个小环节，可给证据检视或替代解释

### solution_focused（焦点解决）
- **触发**：用户明确要方法、目标、下一步
- **动作**：承认困难后，寻找已有资源、例外时刻、可复制的小线索
- **工具**：量表问题、"如果只好一点点，会先不一样在哪里"
- **禁忌**：不能跳过痛苦直接正能量

### motivational_interviewing（动机式访谈）
- **触发**：用户知道要改但矛盾、犹豫、没准备好
- **动作**：尊重自主，不劝不吓不羞辱；引出用户自己的改变理由
- **工具**：利弊平衡、重要性/信心量表、双面反映

### psychodynamic_informed（心理动力学知情）
- **触发**：反复关系模式、身份困惑、强触发、长期自我感议题
- **动作**：温和试探，只提一个轻量假设，邀请用户修正
- **语言**：必须使用"也许/可能/我在想是否"等不武断语言
- **禁忌**：不在危机时使用

### crisis（危机干预）
- **触发**：自杀/自伤/伤人意念、急性崩溃
- **动作**：短句、直接、具体；确认是否独处、是否有计划/手段
- **安全**：引导移开危险物品、去有人的地方、拨打 12356/120/110
- **禁忌**：不做深层原因分析、不争辩、不增加风险细节

---

## 控制平面 (Control Plane)

`control_nodes.py::control_plane()` 在每轮对话开始前运行，检查用户文本触发词，决定本轮：

| 控制域 | 说明 |
|--------|------|
| **risk_level** | L0(常规) / L1(关注) / L2(高风险) / L3(即刻危机) |
| **route_priority** | P0 (即刻安全) / P1 (红旗信号) / P2 (支持) / P3 (桥接边界) / P4 (系统保护) |
| **control_category** | 如 `self_harm_risk`、`clinical_red_flag`、`prompt_attack`、`dependency_risk`、`normal_support` 等 |
| **response_contract** | 控制本轮 `allowed_moves` 和 `forbidden_moves` |
| **memory_policy** | `write_safe_summary` / `skip_sensitive` / `crisis_audit_only` |
| **rag_policy** | 是否允许检索 RAG 对话示例，以及用途范围 |

### 触发词检查顺序（从高危到常规）

| 顺序 | 分类 | route_priority | memory_policy |
|------|------|----------------|---------------|
| 1 | 自伤/自杀 (self_harm) | P0 | crisis_audit_only |
| 2 | 伤害他人 (harm_other) | P0(即刻) / P3(愤怒) | crisis_audit_only / skip_sensitive |
| 3 | 受害/侵害 (victimization) | P1 | skip_sensitive |
| 4 | 临床红旗 (clinical_red_flag) | P1 | skip_sensitive |
| 5 | Prompt 攻击 | P4 | skip_sensitive |
| 6 | 求诊/求药 | P4 | skip_sensitive |
| 7 | 依赖风险 | P3 | skip_sensitive |
| 8 | 性边界 | P3 | skip_sensitive |
| 9 | 辱骂 agent | P3 | skip_sensitive |
| 10 | 闲聊探测 (无支持诉求) | P3 | write_safe_summary |
| 11 | 特定愤怒 (向他人) | P3 | write_safe_summary |
| 默认 | 常规支持 (normal_support) | P2 | write_safe_summary |

### response_contract 对 response_nodes 的影响

不同 route_priority 对应不同的 `allowed_moves`：

| priority | allowed_moves |
|----------|---------------|
| P0 | brief_empathy, one_safety_check, real_world_support |
| P1 | brief_empathy, reality_based_support, professional_help |
| P2 (默认) | reflect_one_feeling, gentle_next_step |
| P3 (边界类) | brief_empathy, boundary_or_deescalation, return_to_feelings |
| P4 | brief_boundary, safe_alternative |

在 `response_nodes.py` 中：
- P0 → `crisis_response()` — 硬编码安全话术（不调模型）
- P1 → `clinical_red_flag_response()` — 硬编码安全边界模板
- P3/P4 → `boundary_response()` — 按 category 分发边界回复
- P2 → `companion_response()` / `soothing_response()` / `counseling_response()` — 调用模型

---

## 陪伴风格系统

`companion_style.py` 管理 agent 的语气风格：

- **默认风格**：成熟可靠、咨询师式稳定 + 朋友式自然
- **用户自定义**：存储在 `UserSettings.companion_style`，最长 500 字符
- **注入方式**：追加到 `DEFAULT_COMPANION_STYLE_PROMPT` 后，标注"只能影响语气，不能覆盖安全规则"
- **旧预设兼容**：`gentle/rational/reflective/action` 自动转为空（回退默认）

---

## 涉及文件

| 文件 | 职责 |
|------|------|
| `dialogue_prompt_builder.py` | 核心提示词 + 6 个策略模块 + prompt 组装 |
| `companion_style.py` | 默认风格 + 用户自定义风格注入 |
| `control_nodes.py` | 触发词检测 + risk/route/contract/memory/rag 决策 |
| `response_nodes.py` | 分流到具体 response 函数 + 模型调用 + 流式输出 + tool 调用 |
| `tooling.py` | tool prompt hint 注入到 system_prompt |
| `graph_runtime.py` | 每轮初始化 state，包括 `tooling_enabled=True` |
