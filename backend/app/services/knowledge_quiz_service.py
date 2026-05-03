from __future__ import annotations

import random
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from app.schemas.knowledge import (
    KnowledgeQuizBankStatsResponse,
    KnowledgeQuizOptionResponse,
    KnowledgeQuizQuestionResponse,
    KnowledgeQuizResultResponse,
    KnowledgeQuizReviewItem,
    KnowledgeQuizSessionResponse,
    KnowledgeQuizVisualResponse,
    QuizMode,
    QuizQuestionType,
    SubmitKnowledgeQuizAnswer,
)


@dataclass(frozen=True)
class QuizTopic:
    key: str
    topic: str
    category: str
    source_title: str
    source_url: str
    fact: str
    action: str
    misconception: str
    seek_help: str
    visual_kind: str
    visual_lines: tuple[str, str, str]


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    type: QuizQuestionType
    topic: str
    difficulty: int
    stem: str
    options: tuple[tuple[str, str], ...]
    correct_answer: str
    explanation: str
    source_title: str
    source_url: str
    visual: KnowledgeQuizVisualResponse | None = None


QUIZ_TOPICS: tuple[QuizTopic, ...] = (
    QuizTopic("anxiety", "焦虑", "emotion", "NIMH Generalized Anxiety Disorder", "https://www.nimh.nih.gov/health/publications/generalized-anxiety-disorder-gad", "焦虑会同时影响想法、身体和行为，持续影响生活时需要认真处理。", "先稳定身体，再把担心拆成一个今天能做的小步骤。", "焦虑不是简单的想太多，也不是一句放松点就能结束。", "焦虑持续影响睡眠、学习、工作或关系时，适合联系专业支持。", "emotion_meter", ("担心反复出现", "身体紧绷或心慌", "开始回避重要事情")),
    QuizTopic("stress", "压力", "emotion", "NIMH Stress", "https://www.nimh.nih.gov/health/publications/stress/index.shtml", "压力通常和外部事件有关，长期压力会影响睡眠、身体和注意力。", "先识别压力源，再安排一个可执行的小行动。", "有压力不代表能力差。", "压力长期无法缓解并影响日常功能时，应考虑现实支持。", "load_map", ("任务变多", "身体疲惫", "恢复时间变少")),
    QuizTopic("panic", "惊恐发作", "emotion", "NIMH Panic Disorder", "https://www.nimh.nih.gov/health/publications/panic-disorder-when-fear-overwhelms", "惊恐发作像身体突然拉响强警报，常伴随心跳快、胸闷和强烈害怕。", "把呼气拉长，提醒自己这是身体警报，再评估是否需要医学排查。", "惊恐发作不是装出来的，也不等于人一定会失控。", "第一次出现胸痛、晕厥或反复回避生活场景时，应寻求专业评估。", "body_alarm", ("心跳很快", "害怕失控", "几分钟内达到高峰")),
    QuizTopic("depression", "抑郁", "emotion", "NIMH Depression", "https://www.nimh.nih.gov/health/publications/depression", "抑郁相关信号可能包括持续低落、兴趣下降、精力变差和无望感。", "记录近两周睡眠、食欲、兴趣和功能变化。", "抑郁不是懒，也不是不够坚强。", "低落或兴趣下降持续影响生活，或出现自伤想法时，应优先求助。", "mood_log", ("兴趣下降", "精力变差", "持续低落")),
    QuizTopic("sleep", "失眠", "sleep", "MedlinePlus Insomnia", "https://medlineplus.gov/insomnia.html", "失眠包括入睡困难、维持睡眠困难、早醒或醒后不恢复，并影响白天状态。", "固定起床时间，减少睡前高刺激内容和咖啡因。", "躺得越久不一定睡得越好。", "睡眠问题持续影响白天功能时，需要评估压力、身体和作息因素。", "sleep_log", ("入睡时间推迟", "夜间反复醒", "白天注意力下降")),
    QuizTopic("rumination", "反刍思维", "emotion", "内部审核心理知识种子库", "local://internal-curated", "反刍是反复想同一件事却很少产生下一步的循环。", "把问题改写成一个可行动问题，并设置固定担忧时段。", "反复想不代表更负责。", "反刍导致长期失眠、注意力下降或明显痛苦时，适合寻求支持。", "thought_loop", ("重复复盘", "越想越自责", "没有新行动")),
    QuizTopic("boundaries", "边界感", "relationship", "内部审核心理知识种子库", "local://internal-curated", "边界感是分清什么属于自己、什么属于别人，并清楚表达能接受的范围。", "用“我能/我不能/我需要”表达一个低风险边界。", "设边界不是自私，也不是惩罚对方。", "设边界会引发现实危险时，应优先考虑安全和外部支持。", "boundary_scene", ("对方提出要求", "我感到不舒服", "表达可接受范围")),
    QuizTopic("attachment", "焦虑依恋", "relationship", "内部审核心理知识种子库", "local://internal-curated", "焦虑依恋常表现为对回应、冷淡和不确定特别敏感。", "先延迟冲动确认，再用感受和需要表达。", "焦虑依恋不等于爱得太多，也不代表关系一定坏了。", "关系焦虑导致失眠、失控争吵或自伤冲动时，需要现实支持。", "relationship_signal", ("消息延迟", "不安上升", "反复确认")),
    QuizTopic("social_anxiety", "社交焦虑", "relationship", "NIMH Social Anxiety Disorder", "https://www.nimh.nih.gov/health/publications/social-anxiety-disorder-more-than-just-shyness", "社交焦虑常和害怕被评价、出丑或被否定有关，并可能导致回避。", "从低风险社交动作开始，练习带着紧张完成行动。", "社交焦虑不是性格差，也不是必须立刻变外向。", "回避明显影响上课、会议、面试或必要沟通时，适合专业支持。", "social_scene", ("上台前担心", "现场监控自己", "结束后反复复盘")),
    QuizTopic("ocd", "强迫症/OCD", "emotion", "NIMH Obsessive-Compulsive Disorder", "https://www.nimh.nih.gov/health/publications/obsessive-compulsive-disorder-when-unwanted-thoughts-or-repetitive-behaviors-take-over", "OCD 通常包括侵入性想法和为了缓解焦虑而重复进行的行为或心理动作。", "记录触发场景、焦虑峰值和重复行为，避免独自做高强度暴露。", "OCD 不只是爱干净。侵入性想法也不等于真实意愿。", "重复检查、清洗或确认耗时且痛苦时，应考虑专业评估。", "loop_card", ("侵入想法", "焦虑升高", "重复确认")),
    QuizTopic("ptsd", "创伤/PTSD", "emotion", "NIMH PTSD", "https://www.nimh.nih.gov/health/publications/post-traumatic-stress-disorder-ptsd", "PTSD 可能涉及再体验、回避、警觉反应和认知情绪变化。", "被触发时先用脚踩地、观察环境等方式回到当下。", "创伤反应不是矫情，也不一定会立刻出现。", "闪回、噩梦或回避持续影响生活时，适合找创伤知情专业人员。", "grounding_card", ("画面闯入", "身体警觉", "回到当下")),
    QuizTopic("dissociation", "解离", "emotion", "NIMH PTSD", "https://www.nimh.nih.gov/health/publications/post-traumatic-stress-disorder-ptsd", "解离可能表现为不真实感、像旁观自己或记忆断片，常和压力或创伤有关。", "先用感官定位当下，再记录触发因素。", "解离不是故意装出来，也不是简单走神。", "解离反复出现、伴随危险行为或影响功能时，应寻求专业评估。", "grounding_card", ("环境像隔着膜", "身体感变远", "用感官定位")),
    QuizTopic("adhd", "ADHD", "self_help", "NIMH ADHD", "https://www.nimh.nih.gov/health/publications/attention-deficit-hyperactivity-disorder-what-you-need-to-know", "ADHD 涉及持续的注意力、多动或冲动困难，并会影响多个场景的功能。", "把任务拆到 10-15 分钟，减少环境干扰。", "ADHD 不是懒或故意不自律。", "注意力和冲动问题长期影响学习、工作或关系时，适合专业评估。", "task_board", ("任务启动难", "时间感模糊", "容易被打断")),
    QuizTopic("time_blindness", "时间盲", "self_help", "NIMH ADHD", "https://www.nimh.nih.gov/health/publications/attention-deficit-hyperactivity-disorder-what-you-need-to-know", "时间盲是对时间流逝、任务耗时和截止期限感知困难的一种表现。", "使用可视计时器和外部提醒，把任务切成短段。", "时间管理困难不一定是态度问题。", "长期影响履约、学习或工作时，可以评估执行功能支持。", "task_board", ("低估耗时", "拖到最后", "需要外部提醒")),
    QuizTopic("cbt", "CBT", "self_help", "内部审核心理知识种子库", "local://internal-curated", "CBT 常关注想法、情绪、身体反应和行为之间的相互影响。", "写下自动想法，列出支持和不支持它的证据。", "CBT 不是强行积极，也不是否定感受。", "痛苦严重、创伤复杂或风险升高时，需要更完整的专业支持。", "thought_record", ("事件", "自动想法", "更平衡说法")),
    QuizTopic("dbt", "DBT", "relationship", "NIMH Borderline Personality Disorder", "https://www.nimh.nih.gov/health/publications/borderline-personality-disorder", "DBT 常用于情绪调节、痛苦耐受、人际效能和正念等技能训练。", "情绪很强时，先暂停并稳定身体，再处理关系问题。", "DBT 不是压抑情绪，而是学习更安全地承载情绪。", "强烈情绪伴随自伤冲动或关系失控时，应联系现实支持。", "skills_card", ("暂停", "命名情绪", "选择行动")),
    QuizTopic("mindfulness", "正念", "self_help", "内部审核心理知识种子库", "local://internal-curated", "正念是把注意力带回当下，并以较少评判的方式观察体验。", "选一个感官锚点，观察 60 秒而不急着改变。", "正念不是清空大脑，也不是假装没事。", "练习中创伤反应或惊恐明显加重时，应停止并寻求支持。", "breathing_card", ("注意呼吸", "发现走神", "温和带回")),
    QuizTopic("grounding", "稳定练习", "self_help", "内部审核心理知识种子库", "local://internal-curated", "稳定练习用于把注意力从失控感拉回此时此地。", "说出看得到、摸得到和听得到的具体事物。", "稳定练习不是逃避问题，而是先恢复处理问题的能力。", "无法保证安全或现实风险升高时，应优先联系现实帮助。", "grounding_card", ("5 个看到的", "4 个摸到的", "3 个听到的")),
    QuizTopic("cognitive_distortion", "认知偏差", "self_help", "内部审核心理知识种子库", "local://internal-curated", "认知偏差是压力下大脑快速下结论的习惯，比如灾难化和非黑即白。", "问自己：有什么证据？有没有另一个解释？", "识别偏差不是强行积极。", "负面想法持续影响生活或涉及安全风险时，应寻求支持。", "thought_record", ("自动想法", "证据", "替代解释")),
    QuizTopic("perfectionism", "完美主义", "self_help", "内部审核心理知识种子库", "local://internal-curated", "完美主义可能让人把价值感绑在零失误和高标准上。", "把目标改成足够好，并定义最小完成标准。", "降低标准不等于摆烂。", "完美主义导致长期拖延、失眠或自责时，适合寻求支持。", "task_board", ("标准很高", "迟迟不开始", "害怕出错")),
    QuizTopic("burnout", "倦怠/耗竭", "emotion", "WHO Mental Health", "https://www.who.int/news-room/fact-sheets/detail/mental-health-strengthening-our-response", "长期压力和恢复不足可能带来耗竭、疏离和效率下降。", "先恢复基本睡眠和休息，再减少不必要负荷。", "倦怠不是简单懒散。", "耗竭持续且影响基本生活或伴随抑郁信号时，应寻求帮助。", "load_map", ("长期消耗", "恢复不足", "效率下降")),
    QuizTopic("help_seeking", "求助边界", "safety", "NIMH My Mental Health: Do I Need Help?", "https://www.nimh.nih.gov/health/publications/my-mental-health-do-i-need-help", "当情绪、睡眠或行为问题持续影响生活，自助之外的现实支持很重要。", "把最近最影响生活的三个变化写下来，联系可信任的人或专业资源。", "求助不是失败，也不需要等到危机才开始。", "出现自伤想法、无法保证安全或功能明显受损时，应优先求助。", "support_map", ("可信任的人", "专业资源", "紧急支持")),
    QuizTopic("crisis_warning", "危机预警", "safety", "NIMH Warning Signs of Suicide", "https://www.nimh.nih.gov/health/publications/warning-signs-of-suicide", "谈到想死、计划、告别、无望或突然危险行为增加，都需要认真对待。", "不要承诺保密，优先联系现实支持或紧急服务。", "直接温和询问自杀想法不会把想法种进去。", "有计划、工具、冲动或无法保证安全时，需要立即求助。", "support_map", ("谈到想死", "出现计划", "联系现实帮助")),
    QuizTopic("teen_stress", "青少年学业压力", "teen", "MedlinePlus Teen Mental Health", "https://medlineplus.gov/teenmentalhealth.html", "考试和学业压力会影响情绪、睡眠和身体状态。", "把任务拆小，并告诉一个可信任的大人当前压力。", "一次考试不能定义整个人。", "压力让人睡不着、吃不下或想伤害自己时，要尽快求助。", "study_card", ("考试临近", "睡眠变差", "找大人支持")),
    QuizTopic("body_image", "身体形象", "self_help", "NIMH Eating Disorders", "https://www.nimh.nih.gov/health/publications/eating-disorders", "身体形象困扰可能和自我价值、控制感、社交评价交织。", "减少反复检查身体，记录触发场景和情绪。", "身体形象困扰不只是爱美。", "体重、进食或身体检查想法支配生活时，应寻求专业支持。", "body_image_card", ("照镜子变多", "比较身体", "情绪被影响")),
    QuizTopic("eating_disorder", "饮食障碍", "self_help", "NIMH Eating Disorders", "https://www.nimh.nih.gov/health/publications/eating-disorders", "饮食障碍可能涉及限制进食、暴食、催吐或过度运动，并可能危及健康。", "不要只靠意志力处理，尽早联系医疗和心理专业支持。", "体重看起来正常也可能有饮食障碍。", "出现催吐、极端节食、快速体重变化或自伤想法时，应尽快求助。", "meal_log", ("限制进食", "暴食或催吐", "身体风险")),
    QuizTopic("binge_eating", "暴食", "self_help", "NIMH Eating Disorders", "https://www.nimh.nih.gov/health/publications/eating-disorders", "暴食通常涉及短时间大量进食和失控感，常伴随羞耻。", "记录触发情绪，避免用羞辱方式补偿。", "暴食不是单纯贪吃。", "暴食反复出现并伴随痛苦或补偿行为时，应寻求专业支持。", "meal_log", ("情绪触发", "失控进食", "羞耻自责")),
    QuizTopic("phobia", "恐惧/恐惧症", "emotion", "MedlinePlus Phobias", "https://medlineplus.gov/phobias.html", "恐惧症是对特定对象或场景的强烈、持续恐惧和回避。", "记录触发对象、回避程度和生活影响。", "恐惧症不是胆小。", "恐惧导致明显回避或影响生活时，适合专业评估。", "fear_ladder", ("触发对象", "恐惧升高", "开始回避")),
    QuizTopic("grief", "哀伤", "emotion", "MedlinePlus Mental Health", "https://medlineplus.gov/mentalhealth.html", "哀伤是失去后的自然反应，可能包括难过、麻木、愤怒和想念。", "允许情绪波动，并维持基本作息和现实支持。", "哀伤没有固定时间表。", "哀伤长期严重影响功能或伴随自伤想法时，应求助。", "mood_log", ("失去之后", "情绪波动", "需要陪伴")),
    QuizTopic("loneliness", "孤独感", "relationship", "MedlinePlus Mental Health", "https://medlineplus.gov/mentalhealth.html", "孤独感是关系需要没有被满足的信号，不等于没有价值。", "先连接一个低压力的人或场景，降低隔离。", "孤独不是矫情。", "孤独伴随长期低落、无望或自伤想法时，应寻求支持。", "support_map", ("想被看见", "减少隔离", "低压力连接")),
    QuizTopic("self_esteem", "自尊", "self_help", "MedlinePlus Mental Health", "https://medlineplus.gov/mentalhealth.html", "自尊和一个人如何看待自身价值有关，会受关系、成就和经历影响。", "把自我评价从单次表现中拆出来，记录稳定证据。", "自尊不是盲目自信。", "自我否定持续影响生活或安全时，应寻求支持。", "thought_record", ("一次失误", "整体否定", "寻找稳定证据")),
    QuizTopic("communication", "沟通", "relationship", "内部审核心理知识种子库", "local://internal-curated", "有效沟通通常包括表达事实、感受、需要和请求。", "用“我感到……我需要……”表达，而不是直接指责。", "沟通不是赢辩论。", "沟通涉及控制、威胁或暴力时，安全优先。", "dialogue_card", ("事实", "感受", "请求")),
    QuizTopic("conflict", "关系冲突", "relationship", "内部审核心理知识种子库", "local://internal-curated", "冲突中先稳定情绪，往往比马上讲道理更有效。", "约定暂停时间，冷静后再回到具体问题。", "暂停不是冷暴力，前提是说明会回来处理。", "冲突中有威胁、控制或伤害风险时，应寻求现实支持。", "dialogue_card", ("情绪升高", "暂停", "再讨论")),
    QuizTopic("people_pleasing", "讨好", "relationship", "内部审核心理知识种子库", "local://internal-curated", "讨好常表现为过度迎合别人、压低自己的需要以换取安全感。", "先练习一个低风险拒绝，并观察真实后果。", "拒绝别人不等于伤害别人。", "讨好让你长期被利用或无法保护自己时，适合寻求支持。", "boundary_scene", ("想拒绝", "害怕失去关系", "表达小边界")),
    QuizTopic("reassurance", "反复确认", "emotion", "NIMH OCD", "https://www.nimh.nih.gov/health/publications/obsessive-compulsive-disorder-when-unwanted-thoughts-or-repetitive-behaviors-take-over", "反复确认短期降低焦虑，长期可能让不确定感更难承受。", "延迟一次确认，把焦虑峰值记录下来。", "需要确认不代表你很烦人，但循环值得被看见。", "确认行为耗时、痛苦并影响生活时，适合专业评估。", "loop_card", ("不确定", "确认", "短暂放心")),
    QuizTopic("avoidance", "回避", "emotion", "NIMH Anxiety Disorders", "https://www.nimh.nih.gov/health/topics/anxiety-disorders", "回避会短期缓解焦虑，但长期可能让害怕的场景更难面对。", "选择一个低难度、可控的小接近步骤。", "面对不是硬扛到崩溃。", "回避影响学习、工作、关系或出门时，应寻求支持。", "fear_ladder", ("害怕场景", "回避", "难度变高")),
    QuizTopic("uncertainty", "不确定性", "emotion", "NIMH Generalized Anxiety Disorder", "https://www.nimh.nih.gov/health/publications/generalized-anxiety-disorder-gad", "不确定性会让焦虑系统更活跃，尤其在无法控制结果时。", "区分可控和不可控部分，只行动可控的一步。", "反复搜索答案不一定带来安全感。", "担心难以控制且长期影响生活时，适合专业支持。", "thought_loop", ("不确定", "搜索答案", "担心继续")),
    QuizTopic("nightmares", "噩梦", "sleep", "NIMH PTSD", "https://www.nimh.nih.gov/health/publications/post-traumatic-stress-disorder-ptsd", "噩梦可能和压力、创伤、睡眠状态或情绪唤醒有关。", "醒来后先定位当下环境，再做低刺激收尾。", "噩梦不是你的错。", "噩梦反复出现并影响睡眠或白天功能时，应寻求支持。", "sleep_log", ("醒来很慌", "确认当下", "重新收尾")),
    QuizTopic("caffeine_sleep", "咖啡因与睡眠", "sleep", "MedlinePlus Insomnia", "https://medlineplus.gov/insomnia.html", "咖啡因可能提高唤醒水平，影响入睡和睡眠质量。", "观察咖啡因摄入时间和睡眠变化，下午后逐步减少。", "咖啡因影响不是意志力问题。", "睡眠长期受影响时，应评估作息、压力和身体因素。", "sleep_log", ("下午咖啡", "入睡变晚", "白天疲惫")),
    QuizTopic("screen_sleep", "屏幕与睡前唤醒", "sleep", "MedlinePlus Insomnia", "https://medlineplus.gov/insomnia.html", "睡前高刺激内容会让大脑更难降速。", "睡前设置低刺激收尾，比如纸笔记录或安静音频。", "睡前刷手机不是唯一原因，但可能放大入睡困难。", "持续失眠影响白天功能时，应寻求评估。", "sleep_log", ("睡前刷屏", "脑子更醒", "低刺激收尾")),
    QuizTopic("school_support", "学校支持", "teen", "MedlinePlus Teen Mental Health", "https://medlineplus.gov/teenmentalhealth.html", "学校心理老师、班主任或可信任老师可以成为青少年现实支持的一部分。", "把最困扰的变化和需要支持的地方说清楚。", "向学校求助不是丢脸。", "压力或情绪影响安全和学习功能时，应尽快告诉可信任成年人。", "support_map", ("老师", "家人", "心理资源")),
    QuizTopic("stigma", "心理污名", "self_help", "WHO Mental Health", "https://www.who.int/news-room/fact-sheets/detail/mental-health-strengthening-our-response", "心理困扰很常见，污名会阻碍人寻求帮助。", "用具体状态和需要替代贴标签。", "有心理困扰不代表人失败。", "因羞耻而不敢求助但状态恶化时，应联系可信任的人。", "support_map", ("羞耻", "说出需要", "获得支持")),
    QuizTopic("autism", "自闭谱系", "self_help", "NIMH Autism Spectrum Disorder", "https://www.nimh.nih.gov/health/publications/autism-spectrum-disorder", "自闭谱系涉及社会沟通、互动方式、限制性兴趣和感官差异。", "用清楚、具体和可预测的方式降低压力。", "自闭谱系不是不礼貌，也不只有困难。", "社交沟通、感官或生活功能长期受影响时，可寻求专业评估。", "sensory_card", ("声音很刺", "规则不清", "需要可预测")),
    QuizTopic("sensory_overload", "感官过载", "self_help", "NIMH Autism Spectrum Disorder", "https://www.nimh.nih.gov/health/publications/autism-spectrum-disorder", "感官过载是声音、光线、触感等刺激超过调节能力。", "减少刺激，预留恢复空间。", "过载下的崩溃不是故意闹。", "感官压力明显影响学习、工作或安全时，适合寻求支持。", "sensory_card", ("光线太强", "声音太多", "需要恢复")),
    QuizTopic("psychosis_warning", "精神病性体验预警", "safety", "NIMH RAISE: What is Psychosis?", "https://www.nimh.nih.gov/health/topics/schizophrenia/raise/what-is-psychosis", "幻听、妄想或现实判断明显混乱需要尽早专业评估。", "减少争辩真实与否，优先保持安全和联系专业帮助。", "异常体验不是靠意志硬扛就能解决。", "异常体验影响安全、睡眠或自我照顾时，应尽快求助。", "support_map", ("异常感知", "现实混乱", "专业评估")),
    QuizTopic("medication_boundary", "用药边界", "safety", "MedlinePlus Mental Health", "https://medlineplus.gov/mentalhealth.html", "用药问题需要医生评估，知识问答不能替代处方或调整剂量。", "把症状、用药和副作用记录下来，带给医生讨论。", "不要自行停药、加药或换药。", "出现严重副作用、风险升高或无法判断安全时，应联系医疗人员。", "medical_boundary", ("记录变化", "联系医生", "不自行调整")),
    QuizTopic("diagnosis_boundary", "诊断边界", "safety", "NIMH Mental Health Information", "https://www.nimh.nih.gov/health", "诊断需要专业人员结合症状、持续时间、功能影响和排除因素判断。", "把具体表现和影响记录下来，作为咨询或就医材料。", "网上描述或测验不能直接等同诊断。", "需要诊断、治疗计划或证明时，应联系专业人员。", "medical_boundary", ("症状", "持续时间", "功能影响")),
    QuizTopic("sleep_appetite", "睡眠食欲变化", "emotion", "NIMH Depression", "https://www.nimh.nih.gov/health/publications/depression", "睡眠和食欲明显变化可能与压力、抑郁、焦虑或身体因素有关。", "记录两周变化趋势，而不是只看一天。", "睡多或吃多不一定是懒。", "变化持续并影响功能时，应寻求评估。", "mood_log", ("睡眠变化", "食欲变化", "功能影响")),
    QuizTopic("self_harm_support", "自伤风险支持", "safety", "NIMH Warning Signs of Suicide", "https://www.nimh.nih.gov/health/publications/warning-signs-of-suicide", "自伤想法或冲动意味着需要优先处理现实安全。", "远离工具，联系可信任的人或紧急服务。", "有自伤冲动不是道德失败，但不能独自硬扛。", "无法保证安全、有计划或工具时，应立即求助。", "support_map", ("冲动升高", "远离工具", "联系现实帮助")),
    QuizTopic("emotion_regulation", "情绪调节", "self_help", "MedlinePlus Mental Health", "https://medlineplus.gov/mentalhealth.html", "情绪调节不是消灭情绪，而是识别情绪、降低强度并选择更安全的行动。", "先命名情绪和身体反应，再决定下一步。", "情绪强烈不代表人有问题，也不代表必须立刻行动。", "情绪强到影响安全、关系或基本生活时，应联系现实支持。", "skills_card", ("命名情绪", "稳定身体", "选择行动")),
)


