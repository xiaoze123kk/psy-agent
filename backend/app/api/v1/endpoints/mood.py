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
from app.schemas.mood import DailyMoodPoint, MoodLogRequest, MoodLogResponse, MoodTrendResponse


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
