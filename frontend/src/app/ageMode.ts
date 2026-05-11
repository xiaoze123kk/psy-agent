import type { AgeRange, UserMode } from "../types/api";

export interface AgeModeProfile {
  ageRange: AgeRange;
  ageLabel: string;
  userMode: UserMode;
  modeLabel: string;
  description: string;
}

export const ageRangeLabels: Record<AgeRange, string> = {
  "13_15": "13-15 岁",
  "16_17": "16-17 岁",
  "18_plus": "18 岁及以上",
};

export const userModeLabels: Record<UserMode, string> = {
  teen: "青少年模式",
  adult: "成人模式",
};

const userModeDescriptions: Record<UserMode, string> = {
  teen: "更重视安全边界、可信任成人提示和温和陪伴。",
  adult: "以自主设置、隐私管理和持续自助支持为主。",
};

export function inferUserModeFromAgeRange(ageRange: AgeRange): UserMode {
  return ageRange === "18_plus" ? "adult" : "teen";
}

export function buildAgeModeProfile(ageRange: AgeRange, returnedUserMode?: UserMode | null): AgeModeProfile {
  const userMode = returnedUserMode ?? inferUserModeFromAgeRange(ageRange);

  return {
    ageRange,
    ageLabel: ageRangeLabels[ageRange],
    userMode,
    modeLabel: userModeLabels[userMode],
    description: userModeDescriptions[userMode],
  };
}
