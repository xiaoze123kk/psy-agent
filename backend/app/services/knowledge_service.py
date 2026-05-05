from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from threading import Lock
from uuid import UUID

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.models import KnowledgeArticle, KnowledgeChunk, KnowledgeGap, KnowledgeSource, utcnow
from app.graphs.nodes import risk_classifier, sync_risk_classify
from app.schemas.knowledge import (
    AskKnowledgeResponse,
    ContinueChatPayload,
    KnowledgeAnswer,
    KnowledgeArticleResponse,
    KnowledgeGapItemResponse,
    KnowledgeGapListResponse,
    KnowledgeGapMutationResponse,
    KnowledgeQuestionSuggestion,
    KnowledgeSearchItemResponse,
    KnowledgeSearchResponse,
    KnowledgeSourceRefResponse,
)
from app.services.deepseek_client import deepseek_client
from app.services.embedding_service import embedding_client
from app.services.knowledge_taxonomy import (
    ExpandedKnowledgeQuery,
    KnowledgeScopeStatus,
    OUT_OF_SCOPE_TERMS,
    SEXUAL_KNOWLEDGE_TERMS,
    apply_known_typo_corrections,
    classify_knowledge_scope,
    contains_any,
    expand_knowledge_query,
    normalize_knowledge_text,
)
from app.services.knowledge_seed_expansion import EXPANDED_SEED_ARTICLES
from app.services.milvus_service import milvus_store


@dataclass(frozen=True)
class ChunkHit:
    article: KnowledgeArticle
    chunk: KnowledgeChunk
    score: int


@dataclass(frozen=True)
class GeneratedKnowledgeAnswer:
    answer: KnowledgeAnswer
    scope_status: KnowledgeScopeStatus = "in_scope"


@dataclass(frozen=True)
class QuestionGuess:
    guessed_question: str
    matched_term: str
    confidence: str


SEED_SOURCES: list[dict[str, object]] = [
    {
        "source_key": "internal_curated",
        "name": "内部审核心理知识种子库",
        "base_url": "local://internal-curated",
        "terms_url": None,
        "license": "internal-curated",
        "language": "zh-CN",
        "is_commercial_allowed": True,
    },
    {
        "source_key": "nimh_public_domain",
        "name": "National Institute of Mental Health",
        "base_url": "https://www.nimh.nih.gov/health/publications",
        "terms_url": "https://www.nimh.nih.gov/site-info/policies",
        "license": "public-domain-text",
        "language": "en",
        "is_commercial_allowed": True,
    },
    {
        "source_key": "medlineplus_public_domain",
        "name": "MedlinePlus Health Topic Summaries",
        "base_url": "https://medlineplus.gov/mentalhealthandbehavior.html",
        "terms_url": "https://medlineplus.gov/about/using/usingcontent/",
        "license": "public-domain-health-topic-summaries",
        "language": "en",
        "is_commercial_allowed": True,
    },
    {
        "source_key": "childmind_mhdb",
        "name": "Child Mind Institute MHDB",
        "base_url": "https://matter.childmind.org/mhdb.html",
        "terms_url": "https://creativecommons.org/licenses/by/4.0/",
        "license": "CC BY 4.0",
        "language": "en",
        "is_commercial_allowed": True,
    },
]


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
            "slug": "ptsd-basics",
            "title": "PTSD 是什么",
            "category": "emotion",
            "audience": "all",
            "summary_30s": "PTSD 通常指创伤后应激障碍，是人在经历或目睹严重威胁事件后，身心警报长期难以恢复的一类反应。",
            "explanation_3min": "PTSD 可能表现为反复闯入的画面或噩梦、回避相关地点和话题、持续紧绷警觉、容易被惊吓，以及对自己或世界产生很负面的看法。不是每个经历创伤的人都会发展成 PTSD，也不能只凭一个症状自我诊断。如果这些反应持续影响睡眠、学习、工作或关系，更适合找心理咨询师、精神科医生或创伤知情的专业人员评估和支持。",
            "advanced_text": "知识问答只做心理健康科普，不提供诊断。PTSD 的诊断需要专业人员结合创伤暴露、症状持续时间、功能影响和排除其他因素综合判断。",
            "common_misunderstandings": ["PTSD 不是矫情或意志力差。", "创伤反应不一定会立刻出现，也可能被某些场景重新触发。"],
            "actions": ["先把它理解为身心警报系统在创伤后过度敏感。", "如果被触发，优先用脚踩地、观察环境等稳定练习回到当下。", "持续受影响时，联系可信任的人或专业支持。"],
            "seek_help_when": ["反复噩梦、闪回或回避已经影响日常功能。", "出现强烈解离、失控感、自伤想法或现实安全风险。", "你需要判断是否达到 PTSD 或其他临床问题标准。"],
            "tags": ["PTSD", "创伤后应激障碍", "创伤后应激", "创伤", "闪回", "噩梦"],
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


SEED_ARTICLES.extend(EXPANDED_SEED_ARTICLES)

_SEEDED_BIND_IDS: set[int] = set()
_CHUNK_INDEX_BY_BIND: dict[int, list[tuple[KnowledgeChunk, KnowledgeArticle]]] = {}
_SEED_LOCK = Lock()


