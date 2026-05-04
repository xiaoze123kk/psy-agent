from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import MoodLog, User
from app.db.session import get_db_session
from app.schemas.mood import DailyMoodPoint, MoodLogRequest, MoodLogResponse, MoodTrendResponse, WeeklySummaryResponse
from app.services.deepseek_client import deepseek_client


router = APIRouter(prefix="/moods", tags=["mood"])


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("", response_model=MoodLogResponse)
async def create_mood_log(
    payload: MoodLogRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MoodLogResponse:
    log = MoodLog(
        user_id=current_user.id,
        mood_score=payload.mood_score,
        anxiety_score=payload.anxiety_score,
        energy_score=payload.energy_score,
        sleep_quality=payload.sleep_quality,
        mood_tags=list(payload.mood_tags),
        note=payload.note,
        source="checkin",
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return MoodLogResponse(log_id=log.id, created_at=log.created_at, mood_score=log.mood_score)


def _generate_fallback_actions(top_tags: list[str]) -> list[str]:
    action_map: dict[str, list[str]] = {
        "焦虑": [
            "选一天提前30分钟结束学习或工作任务",
            "做一次3分钟的呼吸练习",
            "把担心的事情写下来再回看",
        ],
        "疲惫": [
            "睡前做一次低刺激放松（如听轻音乐或白噪音）",
            "给自己一个不被打扰的休息时段",
            "减少一件不需要今天就完成的事",
        ],
        "难过": [
            "给自己留出15分钟安静地感受这份情绪",
            "试着向一个信任的人说一句‘我今天不太好’",
            "看一部能让你感到温暖的电影或书",
        ],
        "委屈": [
            "把想说的话写给自己看，不需要修饰",
            "给自己一会儿完全属于自己的时间",
            "确认一下是不是有些需要没有被说出来",
        ],
        "压力": [
            "把待办事项分成‘必须做’和‘可以等等’两类",
            "做一次60秒深呼吸，注意力放在呼吸的节奏上",
            "找一个安静的地方短暂离开当前环境",
        ],
        "生气": [
            "先离开当前环境3分钟，让身体先降下来",
            "做一次简短的快走或拉伸",
            "把生气的原因写下来，等情绪降下来再回看",
        ],
        "空虚": [
            "尝试做一件有具体结果的小事（如整理书桌）",
            "给一个朋友发一句简单问候",
            "感受一下是否在回避某种真实需求",
        ],
        "失眠": [
            "睡前一小时减少手机和屏幕时间",
            "尝试4-7-8呼吸法：吸气4秒、屏息7秒、呼气8秒",
            "如果躺下20分钟睡不着，起来做一件安静的事再回去睡",
        ],
    }
    actions: list[str] = []
    for tag in top_tags:
        if tag in action_map:
            actions.extend(action_map[tag][:1])
    if not actions:
        actions = ["给自己一个轻松的时段，不做任何需要努力的事", "试着记录接下来三天的情绪变化"]
    return actions[:4]


def _build_fallback_summary(avg_score: float, top_tags: list[str], log_count: int) -> str:
    if log_count == 0:
        return "这周还没有情绪记录。当你准备好了，随时可以做一次情绪检查。"
    if avg_score >= 4.0:
        return "这周你的情绪整体比较平稳，积极的时刻比困难时刻多。继续保持对自己的关照。"
    if avg_score >= 3.0:
        return "这周你的情绪有起伏，有时感到轻松，有时感到压力。这是很正常的波动，不必苛责自己。"
    if avg_score >= 2.0:
        return "这周你的情绪整体偏紧绷，焦虑和疲惫出现得比较多。给自己多一些温柔的关照，你不需要一个人扛着。"
    return "这周你过得不太容易。很多情绪可能堆积在一起了。你不需要一个人扛着——如果需要，可以向信任的人或专业资源寻求支持。"


@router.get("/trends", response_model=MoodTrendResponse)
async def get_mood_trend(
    range: Literal["7d", "30d"] = Query(default="7d"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MoodTrendResponse:
    days = 30 if range == "30d" else 7
    since = datetime.now(timezone.utc) - timedelta(days=days)
    logs = list(
        db.scalars(
            select(MoodLog)
            .where(MoodLog.user_id == current_user.id, MoodLog.created_at >= since)
            .order_by(MoodLog.created_at.asc())
        )
    )

    if not logs:
        return MoodTrendResponse(
            range=range,
            avg_mood_score=0,
            top_tags=[],
            daily=[],
            summary="当前时间范围内还没有情绪记录。",
        )

    avg_mood = round(sum(log.mood_score for log in logs) / len(logs), 2)
    tag_counter: Counter[str] = Counter()
    daily_scores: dict[str, list[int]] = defaultdict(list)
    daily_tags: dict[str, Counter[str]] = defaultdict(Counter)

    for log in logs:
        day = _to_utc(log.created_at).date().isoformat()
        daily_scores[day].append(log.mood_score)
        for tag in log.mood_tags or []:
            normalized_tag = tag.strip() if isinstance(tag, str) else ""
            if normalized_tag:
                tag_counter[normalized_tag] += 1
                daily_tags[day][normalized_tag] += 1

    daily = [
        DailyMoodPoint(
            date=day,
            mood_score=round(sum(scores) / len(scores), 2),
            tags=[tag for tag, _ in daily_tags[day].most_common(3)],
        )
        for day, scores in sorted(daily_scores.items())
    ]
    top_tags = [tag for tag, _ in tag_counter.most_common(5)]

    summary = f"最近 {days} 天共记录 {len(logs)} 次情绪，平均情绪分为 {avg_mood}。"
    if top_tags:
        summary += f" 高频标签主要是：{'、'.join(top_tags[:3])}。"

    return MoodTrendResponse(
        range=range,
        avg_mood_score=avg_mood,
        top_tags=top_tags,
        daily=daily,
        summary=summary,
    )


@router.get("/weekly-summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> WeeklySummaryResponse:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    logs = list(
        db.scalars(
            select(MoodLog)
            .where(MoodLog.user_id == current_user.id, MoodLog.created_at >= since)
            .order_by(MoodLog.created_at.asc())
        )
    )

    if not logs:
        return WeeklySummaryResponse(
            range="7d",
            summary="这周还没有情绪记录。当你准备好了，随时可以做一次情绪检查。",
            top_tags=[],
            suggested_actions=["试试记录今天的心情", "给自己一个轻松的时段"],
            generated_by="fallback",
        )

    avg_mood = round(sum(log.mood_score for log in logs) / len(logs), 2)
    tag_counter: Counter[str] = Counter()
    for log in logs:
        for tag in log.mood_tags or []:
            normalized_tag = tag.strip() if isinstance(tag, str) else ""
            if normalized_tag:
                tag_counter[normalized_tag] += 1
    top_tags = [tag for tag, _ in tag_counter.most_common(5)]
    suggested_actions = _generate_fallback_actions(top_tags)
    fallback_summary = _build_fallback_summary(avg_mood, top_tags, len(logs))

    # Try LLM generation if configured
    if deepseek_client.is_configured:
        try:
            tag_list = "、".join(top_tags) if top_tags else "无明显标签"
            llm_prompt = (
                f"用户最近7天的情绪记录概况：共记录{len(logs)}次，平均情绪分{avg_mood:.1f}/5，"
                f"高频情绪标签：{tag_list}。"
                f"请用温和、不评判的语气，写一段50-80字的每周情绪小结。"
                f"不使用诊断措辞，只做观察和温和建议。保持鼓励和支持的态度。"
            )
            llm_summary = await deepseek_client.chat(
                [{"role": "user", "content": llm_prompt}],
                temperature=0.7,
                max_tokens=200,
            )
            if llm_summary and len(llm_summary.strip()) >= 10:
                return WeeklySummaryResponse(
                    range="7d",
                    summary=llm_summary.strip(),
                    top_tags=top_tags,
                    suggested_actions=suggested_actions,
                    generated_by="llm",
                )
        except Exception:
            pass  # fall through to fallback

    return WeeklySummaryResponse(
        range="7d",
        summary=fallback_summary,
        top_tags=top_tags,
        suggested_actions=suggested_actions,
        generated_by="fallback",
    )