SINGLE_VARIANTS: tuple[tuple[str, str], ...] = (
    ("概念理解", "以下哪一项更符合“{topic}”的可靠理解？"),
    ("第一步", "当一个人遇到“{topic}”相关困扰时，更稳妥的第一步是什么？"),
    ("常见误区", "关于“{topic}”，哪一种说法更需要避免？"),
    ("求助信号", "哪种情况提示“{topic}”相关困扰可能需要现实或专业支持？"),
    ("自助边界", "关于“{topic}”的自助边界，哪项更准确？"),
    ("支持他人", "如果朋友提到“{topic}”相关困扰，更合适的回应是哪项？"),
)

TRUE_FALSE_VARIANTS: tuple[tuple[bool, str], ...] = (
    (True, "“{fact}”这个说法是否正确？"),
    (True, "“{action}”通常可以作为处理“{topic}”的轻量起点。这个说法是否正确？"),
    (True, "“{seek_help}”这个求助信号值得认真对待。这个说法是否正确？"),
    (False, "“{misconception} 所以只要忍一忍就会自然消失。”这个说法是否正确？"),
    (False, "“只凭一道测验就能诊断自己是否存在{topic}问题。”这个说法是否正确？"),
)

IMAGE_VARIANTS: tuple[str, ...] = (
    "看这张场景卡，哪种理解更符合心理健康科普？",
    "根据图中的三个线索，更合适的下一步是什么？",
    "这张卡片更像在提醒哪类心理知识点？",
)

