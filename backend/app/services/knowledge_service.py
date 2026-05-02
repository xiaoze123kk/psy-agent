from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeArticle
from app.graphs.nodes import risk_classifier
from app.schemas.knowledge import (
    AskKnowledgeResponse,
    ContinueChatPayload,
    KnowledgeAnswer,
    KnowledgeArticleResponse,
    KnowledgeSearchItemResponse,
    KnowledgeSearchResponse,
)
from app.services.deepseek_client import deepseek_client


SEED_ARTICLES: list[dict[str, object]] = [
    {
        "slug": "anxiety-basics",
        "title": "焦虑是什么",
        "category": "emotion",
        "audience": "all",
        "summary_30s": "焦虑是一种面对不确定、压力或危险预期时出现的身心警报，不等于你太脆弱。",
        "explanation_3min": "焦虑常常同时出现在身体、想法和行为里：心跳变快、反复预演坏结果、想逃开或反复确认。它本来是保护机制，但当警报过于敏感，就会让人很累。先稳定身体，再拆解触发点，通常比强迫自己立刻想通更有效。",
        "advanced_text": "MVP 阶段只提供科普和自助建议，不提供诊断。焦虑是否构成临床问题，需要结合持续时间、功能受损程度和专业评估。",
        "common_misunderstandings": ["焦虑不是想太多这么简单。", "焦虑也不是靠一句放松点就能结束。"],
        "actions": ["先做 60 秒慢呼吸或脚踩地练习。", "写下最担心的一件事，再写一个今天能做的最小动作。"],
        "seek_help_when": ["焦虑持续影响睡眠、学习或工作。", "出现自伤想法、强烈失控感或现实安全风险。"],
        "tags": ["焦虑", "心慌", "压力", "自助"],
    },
    {
        "slug": "anxious-attachment",
        "title": "什么是焦虑依恋",
        "category": "relationship",
        "audience": "all",
        "summary_30s": "焦虑依恋是关系里对失去、冷淡和不确定特别敏感的一种模式，不等于你爱得太多。",
        "explanation_3min": "焦虑依恋常表现为很在意对方回应、容易反复确认、对消息延迟或语气变化高度敏感。它背后通常是安全感被外部回应强烈牵动。调整时不是逼自己不在乎，而是学习把感受说清楚、延迟冲动确认，并建立关系外的稳定支点。",
        "advanced_text": "依恋风格是理解关系反应的工具，不是固定标签。一个人在不同关系和阶段里也可能呈现不同状态。",
        "common_misunderstandings": ["焦虑依恋不是矫情。", "它也不代表这段关系一定有问题。"],
        "actions": ["先把想确认的话写下来，等 10 分钟再决定是否发送。", "用我现在感到不安，因为我需要更清楚的回应来表达，而不是指责。"],
        "seek_help_when": ["关系焦虑反复导致失眠、失控争吵或自我伤害冲动。", "你感觉自己很难离开伤害性关系。"],
        "tags": ["焦虑依恋", "亲密关系", "安全感", "边界"],
    },
    {
        "slug": "low-mood-vs-depression",
        "title": "低落和抑郁有什么区别",
        "category": "emotion",
        "audience": "all",
        "summary_30s": "低落是一种常见情绪状态，抑郁障碍则需要专业评估，不能靠一次测试或聊天下结论。",
        "explanation_3min": "低落可能来自压力、关系受挫、疲惫或失望，通常会随情境变化而波动。需要警惕的是：低落持续较久、兴趣明显下降、睡眠食欲明显改变、学习工作功能受损，或出现自伤自杀想法。此时更适合联系现实支持和专业帮助。",
        "advanced_text": "产品只能提供情绪识别、自助支持和求助建议，不做临床诊断。",
        "common_misunderstandings": ["难过不等于抑郁症。", "抑郁也不是意志力差。"],
        "actions": ["把今天必须完成的事缩到一件最小任务。", "联系一个可信任的人，说清楚我最近状态不太好。"],
        "seek_help_when": ["低落持续两周以上并影响日常功能。", "出现不想活、自伤计划或明显安全风险。"],
        "tags": ["低落", "抑郁情绪", "求助", "风险"],
    },
    {
        "slug": "sleep-rumination",
        "title": "睡前脑子停不下来怎么办",
        "category": "sleep",
        "audience": "all",
        "summary_30s": "睡前反复想事情常见于压力未收束时，目标不是立刻想通，而是降低大脑唤醒。",
        "explanation_3min": "越努力逼自己睡着，身体越可能紧绷。可以先把问题从脑内搬到纸上：写下担心、明天可做的一步、暂时不处理的部分。睡前更适合重复、低刺激、可预测的动作，比如呼吸、身体扫描或轻声记录，而不是深度复盘人生问题。",
        "advanced_text": "长期失眠需要结合作息、压力源、躯体状态和专业建议综合处理。",
        "common_misunderstandings": ["睡不着不是因为你不够自律。", "深夜不适合做重大关系或人生决策。"],
        "actions": ["写一个明天再处理清单。", "做 4 秒吸气、6 秒呼气，重复 5 轮。"],
        "seek_help_when": ["失眠持续影响白天功能。", "伴随强烈绝望、自伤想法或惊恐发作。"],
        "tags": ["失眠", "反刍", "睡前", "焦虑"],
    },
    {
        "slug": "grounding-60-seconds",
        "title": "60 秒稳定练习",
        "category": "self_help",
        "audience": "all",
        "summary_30s": "稳定练习的目的不是解决所有问题，而是先把注意力从失控感拉回当下。",
        "explanation_3min": "当焦虑或崩溃感很强时，大脑会把很多可能性当作正在发生的危险。你可以先用身体做锚点：双脚踩地，感受椅子支撑，说出眼前 5 个看得到的东西、4 个摸得到的东西、3 个听得到的声音。身体稳定一点后，再处理问题。",
        "advanced_text": "Grounding 是常见自助稳定技巧，但不能替代紧急危机干预。",
        "common_misunderstandings": ["稳定练习不是假装没事。", "一次没效果不代表你做错了。"],
        "actions": ["双脚踩地，慢慢呼气。", "按 5-4-3-2-1 顺序描述当下感官。"],
        "seek_help_when": ["你已经无法保证自己安全。", "强烈惊恐或解离感反复出现。"],
        "tags": ["稳定练习", "grounding", "急救", "焦虑"],
    },
    {
        "slug": "boundaries",
        "title": "边界感是什么",
        "category": "relationship",
        "audience": "all",
        "summary_30s": "边界感是知道什么属于我、什么属于别人，并用清楚但不攻击的方式表达。",
        "explanation_3min": "边界不是冷漠，也不是拒绝所有人。它更像关系里的说明书：我能接受什么、不能接受什么、我愿意承担哪部分、不替别人承担哪部分。边界越清楚，关系反而越不容易靠猜测和委屈维持。",
        "advanced_text": "边界练习需要结合安全环境；在控制或暴力关系中，优先考虑现实安全。",
        "common_misunderstandings": ["设边界不是自私。", "边界不是用来惩罚对方。"],
        "actions": ["用我能/我不能/我需要来表达。", "先从一个低风险小边界开始练习。"],
        "seek_help_when": ["设边界会引发现实危险。", "你长期处在被控制、威胁或伤害的关系里。"],
        "tags": ["边界", "关系", "沟通", "自我保护"],
    },
    {
        "slug": "teen-exam-stress",
        "title": "考试压力很大时怎么办",
        "category": "teen",
        "audience": "teen",
        "summary_30s": "考试压力大不代表你不行，先把任务拆小，再找一个现实中的支持点。",
        "explanation_3min": "考试前容易把一次结果想成对自己的全部评价。可以先分清三件事：必须复习的最小范围、现在最影响你的情绪、可以求助的人。青少年模式下，如果你已经很崩溃或不安全，优先联系家长、老师、班主任或学校心理老师。",
        "advanced_text": "学习压力支持不能替代学校、家庭和专业资源。",
        "common_misunderstandings": ["一次考试不能定义你整个人。", "求助不是给别人添麻烦。"],
        "actions": ["列出今天只复习 25 分钟的一小块内容。", "告诉一个可信任的大人：我最近压力有点扛不住。"],
        "seek_help_when": ["压力让你睡不着、吃不下或想伤害自己。", "你觉得自己已经不安全。"],
        "tags": ["青少年", "考试", "学业压力", "求助"],
    },
    {
        "slug": "when-to-seek-help",
        "title": "什么时候需要找现实帮助",
        "category": "safety",
        "audience": "all",
        "summary_30s": "当痛苦已经超过自助能承受的范围，找现实帮助是更安全的选择。",
        "explanation_3min": "如果你出现明确自伤自杀想法、已经准备工具或计划、无法保证自己安全，应该立刻联系身边可信任的人或当地紧急服务。即使没有紧急风险，只要情绪长期影响睡眠、学习、工作或关系，也值得联系专业支持。",
        "advanced_text": "AI 可以陪你整理和稳定，但不能替代紧急救援、医生、心理咨询师或学校心理老师。",
        "common_misunderstandings": ["求助不是失败。", "等完全撑不住才求助会让风险变高。"],
        "actions": ["现在联系一个可信任的人。", "如果已经有立即危险，拨打当地紧急电话。"],
        "seek_help_when": ["出现自伤自杀计划或冲动。", "痛苦持续影响日常功能。"],
        "tags": ["安全", "求助", "危机", "现实支持"],
    },
]


