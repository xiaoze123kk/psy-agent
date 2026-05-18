# Frontend Single Draft Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Ningyu frontend show at most one empty new conversation, create the backend thread only when the first message is sent, and keep a crowded conversation list readable.

**Architecture:** Add a small thread-list domain helper for draft/list normalization and contract assertions, then integrate it into `NingyuAppShell.tsx` with an explicit draft-vs-thread active conversation state. Keep list styling in `NingyuAppShell.css`, using existing visual language with restrained draft and grouping modifiers.

**Tech Stack:** Vite, React 19, TypeScript strict mode, local top-level contract assertions compiled by `npm run check`, existing API client in `frontend/src/api/endpoints.ts`.

---

## Multi-Agent Execution Map

Use multiple agents with strict write ownership. Do not let two workers edit the same file at the same time.

- Worker A, parallel-safe: owns `frontend/src/app/ningyu/threadList.ts` and `frontend/src/app/ningyu/threadList.contract.ts`.
- Worker B, parallel-safe with Worker A: owns CSS-only changes in `frontend/src/app/ningyu/NingyuAppShell.css`.
- Worker C, after Worker A completes: owns `frontend/src/app/ningyu/NingyuAppShell.tsx` integration.
- Worker D, after Workers B and C complete: owns verification, screenshots if needed, and `docs/dev-log/frontend-conversation-list.md`.

Recommended order:

1. Run Worker A and Worker B in parallel.
2. Review and merge Worker A first because Worker C imports its helper API.
3. Run Worker C.
4. Run Worker D for verification and dev-log.

## File Structure

- Create `frontend/src/app/ningyu/threadList.ts`
  - Owns local draft type, conversation list entry/section types, empty-thread detection, home entries, thread-to-entry mapping, and grouped list building.
- Create `frontend/src/app/ningyu/threadList.contract.ts`
  - Compiles deterministic assertions for duplicate empty-thread folding, risk preservation, summary preservation, draft section behavior, and overflow counts.
- Modify `frontend/src/app/ningyu/NingyuAppShell.tsx`
  - Replaces immediate backend thread creation with local draft activation.
  - Uses a discriminated active conversation state rather than pretending a draft is a backend `thread_id`.
  - Creates the backend thread inside `handleSend()` when the active conversation is a draft.
  - Guards stale `loadMessages()` and stale stream callbacks.
  - Renders grouped thread sections through `LeftSidebar`.
- Modify `frontend/src/app/ningyu/NingyuAppShell.css`
  - Adds draft item, section count, hidden-empty summary, group spacing, and more-button styling.
  - Narrows existing `.ningyu-thread span` rules so nested spans do not accidentally break new layout.
- Modify `docs/dev-log/frontend-conversation-list.md`
  - Records implementation decisions, verification commands, and remaining backend follow-ups.

## Task 1: Thread List Domain Helper

**Agent Ownership:** Worker A only.

**Files:**
- Create: `frontend/src/app/ningyu/threadList.contract.ts`
- Create: `frontend/src/app/ningyu/threadList.ts`

- [ ] **Step 1: Write the failing contract assertions**

Create `frontend/src/app/ningyu/threadList.contract.ts` with this content:

```ts
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
```

- [ ] **Step 2: Run the contract and confirm it fails for the expected reason**

Run:

```powershell
npm run check
```

Expected: TypeScript fails because `./threadList` does not exist yet.

- [ ] **Step 3: Implement the thread-list helper**

Create `frontend/src/app/ningyu/threadList.ts` with this content:

```ts
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
      time: "SOS",
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
```

- [ ] **Step 4: Run the contract and confirm it passes**

Run:

```powershell
npm run check
```

Expected: PASS with no TypeScript errors.

- [ ] **Step 5: Commit Worker A files**

Run:

```powershell
git add frontend/src/app/ningyu/threadList.ts frontend/src/app/ningyu/threadList.contract.ts
git commit -m "feat: 增加前端对话列表草稿模型"
```

Expected: commit succeeds and includes only Worker A files.

## Task 2: Sidebar Styling For Draft And Crowded Lists

