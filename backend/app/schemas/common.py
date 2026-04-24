from __future__ import annotations

from enum import Enum


class AgeRange(str, Enum):
    age_13_15 = "13_15"
    age_16_17 = "16_17"
    age_18_plus = "18_plus"


class UserMode(str, Enum):
    teen = "teen"
    adult = "adult"


class ThreadMode(str, Enum):
    companion = "companion"
    knowledge = "knowledge"
    test = "test"
    crisis = "crisis"


class InputType(str, Enum):
    text = "text"
    voice = "voice"
    test = "test"
    system = "system"


class RiskLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class MemoryMode(str, Enum):
    off = "off"
    summary_only = "summary_only"
    long_term = "long_term"


class SafetyAudience(str, Enum):
    all = "all"
    teen = "teen"
    adult = "adult"


def infer_user_mode(age_range: AgeRange | str) -> UserMode:
    value = age_range.value if isinstance(age_range, AgeRange) else age_range
    return UserMode.teen if value in {AgeRange.age_13_15.value, AgeRange.age_16_17.value} else UserMode.adult