def _ensure_seed_sources(db: Session) -> dict[str, KnowledgeSource]:
    changed = False
    sources: dict[str, KnowledgeSource] = {}
    for payload in SEED_SOURCES:
        source_key = str(payload["source_key"])
        source = db.scalar(select(KnowledgeSource).where(KnowledgeSource.source_key == source_key))
        if source is None:
            source = KnowledgeSource(**payload)
            db.add(source)
            db.flush()
            changed = True
        else:
            for key, value in payload.items():
                if getattr(source, key) != value:
                    setattr(source, key, value)
                    changed = True
        sources[source_key] = source

    if changed:
        db.flush()
    return sources


def _source_ref_from_article(article: KnowledgeArticle) -> dict[str, object]:
    source = article.source
    return {
        "source_name": source.name if source else "内部审核心理知识种子库",
        "source_url": article.source_url or (source.base_url if source else None),
        "license": article.license or (source.license if source else "internal-curated"),
        "article_id": article.id,
        "article_title": article.title,
    }


def _split_text_chunks(text: str, *, max_chars: int = 600) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)
    return chunks or [text.strip()]


def _article_chunk_texts(article: KnowledgeArticle) -> list[str]:
    parts = [
        f"标题：{article.title}",
        f"30秒摘要：{article.summary_30s}",
        f"解释：{article.explanation_3min}",
    ]
    if article.advanced_text:
        parts.append(f"补充说明：{article.advanced_text}")
    if article.common_misunderstandings:
        parts.append("常见误区：" + "；".join(article.common_misunderstandings))
    if article.actions:
        parts.append("可以先做：" + "；".join(article.actions))
    if article.seek_help_when:
        parts.append("需要现实支持时：" + "；".join(article.seek_help_when))
    return _split_text_chunks("\n".join(parts))


def _sync_article_chunks(db: Session, article: KnowledgeArticle) -> bool:
    changed = False
    existing = {
        chunk.chunk_index: chunk
        for chunk in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.article_id == article.id))
    }
    expected_chunks = _article_chunk_texts(article)
    for index, content in enumerate(expected_chunks):
        chunk = existing.get(index)
        payload = {
            "title": article.title,
            "content": content,
            "keywords": list(article.tags or []),
            "tags": list(article.tags or []),
            "token_count": max(1, len(content) // 2),
            "source_url": article.source_url,
            "license": article.license,
            "status": article.status,
        }
        if chunk is None:
            db.add(KnowledgeChunk(article_id=article.id, chunk_index=index, **payload))
            changed = True
            continue

        for key, value in payload.items():
            if getattr(chunk, key) != value:
                setattr(chunk, key, value)
                changed = True

    for index, chunk in existing.items():
        if index >= len(expected_chunks) and chunk.status != "archived":
            chunk.status = "archived"
            changed = True

    return changed


def ensure_seed_articles(db: Session, *, force: bool = False) -> None:
    bind_id = id(db.get_bind())
    if not force and bind_id in _SEEDED_BIND_IDS:
        return

    changed = False
    with _SEED_LOCK:
        if not force and bind_id in _SEEDED_BIND_IDS:
            return

        sources = _ensure_seed_sources(db)
        for payload in SEED_ARTICLES:
            raw_payload = dict(payload)
            slug = str(raw_payload["slug"])
            article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.slug == slug))
            source_key = str(raw_payload.pop("source_key", "internal_curated"))
            source = sources.get(source_key, sources["internal_curated"])
            source_url = str(raw_payload.get("source_url") or source.base_url or "local://internal-curated")
            license_name = str(raw_payload.get("license") or source.license or "internal-curated")
            payload = {
                **raw_payload,
                "source_id": source.id,
                "review_status": "published",
                "license": license_name,
                "source_url": source_url,
                "published_at": utcnow(),
            }
            if not payload.get("source_refs"):
                payload["source_refs"] = [
                    {
                        "source_name": source.name,
                        "source_url": source_url,
                        "license": license_name,
                    }
                ]
            if article is None:
                article = KnowledgeArticle(**payload)
                db.add(article)
                db.flush()
                changed = True
            else:
                for key, value in payload.items():
                    if key == "published_at" and getattr(article, key) is not None:
                        continue
                    if getattr(article, key) != value:
                        setattr(article, key, value)
                        changed = True

            if _sync_article_chunks(db, article):
                changed = True

        if changed:
            db.commit()
            _CHUNK_INDEX_BY_BIND.pop(bind_id, None)
        _SEEDED_BIND_IDS.add(bind_id)


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
    source_refs = list(article.source_refs or [])
    if not source_refs:
        source_refs = [_source_ref_from_article(article)]
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
        source_refs=source_refs,
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
    return normalize_knowledge_text(" ".join(parts))


