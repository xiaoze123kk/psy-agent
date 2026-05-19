export interface OnboardingSafetyNoteCopy {
  bullets: string[];
  boundaryNote: string;
}

export function getOnboardingSafetyNoteCopy(): OnboardingSafetyNoteCopy {
  return {
    bullets: [
      "这不是医疗诊断，不能替代专业医生。",
      "你可以随时退出或跳过问题。",
      "如有危险想法，宁语会引导联系专业帮助。",
    ],
    boundaryNote:
      "宁语只提供陪伴、记录和自助支持，不做诊断。你可以选择让它记住摘要、关闭记忆，或之后在设置里重新调整。",
  };
}