**Agent Ownership:** Worker B only.

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.css`

- [ ] **Step 1: Inspect current selectors before editing**

Run:

```powershell
rg -n "ningyu-thread|thread-list|section-label|new-chat" frontend/src/app/ningyu/NingyuAppShell.css
```

Expected: confirms existing selectors around `.ningyu-thread`, `.ningyu-thread__content`, `.ningyu-thread__meta`, and `.ningyu-section-label`.

- [ ] **Step 2: Add draft/list controls to the shared transition selector**

Modify the selector near the existing transition block so it includes the new buttons:

```css
.ningyu-round-button,
.ningyu-safety,
.ningyu-safety-entry,
.ningyu-login__box button,
.ningyu-input button,
.ningyu-new-chat,
.ningyu-thread,
.ningyu-thread-list__more,
.ningyu-sidebar__bottom button,
.ningyu-support-card,
.ningyu-suggestions button {
  transition:
    transform 220ms ease,
    background 1000ms ease-in-out,
    border-color 1000ms ease-in-out,
    color 1000ms ease-in-out,
    box-shadow 300ms ease;
}
```

Modify the hover selector in the same area:

```css
.ningyu-round-button:hover,
.ningyu-new-chat:hover,
.ningyu-thread:hover,
.ningyu-thread-list__more:hover,
.ningyu-support-card:hover,
.ningyu-suggestions button:hover {
  transform: translateY(-1px);
}
```

- [ ] **Step 3: Add grouped list and draft CSS**

Add these rules after the existing `.ningyu-section-label` rules and before `.ningyu-thread`:

```css
.ningyu-thread-group {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
}

.ningyu-thread-group__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px 4px;
  color: rgba(17, 94, 89, 0.62);
  font-size: 12px;
  font-weight: 700;
}

.ningyu-thread-group__header span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ningyu-thread-group__count {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(240, 253, 250, 0.48);
  color: rgba(15, 118, 110, 0.62);
  font-size: 10px;
  font-weight: 800;
}

.ningyu-thread-list__meta {
  margin: 8px 10px 10px;
  color: rgba(17, 94, 89, 0.58);
  font-size: 11px;
  line-height: 1.45;
}

.ningyu-thread-list__more {
  width: calc(100% - 20px);
  min-height: 34px;
  margin: 4px 10px 12px;
  border: 1px solid rgba(153, 246, 228, 0.28);
  border-radius: 14px;
  background: rgba(240, 253, 250, 0.24);
  color: rgba(17, 94, 89, 0.72);
  font-size: 12px;
  font-weight: 700;
}
```

Add this modifier near the existing `.ningyu-thread.is-active` rules:

```css
.ningyu-thread--draft {
  border-color: rgba(45, 212, 191, 0.24);
  background: rgba(240, 253, 250, 0.24);
}

.ningyu-thread--draft .ningyu-thread__dot {
  width: 8px;
  height: 8px;
  background: transparent;
  border: 2px solid rgba(20, 184, 166, 0.55);
}
```

- [ ] **Step 4: Narrow text overflow selectors to content children**

Replace the broad selector:

```css
.ningyu-thread strong,
.ningyu-thread span,
.ningyu-thread small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

with:

```css
.ningyu-thread__content > strong,
.ningyu-thread__content > span,
.ningyu-thread__content > small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

Replace the following `.ningyu-thread strong`, `.ningyu-thread span`, `.ningyu-thread small`, and night-mode variants with the narrower versions:

```css
.ningyu-thread__content > strong {
  color: rgba(19, 78, 74, 0.96);
  font-size: 13px;
  line-height: 1.32;
}

.ningyu-thread__content > span {
  color: rgba(17, 94, 89, 0.72);
  font-size: 12px;
  line-height: 1.35;
}

.ningyu-thread__content > small {
  color: rgba(15, 118, 110, 0.5);
  font-size: 10px;
  line-height: 1.2;
}

.ningyu-shell.is-night .ningyu-thread__content > strong {
  color: #e2e8f0;
}

.ningyu-shell.is-night .ningyu-thread__content > span {
  color: #94a3b8;
}