def _score_article(article: KnowledgeArticle, query: str | ExpandedKnowledgeQuery) -> int:
    expanded = expand_knowledge_query(query) if isinstance(query, str) else query
    if not expanded.normalized:
        return 1

    score = 0
    article_title = normalize_knowledge_text(article.title)
    article_tags = [normalize_knowledge_text(tag) for tag in article.tags or []]
    article_category = normalize_knowledge_text(article.category)
    article_summary = normalize_knowledge_text(article.summary_30s)
    article_explanation = normalize_knowledge_text(article.explanation_3min)
    article_blob = _article_blob(article)

    if expanded.normalized in article_title:
        score += 50
    if any(tag and expanded.normalized in tag for tag in article_tags):
        score += 35
    if expanded.normalized in article_category:
        score += 20
    if expanded.normalized in article_summary:
        score += 15
    if expanded.normalized in article_explanation:
        score += 8

    primary_term = expanded.strong_terms[0] if expanded.strong_terms else ""
    if len(primary_term) >= 3:
        if primary_term in article_title:
            score += 150
        if any(primary_term == tag or primary_term in tag for tag in article_tags):
            score += 130
        if primary_term in article_summary:
            score += 60
        if primary_term in article_explanation:
            score += 35

    for phrase in [article_title, *article_tags]:
        if phrase and phrase in expanded.normalized:
            score += 28

    for term in expanded.strong_terms:
        if term in article_title:
            score += 42
        if any(term == tag or term in tag for tag in article_tags):
            score += 38
        if term in article_category:
            score += 12
        if term in article_summary:
            score += 14
        if term in article_explanation:
            score += 8

    for term in expanded.weak_terms:
        if term in article_title:
            score += 12
        if any(term == tag or term in tag for tag in article_tags):
            score += 10
        if term in article_summary:
            score += 6
        if term in article_explanation:
            score += 4

    if score > 0:
        query_chars = {char for char in expanded.normalized if "\u4e00" <= char <= "\u9fff"}
        if query_chars:
            article_chars = {char for char in article_blob if "\u4e00" <= char <= "\u9fff"}
            score += min(len(query_chars & article_chars), 4)

    return score


def _chunk_blob(hit: KnowledgeChunk, article: KnowledgeArticle) -> str:
    parts = [
        hit.title,
        hit.content,
        article.title,
        article.category,
        " ".join(article.tags or []),
        " ".join(hit.tags or []),
        " ".join(hit.keywords or []),
    ]
    return normalize_knowledge_text(" ".join(parts))


def _score_chunk(chunk: KnowledgeChunk, article: KnowledgeArticle, query: str | ExpandedKnowledgeQuery) -> int:
    expanded = expand_knowledge_query(query) if isinstance(query, str) else query
    if not expanded.normalized:
        return 1

    score = _score_article(article, expanded)
    blob = _chunk_blob(chunk, article)
    chunk_title = normalize_knowledge_text(chunk.title)
    chunk_content = normalize_knowledge_text(chunk.content)
    tags = [
        normalize_knowledge_text(tag)
        for tag in set(list(article.tags or []) + list(chunk.tags or []) + list(chunk.keywords or []))
    ]

    if expanded.normalized in chunk_title:
        score += 35
    if expanded.normalized in chunk_content:
        score += 28

    for term in expanded.strong_terms:
        if term in chunk_title:
            score += 38
        if any(tag and (term == tag or term in tag) for tag in tags):
            score += 34
        if term in chunk_content:
            score += 18

    for term in expanded.weak_terms:
        if term in chunk_title:
            score += 12
        if any(tag and (term == tag or term in tag) for tag in tags):
            score += 10
        if term in chunk_content:
            score += 5

    if score > 0:
        query_chars = {char for char in expanded.normalized if "\u4e00" <= char <= "\u9fff"}
        if query_chars:
            chunk_chars = {char for char in blob if "\u4e00" <= char <= "\u9fff"}
            score += min(len(query_chars & chunk_chars), 4)

    return score


def _search_chunk_hits(
    db: Session,
    *,
    query: str,
    category: str | None = None,
    audience: str | None = None,
    limit: int = 8,
) -> list[ChunkHit]:
    ensure_seed_articles(db)
    rows = _published_chunk_rows(db)
    expanded_query = expand_knowledge_query(query)

    hits: list[ChunkHit] = []
    for chunk, article in rows:
        if category and article.category != category:
            continue
        if audience and article.audience not in {"all", audience}:
            continue
        score = _score_chunk(chunk, article, expanded_query)
        if score > 0:
            hits.append(ChunkHit(article=article, chunk=chunk, score=score))

    hits.sort(key=lambda hit: (-hit.score, hit.article.title, hit.chunk.chunk_index))
    return hits[:limit]


async def _search_chunk_hits_semantic(
    db: Session,
    *,
    query: str,
    category: str | None = None,
    audience: str | None = None,
    limit: int = 8,
) -> list[ChunkHit]:
    ensure_seed_articles(db)
    if not milvus_store.is_enabled:
        return []
    vector = await embedding_client.embed_query(query)
    if vector is None:
        return []

    vector_hits = milvus_store.search_knowledge(vector, limit=max(limit * 2, 8))
    chunk_ids = [str(hit.entity.get("chunk_id") or hit.id) for hit in vector_hits]
    chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
    if not chunk_ids:
        return []

    rows = db.execute(
        select(KnowledgeChunk, KnowledgeArticle)
        .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
        .options(joinedload(KnowledgeArticle.source))
        .where(
            KnowledgeChunk.id.in_(chunk_ids),
            KnowledgeArticle.status == "published",
            KnowledgeArticle.review_status == "published",
            KnowledgeChunk.status == "published",
        )
    ).all()
    row_by_chunk_id = {chunk.id: (chunk, article) for chunk, article in rows}

    hits: list[ChunkHit] = []
    for vector_hit in vector_hits:
        chunk_id = str(vector_hit.entity.get("chunk_id") or vector_hit.id)
        row = row_by_chunk_id.get(chunk_id)
        if row is None:
            continue
        chunk, article = row
        if category and article.category != category:
            continue
        if audience and article.audience not in {"all", audience}:
            continue
        semantic_score = int(max(0.0, min(vector_hit.score, 1.0)) * 100)
        lexical_score = _score_chunk(chunk, article, query)
        hits.append(ChunkHit(article=article, chunk=chunk, score=max(semantic_score, lexical_score, 1)))

    hits.sort(key=lambda hit: (-hit.score, hit.article.title, hit.chunk.chunk_index))
    return hits[:limit]