SEED_ARTICLES.extend(
    [
        {
            "slug": "panic-attack-basics",
            "title": "惊恐发作时身体发生了什么",
            "category": "emotion",
            "audience": "all",
            "summary_30s": "惊恐发作像身体突然拉响强警报，心跳、呼吸和眩晕会很吓人，但它本身不等于马上会失控或死亡。",
            "explanation_3min": "惊恐发作常见表现包括心跳很快、胸闷、手麻、发抖、出汗、濒死感或失控感。它通常是身体的威胁系统被强烈激活，越害怕这些身体感觉，警报越容易被放大。先把注意力放回呼气、脚底和眼前环境，等峰值过去后再复盘诱因。频繁发作或伴随回避时，适合寻求专业评估。",
            "advanced_text": "胸痛、晕厥、呼吸困难等症状也可能涉及身体疾病；第一次出现或症状异常时应优先排除医学风险。",
            "common_misunderstandings": ["惊恐发作不是装出来的。", "让自己立刻不害怕通常会加重紧张。"],
            "actions": ["把呼气拉长到 6 秒，重复 5 轮。", "说出眼前 5 个看得到的物品，提醒自己正在这里。", "记录发作前的压力、咖啡因、睡眠和场景。"],
            "seek_help_when": ["惊恐反复出现并让你开始回避出门、上课或工作。", "症状像心脏或呼吸急症，或你无法判断安全性。"],
            "tags": ["惊恐发作", "心慌", "呼吸", "身体警报"],
        },
        {
            "slug": "cognitive-distortions",
            "title": "常见认知偏差有哪些",
            "category": "self_help",
            "audience": "all",
            "summary_30s": "认知偏差是压力下大脑快速下结论的习惯，比如灾难化、读心术、非黑即白。",
            "explanation_3min": "人在焦虑或低落时更容易把可能性当成事实。常见模式包括：把一次失误看成全部失败，默认别人一定讨厌自己，只看坏证据，或把未来想成最糟。识别认知偏差不是否定感受，而是给大脑一点空间：我现在有什么证据？有没有另一个解释？如果朋友遇到同样的事，我会怎么说？",
            "advanced_text": "认知重评是 CBT 常见技术之一，但严重痛苦或创伤反应需要更完整的专业支持。",
            "common_misunderstandings": ["识别偏差不是强行积极。", "想法不等于事实，但感受仍然值得被认真对待。"],
            "actions": ["写下最强烈的自动想法。", "列出支持和不支持它的证据各 2 条。", "换成一句更平衡的说法。"],
            "seek_help_when": ["负面想法持续影响睡眠、学习、工作或关系。", "出现自我伤害、绝望或强烈失控感。"],
            "tags": ["CBT", "认知偏差", "灾难化", "自动想法"],
        },
        {
            "slug": "rumination-loop",
            "title": "反刍思维停不下来怎么办",
            "category": "emotion",
            "audience": "all",
            "summary_30s": "反刍是大脑反复咀嚼同一件事，却很少真正解决问题的一种循环。",
            "explanation_3min": "反刍常披着复盘的外衣，但它会让问题越想越大、情绪越陷越深。可以先判断：我是在产生一个下一步，还是只是在重复责备自己？如果是后者，先把思考延期到固定时间，做一个身体动作切换状态，再写下一个最小可执行步骤。",
            "advanced_text": "长期反刍常与焦虑、抑郁情绪、完美主义和压力事件有关。",
            "common_misunderstandings": ["反复想不代表你更负责。", "停止反刍不是逃避问题。"],
            "actions": ["设一个 15 分钟担忧时段，其他时间先写下来稍后处理。", "站起来喝水、洗脸或走 3 分钟。", "把问题改写成一个可行动问题。"],
            "seek_help_when": ["反刍让你长期失眠、注意力下降或明显痛苦。", "内容涉及创伤、羞耻或安全风险。"],
            "tags": ["反刍", "内耗", "焦虑", "复盘"],
        },
        {
            "slug": "social-anxiety",
            "title": "社交焦虑和害羞有什么不同",
            "category": "relationship",
            "audience": "all",
            "summary_30s": "害羞是慢热，社交焦虑更像害怕被评价、出丑或被否定，并因此回避重要场景。",
            "explanation_3min": "社交焦虑常让人提前很多天担心、现场高度监控自己、结束后反复回放细节。调整时不需要一下子变外向，而是逐步练习低风险暴露：短暂发言、主动问一个问题、允许自己有一点紧张。目标不是完全不紧张，而是带着紧张也能完成重要行动。",
            "advanced_text": "如果回避严重影响学业、工作或关系，可以考虑专业评估和循序渐进的暴露训练。",
            "common_misunderstandings": ["社交焦虑不是性格差。", "练习社交不等于逼自己讨好所有人。"],
            "actions": ["选一个 20% 难度的小社交动作。", "提前写一句开场白。", "结束后只记录事实，不做羞辱式复盘。"],
            "seek_help_when": ["你开始长期逃避上课、会议、面试或必要沟通。", "社交后出现强烈自责、绝望或自伤想法。"],
            "tags": ["社交焦虑", "害羞", "评价恐惧", "暴露练习"],
        },
        {
            "slug": "burnout-signs",
            "title": "心理耗竭有哪些信号",
            "category": "stress",
            "audience": "all",
            "summary_30s": "耗竭不只是累，通常还包括麻木、效率下降、易怒、睡不恢复和对事情失去意义感。",
            "explanation_3min": "长期压力下，身体和心理会从硬撑进入保护性关机。你可能发现自己休息了也不恢复，对以前在意的事没感觉，或者小事也很容易爆炸。第一步不是再加自律，而是减少负荷、恢复睡眠和边界，重新区分必须做、可以推迟、可以求助的事。",
            "advanced_text": "耗竭和抑郁症状可能重叠；持续低落、兴趣显著下降或自伤想法需要专业帮助。",
            "common_misunderstandings": ["耗竭不是懒。", "短暂娱乐不一定等于真正恢复。"],
            "actions": ["列出本周可以降低 20% 的一项负荷。", "固定一个不处理任务的恢复窗口。", "向一个现实中的人说明你需要支持。"],
            "seek_help_when": ["耗竭持续影响工作、学习、关系或身体健康。", "你出现明显绝望、麻木或不想活的想法。"],
            "tags": ["耗竭", "压力", "倦怠", "恢复"],
        },
        {
            "slug": "perfectionism",
            "title": "完美主义为什么会让人拖住",
            "category": "self_help",
            "audience": "all",
            "summary_30s": "完美主义常把开始变得很难，因为大脑把不够好等同于危险或失败。",
            "explanation_3min": "完美主义不只是追求高标准，也可能包含对犯错的强烈恐惧。越想一次做完美，越容易拖延、反复修改、无法交付。可以把目标改成先完成一个可被改进的版本，明确什么叫够用，并允许自己用迭代代替一次到位。",
            "advanced_text": "完美主义可能与焦虑、自我价值感和早期评价经验有关。",
            "common_misunderstandings": ["降低第一版标准不代表放弃质量。", "完美主义不总是高效的优点。"],
            "actions": ["给任务定义一个 60 分及格版本。", "设定停止修改的时间点。", "先交付最小版本，再收反馈。"],
            "seek_help_when": ["你长期因为怕不完美而无法学习、工作或表达。", "失败感引发强烈自责或伤害自己的冲动。"],
            "tags": ["完美主义", "拖延", "自我要求", "行动"],
        },
        {
            "slug": "loneliness",
            "title": "孤独感很强时可以怎么做",
            "category": "relationship",
            "audience": "all",
            "summary_30s": "孤独不只是身边有没有人，也和是否被理解、被回应、能真实表达有关。",
            "explanation_3min": "孤独感很强时，人容易把没有回应理解成自己不值得。可以先承认需要连接是正常的，再选择一个低风险连接动作：给熟人发一句近况、参加固定场景、或把想说的话先写出来。连接不一定从深聊开始，稳定重复的小接触也能慢慢恢复安全感。",
            "advanced_text": "长期孤独会加重压力和低落，现实支持网络很重要。",
            "common_misunderstandings": ["孤独不是矫情。", "拥有很多联系人不等于没有孤独。"],
            "actions": ["给一个可信任的人发一句具体近况。", "安排一次低压力线下活动。", "把想被理解的部分写成三句话。"],
            "seek_help_when": ["孤独伴随持续低落、绝望或不想活。", "你长期失去现实连接并难以恢复日常功能。"],
            "tags": ["孤独", "连接", "关系", "支持"],
        },
        {
            "slug": "self-compassion",
            "title": "自我关怀不是纵容自己",
            "category": "self_help",
            "audience": "all",
            "summary_30s": "自我关怀是用更不伤人的方式面对困难，让自己更有力气修正和行动。",
            "explanation_3min": "很多人以为只有骂自己才会进步，但长期羞辱会消耗行动力。自我关怀不是说一切都没关系，而是承认这很难、我不是唯一会这样的人、我可以从一个小步骤开始。它把自责换成责任，把惩罚换成修复。",
            "advanced_text": "自我关怀训练常用于降低羞耻、焦虑和自我批评。",
            "common_misunderstandings": ["对自己温和不等于给错误找借口。", "自我关怀也可以包含承担责任。"],
            "actions": ["把骂自己的话改写成对朋友会说的话。", "问自己现在最需要的一点支持是什么。", "选一个修复性小行动。"],
            "seek_help_when": ["自我攻击强到难以停止。", "自责伴随自伤冲动、绝望或严重功能受损。"],
            "tags": ["自我关怀", "自责", "羞耻", "修复"],
        },
        {
            "slug": "family-communication",
            "title": "和家人沟通总是吵起来怎么办",
            "category": "relationship",
            "audience": "all",
            "summary_30s": "家人沟通容易吵起来时，先降低当场升级，再选择更清楚、更短的表达。",
            "explanation_3min": "亲近关系里，旧模式很容易被触发。你可以先识别升级信号：音量变大、开始翻旧账、想证明谁对谁错。暂停不是认输，而是保护沟通窗口。重新开口时，用我感到、我希望、我现在能做什么来表达，比你总是、你从来更不容易引发防御。",
            "advanced_text": "如果关系中存在暴力、威胁或控制，沟通技巧不是首要任务，安全计划更重要。",
            "common_misunderstandings": ["暂停争吵不是逃避。", "表达感受不等于要求对方立刻改变。"],
            "actions": ["在升级前说：我需要先停 10 分钟。", "一次只谈一个具体事件。", "把要求改成可执行的小请求。"],
            "seek_help_when": ["沟通会引发人身威胁、暴力或严重控制。", "家庭冲突让你持续恐惧、失眠或想伤害自己。"],
            "tags": ["家庭", "沟通", "冲突", "边界"],
        },
        {
            "slug": "teen-online-conflict",
            "title": "青少年遇到网络冲突怎么办",
            "category": "teen",
            "audience": "teen",
            "summary_30s": "网络冲突会让人很难受，先保护证据和安全，再找可信任的大人一起处理。",
            "explanation_3min": "被群嘲、造谣、排挤或威胁时，不要急着一个人硬扛或马上反击。先截图保存证据，减少继续暴露，屏蔽或举报明显攻击内容。更重要的是告诉现实中的可信任成年人，比如家长、老师、班主任或学校心理老师。青少年模式下，现实保护优先于独自解决。",
            "advanced_text": "网络欺凌可能涉及学校纪律、平台规则甚至法律风险，必要时需要成年人介入。",
            "common_misunderstandings": ["被攻击不是你的错。", "求助不是告状。"],
            "actions": ["截图保存时间、账号和内容。", "先停止继续争辩，保护自己。", "联系一个可信任的大人。"],
            "seek_help_when": ["出现威胁、人肉、勒索或现实安全风险。", "你因此想伤害自己或不敢上学。"],
            "tags": ["青少年", "网络冲突", "霸凌", "安全"],
        },
        {
            "slug": "grief-basics",
            "title": "失去之后为什么会反复难过",
            "category": "emotion",
            "audience": "all",
            "summary_30s": "哀伤不是线性恢复，想起、难过、麻木、愤怒和怀念可能会反复出现。",
            "explanation_3min": "重要失去之后，大脑和生活都需要重新适应。你可能一会儿很平静，一会儿又被某个场景击中，这并不说明你退步了。可以给哀伤留出位置：允许纪念、说出想念、保持基本作息，并在特别难的日子提前安排支持。",
            "advanced_text": "如果哀伤长期严重影响功能，或伴随强烈自责、创伤画面、自伤想法，需要专业支持。",
            "common_misunderstandings": ["不哭不代表不在乎。", "重新生活不等于背叛失去的人或事。"],
            "actions": ["写一段想对失去对象说的话。", "把今天必须完成的事降到最低。", "提前联系一个能陪你的人。"],
            "seek_help_when": ["痛苦持续强烈到无法维持基本生活。", "出现自伤、自杀想法或强烈创伤反应。"],
            "tags": ["哀伤", "失去", "低落", "支持"],
        },
        {
            "slug": "mindfulness-basics",
            "title": "正念练习适合什么时候用",
            "category": "self_help",
            "audience": "all",
            "summary_30s": "正念不是清空大脑，而是练习注意到此刻发生了什么，并少一点被念头拖走。",
            "explanation_3min": "正念可以用于焦虑、反刍、冲动或压力很高的时候。做法可以很简单：注意一次呼吸、脚底触地、杯子的温度，或者当前正在出现的念头。目标不是让念头消失，而是发现我正在有这个念头，然后把注意力带回当下。",
            "advanced_text": "有创伤史或解离体验的人做正念时可能不舒服，可以从外部感官和短时间练习开始。",
            "common_misunderstandings": ["正念不是必须放空。", "走神不是失败，发现走神本身就是练习。"],
            "actions": ["用 30 秒感受脚底接触地面。", "给当前情绪命名：我注意到焦虑来了。", "把注意力放回一个外部物体。"],
            "seek_help_when": ["练习引发强烈恐惧、解离或创伤画面。", "你无法保证自己的现实安全。"],
            "tags": ["正念", "当下", "情绪调节", "反刍"],
        },
    ]
)