.ningyu-shell.is-night .ningyu-thread__content > small {
  color: #64748b;
}
```

- [ ] **Step 5: Add night-mode styling for new list controls**

Add these rules near nearby night-mode sidebar rules:

```css
.ningyu-shell.is-night .ningyu-thread-group__header,
.ningyu-shell.is-night .ningyu-thread-list__meta {
  color: #94a3b8;
}

.ningyu-shell.is-night .ningyu-thread-group__count {
  background: rgba(30, 41, 59, 0.58);
  color: #94a3b8;
}

.ningyu-shell.is-night .ningyu-thread-list__more {
  border-color: rgba(51, 65, 85, 0.58);
  background: rgba(30, 41, 59, 0.32);
  color: #cbd5e1;
}

.ningyu-shell.is-night .ningyu-thread--draft {
  border-color: rgba(52, 211, 153, 0.28);
  background: rgba(20, 83, 45, 0.18);
}

.ningyu-shell.is-night .ningyu-thread--draft .ningyu-thread__dot {
  border-color: rgba(52, 211, 153, 0.55);
}
```

- [ ] **Step 6: Run frontend type check**

Run:

```powershell
npm run check
```

Expected: PASS. CSS changes do not affect TypeScript.

- [ ] **Step 7: Commit Worker B file**

Run:

```powershell
git add frontend/src/app/ningyu/NingyuAppShell.css
git commit -m "feat: 优化前端对话列表草稿样式"
```

Expected: commit succeeds and includes only the CSS file.

## Task 3: Ningyu Shell Draft-State Integration

**Agent Ownership:** Worker C only. Start after Task 1 is merged.

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.tsx`

- [ ] **Step 1: Update imports and local active conversation types**

Modify the React import to include `useRef`:

```ts
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
```

Add the helper import after the existing conversation quality imports:

```ts
import {
  buildConversationList,
  buildDraftThread,
  formatMessageTime,
  toThreadListItemFromStartThread,
  type ConversationListEntry,
  type ConversationListSection,
  type DraftThread,
} from "./threadList";
```

Remove the local `HomeEntry` interface and remove the local `formatThreadTime`, `formatMessageTime`, `mapThreadToHomeEntry`, and `buildHomeEntries` functions from `NingyuAppShell.tsx`. Keep `buildHomeSuggestions()` in the shell.

Add this type near the existing shell status type aliases:

```ts
type ActiveConversation = { kind: "thread"; threadId: string } | { kind: "draft" } | null;
```

- [ ] **Step 2: Replace active thread state with active conversation state**

Replace:

```ts
const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
```

with:

```ts
const [draftThread, setDraftThread] = useState<DraftThread | null>(null);
const [activeConversation, setActiveConversation] = useState<ActiveConversation>(null);
const activeThreadId = activeConversation?.kind === "thread" ? activeConversation.threadId : null;
const isDraftActive = activeConversation?.kind === "draft";
const activeThreadIdRef = useRef<string | null>(null);
const sendOperationRef = useRef<string | null>(null);
const skipNextMessageLoadRef = useRef<string | null>(null);
```

Add this effect after the initial `shellPhase` effect:

```ts
useEffect(() => {
  activeThreadIdRef.current = activeThreadId;
}, [activeThreadId]);
```

- [ ] **Step 3: Guard thread and message loading**

Update `loadThreads()` so it no longer steals focus from an active draft:

```ts
const loadThreads = useCallback(async () => {
  setThreadListStatus("loading");
  setThreadListError(null);

  try {
    const response = await api.listThreads();
    setThreads(response.items);
    setThreadListStatus("success");
    setActiveConversation((current) => {
      if (current?.kind === "draft" || current?.kind === "thread") {
        return current;
      }

      const firstThreadId = response.items[0]?.thread_id;
      return firstThreadId ? { kind: "thread", threadId: firstThreadId } : null;
    });
  } catch (error) {
    setThreadListStatus("error");
    setThreadListError(error instanceof Error ? error.message : "最近对话加载失败，请稍后再试。");
  }
}, []);
```