def _published_chunk_rows(db: Session) -> list[tuple[KnowledgeChunk, KnowledgeArticle]]:
    bind_id = id(db.get_bind())
    cached = _CHUNK_INDEX_BY_BIND.get(bind_id)
    if cached is not None:
        return cached

    rows = db.execute(
        select(KnowledgeChunk, KnowledgeArticle)
        .join(KnowledgeArticle, KnowledgeChunk.article_id == KnowledgeArticle.id)
        .options(joinedload(KnowledgeArticle.source))
        .where(
            KnowledgeArticle.status == "published",
            KnowledgeArticle.review_status == "published",
            KnowledgeChunk.status == "published",
        )
    ).all()

    cached_rows = [(chunk, article) for chunk, article in rows]
    _CHUNK_INDEX_BY_BIND[bind_id] = cached_rows
    return cached_rows


def warm_knowledge_search_index(db: Session) -> None:
    ensure_seed_articles(db)
    _published_chunk_rows(db)


def _unique_articles_from_hits(hits: list[ChunkHit], *, limit: int) -> list[KnowledgeArticle]:
    seen: set[str] = set()
    articles: list[KnowledgeArticle] = []
    for hit in hits:
        if hit.article.id in seen:
            continue
        seen.add(hit.article.id)
        articles.append(hit.article)
        if len(articles) >= limit:
            break
    return articles


def _coverage_from_hits(hits: list[ChunkHit]) -> tuple[str, str, int]:
    top_score = hits[0].score if hits else 0
    if top_score >= 52:
        return "sufficient", "high", top_score
    if top_score >= 35:
        return "partial", "medium", top_score
    return "insufficient", "low", top_score


def _source_refs_from_hits(hits: list[ChunkHit], *, limit: int = 4) -> list[KnowledgeSourceRefResponse]:
    refs: list[KnowledgeSourceRefResponse] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.article.id, hit.chunk.id)
        if key in seen:
            continue
        seen.add(key)
        source = hit.article.source
        refs.append(
            KnowledgeSourceRefResponse(
                source_name=source.name if source else "内部审核心理知识种子库",
                source_url=hit.chunk.source_url or hit.article.source_url or (source.base_url if source else None),
                license=hit.chunk.license or hit.article.license or (source.license if source else None),
                article_id=hit.article.id,
                article_title=hit.article.title,
                chunk_id=hit.chunk.id,
                chunk_index=hit.chunk.chunk_index,
                score=hit.score,
            )
        )
        if len(refs) >= limit:
            break
    return refs


def _source_refs_as_dicts(refs: list[KnowledgeSourceRefResponse]) -> list[dict]:
    return [ref.model_dump() for ref in refs]


def _classify_knowledge_scope(question: str) -> KnowledgeScopeStatus:
    return classify_knowledge_scope(question)


QUESTION_CLEANUP_PHRASES: tuple[str, ...] = (
    "是什么",
    "是啥",
    "什么意思",
    "啥意思",
    "怎么办",
    "怎么回事",
    "有用吗",
    "为什么",
    "如何",
    "怎么",
)

FUZZY_EXCLUDED_TERMS: set[str] = {
    "心理",
    "心理学",
    "心理健康",
    "情绪",
    "关系",
    "自助",
    "求助",
    "安全",
    "风险",
    "支持",
    "all",
}


def _contains_explicit_out_of_scope_terms(question: str) -> bool:
    normalized = normalize_knowledge_text(question)
    return contains_any(normalized, SEXUAL_KNOWLEDGE_TERMS) or contains_any(normalized, OUT_OF_SCOPE_TERMS)


def _known_typo_guess(question: str) -> QuestionGuess | None:
    guessed_question, replacements = apply_known_typo_corrections(question)
    if not replacements or guessed_question == normalize_knowledge_text(question):
        return None

    return QuestionGuess(
        guessed_question=guessed_question,
        matched_term=replacements[0][1],
        confidence="high",
    )


def _suggestion_response(question: str, guess: QuestionGuess | None) -> KnowledgeQuestionSuggestion | None:
    if guess is None:
        return None
    confidence = "high" if guess.confidence == "high" else "medium"
    return KnowledgeQuestionSuggestion(
        original_question=question,
        guessed_question=guess.guessed_question,
        confidence=confidence,
        matched_term=guess.matched_term,
    )


def _clean_candidate_term(term: str) -> str:
    normalized = normalize_knowledge_text(term)
    for phrase in QUESTION_CLEANUP_PHRASES:
        normalized = normalized.replace(phrase, " ")
    return " ".join(normalized.split())


