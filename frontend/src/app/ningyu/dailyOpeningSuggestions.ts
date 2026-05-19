import type { MemoryMode, MoodLogResponse, MoodTrendResponse, UserMode, WeeklySummaryResponse } from "../../types/api";

const DAILY_OPENING_SUGGESTIONS_SEEN_DAY_PREFIX = "ningyu.dailyOpeningSuggestions.seenDay";

export interface DailyOpeningSuggestion {
  id: string;
  label: string;
  title: string;
  kind: "chat";
}

export interface DailyOpeningSuggestionsInput {
  userMode: UserMode;
  memoryMode: MemoryMode;
  isNight: boolean;
  latestMoodLog: MoodLogResponse | null;
  moodTrend: MoodTrendResponse | null;
  weeklySummary: WeeklySummaryResponse | null;
  hasRecordedMoodToday: boolean;
  now?: Date;
}

export interface DailyOpeningSuggestionVisibilityInput {
  seenDay: string | null;
  suggestions: DailyOpeningSuggestion[];
  now?: Date;
}

export interface DailyOpeningSuggestionStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface DailyOpeningSuggestionSessionInput {
  storage: DailyOpeningSuggestionStorage | null;
  ownerId: string;
  now?: Date;
  sessionKeys: Set<string>;
}

export interface DailyOpeningSuggestionSessionClaim {
  visible: boolean;
  seenDay: string | null;
}

interface SuggestionCandidate {
  id: string;
  label: string;
  title?: string;
}

const fallbackCandidates: SuggestionCandidate[] = [
  {
    id: "unspoken",
    label: "先写一句今天没有说出口的话",
    title: "今天没有说出口的那句话是……",
  },
  {
    id: "body-first",
    label: "从身体最先知道的那个感觉开始",
    title: "身体最先提醒我的感觉是……",
  },
  {
    id: "small-light",
    label: "给此刻的自己留一句很轻的话",
    title: "此刻我想轻轻对自己说……",
  },
];

const tagCandidates: Record<string, SuggestionCandidate> = {
  anxious: {
    id: "tag-anxious",
    label: "把今天最紧的那一刻先放在这里",
    title: "今天最让我发紧的那一刻是……",
  },
  焦虑: {
    id: "tag-anxious-cn",
    label: "把今天最紧的那一刻先放在这里",
    title: "今天最让我发紧的那一刻是……",
  },
  紧张: {
    id: "tag-tense-cn",
    label: "先说说那份紧绷从哪里开始",
    title: "那份紧绷好像是从这里开始的……",
  },
  tired: {
    id: "tag-tired",
    label: "把今天最耗力的一段先放下来",
    title: "今天最耗力的一段是……",
  },
  疲惫: {
    id: "tag-tired-cn",
    label: "把今天最耗力的一段先放下来",
    title: "今天最耗力的一段是……",
  },
  lonely: {
    id: "tag-lonely",
    label: "让那句没人听见的话先有个位置",
    title: "那句好像没人听见的话是……",
  },
  孤单: {
    id: "tag-lonely-cn",
    label: "让那句没人听见的话先有个位置",
    title: "那句好像没人听见的话是……",
  },
  calm: {
    id: "tag-calm",
    label: "把今天稍微稳住你的那一点留下来",
    title: "今天稍微稳住我的那一点是……",
  },
  平静: {
    id: "tag-calm-cn",
    label: "把今天稍微稳住你的那一点留下来",
    title: "今天稍微稳住我的那一点是……",
  },
};

export function getDailyOpeningSuggestionDayKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

export function getDailyOpeningSuggestionOwnerId(userId: string | null | undefined): string {
  return userId?.trim() || "local";
}

export function readDailyOpeningSuggestionsSeenDay(
  storage: DailyOpeningSuggestionStorage | null,
  ownerId: string,
): string | null {
  if (!storage) {
    return null;
  }

  try {
    return storage.getItem(getDailyOpeningSuggestionStorageKey(ownerId));
  } catch {
    return null;
  }
}

export function markDailyOpeningSuggestionsSeenToday(
  storage: DailyOpeningSuggestionStorage | null,
  ownerId: string,
  date = new Date(),
): string | null {
  if (!storage) {
    return null;
  }

  const dayKey = getDailyOpeningSuggestionDayKey(date);

  try {
    storage.setItem(getDailyOpeningSuggestionStorageKey(ownerId), dayKey);
    return dayKey;
  } catch {
    return null;
  }
}

export function shouldShowDailyOpeningSuggestions({
  seenDay,
  suggestions,
  now = new Date(),
}: DailyOpeningSuggestionVisibilityInput): boolean {
  return suggestions.length > 0 && seenDay !== getDailyOpeningSuggestionDayKey(now);
}

export function claimDailyOpeningSuggestionsForSession({
  storage,
  ownerId,
  now = new Date(),
  sessionKeys,
}: DailyOpeningSuggestionSessionInput): DailyOpeningSuggestionSessionClaim {
  const today = getDailyOpeningSuggestionDayKey(now);
  const sessionKey = getDailyOpeningSuggestionSessionKey(ownerId, today);
  const seenDay = readDailyOpeningSuggestionsSeenDay(storage, ownerId);

  if (sessionKeys.has(sessionKey)) {
    return { visible: true, seenDay: seenDay ?? today };
  }

  if (seenDay === today) {
    return { visible: false, seenDay };
  }

  const markedDay = markDailyOpeningSuggestionsSeenToday(storage, ownerId, now) ?? seenDay;
  sessionKeys.add(sessionKey);

  return { visible: true, seenDay: markedDay };
}