def ensure_seed_articles(db: Session) -> None:
    changed = False
    for payload in SEED_ARTICLES:
        slug = str(payload["slug"])
        article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.slug == slug))
        if article is None:
            article = KnowledgeArticle(**payload)
            db.add(article)
            changed = True
            continue

        for key, value in payload.items():
            if getattr(article, key) != value:
                setattr(article, key, value)
                changed = True

    if changed:
        db.commit()


def article_to_search_item(article: KnowledgeArticle) -> KnowledgeSearchItemResponse:
    return KnowledgeSearchItemResponse(
        article_id=article.id,
        slug=article.slug,
        title=article.title,
        category=article.category,
        audience=article.audience,
        summary_30s=article.summary_30s,
        tags=list(article.tags or []),
    )


def article_to_detail(article: KnowledgeArticle) -> KnowledgeArticleResponse:
    return KnowledgeArticleResponse(
        article_id=article.id,
        slug=article.slug,
        title=article.title,
        category=article.category,
        audience=article.audience,
        summary_30s=article.summary_30s,
        explanation_3min=article.explanation_3min,
        advanced_text=article.advanced_text,
        common_misunderstandings=list(article.common_misunderstandings or []),
        actions=list(article.actions or []),
        seek_help_when=list(article.seek_help_when or []),
        source_refs=list(article.source_refs or []),
        tags=list(article.tags or []),
        updated_at=article.updated_at,
    )