def _iter_knowledge_terms(db: Session) -> list[str]:
    ensure_seed_articles(db)
    articles = db.scalars(
        select(KnowledgeArticle).where(
            KnowledgeArticle.status == "published",
            KnowledgeArticle.review_status == "published",
        )
    )
    terms: set[str] = set()
    for article in articles:
        raw_terms = [article.title, *(article.tags or [])]
        for raw_term in raw_terms:
            term = _clean_candidate_term(str(raw_term))
            if term in FUZZY_EXCLUDED_TERMS:
                continue
            if len(term) < 2 or len(term) > 18:
                continue
            terms.add(term)
    return sorted(terms, key=lambda item: (-len(item), item))


def _substring_windows(text: str, target_length: int) -> list[str]:
    compact = text.replace(" ", "")
    lengths = {target_length}
    if target_length >= 4:
        lengths.update({target_length - 1, target_length + 1})
    elif target_length == 3:
        lengths.add(2)

    windows: set[str] = set()
    for length in lengths:
        if length <= 0 or length > len(compact):
            continue
        for index in range(0, len(compact) - length + 1):
            windows.add(compact[index : index + length])
    return list(windows)


def _best_term_window(query: str, term: str) -> tuple[float, str]:
    normalized_query = normalize_knowledge_text(query)
    normalized_term = normalize_knowledge_text(term)
    if not normalized_query or not normalized_term or normalized_term in normalized_query:
        return 0.0, ""

    best_score = 0.0
    best_window = ""
    if normalized_term.isascii():
        tokens = [token for token in normalized_query.replace("-", " ").split() if token.isascii()]
        tokens.extend(_substring_windows(normalized_query, len(normalized_term)))
        candidates = tokens
    else:
        candidates = _substring_windows(normalized_query, len(normalized_term))

    for candidate in candidates:
        if not candidate or candidate == normalized_term:
            continue
        score = SequenceMatcher(None, candidate, normalized_term).ratio()
        if score > best_score:
            best_score = score
            best_window = candidate
    return best_score, best_window


def _passes_fuzzy_threshold(term: str, score: float) -> bool:
    if term.isascii():
        return len(term) >= 3 and score >= 0.74
    if len(term) >= 4:
        return score >= 0.74
    if len(term) == 3:
        return score >= 0.67
    return False


def _fuzzy_question_guess(db: Session, question: str) -> QuestionGuess | None:
    if _contains_explicit_out_of_scope_terms(question):
        return None

    normalized_question = normalize_knowledge_text(question)
    best: tuple[float, str, str] | None = None
    for term in _iter_knowledge_terms(db):
        score, window = _best_term_window(normalized_question, term)
        if not window or not _passes_fuzzy_threshold(term, score):
            continue
        if best is None or score > best[0] or (score == best[0] and len(term) > len(best[1])):
            best = (score, term, window)

    if best is None:
        return None

    score, term, window = best
    guessed_question = normalized_question.replace(window, term, 1)
    if guessed_question == normalized_question:
        return None

    return QuestionGuess(
        guessed_question=guessed_question,
        matched_term=term,
        confidence="high" if score >= 0.86 else "medium",
    )


def _out_of_scope_knowledge_answer() -> KnowledgeAnswer:
    return KnowledgeAnswer(
        summary_30s="抱歉，这个问题不属于心理健康知识问答范围。",
        explanation_3min=(
            "这里主要回答情绪、压力、睡眠、关系、自我理解和求助边界相关的问题。"
            "如果这个词或场景让你感到困扰，可以描述你的具体感受，我可以从心理支持角度陪你整理。"
        ),
        actions=[],
        seek_help_when=[],
    )


def _is_broad_psychology_request(question: str) -> bool:
    normalized = " ".join(question.strip().lower().split())
    if not normalized:
        return False

    broad_phrases = (
        "心理学知识",
        "心理知识",
        "心理健康知识",
        "讲点心理",
        "介绍心理",
        "科普心理",
        "一些心理",
        "一点心理",
        "心理学科普",
    )
    if any(phrase in normalized for phrase in broad_phrases):
        return True

    return "心理" in normalized and any(verb in normalized for verb in ("给我", "讲讲", "介绍", "科普", "随便"))


def _broad_psychology_hits(db: Session) -> list[ChunkHit]:
    preferred_slugs = [
        "medlineplus-mental-health-35",
        "medlineplus-how-to-improve-mental-health-7407",
        "cognitive-distortions",
        "anxiety-basics",
        "medlineplus-stress-3",
        "sleep-rumination",
        "boundaries",
        "when-to-seek-help",
    ]
    hits: list[ChunkHit] = []
    for index, slug in enumerate(preferred_slugs):
        row = db.execute(
            select(KnowledgeArticle, KnowledgeChunk)
            .join(KnowledgeChunk, KnowledgeChunk.article_id == KnowledgeArticle.id)
            .where(
                KnowledgeArticle.slug == slug,
                KnowledgeArticle.status == "published",
                KnowledgeArticle.review_status == "published",
                KnowledgeChunk.status == "published",
            )
            .order_by(KnowledgeChunk.chunk_index)
            .limit(1)
        ).first()
        if row is None:
            continue
        article, chunk = row
        hits.append(ChunkHit(article=article, chunk=chunk, score=96 - index))
    return hits