Update `loadMessages()` so stale responses cannot overwrite the current conversation:

```ts
const loadMessages = useCallback(async (threadId: string) => {
  setMessageListStatus("loading");
  setMessageListError(null);

  try {
    const response = await api.listMessages(threadId);
    if (activeThreadIdRef.current !== threadId) {
      return;
    }

    setMessages(response.items.map(mapMessageItem));
    setMessageListStatus("success");
  } catch (error) {
    if (activeThreadIdRef.current !== threadId) {
      return;
    }

    setMessageListStatus("error");
    setMessageListError(error instanceof Error ? error.message : "消息列表加载失败，请稍后再试。");
  }
}, []);
```

Update the `activeThreadId` effect:

```ts
useEffect(() => {
  if (!activeThreadId) {
    setMessageListStatus(isDraftActive ? "success" : "idle");
    return;
  }

  if (skipNextMessageLoadRef.current === activeThreadId) {
    skipNextMessageLoadRef.current = null;
    setMessageListStatus("success");
    return;
  }

  void loadMessages(activeThreadId);
}, [activeThreadId, isDraftActive, loadMessages]);
```

- [ ] **Step 4: Update thread activation and draft activation helpers**

Replace `activateThread` with:

```ts
const activateThread = useCallback((thread: ThreadListItem, options: { clearMessages?: boolean; skipMessageLoad?: boolean } = {}) => {
  setThreads((current) => [thread, ...current.filter((item) => item.thread_id !== thread.thread_id)]);
  if (options.skipMessageLoad) {
    skipNextMessageLoadRef.current = thread.thread_id;
  }
  setActiveConversation({ kind: "thread", threadId: thread.thread_id });
  setMessageListError(null);

  if (options.clearMessages) {
    setMessages([]);
    setMessageListStatus("success");
  }
}, []);
```

Add:

```ts
const activateDraft = useCallback(() => {
  setDraftThread((current) => current ?? buildDraftThread());
  setActiveConversation({ kind: "draft" });
  setMessages([]);
  setGraphUpdates([]);
  setStreamStatusDetail(null);
  setChatStreamStatus("idle");
  setChatStreamError(null);
  setMessageListError(null);
  setMessageListStatus("success");
  setCreateThreadStatus("success");
  setCreateThreadError(null);
}, []);
```

- [ ] **Step 5: Build grouped conversation sections**

Replace `homeEntries` with:

```ts
const conversationList = useMemo(
  () =>
    buildConversationList({
      threads,
      draft: draftThread,
      displayName,
      userMode,
      memoryMode,
    }),
  [displayName, draftThread, memoryMode, threads, userMode],
);
```

Update the `LeftSidebar` props in the shell render:

```tsx
<LeftSidebar
  isNight={isNight}
  sections={conversationList.sections}
  activeConversation={activeConversation}
  threadListStatus={threadListStatus}
  threadListError={threadListError}
  hiddenEmptyThreadCount={conversationList.hiddenEmptyThreadCount}
  overflowThreadCount={conversationList.overflowThreadCount}
  createThreadStatus={createThreadStatus}
  createThreadError={createThreadError}
  userModeLabel={userModeLabels[userMode]}
  memoryModeLabel={memoryModeLabels[memoryMode]}
  onSelectEntry={handleSelectConversationEntry}
  onStartNewThread={handleStartNewThread}
/>
```

- [ ] **Step 6: Add entry selection and lazy thread creation for draft send**

Add before `handleSend`:

