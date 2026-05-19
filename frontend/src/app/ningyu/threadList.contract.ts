import type { MemoryMode, ThreadListItem, UserMode } from "../../types/api";
import {
  buildConversationList,
  buildDraftThread,
  isProbablyEmptyThread,
  toThreadListItemFromStartThread,
  type ConversationListSection,
} from "./threadList";

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

const makeThread = (overrides: Partial<ThreadListItem> = {}): ThreadListItem => ({
  thread_id: overrides.thread_id ?? crypto.randomUUID(),
  title: overrides.title ?? "新的陪伴对话",
  mode: overrides.mode ?? "companion",
  last_summary: overrides.last_summary ?? null,
  last_risk_level: overrides.last_risk_level ?? "L0",
  updated_at: overrides.updated_at ?? "2026-05-18T08:00:00.000Z",
});

const userMode: UserMode = "teen";
const memoryMode: MemoryMode = "summary_only";
const now = new Date("2026-05-18T12:00:00.000Z");

const emptyThread = makeThread({ thread_id: "empty-1" });
const secondEmptyThread = makeThread({ thread_id: "empty-2", updated_at: "2026-05-18T07:00:00.000Z" });
const summaryThread = makeThread({
  thread_id: "summary-1",
  title: "睡前复盘",
  last_summary: "聊到了睡前焦虑。",
});
const riskThread = makeThread({
  thread_id: "risk-1",
  title: "安全支持",
  last_risk_level: "L2",
});

assertEqual(isProbablyEmptyThread(emptyThread), true, "blank L0 new conversation should be probably empty");
assertEqual(isProbablyEmptyThread(summaryThread), false, "thread with summary should not be probably empty");
assertEqual(isProbablyEmptyThread(riskThread), false, "risk thread should not be probably empty");

const draft = buildDraftThread("2026-05-18T12:00:00.000Z");
const listWithDraft = buildConversationList({
  threads: [emptyThread, secondEmptyThread, summaryThread, riskThread],
  draft,
  displayName: "小宁",
  userMode,
  memoryMode,
  now,
  maxVisibleThreads: 12,
});

assertEqual(listWithDraft.hiddenEmptyThreadCount, 1, "only older duplicate empty thread should be hidden");
assertEqual(listWithDraft.sections[0]?.id, "draft", "draft section should be first");
assertEqual(listWithDraft.sections[0]?.entries[0]?.kind, "draft", "draft entry should be marked as draft");
assertEqual(listWithDraft.sections[1]?.id, "today", "real threads should be grouped after draft");
assert(
  listWithDraft.sections.flatMap((section: ConversationListSection) => section.entries).some((entry) => entry.threadId === "risk-1"),
  "risk thread should remain visible",
);
assert(
  listWithDraft.sections.flatMap((section: ConversationListSection) => section.entries).some((entry) => entry.threadId === "summary-1"),
  "summary thread should remain visible",
);

const fiftyThreads = Array.from({ length: 50 }, (_, index) =>
  makeThread({
    thread_id: `thread-${index}`,
    title: `历史对话 ${index}`,
    last_summary: `摘要 ${index}`,
    updated_at: "2026-05-16T08:00:00.000Z",
  }),
);
const crowdedList = buildConversationList({
  threads: fiftyThreads,
  draft: null,
  displayName: "小宁",
  userMode,
  memoryMode,
  now,
  maxVisibleThreads: 12,
});

assertEqual(crowdedList.visibleThreadCount, 12, "crowded list should show capped recent threads");
assertEqual(crowdedList.overflowThreadCount, 38, "crowded list should report overflow count");
assertEqual(crowdedList.totalThreadCount, 50, "crowded list should keep total count");

const emptyHome = buildConversationList({
  threads: [],
  draft: null,
  displayName: "小宁",
  userMode,
  memoryMode: "off",
  now,
});
assertEqual(emptyHome.sections[0]?.id, "home", "empty state should use home section");
assertEqual(emptyHome.sections[0]?.entries.length, 3, "empty state should preserve three home entries");

const mappedStartThread = toThreadListItemFromStartThread({
  thread_id: "new-1",
  langgraph_thread_id: "lg-new-1",
  title: "新的陪伴对话",
  mode: "companion",
  updated_at: "2026-05-18T12:01:00.000Z",
});
assertEqual(mappedStartThread.thread_id, "new-1", "start thread response should map thread id");
assertEqual(mappedStartThread.last_risk_level, "L0", "start thread response should default risk level");