def _broad_psychology_answer() -> KnowledgeAnswer:
    return KnowledgeAnswer(
        summary_30s="可以。入门心理知识可以先从情绪、认知、关系、压力睡眠和求助边界这几块理解，它们比单个技巧更能帮你看懂自己的状态。",
        explanation_3min=(
            "心理学和心理健康知识不只是解释“我怎么了”，也包括看见情绪怎么被触发、想法怎么影响感受、关系里边界和依恋如何运作、"
            "压力和睡眠怎样互相放大，以及什么时候需要现实支持。一个实用的理解方式是：先分清身体反应、自动想法、情绪和行动冲动，"
            "再看它们是在什么场景里反复出现。这里的内容只用于科普和自助整理，不能替代诊断、治疗或用药建议。"
        ),
        actions=[
            "先选一个方向继续问：情绪调节、焦虑、睡眠、关系边界、认知偏差或求助资源。",
            "把最近一个困扰拆成四栏：发生了什么、我想到什么、我有什么感受、我做了什么。",
            "如果你只是想随便学一点，可以从“认知偏差”“压力和睡眠”“边界感”三个主题开始。",
        ],
        seek_help_when=[
            "情绪或睡眠问题持续影响学习、工作、关系或基本生活。",
            "出现自伤想法、明显失控感、现实安全风险或强烈绝望感。",
            "你需要诊断、治疗计划或药物相关建议。",
        ],
    )


def _record_knowledge_gap(
    db: Session,
    *,
    question: str,
    category: str | None,
    audience: str | None,
    top_score: int,
    source_refs: list[KnowledgeSourceRefResponse],
    thread_id: str | None,
) -> KnowledgeGap:
    normalized = " ".join(question.strip().lower().split())
    gap = db.scalar(
        select(KnowledgeGap).where(
            KnowledgeGap.normalized_question == normalized,
            KnowledgeGap.status == "open",
        )
    )
    now = utcnow()
    if gap is None:
        gap = KnowledgeGap(
            question=question,
            normalized_question=normalized,
            category=category,
            audience=audience,
            coverage_status="insufficient",
            confidence="low",
            top_score=top_score,
            source_refs=_source_refs_as_dicts(source_refs),
            thread_id=thread_id,
        )
        db.add(gap)
        db.flush()
    else:
        gap.hit_count += 1
        gap.top_score = max(gap.top_score, top_score)
        gap.source_refs = _source_refs_as_dicts(source_refs)
        gap.updated_at = now
        if thread_id:
            gap.thread_id = thread_id
    db.commit()
    return gap


def search_articles(
    db: Session,
    *,
    query: str = "",
    category: str | None = None,
    audience: str | None = None,
    limit: int = 8,
) -> KnowledgeSearchResponse:
    ensure_seed_articles(db)
    if query.strip():
        risk_level = sync_risk_classify(query)
        if risk_level in {"L2", "L3"}:
            # 高风险查询不返回知识内容
            return KnowledgeSearchResponse(items=[])
        hits = _search_chunk_hits(db, query=query, category=category, audience=audience, limit=max(limit * 2, 8))
        articles = _unique_articles_from_hits(hits, limit=limit)
        return KnowledgeSearchResponse(items=[article_to_search_item(article) for article in articles])

    articles = list(
        db.scalars(
            select(KnowledgeArticle).where(
                KnowledgeArticle.status == "published",
                KnowledgeArticle.review_status == "published",
            )
        )
    )

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
            KnowledgeArticle.review_status == "published",
            or_(*filters),
        )
    )