export function dismissDailyOpeningSuggestionsForSession({
  ownerId,
  now = new Date(),
  sessionKeys,
}: Omit<DailyOpeningSuggestionSessionInput, "storage">): void {
  sessionKeys.delete(getDailyOpeningSuggestionSessionKey(ownerId, getDailyOpeningSuggestionDayKey(now)));
}

export function getDailyOpeningSuggestionStorage(): DailyOpeningSuggestionStorage | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function buildDailyOpeningSuggestions({
  userMode,
  memoryMode,
  isNight,
  latestMoodLog,
  moodTrend,
  weeklySummary,
  hasRecordedMoodToday,
}: DailyOpeningSuggestionsInput): DailyOpeningSuggestion[] {
  const candidates: SuggestionCandidate[] = [];
  const tags = collectTags(moodTrend, weeklySummary);
  const tagCandidate = tags.map((tag) => tagCandidates[tag]).find(Boolean);
  const weeklyAction = normalizeWeeklyAction(weeklySummary);

  if (tagCandidate) {
    candidates.push(tagCandidate);
  }

  if (weeklySummary?.generated_by === "llm" && weeklyAction) {
    candidates.push({
      id: "weekly-model-action",
      label: `顺着这周小结，先聊聊「${weeklyAction}」`,
      title: `我想先聊聊这周反复出现的这件事：${weeklyAction}`,
    });
  } else if (weeklySummary?.generated_by === "llm" && weeklySummary.summary.trim()) {
    candidates.push({
      id: "weekly-model-summary",
      label: "顺着这周小结，挑一句最像今天的感受",
      title: "这周小结里最像今天的一句感受是……",
    });
  }

  if (latestMoodLog && latestMoodLog.mood_score <= 2) {
    candidates.push({
      id: "low-score",
      label: "只说今天最难的那一小块就好",
      title: "今天最难的那一小块是……",
    });
  } else if (latestMoodLog && latestMoodLog.mood_score >= 4) {
    candidates.push({
      id: "steady-score",
      label: "把今天让你松一点的时刻留下来",
      title: "今天让我松一点的时刻是……",
    });
  }

  if (isNight) {
    candidates.push({
      id: "night",
      label: "从今晚最放不下的一小段开始",
      title: "今晚最放不下的那一小段是……",
    });
  } else {
    candidates.push({
      id: "day",
      label: "从今天反复回来的那个念头开始",
      title: "今天反复回来的那个念头是……",
    });
  }

  if (!hasRecordedMoodToday) {
    candidates.push({
      id: "unrecorded-mood",
      label: "先给今天的心情取一个名字",
      title: "如果给今天的心情取一个名字，它会叫……",
    });
  }

  if (memoryMode === "off") {
    candidates.push({
      id: "memory-off",
      label: "只说这一刻，不必把它留得很久",
      title: "这一刻我想说的是……",
    });
  }

  if (userMode === "teen") {
    candidates.push({
      id: "teen-support",
      label: "想想哪位真实的人可以稍微知道一点",
      title: "我想到一个可以稍微知道这件事的人是……",
    });
  }

  candidates.push(...fallbackCandidates);

  return uniqueCandidates(candidates)
    .slice(0, 3)
    .map((candidate) => ({
      id: candidate.id,
      label: candidate.label,
      title: candidate.title ?? candidate.label,
      kind: "chat" as const,
    }));
}

function collectTags(moodTrend: MoodTrendResponse | null, weeklySummary: WeeklySummaryResponse | null): string[] {
  const tags = [
    ...(moodTrend?.daily.at(-1)?.tags ?? []),
    ...(moodTrend?.top_tags ?? []),
    ...(weeklySummary?.top_tags ?? []),
  ];

  return tags.map((tag) => tag.trim()).filter(Boolean);
}

function normalizeWeeklyAction(weeklySummary: WeeklySummaryResponse | null): string | null {
  const action = weeklySummary?.suggested_actions.find((item) => item.trim());
  if (!action) {
    return null;
  }

  const compactAction = action.replace(/\s+/g, " ").trim();
  return compactAction.length > 22 ? `${compactAction.slice(0, 22)}…` : compactAction;
}

function uniqueCandidates(candidates: SuggestionCandidate[]): SuggestionCandidate[] {
  const seenLabels = new Set<string>();
  const unique: SuggestionCandidate[] = [];

  for (const candidate of candidates) {
    const label = candidate.label.trim();
    if (!label || seenLabels.has(label)) {
      continue;
    }

    seenLabels.add(label);
    unique.push({ ...candidate, label });
  }

  return unique;
}

function getDailyOpeningSuggestionStorageKey(ownerId: string): string {
  return `${DAILY_OPENING_SUGGESTIONS_SEEN_DAY_PREFIX}.${ownerId}`;
}

function getDailyOpeningSuggestionSessionKey(ownerId: string, dayKey: string): string {
  return `${ownerId}:${dayKey}`;
}
