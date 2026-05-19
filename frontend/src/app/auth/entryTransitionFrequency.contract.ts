import {
  getEntryTransitionDayKey,
  markEntryTransitionSeenToday,
  shouldShowEntryTransitionToday,
  type EntryTransitionStorage,
} from "./entryTransitionFrequency";

const assertEqual = (actual: unknown, expected: unknown, message: string) => {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, received ${String(actual)}`);
  }
};

class MemoryStorage implements EntryTransitionStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const storage = new MemoryStorage();
const today = new Date("2026-05-18T08:00:00");
const laterToday = new Date("2026-05-18T22:00:00");
const tomorrow = new Date("2026-05-19T08:00:00");

assertEqual(getEntryTransitionDayKey(today), "2026-05-18", "day key should use the local calendar date");
assertEqual(shouldShowEntryTransitionToday(storage, today), true, "transition should show before today's entry is marked");

markEntryTransitionSeenToday(storage, today);

assertEqual(shouldShowEntryTransitionToday(storage, laterToday), false, "transition should not show again on the same day");
assertEqual(shouldShowEntryTransitionToday(storage, tomorrow), true, "transition should show again on the next local day");
assertEqual(shouldShowEntryTransitionToday(null, today), true, "transition should show when storage is unavailable");
