from __future__ import annotations

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
    if normalized_query in article.title.lower():
        score += 50
    if normalized_query in " ".join(article.tags or []).lower():
        score += 35
    if normalized_query in article.category.lower():
        score += 20
    if normalized_query in article.summary_30s.lower():
        score += 15
    if normalized_query in article.explanation_3min.lower():
        score += 8

    for token in normalized_query.split():
        if token and token in _article_blob(article):
            score += 4

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

    related = search_articles(db, query=question, limit=3).items
    if not related:
        related = search_articles(db, query="", limit=3).items

    article = get_article(db, related[0].article_id) if related else None
    if article is None:
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

    context_tail = " 如果这和你自己的近况有关，可以把具体场景带回对话里继续拆小。" if use_my_context else ""
    return AskKnowledgeResponse(
        answer=KnowledgeAnswer(
            summary_30s=article.summary_30s,
            explanation_3min=f"{article.explanation_3min}{context_tail}",
            actions=list(article.actions or [])[:3],
            seek_help_when=list(article.seek_help_when or [])[:3],
        ),
        related_articles=related,
        continue_chat_payload=ContinueChatPayload(
            mode="knowledge",
            context_type="knowledge_article",
            article_id=article.id,
            thread_id=thread_id,
        ),
        risk_level=risk_level,
    )