GENERAL_DISTRACTORS: tuple[str, ...] = (
    "只要暂时转移注意力，就不需要再观察变化。",
    "先把问题压下去，等完全撑不住时再处理。",
    "把所有反应都归因于性格不好或意志力不够。",
    "不看持续时间和生活影响，只凭一次表现下结论。",
    "把网上看到的描述直接套成自己的诊断。",
    "先要求自己立刻恢复正常，不需要任何支持。",
    "只要别人说没事，就不用继续关注自己的状态。",
    "用羞辱、责备或比较的方式推动自己改变。",
    "把困扰藏起来，不和任何现实中的可信任的人说。",
    "只寻找最严重解释，直到自己更紧张。",
    "把一次测验结果当成最终判断。",
    "认为求助会证明自己失败，所以必须独自处理。",
)

CATEGORY_DISTRACTORS: dict[str, tuple[str, ...]] = {
    "emotion": (
        "情绪一出现就必须马上消除，否则说明自己失控。",
        "只分析道理，不需要注意身体紧绷、心跳或睡眠变化。",
        "把强烈情绪当成事实本身，立刻按冲动行动。",
        "要求自己永远保持平静，才算情绪管理成功。",
        "反复压住感受，不给它任何被命名和整理的机会。",
    ),
    "relationship": (
        "只要对方不高兴，就说明自己的边界一定错了。",
        "为了维持关系，长期忽略自己的不舒服和需要。",
        "用冷处理或威胁代替清楚表达。",
        "把一次冲突直接等同于关系已经失败。",
        "只关注谁对谁错，不看安全、尊重和具体请求。",
    ),
    "sleep": (
        "越睡不着越要强迫自己立刻入睡。",
        "白天状态被影响也不用记录，晚上再硬撑就好。",
        "把睡眠问题完全看成自控力差。",
        "睡前继续高刺激内容，直到困到撑不住。",
        "只看昨晚睡得怎样，不看一段时间的趋势。",
    ),
    "self_help": (
        "自助练习越多越好，不需要根据承受度调整。",
        "只要知道技巧名称，就等于已经改变了模式。",
        "练习时更痛苦也继续硬做，不用停下来评估。",
        "把工具当成必须完美完成的任务。",
        "只做记录，不把下一步缩小到可执行范围。",
    ),
    "safety": (
        "先答应替对方保密，再慢慢观察。",
        "有风险信号时仍优先保持礼貌，不打扰别人。",
        "等问题自己缓解后再考虑现实支持。",
        "把安全风险当成普通情绪波动处理。",
        "只在聊天里安慰，不连接现实中的人或服务。",
    ),
    "teen": (
        "只用成绩好坏判断自己的价值。",
        "遇到压力时完全不告诉可信任的大人。",
        "把一次考试或一次冲突看成无法改变的结论。",
        "为了不麻烦别人，长期隐瞒睡眠和情绪变化。",
        "只靠熬夜补救，不调整任务和支持资源。",
    ),
}