def _article_blob(article: KnowledgeArticle) -> str:
    parts = [
        article.title,
        article.category,
        article.summary_30s,
        article.explanation_3min,
        article.advanced_text or "",
        " ".join(article.tags or []),
    ]
    return " ".join(parts).lower()


def _score_article(article: KnowledgeArticle, query: str) -> int:
    normalized_query = query.strip().lower()
    if not normalized_query:
        return 1

    score = 0
    article_title = article.title.lower()
    article_tags = [tag.lower() for tag in article.tags or []]
    article_category = article.category.lower()
    article_summary = article.summary_30s.lower()
    article_explanation = article.explanation_3min.lower()

    if normalized_query in article_title:
        score += 50
    if any(tag and normalized_query in tag for tag in article_tags):
        score += 35
    if normalized_query in article_category:
        score += 20
    if normalized_query in article_summary:
        score += 15
    if normalized_query in article_explanation:
        score += 8

    for phrase in [article_title, *article_tags]:
        if phrase and phrase in normalized_query:
            score += 28

    query_terms = [token for token in normalized_query.split() if token]
    if not query_terms:
        query_terms = [tag for tag in article_tags if tag and tag in normalized_query]

    for token in query_terms:
        if token and token in _article_blob(article):
            score += 4

    query_chars = {char for char in normalized_query if "\u4e00" <= char <= "\u9fff"}
    if query_chars:
        article_chars = {char for char in _article_blob(article) if "\u4e00" <= char <= "\u9fff"}
        score += min(len(query_chars & article_chars), 12)

    return score