def _chunk_context(hit: ChunkHit, index: int) -> str:
    article = hit.article
    actions = "；".join(list(article.actions or [])[:3])
    seek_help = "；".join(list(article.seek_help_when or [])[:3])
    misunderstandings = "；".join(list(article.common_misunderstandings or [])[:2])
    return (
        f"[{index}] 标题：{article.title}\n"
        f"分类：{article.category}；适用人群：{article.audience}\n"
        f"知识片段：{hit.chunk.content}\n"
        f"常见误区：{misunderstandings or '无'}\n"
        f"可做行动：{actions or '无'}\n"
        f"何时求助：{seek_help or '无'}\n"
        f"来源许可：{hit.chunk.license or article.license or 'unknown'}"
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


def _answer_from_model_payload(payload: dict, fallback: KnowledgeAnswer) -> GeneratedKnowledgeAnswer | None:
    summary = str(payload.get("summary_30s", "")).strip()
    explanation = str(payload.get("explanation_3min", "")).strip()
    if not summary or not explanation:
        return None

    scope_status: KnowledgeScopeStatus = "out_of_scope" if payload.get("scope_status") == "out_of_scope" else "in_scope"
    answer = KnowledgeAnswer(
        summary_30s=summary[:260],
        explanation_3min=explanation[:900],
        actions=_string_list(payload.get("actions"), fallback=fallback.actions if scope_status == "in_scope" else [], limit=4),
        seek_help_when=_string_list(
            payload.get("seek_help_when"),
            fallback=fallback.seek_help_when if scope_status == "in_scope" else [],
            limit=4,
        ),
    )
    return GeneratedKnowledgeAnswer(answer=answer, scope_status=scope_status)


async def _generate_knowledge_answer(
    *,
    question: str,
    hits: list[ChunkHit],
    use_my_context: bool,
) -> GeneratedKnowledgeAnswer | None:
    if not hits:
        return None

    fallback = _fallback_answer(hits[0].article, use_my_context=use_my_context)
    if not settings.knowledge_llm_answers_enabled or not deepseek_client.is_configured:
        return GeneratedKnowledgeAnswer(answer=fallback)

    source_context = "\n\n".join(_chunk_context(hit, index + 1) for index, hit in enumerate(hits[:4]))
    context_note = "可以轻微承接用户近况，但不要假装知道未提供的个人信息。" if use_my_context else "不要引用用户个人近况。"
    system_prompt = (
        "你是心理健康知识问答 agent，负责把已检索到的知识库内容组织成清楚、温和、可执行的回答。"
        "你不是医生或心理咨询师，不做诊断，不承诺疗效，不编造知识库以外的事实。"
        "回答边界：只回答心理健康知识范围，包括情绪、压力、睡眠、关系、自我理解、认知偏差、创伤、心理健康科普和求助资源。"
        "不要回答泛百科、代码、金融、路线、娱乐、性俚语、性技巧、生理细节、医学诊断或用药等非心理知识。"
        "如果用户的核心问题不属于心理健康知识范围，即使检索资料里有相似词，也必须把 scope_status 设为 out_of_scope，并使用范围外抱歉话术。"
        "如果非心理词汇出现在心理困扰语境中，只回应焦虑、羞耻、失控、影响生活等心理支持部分，不解释非心理知识本身。"
        "如果问题属于心理健康范围但超出资料范围，要说明只能基于现有资料回答，并引导用户换更具体的问题。"
        "用简体中文，语气稳定、克制，避免说教。只输出 JSON，不要 Markdown。"
    )
    user_prompt = (
        f"用户问题：{question}\n"
        f"上下文要求：{context_note}\n\n"
        f"可用知识库资料：\n{source_context}\n\n"
        "请输出 JSON，字段如下：\n"
        "{\n"
        '  "scope_status": "in_scope 或 out_of_scope。只有核心问题属于心理健康知识范围时才用 in_scope",\n'
        '  "summary_30s": "用 1-2 句话直接回答",\n'
        '  "explanation_3min": "用 1 段解释原因、机制和边界，120-260 字",\n'
        '  "actions": ["2-4 个安全、具体、轻量的行动"],\n'
        '  "seek_help_when": ["2-4 个需要现实或专业帮助的信号"]\n'
        "}\n"
        "范围外固定话术：summary_30s 写“抱歉，这个问题不属于心理健康知识问答范围。”；"
        "explanation_3min 写“这里主要回答情绪、压力、睡眠、关系、自我理解和求助边界相关的问题。"
        "如果这个词或场景让你感到困扰，可以描述你的具体感受，我可以从心理支持角度陪你整理。”；"
        "actions 和 seek_help_when 返回空数组。"
    )

    reply = await deepseek_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=deepseek_client.knowledge_model,
        temperature=0.35,
        max_tokens=760,
    )
    if not reply:
        return GeneratedKnowledgeAnswer(answer=fallback)

    payload = _json_from_model(reply)
    if payload is None:
        return GeneratedKnowledgeAnswer(answer=fallback)

    return _answer_from_model_payload(payload, fallback) or GeneratedKnowledgeAnswer(answer=fallback)


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
            coverage_status="insufficient",
            scope_status="in_scope",
            confidence="low",
            source_refs=[],
            risk_level=risk_level,
        )

    question_guess = _known_typo_guess(question)
    effective_question = question_guess.guessed_question if question_guess else question
    scope_status = _classify_knowledge_scope(effective_question)
    if scope_status == "out_of_scope" and not _contains_explicit_out_of_scope_terms(question):
        fuzzy_guess = _fuzzy_question_guess(db, effective_question)
        if fuzzy_guess is not None:
            question_guess = fuzzy_guess
            effective_question = fuzzy_guess.guessed_question
            scope_status = _classify_knowledge_scope(effective_question)

    if scope_status == "out_of_scope":
        return AskKnowledgeResponse(
            answer=_out_of_scope_knowledge_answer(),
            related_articles=[],
            coverage_status="not_applicable",
            scope_status=scope_status,
            confidence="low",
            source_refs=[],
            gap_id=None,
            continue_chat_payload=ContinueChatPayload(
                mode="knowledge",
                context_type="knowledge_out_of_scope",
                thread_id=thread_id,
            ),
            risk_level=risk_level,
        )

    question_suggestion = _suggestion_response(question, question_guess)

    if _is_broad_psychology_request(effective_question):
        hits = _broad_psychology_hits(db)
        articles = _unique_articles_from_hits(hits, limit=4)
        return AskKnowledgeResponse(
            answer=_broad_psychology_answer(),
            related_articles=[article_to_search_item(article) for article in articles],
            coverage_status="sufficient",
            scope_status="in_scope",
            confidence="high",
            source_refs=_source_refs_from_hits(hits),
            question_suggestion=question_suggestion,
            continue_chat_payload=ContinueChatPayload(
                mode="knowledge",
                context_type="knowledge_overview",
                article_id=hits[0].article.id if hits else None,
                thread_id=thread_id,
            ),
            risk_level=risk_level,
        )

    hits = await _search_chunk_hits_semantic(db, query=effective_question, limit=8)
    if not hits:
        hits = _search_chunk_hits(db, query=effective_question, limit=8)
    coverage_status, confidence, top_score = _coverage_from_hits(hits)
    if coverage_status == "insufficient" and question_guess is None:
        fuzzy_guess = _fuzzy_question_guess(db, effective_question)
        if fuzzy_guess is not None:
            question_guess = fuzzy_guess
            effective_question = fuzzy_guess.guessed_question
            question_suggestion = _suggestion_response(question, question_guess)
            hits = await _search_chunk_hits_semantic(db, query=effective_question, limit=8)
            if not hits:
                hits = _search_chunk_hits(db, query=effective_question, limit=8)
            coverage_status, confidence, top_score = _coverage_from_hits(hits)

    source_refs = _source_refs_from_hits(hits)
    articles = _unique_articles_from_hits(hits, limit=4)
    related = [article_to_search_item(article) for article in articles]

    if coverage_status == "insufficient":
        gap = _record_knowledge_gap(
            db,
            question=question,
            category=articles[0].category if articles else None,
            audience=articles[0].audience if articles else None,
            top_score=top_score,
            source_refs=source_refs,
            thread_id=thread_id,
        )
        return AskKnowledgeResponse(
            answer=KnowledgeAnswer(
                summary_30s="当前知识库还没有足够可靠的资料来回答这个问题。",
                explanation_3min=(
                    "我已经把这个问题记录为待补充主题。为了避免误导，我不会用大模型凭空扩写答案。"
                    "你可以换一个更具体的关键词再问，或回到对话里先描述你的具体场景。"
                ),
                actions=["换一个更具体的关键词提问", "回到咨询对话里描述具体场景", "等待知识库补充后再查看"],
                seek_help_when=["问题涉及现实安全、自伤风险、持续失眠或明显功能受损时，请优先联系现实支持或专业人员"],
            ),
            related_articles=related,
            coverage_status=coverage_status,
            scope_status="in_scope",
            confidence=confidence,
            source_refs=[],
            question_suggestion=question_suggestion,
            gap_id=gap.id,
            continue_chat_payload=ContinueChatPayload(mode="knowledge", context_type="knowledge_fallback", thread_id=thread_id),
            risk_level=risk_level,
        )

    generated = await _generate_knowledge_answer(
        question=effective_question,
        hits=hits,
        use_my_context=use_my_context,
    )
    if generated and generated.scope_status == "out_of_scope":
        return AskKnowledgeResponse(
            answer=generated.answer,
            related_articles=[],
            coverage_status="not_applicable",
            scope_status="out_of_scope",
            confidence="low",
            source_refs=[],
            question_suggestion=question_suggestion,
            gap_id=None,
            continue_chat_payload=ContinueChatPayload(
                mode="knowledge",
                context_type="knowledge_out_of_scope",
                thread_id=thread_id,
            ),
            risk_level=risk_level,
        )

    return AskKnowledgeResponse(
        answer=generated.answer if generated else _fallback_answer(hits[0].article, use_my_context=use_my_context),
        related_articles=related,
        coverage_status=coverage_status,
        scope_status="in_scope",
        confidence=confidence,
        source_refs=source_refs,
        question_suggestion=question_suggestion,
        continue_chat_payload=ContinueChatPayload(
            mode="knowledge",
            context_type="knowledge_article_guess" if question_suggestion else "knowledge_article",
            article_id=hits[0].article.id,
            thread_id=thread_id,
        ),
        risk_level=risk_level,
    )


