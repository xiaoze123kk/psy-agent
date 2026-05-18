import type { MoodLogResponse, MoodTrendResponse } from "../../types/api";

const MOOD_CHECK_IN_RECORDED_DAY_KEY_PREFIX = "ningyu.moodCheckIn.recordedDay";

export interface MoodCheckInStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface MoodCheckInTodayInput {
  recordedDay?: string | null;
  latestMoodLog?: MoodLogResponse | null;
  moodTrend?: MoodTrendResponse | null;
  now?: Date;
}

export interface MoodCheckInControlStateInput {
  hasRecordedMoodToday: boolean;
}

export function getMoodCheckInDayKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

export function getMoodCheckInOwnerId(userId: string | null | undefined): string {
  return userId?.trim() || "local";
}

export function readRecordedMoodCheckInDay(storage: MoodCheckInStorage | null, ownerId: string): string | null {
  if (!storage) {
    return null;
  }

  try {
    return storage.getItem(getMoodCheckInStorageKey(ownerId));
  } catch {
    return null;
  }
}

export function markMoodCheckInRecordedToday(storage: MoodCheckInStorage | null, ownerId: string, date = new Date()): string | null {
  if (!storage) {
    return null;
  }

  const dayKey = getMoodCheckInDayKey(date);

  try {
    storage.setItem(getMoodCheckInStorageKey(ownerId), dayKey);
    return dayKey;
  } catch {
    return null;
  }
}

export function hasMoodCheckInForToday({
  recordedDay,
  latestMoodLog,
  moodTrend,
  now = new Date(),
}: MoodCheckInTodayInput): boolean {
  const today = getMoodCheckInDayKey(now);

  if (recordedDay === today) {
    return true;
  }

  if (latestMoodLog && getMoodCheckInDayKey(new Date(latestMoodLog.created_at)) === today) {
    return true;
  }

  return Boolean(moodTrend?.daily.some((point) => point.date === today));
}

export function shouldShowMoodCheckInControls({ hasRecordedMoodToday }: MoodCheckInControlStateInput): boolean {
  return !hasRecordedMoodToday;
}

export function getMoodCheckInStorage(): MoodCheckInStorage | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function getMoodCheckInStorageKey(ownerId: string): string {
  return `${MOOD_CHECK_IN_RECORDED_DAY_KEY_PREFIX}.${ownerId}`;
}