VARIANT_DISTRACTORS: dict[str, tuple[str, ...]] = {
    "概念理解": (
        "把它简化成想太多、太敏感或不够努力。",
        "只记住标签，不看具体情境、持续时间和影响。",
        "认为同一个词在每个人身上都会完全一样。",
        "把心理科普当成诊断书使用。",
    ),
    "第一步": (
        "先反复搜索最严重后果，直到完全安心。",
        "马上要求自己改变所有习惯。",
        "先证明自己不该有这种感受。",
        "直接做高强度挑战，不给自己稳定的缓冲。",
    ),
    "常见误区": (
        "先看具体表现持续多久、是否影响生活。",
        "把困扰放回压力、身体和关系情境里理解。",
        "需要时可以寻求现实或专业支持。",
        "强烈感受不等于人有问题，也不等于必须立刻行动。",
    ),
    "求助信号": (
        "只是偶尔想起这个词，但没有困扰或功能影响。",
        "一次短暂波动后能自然恢复，也没有安全风险。",
        "只是想了解概念，暂时不影响睡眠、学习、工作或关系。",
        "能正常生活，并且已经有稳定支持和恢复方式。",
    ),
    "自助边界": (
        "自助材料可以直接替代医生、治疗师或危机服务。",
        "只要看完科普，就能自己完成诊断和治疗。",
        "遇到安全风险时，继续独自做练习就够了。",
        "所有建议都应该立即照做，不需要结合自身情况。",
    ),
    "支持他人": (
        "马上分析对方哪里做错了。",
        "告诉对方别想太多，很快就会好。",
        "替对方下诊断，再要求对方按你的判断行动。",
        "把对方的困扰转成自己的经历，打断对方表达。",
    ),
}