```ts
const handleSelectConversationEntry = useCallback((entry: ConversationListEntry) => {
  if (entry.kind === "draft") {
    activateDraft();
    return;
  }

  if (!entry.threadId) {
    return;
  }

  sendOperationRef.current = null;
  setActiveConversation({ kind: "thread", threadId: entry.threadId });
}, [activateDraft]);

const ensureThreadForSend = useCallback(async (): Promise<string | null> => {
  if (activeThreadId) {
    return activeThreadId;
  }

  if (!isDraftActive) {
    return null;
  }

  setCreateThreadStatus("loading");
  setCreateThreadError(null);

  try {
    const thread = await api.startThread({
      mode: "companion",
      title: draftThread?.title ?? "新的陪伴对话",
    });
    const threadItem = toThreadListItemFromStartThread(thread);
    setDraftThread(null);
    activateThread(threadItem, { clearMessages: false, skipMessageLoad: true });
    setCreateThreadStatus("success");
    return threadItem.thread_id;
  } catch (error) {
    setCreateThreadStatus("error");
    setCreateThreadError(error instanceof Error ? error.message : "新对话暂时没创建成功，可以稍后重试。");
    return null;
  }
}, [activeThreadId, activateThread, draftThread?.title, isDraftActive]);
```

- [ ] **Step 7: Update start-new-thread behavior**

Replace `handleStartNewThread` with:

```ts
const handleStartNewThread = () => {
  if (chatStreamStatus === "streaming" || createThreadStatus === "loading") return;
  activateDraft();
};
```

- [ ] **Step 8: Update `handleSend()` to create a thread only when needed**

At the start of `handleSend`, replace the active-thread guard with:

```ts
if (chatStreamStatus === "streaming" || createThreadStatus === "loading") return;

const resolvedThreadId = await ensureThreadForSend();
if (!resolvedThreadId) {
  setChatStreamStatus("error");
  setChatStreamError(isDraftActive ? "新对话暂时没创建成功，可以稍后重试。" : "请先从左侧开始一段新对话，再发送消息。");
  return;
}
```

After building `payload`, add:

```ts
const sendOperationId = crypto.randomUUID();
sendOperationRef.current = sendOperationId;
```

Replace every `api.streamMessage(activeThreadId, payload, ...` call with:

```ts
api.streamMessage(resolvedThreadId, payload, (eventName, data) => {
  if (sendOperationRef.current !== sendOperationId || activeThreadIdRef.current !== resolvedThreadId) {
    return;
  }
```

Keep the existing event handling inside that callback after the guard.

Replace all thread id fallback uses in the function:

```ts
final.thread_id || activeThreadId
fallback.thread_id || activeThreadId
api.sendMessage(activeThreadId, payload)
```

with:

```ts
final.thread_id || resolvedThreadId
fallback.thread_id || resolvedThreadId
api.sendMessage(resolvedThreadId, payload)
```

At the end of the successful stream and fallback paths, leave `sendOperationRef.current` as-is until the next send or selection. The callback guard already uses the current operation id.

- [ ] **Step 9: Update quick actions conservatively**

Keep `handleQuickAction()` as an immediate thread creation flow for now because it creates a titled guided entry and appends a local assistant message. Add one line before `activateThread(...)`:

```ts
setDraftThread(null);
```

This prevents a quick-action thread and an unrelated empty draft from showing together after the user uses a right-panel suggestion.

- [ ] **Step 10: Update `LeftSidebar` props and rendering**

Replace the current `LeftSidebar` signature:

```ts
function LeftSidebar({
  isNight,
  entries,
  activeThreadId,
  threadListStatus,
  threadListError,
  createThreadStatus,
  createThreadError,
  userModeLabel,
  memoryModeLabel,
  onSelectThread,
  onStartNewThread,
}: {
  isNight: boolean;
  entries: HomeEntry[];
  activeThreadId: string | null;
  threadListStatus: ThreadListStatus;
  threadListError: string | null;
  createThreadStatus: CreateThreadStatus;
  createThreadError: string | null;
  userModeLabel: string;
  memoryModeLabel: string;
  onSelectThread: (threadId: string) => void;
  onStartNewThread: () => void;
}) {
```

with:

```ts
function LeftSidebar({
  isNight,
  sections,
  activeConversation,
  threadListStatus,
  threadListError,
  hiddenEmptyThreadCount,
  overflowThreadCount,
  createThreadStatus,
  createThreadError,
  userModeLabel,
  memoryModeLabel,
  onSelectEntry,
  onStartNewThread,
}: {
  isNight: boolean;
  sections: ConversationListSection[];
  activeConversation: ActiveConversation;
  threadListStatus: ThreadListStatus;
  threadListError: string | null;
  hiddenEmptyThreadCount: number;
  overflowThreadCount: number;
  createThreadStatus: CreateThreadStatus;
  createThreadError: string | null;
  userModeLabel: string;
  memoryModeLabel: string;
  onSelectEntry: (entry: ConversationListEntry) => void;
  onStartNewThread: () => void;
}) {
```

