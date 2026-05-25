from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_TIMEZONE = "Asia/Wuhan"
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _day_period(hour: int) -> str:
    if 5 <= hour < 6:
        return "清晨"
    if 6 <= hour < 9:
        return "早上"
    if 9 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 20:
        return "傍晚"
    if 20 <= hour < 23:
        return "晚上"
    return "深夜"


def _companion_hint(period: str) -> str:
    hints = {
        "清晨": "清晨可以轻轻问候，但不要打扰式催促。",
        "早上": "早上可以自然说早上好，语气轻一点。",
        "上午": "上午可以保持清醒、稳定的陪伴感。",
        "中午": "中午可以轻轻提醒吃点东西或歇一下。",
        "下午": "下午适合贴着当前话题回应，不要误说成傍晚或夜里。",
        "傍晚": "傍晚可以让语气慢一点，给一点收束感。",
        "晚上": "晚上可以放慢节奏，必要时轻轻提醒休息。",
        "深夜": "深夜可以轻提醒别太熬、早点睡，但不要说教。",
    }
    return hints.get(period, "按当前时间自然回应，不要猜时间。")


def build_temporal_context(*, now: datetime | None = None, timezone_name: str = DEFAULT_TIMEZONE) -> dict[str, Any]:
    current_utc = now or datetime.now(timezone.utc)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=timezone.utc)
    current_utc = current_utc.astimezone(timezone.utc)
    local = current_utc.astimezone(LOCAL_TIMEZONE)
    period = _day_period(local.hour)
    return {
        "utc_iso": current_utc.isoformat(),
        "local_iso": local.strftime("%Y-%m-%d %H:%M:%S"),
        "local_date": local.strftime("%Y-%m-%d"),
        "local_time": local.strftime("%H:%M"),
        "timezone": timezone_name or DEFAULT_TIMEZONE,
        "weekday": WEEKDAY_NAMES[local.weekday()],
        "day_period": period,
        "companion_hint": _companion_hint(period),
    }