IMAGE_DISTRACTORS: tuple[str, ...] = (
    "先给自己贴一个确定诊断标签。",
    "继续忍着，不告诉任何现实中的人。",
    "把困扰完全归因于意志力不足。",
    "只看最坏结果，直到确认没有任何风险。",
    "马上要求自己恢复正常，不记录触发线索。",
    "忽略身体和情绪信号，只靠讲道理压下去。",
    "把一次反应当成固定人格缺陷。",
    "先责备自己，再逼自己完成更多任务。",
    "只在网上反复搜索，不连接现实支持。",
    "把求助理解成软弱，所以继续独自硬扛。",
)


def _with_answer(options: list[str], correct_index: int) -> tuple[tuple[str, str], ...]:
    keys = ("A", "B", "C", "D")
    return tuple((key, options[(index - correct_index) % len(options)]) for index, key in enumerate(keys))


def _correct_key(correct_index: int) -> str:
    return ("A", "B", "C", "D")[correct_index]


def _topic_distractors(topic: QuizTopic) -> tuple[str, ...]:
    return (
        f"只要出现“{topic.topic}”相关困扰，就说明一定有严重问题。",
        f"把“{topic.topic}”完全看成个人缺点，不需要考虑压力和支持。",
        f"遇到“{topic.topic}”相关困扰时，先在网上给自己确定诊断。",
        f"只记住“{topic.topic}”这个标签，不记录具体场景和变化。",
        f"别人说“{topic.topic}”没什么，就不必在意自己的真实影响。",
    )


