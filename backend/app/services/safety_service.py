from __future__ import annotations

from app.schemas.common import SafetyAudience
from app.schemas.safety import SafetyResourceItem, SafetyResourcesResponse


def _build_resources(region: str, audience: SafetyAudience) -> list[SafetyResourceItem]:
    common_items = [
        SafetyResourceItem(
            resource_type="trusted_person",
            title="联系现实中的可信任对象",
            description="优先联系家人、朋友、同住人，或此刻能到场陪你的人，不要一个人扛着。",
        ),
        SafetyResourceItem(
            resource_type="emergency",
            title="必要时联系当地紧急服务",
            description=f"如果你在 {region} 且已经处于紧急危险，请立刻联系当地急救或报警资源。",
        ),
    ]
    teen_items = [
        SafetyResourceItem(
            resource_type="school",
            title="联系可信任的大人",
            description="优先联系监护人、班主任、任课老师、学校心理老师或辅导员。",
        )
    ]
    adult_items = [
        SafetyResourceItem(
            resource_type="adult_support",
            title="联系成年支持系统",
            description="联系伴侣、家人、朋友、同事，或尽快寻求线下专业支持。",
        )
    ]
    if audience == SafetyAudience.teen:
        return teen_items + common_items
    if audience == SafetyAudience.adult:
        return adult_items + common_items
    return common_items


def build_safety_resources(
    *,
    region: str = "CN",
    audience: SafetyAudience = SafetyAudience.all,
) -> SafetyResourcesResponse:
    return SafetyResourcesResponse(
        region=region,
        audience=audience,
        items=_build_resources(region, audience),
    )