def search_articles(
    db: Session,
    *,
    query: str = "",
    category: str | None = None,
    audience: str | None = None,
    limit: int = 8,
) -> KnowledgeSearchResponse:
    ensure_seed_articles(db)
    articles = list(db.scalars(select(KnowledgeArticle).where(KnowledgeArticle.status == "published")))

    filtered = []
    for article in articles:
        if category and article.category != category:
            continue
        if audience and article.audience not in {"all", audience}:
            continue
        score = _score_article(article, query)
        if score > 0:
            filtered.append((score, article))

    filtered.sort(key=lambda item: (-item[0], item[1].title))
    return KnowledgeSearchResponse(items=[article_to_search_item(article) for _, article in filtered[:limit]])


def get_article(db: Session, article_id: str) -> KnowledgeArticle | None:
    ensure_seed_articles(db)
    filters = [KnowledgeArticle.slug == article_id]
    try:
        UUID(article_id)
    except ValueError:
        pass
    else:
        filters.append(KnowledgeArticle.id == article_id)

    return db.scalar(
        select(KnowledgeArticle).where(
            KnowledgeArticle.status == "published",
            or_(*filters),
        )
    )


def _article_context(article: KnowledgeArticle, index: int) -> str:
    actions = "；".join(list(article.actions or [])[:3])
    seek_help = "；".join(list(article.seek_help_when or [])[:3])
    misunderstandings = "；".join(list(article.common_misunderstandings or [])[:2])
    return (
        f"[{index}] 标题：{article.title}\n"
        f"分类：{article.category}；适用人群：{article.audience}\n"
        f"30秒摘要：{article.summary_30s}\n"
        f"解释：{article.explanation_3min}\n"
        f"常见误区：{misunderstandings or '无'}\n"
        f"可做行动：{actions or '无'}\n"
        f"何时求助：{seek_help or '无'}"
    )