def gap_to_item(gap: KnowledgeGap) -> KnowledgeGapItemResponse:
    return KnowledgeGapItemResponse(
        gap_id=gap.id,
        question=gap.question,
        category=gap.category,
        audience=gap.audience,
        coverage_status=gap.coverage_status,
        confidence=gap.confidence,
        top_score=gap.top_score,
        status=gap.status,
        hit_count=gap.hit_count,
        source_refs=list(gap.source_refs or []),
        created_at=gap.created_at,
        updated_at=gap.updated_at,
        resolved_at=gap.resolved_at,
    )


def list_knowledge_gaps(
    db: Session,
    *,
    status_filter: str = "open",
    limit: int = 50,
) -> KnowledgeGapListResponse:
    query = select(KnowledgeGap)
    if status_filter != "all":
        query = query.where(KnowledgeGap.status == status_filter)
    gaps = list(db.scalars(query.order_by(desc(KnowledgeGap.hit_count), desc(KnowledgeGap.updated_at)).limit(limit)))
    return KnowledgeGapListResponse(items=[gap_to_item(gap) for gap in gaps])


def resolve_knowledge_gap(
    db: Session,
    *,
    gap_id: str,
    article_id: str | None,
    reviewer_note: str | None,
) -> KnowledgeGapMutationResponse:
    gap = db.scalar(select(KnowledgeGap).where(KnowledgeGap.id == gap_id))
    if gap is None:
        raise ValueError("Knowledge gap not found.")

    if article_id:
        article = get_article(db, article_id)
        if article is None:
            raise ValueError("Knowledge article not found.")
        gap.resolved_article_id = article.id
        if reviewer_note:
            article.reviewer_note = reviewer_note

    gap.status = "resolved"
    gap.resolved_at = utcnow()
    gap.updated_at = gap.resolved_at
    db.commit()
    return KnowledgeGapMutationResponse(gap_id=gap.id, status=gap.status)
