const ENTRY_TRANSITION_SEEN_DAY_KEY = "ningyu.entryTransition.seenDay";

export interface EntryTransitionStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function getEntryTransitionDayKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

export function shouldShowEntryTransitionToday(storage = getEntryTransitionStorage(), date = new Date()): boolean {
  if (!storage) {
    return true;
  }

  try {
    return storage.getItem(ENTRY_TRANSITION_SEEN_DAY_KEY) !== getEntryTransitionDayKey(date);
  } catch {
    return true;
  }
}

export function markEntryTransitionSeenToday(storage = getEntryTransitionStorage(), date = new Date()): void {
  if (!storage) {
    return;
  }

  try {
    storage.setItem(ENTRY_TRANSITION_SEEN_DAY_KEY, getEntryTransitionDayKey(date));
  } catch {
    // Storage can be blocked in private or restricted contexts; the transition should still let users enter.
  }
}

function getEntryTransitionStorage(): EntryTransitionStorage | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