Replace the `entries.map(...)` block with:

```tsx
{sections.map((section) => (
  <div className="ningyu-thread-group" key={section.id}>
    <div className="ningyu-thread-group__header">
      <span>{section.label}</span>
      {section.countLabel ? <em className="ningyu-thread-group__count">{section.countLabel}</em> : null}
    </div>
    {section.entries.map((entry) => {
      const isActive =
        entry.kind === "draft"
          ? activeConversation?.kind === "draft"
          : Boolean(entry.threadId && activeConversation?.kind === "thread" && entry.threadId === activeConversation.threadId);
      const isSelectable = entry.kind === "draft" || Boolean(entry.threadId);

      return (
        <button
          className={[
            "ningyu-thread",
            entry.kind === "draft" ? "ningyu-thread--draft" : "",
            isActive ? "is-active" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          key={entry.id}
          type="button"
          onClick={isSelectable ? () => onSelectEntry(entry) : undefined}
          disabled={!isSelectable}
        >
          <span className="ningyu-thread__dot" />
          <span className="ningyu-thread__content">
            <strong>{entry.title}</strong>
            <span>{entry.preview}</span>
            <small>{entry.time}</small>
          </span>
          {entry.kind === "thread" && (entry.riskLevel || entry.mode) ? (
            <span className="ningyu-thread__meta">
              {entry.riskLevel ? <small>{entry.riskLevel}</small> : null}
              {entry.mode ? <small>{entry.mode}</small> : null}
            </span>
          ) : null}
        </button>
      );
    })}
  </div>
))}
{hiddenEmptyThreadCount > 0 ? (
  <p className="ningyu-thread-list__meta">已隐藏 {hiddenEmptyThreadCount} 个未开始的空白对话</p>
) : null}
{overflowThreadCount > 0 ? (
  <button className="ningyu-thread-list__more" type="button">
    查看更多 {overflowThreadCount} 条
  </button>
) : null}
```

- [ ] **Step 11: Run frontend type check**

Run:

```powershell
npm run check
```

Expected: PASS with no TypeScript errors.

- [ ] **Step 12: Commit Worker C file**

Run:

```powershell
git add frontend/src/app/ningyu/NingyuAppShell.tsx
git commit -m "feat: 支持前端单一草稿对话"
```

Expected: commit succeeds and includes only `NingyuAppShell.tsx`.

## Task 4: Verification And Dev Log

**Agent Ownership:** Worker D only. Start after Tasks 1-3 pass.

**Files:**
- Modify: `docs/dev-log/frontend-conversation-list.md`

- [ ] **Step 1: Run type check**

Run:

```powershell
npm run check
```

Expected: PASS.

- [ ] **Step 2: Run production build**

Run:

```powershell
npm run build
```

Expected: PASS and Vite writes to `frontend/dist/`. Do not edit or commit `frontend/dist/`.

- [ ] **Step 3: Start the frontend on a repo-specific port**

Run:

```powershell
npm run dev -- --host 127.0.0.1 --port 5175
```

Expected: Vite serves the current repository frontend at `http://127.0.0.1:5175`. If port `5175` is already occupied by this repo's frontend, reuse it. If it is occupied by another project, use `5176`.

- [ ] **Step 4: Verify with browser network behavior**

Use Playwright or the browser devtools network panel at the frontend URL.

Manual assertions:

- Click “开始新对话” 10 times.
- Expected: left sidebar shows one draft entry, not 10 real thread entries.
- Expected: no `POST /api/v1/chat/threads` request fires before typing and sending a message.
- Send the first message from the draft.
- Expected: exactly one `POST /api/v1/chat/threads` request fires, followed by the existing message send or stream request.
- Expected: the draft entry becomes a real thread entry and the assistant response flow still renders.

