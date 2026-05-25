import type { MemoryMode, StartThreadResponse, ThreadListItem, UserMode } from "../../types/api";

export interface DraftThread {
  id: "local-draft";
  title: string;
  createdAt: string;
}

export type ConversationListEntryKind = "draft" | "thread" | "home";

export interface ConversationListEntry {
  id: string;
  kind: ConversationListEntryKind;
  title: string;
  time: string;
  preview: string;
  mode?: string;
  riskLevel?: string;
  threadId?: string;
}

export interface ConversationListSection {
  id: "draft" | "today" | "week" | "earlier" | "home";
  label: string;
  countLabel?: string;
  entries: ConversationListEntry[];
}

export interface ConversationListBuildResult {
  sections: ConversationListSection[];
  hiddenEmptyThreadCount: number;
  overflowThreadCount: number;
  totalThreadCount: number;
  visibleThreadCount: number;
}

interface BuildConversationListInput {
  threads: ThreadListItem[];
  draft: DraftThread | null;
  displayName: string;
  userMode: UserMode;
  memoryMode: MemoryMode;
  now?: Date;
  maxVisibleThreads?: number;
}

const EMPTY_THREAD_TITLES = new Set(["新的陪伴对话", "未命名对话", "new session"]);
const DEFAULT_MAX_VISIBLE_THREADS = 12;

const userModeLabels: Record<UserMode, string> = {
  teen: "青少年安全陪伴已开启",
  adult: "标准陪伴空间已准备",
};

export function buildDraftThread(createdAt = new Date().toISOString()): DraftThread {
  return {
    id: "local-draft",
    title: "新的陪伴对话",
    createdAt,
  };
}

export function isProbablyEmptyThread(thread: ThreadListItem): boolean {
  return (
    thread.last_summary === null &&
    thread.last_risk_level === "L0" &&
    EMPTY_THREAD_TITLES.has((thread.title || "").trim())
  );
}

export function formatThreadTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "最近";
  }

  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function toThreadListItemFromStartThread(thread: StartThreadResponse): ThreadListItem {
  return {
    thread_id: thread.thread_id,
    title: thread.title || "新的陪伴对话",
    mode: thread.mode,
    last_summary: null,
    last_risk_level: "L0",
    updated_at: thread.updated_at,
  };
}

export function mapThreadToConversationEntry(thread: ThreadListItem): ConversationListEntry {
  return {
    id: thread.thread_id,
    kind: "thread",
    threadId: thread.thread_id,
    title: thread.title || "未命名对话",
    time: formatThreadTime(thread.updated_at),
    preview: thread.last_summary || "这段对话还没有摘要，可以点开继续。",
    mode: thread.mode,
    riskLevel: thread.last_risk_level,
  };
}

export function buildHomeEntries(displayName: string, userMode: UserMode, memoryMode: MemoryMode): ConversationListEntry[] {
  const modeHint = userModeLabels[userMode];
  const memoryHint = memoryMode === "off" ? "本次先轻轻聊，不写入长期记忆" : "可以从上次的感受继续说起";

  return [
    {
      id: "continue",
      kind: "home",
      title: `${displayName}，欢迎回来`,
      time: "续聊入口",
      preview: memoryHint,
    },
    {
      id: "mode",
      kind: "home",
      title: modeHint,
      time: "当前模式",
      preview: userMode === "teen" ? "需要时可以优先找可信任的大人一起处理。" : "你可以按自己的节奏整理今天的感受。",
    },
    {
      id: "safety",
      kind: "home",
      title: "安全支持随时可见",
      time: "求助",
      preview: "如果感觉撑不住，请先打开右侧安全入口。",
    },
  ];
}

function sameLocalDate(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function daysBetween(later: Date, earlier: Date): number {
  const laterStart = new Date(later.getFullYear(), later.getMonth(), later.getDate()).getTime();
  const earlierStart = new Date(earlier.getFullYear(), earlier.getMonth(), earlier.getDate()).getTime();
  return Math.floor((laterStart - earlierStart) / 86_400_000);
}

function sectionIdForThread(thread: ThreadListItem, now: Date): ConversationListSection["id"] {
  const updatedAt = new Date(thread.updated_at);
  if (Number.isNaN(updatedAt.getTime())) {
    return "earlier";
  }

  if (sameLocalDate(updatedAt, now)) {
    return "today";
  }

  return daysBetween(now, updatedAt) <= 7 ? "week" : "earlier";
}

function labelForSection(id: ConversationListSection["id"]): string {
  if (id === "draft") return "当前草稿";
  if (id === "today") return "今天";
  if (id === "week") return "近 7 天";
  if (id === "earlier") return "更早";
  return "续聊与状态";
}

export function buildConversationList({
  threads,
  draft,
  displayName,
  userMode,
  memoryMode,
  now = new Date(),
  maxVisibleThreads = DEFAULT_MAX_VISIBLE_THREADS,
}: BuildConversationListInput): ConversationListBuildResult {
  const normalizedThreads: ThreadListItem[] = [];
  let hasVisibleEmptyThread = false;
  let hiddenEmptyThreadCount = 0;

  for (const thread of threads) {
    if (isProbablyEmptyThread(thread)) {
      if (hasVisibleEmptyThread) {
        hiddenEmptyThreadCount += 1;
        continue;
      }
      hasVisibleEmptyThread = true;
    }

    normalizedThreads.push(thread);
  }

  const visibleThreads = normalizedThreads.slice(0, maxVisibleThreads);
  const overflowThreadCount = Math.max(0, normalizedThreads.length - visibleThreads.length);
  const sections: ConversationListSection[] = [];

  if (draft) {
    sections.push({
      id: "draft",
      label: labelForSection("draft"),
      entries: [
        {
          id: draft.id,
          kind: "draft",
          title: draft.title,
          time: "草稿",
          preview: "还没有开始，写下第一句话后会保存。",
        },
      ],
    });
  }

  if (visibleThreads.length === 0) {
    if (!draft) {
      sections.push({
        id: "home",
        label: labelForSection("home"),
        entries: buildHomeEntries(displayName, userMode, memoryMode),
      });
    }

    return {
      sections,
      hiddenEmptyThreadCount,
      overflowThreadCount,
      totalThreadCount: threads.length,
      visibleThreadCount: 0,
    };
  }

  const grouped = new Map<ConversationListSection["id"], ConversationListEntry[]>();
  for (const thread of visibleThreads) {
    const sectionId = sectionIdForThread(thread, now);
    const entries = grouped.get(sectionId) ?? [];
    entries.push(mapThreadToConversationEntry(thread));
    grouped.set(sectionId, entries);
  }

  for (const sectionId of ["today", "week", "earlier"] as const) {
    const entries = grouped.get(sectionId);
    if (!entries?.length) continue;

    sections.push({
      id: sectionId,
      label: labelForSection(sectionId),
      countLabel: `${entries.length}`,
      entries,
    });
  }

  return {
    sections,
    hiddenEmptyThreadCount,
    overflowThreadCount,
    totalThreadCount: threads.length,
    visibleThreadCount: visibleThreads.length,
  };
}
