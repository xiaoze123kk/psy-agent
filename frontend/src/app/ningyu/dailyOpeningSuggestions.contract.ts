import type { MemoryMode, MoodLogResponse, MoodTrendResponse, UserMode, WeeklySummaryResponse } from "../../types/api";
import {
  buildDailyOpeningSuggestions,
  claimDailyOpeningSuggestionsForSession,
  dismissDailyOpeningSuggestionsForSession,
  getDailyOpeningSuggestionDayKey,
  getDailyOpeningSuggestionOwnerId,
  markDailyOpeningSuggestionsSeenToday,
  readDailyOpeningSuggestionsSeenDay,
  shouldShowDailyOpeningSuggestions,
} from "./dailyOpeningSuggestions";

const assertEqual = (actual: unknown, expected: unknown, message: string) => {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, received ${String(actual)}`);
  }
};

const assert = (condition: boolean, message: string) => {
  if (!condition) {
    throw new Error(message);
  }
};

class MemoryStorage {
  private values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const userMode: UserMode = "adult";
const memoryMode: MemoryMode = "summary_only";
const now = new Date("2026-05-18T09:30:00");
const yesterday = new Date("2026-05-17T23:30:00");
const ownerId = getDailyOpeningSuggestionOwnerId("user-1");
const storage = new MemoryStorage();

assertEqual(getDailyOpeningSuggestionDayKey(now), "2026-05-18", "day key should use local date");
assertEqual(ownerId, "user-1", "owner should prefer user id");
assertEqual(
  shouldShowDailyOpeningSuggestions({
    seenDay: null,
    suggestions: [{ id: "one", label: "先说一句今天没有说出口的话", title: "先说一句今天没有说出口的话", kind: "chat" }],
    now,
  }),
  true,
  "unseen daily suggestions should be visible",
);
assertEqual(
  shouldShowDailyOpeningSuggestions({
    seenDay: getDailyOpeningSuggestionDayKey(now),
    suggestions: [{ id: "one", label: "先说一句今天没有说出口的话", title: "先说一句今天没有说出口的话", kind: "chat" }],
    now,
  }),
  false,
  "seen daily suggestions should be hidden on the same day",
);
assertEqual(
  shouldShowDailyOpeningSuggestions({
    seenDay: getDailyOpeningSuggestionDayKey(yesterday),
    suggestions: [{ id: "one", label: "先说一句今天没有说出口的话", title: "先说一句今天没有说出口的话", kind: "chat" }],
    now,
  }),
  true,
  "yesterday's marker should not hide today's suggestions",
);

markDailyOpeningSuggestionsSeenToday(storage, ownerId, now);
assertEqual(
  readDailyOpeningSuggestionsSeenDay(storage, ownerId),
  "2026-05-18",
  "storage marker should keep today's date",
);

const strictModeStorage = new MemoryStorage();
const strictModeSessionKeys = new Set<string>();
const firstClaim = claimDailyOpeningSuggestionsForSession({
  storage: strictModeStorage,
  ownerId,
  now,
  sessionKeys: strictModeSessionKeys,
});
const secondClaim = claimDailyOpeningSuggestionsForSession({
  storage: strictModeStorage,
  ownerId,
  now,
  sessionKeys: strictModeSessionKeys,
});
assertEqual(firstClaim.visible, true, "first claim should show suggestions");
assertEqual(secondClaim.visible, true, "second claim in the same session should stay visible");
dismissDailyOpeningSuggestionsForSession({ ownerId, now, sessionKeys: strictModeSessionKeys });
const afterDismissClaim = claimDailyOpeningSuggestionsForSession({
  storage: strictModeStorage,
  ownerId,
  now,
  sessionKeys: strictModeSessionKeys,
});
assertEqual(afterDismissClaim.visible, false, "dismissed suggestions should stay hidden in the same session");
const refreshClaim = claimDailyOpeningSuggestionsForSession({
  storage: strictModeStorage,
  ownerId,
  now,
  sessionKeys: new Set<string>(),
});
assertEqual(refreshClaim.visible, false, "a new page session should hide already seen suggestions");

const latestMoodLog: MoodLogResponse = {
  log_id: "mood-1",
  created_at: "2026-05-18T08:30:00.000Z",
  mood_score: 2,
};
const moodTrend: MoodTrendResponse = {
  range: "7d",
  avg_mood_score: 2.4,
  top_tags: ["anxious", "tired", "lonely"],
  daily: [{ date: "2026-05-18", mood_score: 2, tags: ["anxious", "tired"] }],
  summary: "最近情绪偏低，焦虑和疲惫出现较多。",
};
const weeklySummary: WeeklySummaryResponse = {
  range: "7d",
  summary: "这一周你的压力像是反复在学习和睡前回来，但你也在尝试把它说出来。",
  top_tags: ["anxious", "tired"],
  suggested_actions: ["把睡前最难放下的念头写成一句话", "给今天留一个低刺激收尾"],
  generated_by: "llm",
};

const suggestions = buildDailyOpeningSuggestions({
  userMode,
  memoryMode,
  isNight: true,
  latestMoodLog,
  moodTrend,
  weeklySummary,
  hasRecordedMoodToday: true,
  now,
});

assertEqual(suggestions.length, 3, "daily opening should always provide three choices");
assertEqual(new Set(suggestions.map((suggestion) => suggestion.label)).size, 3, "suggestions should be unique");
assert(
  suggestions.some((suggestion) => suggestion.label.includes("紧") || suggestion.label.includes("焦虑")),
  "suggestions should reflect the anxious context",
);
assert(
  suggestions.some((suggestion) => suggestion.label.includes("睡前") || suggestion.label.includes("这周")),
  "suggestions should use weekly model context when available",
);

const oldStaticLabels = new Set([
  "写下此刻最想被听见的一句话",
  "用三句话卸下今晚的压力",
  "试试 30 秒呼吸练习",
  "把问题拆成一个很小的下一步",
  "想想一个可以联系的可信任大人",
]);
assert(
  suggestions.every((suggestion) => !oldStaticLabels.has(suggestion.label)),
  "daily opening suggestions should not reuse the old static trio",
);