def _fallback_answer(article: KnowledgeArticle, *, use_my_context: bool) -> KnowledgeAnswer:
    context_tail = " 如果这和你自己的近况有关，可以把具体场景带回对话里继续拆小。" if use_my_context else ""
    return KnowledgeAnswer(
        summary_30s=article.summary_30s,
        explanation_3min=f"{article.explanation_3min}{context_tail}",
        actions=list(article.actions or [])[:3],
        seek_help_when=list(article.seek_help_when or [])[:3],
    )


def _json_from_model(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _string_list(value: object, *, fallback: list[str], limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return fallback[:limit]

    items = [str(item).strip() for item in value if str(item).strip()]
    return (items or fallback)[:limit]


def _answer_from_model_payload(payload: dict, fallback: KnowledgeAnswer) -> KnowledgeAnswer | None:
    summary = str(payload.get("summary_30s", "")).strip()
    explanation = str(payload.get("explanation_3min", "")).strip()
    if not summary or not explanation:
        return None

    return KnowledgeAnswer(
        summary_30s=summary[:260],
        explanation_3min=explanation[:900],
        actions=_string_list(payload.get("actions"), fallback=fallback.actions, limit=4),
        seek_help_when=_string_list(payload.get("seek_help_when"), fallback=fallback.seek_help_when, limit=4),
    )


async def _generate_knowledge_answer(
    *,
    question: str,
    articles: list[KnowledgeArticle],
    use_my_context: bool,
) -> KnowledgeAnswer | None:
    if not articles:
        return None

    fallback = _fallback_answer(articles[0], use_my_context=use_my_context)
    if not deepseek_client.is_configured:
        return fallback

    source_context = "\n\n".join(_article_context(article, index + 1) for index, article in enumerate(articles[:4]))
    context_note = "可以轻微承接用户近况，但不要假装知道未提供的个人信息。" if use_my_context else "不要引用用户个人近况。"
    system_prompt = (
        "你是心理健康知识问答 agent，负责把已检索到的知识库内容组织成清楚、温和、可执行的回答。"
        "你不是医生或心理咨询师，不做诊断，不承诺疗效，不编造知识库以外的事实。"
        "如果问题超出资料范围，要说明只能基于现有资料回答，并引导用户换更具体的问题。"
        "用简体中文，语气稳定、克制，避免说教。只输出 JSON，不要 Markdown。"
    )
    user_prompt = (
        f"用户问题：{question}\n"
        f"上下文要求：{context_note}\n\n"
        f"可用知识库资料：\n{source_context}\n\n"
        "请输出 JSON，字段如下：\n"
        "{\n"
        '  "summary_30s": "用 1-2 句话直接回答",\n'
        '  "explanation_3min": "用 1 段解释原因、机制和边界，120-260 字",\n'
        '  "actions": ["2-4 个安全、具体、轻量的行动"],\n'
        '  "seek_help_when": ["2-4 个需要现实或专业帮助的信号"]\n'
        "}"
    )

    reply = await deepseek_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.35,
        max_tokens=760,
    )
    if not reply:
        return fallback

    payload = _json_from_model(reply)
    if payload is None:
        return fallback

    return _answer_from_model_payload(payload, fallback) or fallback


async def ask_knowledge(
    db: Session,
    *,
    question: str,
    use_my_context: bool,
    thread_id: str | None,
) -> AskKnowledgeResponse:
    risk_result = await risk_classifier({"normalized_text": question})
    risk_level = str(risk_result.get("risk_level", "L0"))
    if risk_level in {"L2", "L3"}:
        return AskKnowledgeResponse(
            answer=KnowledgeAnswer(
                summary_30s="你现在的安全比解释知识更重要。先暂停普通知识问答，优先联系现实中的人。",
                explanation_3min=(
                    "如果你已经有伤害自己的计划、工具或冲动，请立刻去有人的地方，"
                    "联系可信任的人，或拨打当地紧急电话。AI 可以陪你整理，但不能替代紧急帮助。"
                ),
                actions=["联系可信任的人", "远离危险物品", "打开 SOS 页面", "必要时拨打 120 或 110"],
                seek_help_when=["已经无法保证自己安全", "有明确自伤或自杀计划", "痛苦强到快控制不住"],
            ),
            related_articles=[],
            continue_chat_payload=ContinueChatPayload(
                mode="crisis",
                context_type="safety_escalation",
                thread_id=thread_id,
            ),
            risk_level=risk_level,
        )

    related = search_articles(db, query=question, limit=4).items
    if not related:
        related = search_articles(db, query="", limit=4).items

    articles = [article for item in related if (article := get_article(db, item.article_id)) is not None]
    if not articles:
        return AskKnowledgeResponse(
            answer=KnowledgeAnswer(
                summary_30s="暂时没有匹配到足够可靠的知识条目。",
                explanation_3min="MVP 知识库只回答已收录主题。你可以换一个更具体的问题，或回到对话里先描述你的情况。",
                actions=["换一个关键词搜索", "回到对话里继续说具体场景"],
                seek_help_when=["问题涉及现实安全、伤害风险或持续功能受损"],
            ),
            related_articles=[],
            continue_chat_payload=ContinueChatPayload(mode="knowledge", context_type="knowledge_fallback", thread_id=thread_id),
            risk_level=risk_level,
        )

    answer = await _generate_knowledge_answer(
        question=question,
        articles=articles,
        use_my_context=use_my_context,
    )
    return AskKnowledgeResponse(
        answer=answer or _fallback_answer(articles[0], use_my_context=use_my_context),
        related_articles=related,
        continue_chat_payload=ContinueChatPayload(
            mode="knowledge",
            context_type="knowledge_article",
            article_id=articles[0].id,
            thread_id=thread_id,
        ),
        risk_level=risk_level,
    )