def _misconception_option(topic: QuizTopic, variant_index: int) -> str:
    options = (
        f"把“{topic.topic}”简单理解成想太多、太敏感或不够努力。",
        f"认为只要知道“{topic.topic}”这个标签，就不需要看具体影响。",
        f"把“{topic.topic}”当成必须独自硬扛、不能求助的问题。",
        f"认为“{topic.topic}”出现一两次，就可以直接给自己或别人下诊断。",
        f"把“{topic.topic}”完全归因于性格缺陷，而不看压力、身体和环境。",
        f"觉得“{topic.topic}”只能靠意志力解决，不需要现实支持。",
    )
    return options[variant_index % len(options)]


def _sample_distractors(seed: str, correct: str, candidates: tuple[str, ...], count: int = 3) -> list[str]:
    unique_candidates = list(dict.fromkeys(item for item in candidates if item and item != correct))
    if len(unique_candidates) < count:
        raise ValueError("Not enough unique distractors.")
    digest = sha256(seed.encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    return rng.sample(unique_candidates, count)


def _single_choice_distractors(topic: QuizTopic, variant_name: str, correct: str, variant_index: int) -> list[str]:
    if variant_name == "常见误区":
        candidates = (
            topic.fact,
            topic.action,
            topic.misconception,
            topic.seek_help,
            f"可以先观察“{topic.topic}”持续多久、是否影响睡眠、学习、工作或关系。",
            f"理解“{topic.topic}”时，要把具体场景、身体反应和现实支持一起看。",
            f"如果“{topic.topic}”相关困扰明显影响生活，可以考虑连接专业支持。",
        ) + VARIANT_DISTRACTORS[variant_name]
        return _sample_distractors(f"single:{topic.key}:{variant_name}:{variant_index}", correct, candidates)

    candidates = (
        _topic_distractors(topic)
        + VARIANT_DISTRACTORS[variant_name]
        + CATEGORY_DISTRACTORS.get(topic.category, ())
        + GENERAL_DISTRACTORS
    )
    return _sample_distractors(f"single:{topic.key}:{variant_name}:{variant_index}", correct, candidates)


def _image_distractors(topic: QuizTopic, variant_index: int) -> list[str]:
    candidates = (
        _topic_distractors(topic)
        + CATEGORY_DISTRACTORS.get(topic.category, ())
        + IMAGE_DISTRACTORS
        + GENERAL_DISTRACTORS
    )
    return _sample_distractors(f"image:{topic.key}:{variant_index}", topic.action, candidates)


def _single_choice_question(topic: QuizTopic, variant_index: int) -> QuizQuestion:
    variant_name, stem_template = SINGLE_VARIANTS[variant_index % len(SINGLE_VARIANTS)]
    correct_index = (variant_index + len(topic.key)) % 4
    correct_options = {
        "概念理解": topic.fact,
        "第一步": topic.action,
        "常见误区": _misconception_option(topic, variant_index),
        "求助信号": topic.seek_help,
        "自助边界": f"关于“{topic.topic}”的知识问答只能做科普和自助整理，不能替代诊断、治疗或用药建议。",
        "支持他人": f"先接住对方关于“{topic.topic}”的感受，关注安全，再鼓励对方连接现实支持。",
    }
    correct = correct_options[variant_name]
    options = [correct, *_single_choice_distractors(topic, variant_name, correct, variant_index)]
    return QuizQuestion(
        question_id=f"quiz-{topic.key}-single-{variant_index:02d}",
        type="single_choice",
        topic=topic.topic,
        difficulty=(variant_index % 5) + 1,
        stem=stem_template.format(topic=topic.topic),
        options=_with_answer(options, correct_index),
        correct_answer=_correct_key(correct_index),
        explanation=(
            f"需要避开的说法是：{correct} "
            f"更准确的理解是：{topic.misconception}"
            if variant_name == "常见误区"
            else f"更准确的理解是：{correct} 这类题只用于心理健康科普，不替代专业判断。"
        ),
        source_title=topic.source_title,
        source_url=topic.source_url,
    )


def _true_false_question(topic: QuizTopic, variant_index: int) -> QuizQuestion:
    expected, stem_template = TRUE_FALSE_VARIANTS[variant_index % len(TRUE_FALSE_VARIANTS)]
    answer = "T" if expected else "F"
    return QuizQuestion(
        question_id=f"quiz-{topic.key}-tf-{variant_index:02d}",
        type="true_false",
        topic=topic.topic,
        difficulty=(variant_index % 4) + 1,
        stem=stem_template.format(
            topic=topic.topic,
            fact=topic.fact,
            action=topic.action,
            misconception=topic.misconception,
            seek_help=topic.seek_help,
        ),
        options=(("T", "正确"), ("F", "错误")),
        correct_answer=answer,
        explanation=(
            f"这道题考察“{topic.topic}”的边界：{topic.fact} "
            f"同时要记住，{topic.misconception}"
        ),
        source_title=topic.source_title,
        source_url=topic.source_url,
    )


def _image_question(topic: QuizTopic, variant_index: int) -> QuizQuestion:
    correct_index = (variant_index * 2 + len(topic.topic)) % 4
    options = [topic.action, *_image_distractors(topic, variant_index)]
    return QuizQuestion(
        question_id=f"quiz-{topic.key}-image-{variant_index:02d}",
        type="image",
        topic=topic.topic,
        difficulty=(variant_index % 5) + 1,
        stem=IMAGE_VARIANTS[variant_index % len(IMAGE_VARIANTS)],
        options=_with_answer(options, correct_index),
        correct_answer=_correct_key(correct_index),
        explanation=f"图中线索指向“{topic.topic}”。更稳妥的处理是：{topic.action}",
        source_title=topic.source_title,
        source_url=topic.source_url,
        visual=KnowledgeQuizVisualResponse(kind=topic.visual_kind, title=topic.topic, lines=list(topic.visual_lines)),
    )


def build_quiz_bank() -> list[QuizQuestion]:
    questions: list[QuizQuestion] = []
    for topic in QUIZ_TOPICS:
        questions.extend(_single_choice_question(topic, index) for index in range(24))
        questions.extend(_true_false_question(topic, index) for index in range(10))
        questions.extend(_image_question(topic, index) for index in range(6))
    return questions


QUIZ_BANK: tuple[QuizQuestion, ...] = tuple(build_quiz_bank())


def _question_to_response(question: QuizQuestion) -> KnowledgeQuizQuestionResponse:
    return KnowledgeQuizQuestionResponse(
        question_id=question.question_id,
        type=question.type,
        topic=question.topic,
        difficulty=question.difficulty,
        stem=question.stem,
        options=[KnowledgeQuizOptionResponse(key=key, text=text) for key, text in question.options],
        visual=question.visual,
        source_title=question.source_title,
        source_url=question.source_url,
    )


def _mode_counts(mode: QuizMode) -> dict[QuizQuestionType, int]:
    if mode == "10":
        return {"single_choice": 7, "true_false": 2, "image": 1}
    if mode == "50":
        return {"single_choice": 32, "true_false": 13, "image": 5}
    return {"single_choice": 65, "true_false": 25, "image": 10}


def _seed_to_random(seed: str) -> random.Random:
    digest = sha256(seed.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _parse_session_id(session_id: str) -> tuple[QuizMode, str]:
    parts = session_id.split(":")
    if len(parts) != 3 or parts[0] != "knowledge-quiz" or parts[1] not in {"10", "50", "100"}:
        raise ValueError("Invalid quiz session.")
    return parts[1], parts[2]  # type: ignore[return-value]


def _select_questions(mode: QuizMode, seed: str) -> list[QuizQuestion]:
    rng = _seed_to_random(f"{mode}:{seed}")
    selected: list[QuizQuestion] = []
    for question_type, count in _mode_counts(mode).items():
        pool = [question for question in QUIZ_BANK if question.type == question_type]
        selected.extend(rng.sample(pool, count))
    rng.shuffle(selected)
    return selected


def start_knowledge_quiz(mode: QuizMode) -> KnowledgeQuizSessionResponse:
    seed = uuid4().hex[:12]
    session_id = f"knowledge-quiz:{mode}:{seed}"
    questions = _select_questions(mode, seed)
    return KnowledgeQuizSessionResponse(
        session_id=session_id,
        mode=mode,
        total=len(questions),
        questions=[_question_to_response(question) for question in questions],
    )


def _title_for_score(mode: QuizMode, correct: int) -> tuple[str, str]:
    if mode != "100":
        if correct >= int(mode) * 0.8:
            return "知识热身优秀", "这轮答题说明你对心理健康科普的基本边界比较熟悉。"
        if correct >= int(mode) * 0.6:
            return "知识热身完成", "你已经抓住不少关键点，可以重点看错题解释。"
        return "继续练习", "这轮更适合作为熟悉题型的起点，先看解释再刷下一轮。"

    if correct >= 95:
        return "温柔守护者", "你能稳定识别心理知识、支持边界和求助信号。"
    if correct >= 85:
        return "稳定支持官", "你对常见心理知识和安全边界掌握扎实。"
    if correct >= 75:
        return "自我理解探索者", "你已经能把情绪、认知和关系线索联系起来。"
    if correct >= 60:
        return "心理支持练习生", "你具备基础心理科普意识，继续补足易混点。"
    if correct >= 40:
        return "情绪观察员", "你开始能识别常见情绪和压力信号。"
    return "心理知识萌芽者", "先从基础概念、误区和求助边界继续练习。"


def submit_knowledge_quiz(session_id: str, answers: list[SubmitKnowledgeQuizAnswer]) -> KnowledgeQuizResultResponse:
    mode, seed = _parse_session_id(session_id)
    questions = _select_questions(mode, seed)
    answer_map = {answer.question_id: answer.answer for answer in answers}
    review: list[KnowledgeQuizReviewItem] = []
    correct = 0
    for question in questions:
        user_answer = answer_map.get(question.question_id)
        is_correct = user_answer == question.correct_answer
        if is_correct:
            correct += 1
        review.append(
            KnowledgeQuizReviewItem(
                question_id=question.question_id,
                question=_question_to_response(question),
                is_correct=is_correct,
                user_answer=user_answer,
                correct_answer=question.correct_answer,
                explanation=question.explanation,
                source_title=question.source_title,
                source_url=question.source_url,
            )
        )

    title, title_description = _title_for_score(mode, correct)
    total = len(questions)
    return KnowledgeQuizResultResponse(
        session_id=session_id,
        mode=mode,
        total=total,
        correct=correct,
        accuracy=round(correct / total, 4) if total else 0,
        title=title,
        title_description=title_description,
        review=review,
    )


def get_knowledge_quiz_bank_stats() -> KnowledgeQuizBankStatsResponse:
    by_type: dict[str, int] = {}
    by_topic: dict[str, int] = {}
    for question in QUIZ_BANK:
        by_type[question.type] = by_type.get(question.type, 0) + 1
        by_topic[question.topic] = by_topic.get(question.topic, 0) + 1
    return KnowledgeQuizBankStatsResponse(total=len(QUIZ_BANK), by_type=by_type, by_topic=by_topic)