- [ ] **Step 5: Verify visual breakpoints**

Use browser screenshots or visual inspection at:

```text
1366x768
1080x768
761x768
760x768
390x844
```

Expected:

- At desktop widths, draft item, group labels, hidden-empty message, and more button fit inside the 256px left sidebar.
- At `1080px`, the right sidebar is hidden and the left sidebar remains stable.
- At `760px`, the left sidebar is hidden according to the existing responsive rule.
- Long thread titles and summaries truncate inside the entry and do not overlap risk/mode badges.
- Night mode styles remain legible.

- [ ] **Step 6: Append implementation record to dev-log**

Append this section to `docs/dev-log/frontend-conversation-list.md`. If Step 3 used port `5176` because `5175` was occupied by another project, write `http://127.0.0.1:5176` in the browser verification line.

```md
## 2026-05-18 单一草稿对话实现

### 背景

根据 `docs/superpowers/specs/2026-05-18-frontend-single-draft-conversation-design.md`，左侧“开始新对话”需要从立即创建后端线程改为本地单例草稿，避免空线程堆积。

### 关键改动

- 新增 `frontend/src/app/ningyu/threadList.ts`，集中处理草稿 entry、疑似空线程折叠、最近线程分组和溢出计数。
- 新增 `frontend/src/app/ningyu/threadList.contract.ts`，用 TypeScript contract 覆盖重复空线程、风险线程、摘要线程、草稿和 50 条历史线程场景。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.tsx`，用 draft/thread discriminated state 管理当前会话，并在草稿首条消息发送时创建后端线程。
- 更新 `frontend/src/app/ningyu/NingyuAppShell.css`，增加草稿项、分组标题、隐藏空白对话提示和查看更多入口样式。

### 验证

- `npm run check`：通过。
- `npm run build`：通过。
- 浏览器验证：`http://127.0.0.1:5175` 可打开；连续点击“开始新对话”10 次仅显示一个草稿；发送前没有 `POST /api/v1/chat/threads`；草稿首条消息发送时只创建一个后端线程；桌面、1080px、761px、760px 和 390px 视口没有文字重叠或侧栏遮挡。

### 后续事项

1. 后端 `ThreadListItem` 后续补充 `message_count`、`is_empty` 和 `archived_at`，替代前端启发式空线程判断。
2. 历史对话超过默认展示数量后，后续接入真实分页、搜索和归档接口。
```

- [ ] **Step 7: Commit verification log**

Run:

```powershell
git add docs/dev-log/frontend-conversation-list.md
git commit -m "docs: 记录前端对话列表治理实现"
```

Expected: commit succeeds and includes only the dev-log file.

## Final Review Checklist

- [ ] The first click on “开始新对话” creates one local draft and does not call `POST /api/v1/chat/threads`.
- [ ] Repeated clicks focus the same draft and do not add more drafts.
- [ ] Sending from a draft creates one backend thread and then sends the message through the existing flow.
- [ ] `loadThreads()` does not steal focus from an active draft.
- [ ] `loadMessages()` cannot overwrite messages for a stale thread.
- [ ] Stream callbacks stop updating the UI after the user switches to a different thread.
- [ ] Duplicate old empty threads are folded visually, while summary and `L1+` risk threads remain visible.
- [ ] `npm run check` and `npm run build` pass.
- [ ] Dev-log has the actual verification results.

## Plan Self-Review

- Spec coverage: The plan covers single draft creation, lazy backend thread creation, duplicate old empty thread folding, crowded-list cap, grouped sidebar rendering, CSS responsive risks, and dev-log recording.
- Type consistency: `DraftThread`, `ConversationListEntry`, `ConversationListSection`, and `ActiveConversation` have one definition path and are reused by the shell.
- Multi-agent safety: Workers A and B have disjoint write sets and can run in parallel; Worker C waits for the helper API; Worker D verifies after integration.
- Remaining backend work: The plan intentionally leaves backend pagination, archive, `message_count`, and `is_empty` for a later backend plan because the current spec chose frontend-first containment.
