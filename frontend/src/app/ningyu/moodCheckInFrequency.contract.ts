import type { MoodLogResponse, MoodTrendResponse } from "../../types/api";
import {
  getMoodCheckInDayKey,
  hasMoodCheckInForToday,
  markMoodCheckInRecordedToday,
  readRecordedMoodCheckInDay,
  shouldShowMoodCheckInControls,
  type MoodCheckInStorage,
} from "./moodCheckInFrequency";

const assertEqual = (actual: unknown, expected: unknown, message: string) => {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, received ${String(actual)}`);
  }
};

class MemoryStorage implements MoodCheckInStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const today = new Date("2026-05-18T09:00:00");
const laterToday = new Date("2026-05-18T21:00:00");
const tomorrow = new Date("2026-05-19T09:00:00");
const ownerId = "user-1";
const storage = new MemoryStorage();

assertEqual(getMoodCheckInDayKey(today), "2026-05-18", "day key should use local date");
assertEqual(readRecordedMoodCheckInDay(storage, ownerId), null, "missing storage marker should be null");

markMoodCheckInRecordedToday(storage, ownerId, today);

assertEqual(readRecordedMoodCheckInDay(storage, ownerId), "2026-05-18", "storage marker should keep today's date");
assertEqual(
  hasMoodCheckInForToday({ recordedDay: readRecordedMoodCheckInDay(storage, ownerId), now: laterToday }),
  true,
  "local marker should count as today's record",
);
assertEqual(
  hasMoodCheckInForToday({ recordedDay: readRecordedMoodCheckInDay(storage, ownerId), now: tomorrow }),
  false,
  "local marker should not lock the next day",
);

const latestLog: MoodLogResponse = {
  log_id: "mood-1",
  created_at: "2026-05-18T02:00:00.000Z",
  mood_score: 4,
};
assertEqual(
  hasMoodCheckInForToday({ latestMoodLog: latestLog, now: new Date("2026-05-18T12:00:00") }),
  true,
  "latest mood log from today should count as recorded",
);

const trend: MoodTrendResponse = {
  range: "7d",
  avg_mood_score: 4,
  top_tags: [],
  daily: [{ date: "2026-05-18", mood_score: 4, tags: ["calm"] }],
  summary: "",
};
assertEqual(
  hasMoodCheckInForToday({ moodTrend: trend, now: today }),
  true,
  "trend point for today should count as recorded",
);
assertEqual(shouldShowMoodCheckInControls({ hasRecordedMoodToday: false }), true, "open check-in should show controls");
assertEqual(shouldShowMoodCheckInControls({ hasRecordedMoodToday: true }), false, "recorded check-in should hide controls");
