import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

import bgDay from "../../imports/wcbg.png";
import bgNight from "../../imports/wcbg_night.png";
import logo from "../../imports/wind-chat-logo.png";
import { api } from "../../api";
import { useAppState } from "../state";
import {
  conversationFeedbackOptions,
  formatDuration,
  formatRagStatus,
  graphUpdateDetail,
  traceTimingFromSummary,
  type ConversationFeedbackSubmitStatus,
  type TraceTiming,
} from "./conversationQuality";
import {
  buildConversationList,
  buildDraftThread,
  formatMessageTime,
  toThreadListItemFromStartThread,
  type ConversationListEntry,
  type ConversationListSection,
  type DraftThread,
} from "./threadList";
import {
  getMoodCheckInOwnerId,
  getMoodCheckInStorage,
  hasMoodCheckInForToday,
  markMoodCheckInRecordedToday,
  readRecordedMoodCheckInDay,
  shouldShowMoodCheckInControls,
} from "./moodCheckInFrequency";
import {
  buildDailyOpeningSuggestions,
  claimDailyOpeningSuggestionsForSession,
  dismissDailyOpeningSuggestionsForSession,
  getDailyOpeningSuggestionOwnerId,
  getDailyOpeningSuggestionStorage,
  markDailyOpeningSuggestionsSeenToday,
  type DailyOpeningSuggestion,
} from "./dailyOpeningSuggestions";
import "./NingyuAppShell.css";
import type {
  ChatStreamAcceptedEvent,
  ChatStreamErrorEvent,
  ChatStreamEventName,
  ChatStreamFinalEvent,
  ChatStreamGraphUpdateEvent,
  ChatStreamHeartbeatEvent,
  ChatStreamTokenEvent,
  ConversationFeedbackValue,
  MemoryMode,
  MessageItem,
  MoodLogResponse,
  MoodTrendResponse,
  RiskLevel,
  SendMessageRequest,
  TestListItem,
  ThreadListItem,
  UserMode,
  WeeklySummaryResponse,
} from "../../types/api";

type IconName =
  | "moon"
  | "sun"
  | "shield"
  | "plus"
  | "clock"
  | "spark"
  | "settings"
  | "heart"
  | "phone"
  | "message"
  | "light"
  | "wind"
  | "leaf"
  | "send";

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  riskLevel?: string | null;
  suggestedActions?: string[];
  metadata?: Record<string, unknown>;
  turnId?: string | null;
  assistantMessageId?: string | null;
  trace?: TraceTiming | null;
  feedbackState?: {
    value: ConversationFeedbackValue;
    status: ConversationFeedbackSubmitStatus;
  };
  isStreaming?: boolean;
  deliveryStatus?: string;
  intent?: string;
  sessionSummary?: string;
  turnStatus?: string;
  failureReason?: string | null;
}

interface HomeSupportResource {
  id: string;
  icon: "phone" | "message";
  label: string;
  title: string;
}

type QuickAction = DailyOpeningSuggestion;

interface QuickActionResult {
  title: string;
  detail: string;
  threadId: string;
}

interface GraphUpdateItem {
  id: string;
  node: string;
  status?: string;
  riskLevel?: string;
  intent?: string;
  detail: string;
}

interface HighRiskSafetyState {
  riskLevel: RiskLevel;
  threadId: string;
  eventStatus: "recording" | "recorded" | "error";
  eventId?: string;
  error?: string;
}

type ShellPhase = "loading" | "ready" | "error";
type SafetyTone = "loading" | "stable" | "watch" | "support" | "error";
type MoodCheckInStatus = "idle" | "submitting" | "success" | "error";
type MoodTrendRange = "7d" | "30d";
type MoodTrendStatus = "idle" | "loading" | "success" | "error";
type WeeklySummaryStatus = "idle" | "loading" | "success" | "error";
type QuickActionStatus = "idle" | "loading" | "success" | "error";
type TestListStatus = "idle" | "loading" | "success" | "error";
type ThreadListStatus = "idle" | "loading" | "success" | "error";
type MessageListStatus = "idle" | "loading" | "success" | "error";
type CreateThreadStatus = "idle" | "loading" | "success" | "error";
type ChatStreamStatus = "idle" | "streaming" | "success" | "error";
type ActiveConversation = { kind: "thread"; threadId: string } | { kind: "draft" } | null;
type SendMessageHandler = (content: string) => boolean | Promise<boolean>;
type DraftInputSeed = { id: string; text: string };
type EdgePanel = "history" | "tools" | null;

const focusableSelector =
  'button:not(:disabled), [href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])';

const edgePanelTriggerIds: Record<Exclude<EdgePanel, null>, string> = {
  history: "ningyu-history-trigger",
  tools: "ningyu-tools-trigger",
};

function focusElementById(id: string) {
  window.setTimeout(() => document.getElementById(id)?.focus(), 0);
}

interface MoodTagOption {
  id: string;
  label: string;
}

const moodTagOptions: MoodTagOption[] = [
  { id: "tired", label: "有点累" },
  { id: "anxious", label: "有点紧" },
  { id: "lonely", label: "想被陪伴" },
  { id: "calm", label: "稍微平静" },
];

const moodScoreLabels = ["很低", "偏低", "还可以", "轻一点", "有力量"];

const supportResources: HomeSupportResource[] = [
  { id: "hotline", icon: "phone", label: "24小时热线", title: "010-82951332" },
  { id: "urgent-chat", icon: "message", label: "紧急咨询", title: "立即连接" },
];

const dailyOpeningSuggestionSessionKeys = new Set<string>();
const userModeLabels: Record<UserMode, string> = {
  teen: "青少年模式",
  adult: "标准模式",
};
const memoryModeLabels: Record<MemoryMode, string> = {
  off: "记忆关闭",
  summary_only: "摘要记忆",
  long_term: "长时记忆",
};
function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function recordOrNull(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function extractSuggestedActions(metadata: Record<string, unknown>): string[] {
  const directActions = readStringArray(metadata.suggested_actions);
  if (directActions.length) return directActions;

  const nestedAssistant = metadata.assistant_message;
  if (nestedAssistant && typeof nestedAssistant === "object" && !Array.isArray(nestedAssistant)) {
    return readStringArray((nestedAssistant as Record<string, unknown>).suggested_actions);
  }

  return [];
}

function mapGraphUpdate(update: ChatStreamGraphUpdateEvent): GraphUpdateItem {
  return {
    id: crypto.randomUUID(),
    node: update.node,
    status: update.status,
    riskLevel: update.risk_level,
    intent: update.intent,
    detail: graphUpdateDetail(update),
  };
}

function isHighRiskLevel(riskLevel: RiskLevel | string | null | undefined): riskLevel is "L2" | "L3" {
  return riskLevel === "L2" || riskLevel === "L3";
}

function mapMessageItem(message: MessageItem): Message {
  const metadata = message.metadata;
  const accepted = recordOrNull(metadata.accepted);
  const final = recordOrNull(metadata.final);
  const traceSummary = recordOrNull(metadata.trace_summary) ?? recordOrNull(final?.trace_summary);
  const turnId = stringOrNull(metadata.turn_id) ?? stringOrNull(final?.turn_id) ?? stringOrNull(accepted?.turn_id);
  const assistantMessageId =
    stringOrNull(metadata.assistant_message_id) ??
    stringOrNull(final?.assistant_message_id) ??
    (message.role === "assistant" ? message.id : null);

  return {
    id: message.id,
    role: message.role,
    content: message.content,
    timestamp: formatMessageTime(message.created_at),
    riskLevel: message.risk_level,
    suggestedActions: extractSuggestedActions(metadata),
    metadata,
    turnId,
    assistantMessageId,
    deliveryStatus: stringOrNull(metadata.delivery_status) ?? stringOrNull(final?.delivery_status) ?? undefined,
    trace: traceTimingFromSummary(traceSummary ?? undefined),
  };
}

export function NingyuAppShell() {
  const {
    currentUser,
    ageModeProfile,
    userMode,
    memoryMode,
    isNight,
    toggleThemeMode,
  } = useAppState();
  const [messages, setMessages] = useState<Message[]>([]);
  const [shellPhase, setShellPhase] = useState<ShellPhase>("loading");
  const [isSafetyEntryOpen, setIsSafetyEntryOpen] = useState(false);
  const [moodScore, setMoodScore] = useState(3);
  const [moodTags, setMoodTags] = useState<string[]>([]);
  const [moodNote, setMoodNote] = useState("");
  const [moodStatus, setMoodStatus] = useState<MoodCheckInStatus>("idle");
  const [moodError, setMoodError] = useState<string | null>(null);
  const [latestMoodLog, setLatestMoodLog] = useState<MoodLogResponse | null>(null);
  const [moodTrendRange, setMoodTrendRange] = useState<MoodTrendRange>("7d");
  const [moodTrendStatus, setMoodTrendStatus] = useState<MoodTrendStatus>("idle");
  const [moodTrendError, setMoodTrendError] = useState<string | null>(null);
  const [moodTrend, setMoodTrend] = useState<MoodTrendResponse | null>(null);
  const moodCheckInOwnerId = useMemo(() => getMoodCheckInOwnerId(currentUser?.user_id ?? currentUser?.username), [currentUser]);
  const dailyOpeningSuggestionOwnerId = useMemo(
    () => getDailyOpeningSuggestionOwnerId(currentUser?.user_id ?? currentUser?.username),
    [currentUser],
  );
  const [recordedMoodCheckInDay, setRecordedMoodCheckInDay] = useState<string | null>(() =>
    readRecordedMoodCheckInDay(getMoodCheckInStorage(), "local"),
  );
  const [isDailyOpeningSuggestionsVisible, setIsDailyOpeningSuggestionsVisible] = useState(false);
  const [weeklySummaryStatus, setWeeklySummaryStatus] = useState<WeeklySummaryStatus>("idle");
  const [weeklySummaryError, setWeeklySummaryError] = useState<string | null>(null);
  const [weeklySummary, setWeeklySummary] = useState<WeeklySummaryResponse | null>(null);
  const [quickActionStatus, setQuickActionStatus] = useState<QuickActionStatus>("idle");
  const [activeQuickActionId, setActiveQuickActionId] = useState<string | null>(null);
  const [quickActionError, setQuickActionError] = useState<string | null>(null);
  const [quickActionResult, setQuickActionResult] = useState<QuickActionResult | null>(null);
  const [tests, setTests] = useState<TestListItem[]>([]);
  const [testListStatus, setTestListStatus] = useState<TestListStatus>("idle");
  const [testListError, setTestListError] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadListItem[]>([]);
  const [draftThread, setDraftThread] = useState<DraftThread | null>(null);
  const [activeConversation, setActiveConversation] = useState<ActiveConversation>(null);
  const activeThreadId = activeConversation?.kind === "thread" ? activeConversation.threadId : null;
  const isDraftActive = activeConversation?.kind === "draft";
  const activeConversationRef = useRef<ActiveConversation>(null);
  const activeThreadIdRef = useRef<string | null>(null);
  const sendOperationRef = useRef<string | null>(null);
  const skipNextMessageLoadRef = useRef<string | null>(null);
  const draftCreationRef = useRef<string | null>(null);
  const [threadListStatus, setThreadListStatus] = useState<ThreadListStatus>("idle");
  const [threadListError, setThreadListError] = useState<string | null>(null);
  const [messageListStatus, setMessageListStatus] = useState<MessageListStatus>("idle");
  const [messageListError, setMessageListError] = useState<string | null>(null);
  const [createThreadStatus, setCreateThreadStatus] = useState<CreateThreadStatus>("idle");
  const [createThreadError, setCreateThreadError] = useState<string | null>(null);
  const [chatStreamStatus, setChatStreamStatus] = useState<ChatStreamStatus>("idle");
  const [chatStreamError, setChatStreamError] = useState<string | null>(null);
  const [graphUpdates, setGraphUpdates] = useState<GraphUpdateItem[]>([]);
  const [streamStatusDetail, setStreamStatusDetail] = useState<string | null>(null);
  const [draftInputSeed, setDraftInputSeed] = useState<DraftInputSeed | null>(null);
  const [highRiskSafety, setHighRiskSafety] = useState<HighRiskSafetyState | null>(null);
  const [activeEdgePanel, setActiveEdgePanel] = useState<EdgePanel>(null);
  const shouldReduceMotion = Boolean(useReducedMotion());

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setShellPhase("ready");
    }, 720);

    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    activeConversationRef.current = activeConversation;
    activeThreadIdRef.current = activeThreadId;
  }, [activeConversation, activeThreadId]);

  useEffect(() => {
    if (highRiskSafety) {
      setActiveEdgePanel(null);
      setIsSafetyEntryOpen(true);
    }
  }, [highRiskSafety]);

  const closeEdgePanel = useCallback(() => {
    const closingPanel = activeEdgePanel;
    setActiveEdgePanel(null);
    if (closingPanel) {
      focusElementById(edgePanelTriggerIds[closingPanel]);
    }
  }, [activeEdgePanel]);

  const handleEdgePanelChange = useCallback((panel: EdgePanel) => {
    if (panel === null) {
      closeEdgePanel();
      return;
    }

    setActiveEdgePanel(panel);
  }, [closeEdgePanel]);

  const closeSafetyLayer = useCallback(() => {
    setIsSafetyEntryOpen(false);
    focusElementById("ningyu-safety-trigger");
  }, []);

  useEffect(() => {
    setRecordedMoodCheckInDay(readRecordedMoodCheckInDay(getMoodCheckInStorage(), moodCheckInOwnerId));
  }, [moodCheckInOwnerId]);

  useEffect(() => {
    const claim = claimDailyOpeningSuggestionsForSession({
      storage: getDailyOpeningSuggestionStorage(),
      ownerId: dailyOpeningSuggestionOwnerId,
      sessionKeys: dailyOpeningSuggestionSessionKeys,
    });

    setIsDailyOpeningSuggestionsVisible(claim.visible);
  }, [dailyOpeningSuggestionOwnerId]);

  const loadMoodTrend = useCallback(async (range: MoodTrendRange) => {
    setMoodTrendStatus("loading");
    setMoodTrendError(null);

    try {
      const response = await api.getMoodTrend(range);
      setMoodTrend(response);
      setMoodTrendStatus("success");
    } catch (error) {
      setMoodTrendStatus("error");
      setMoodTrendError(error instanceof Error ? error.message : "情绪趋势加载失败，请稍后再试。");
    }
  }, []);

  const loadWeeklySummary = useCallback(async () => {
    setWeeklySummaryStatus("loading");
    setWeeklySummaryError(null);

    try {
      const response = await api.getWeeklySummary();
      setWeeklySummary(response);
      setWeeklySummaryStatus("success");
    } catch (error) {
      setWeeklySummaryStatus("error");
      setWeeklySummaryError(error instanceof Error ? error.message : "每周情绪小结加载失败，请稍后再试。");
    }
  }, []);

  const loadTests = useCallback(async () => {
    setTestListStatus("loading");
    setTestListError(null);

    try {
      const response = await api.listTests();
      setTests(response.items);
      setTestListStatus("success");
    } catch (error) {
      setTestListStatus("error");
      setTestListError(error instanceof Error ? error.message : "Tests could not be loaded right now.");
    }
  }, []);

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

  const activateThread = useCallback((thread: ThreadListItem, options: { clearMessages?: boolean; skipMessageLoad?: boolean } = {}) => {
    setThreads((current) => [thread, ...current.filter((item) => item.thread_id !== thread.thread_id)]);
    draftCreationRef.current = null;
    activeConversationRef.current = { kind: "thread", threadId: thread.thread_id };
    activeThreadIdRef.current = thread.thread_id;
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

  const activateDraft = useCallback(() => {
    setDraftThread((current) => current ?? buildDraftThread());
    activeConversationRef.current = { kind: "draft" };
    activeThreadIdRef.current = null;
    sendOperationRef.current = null;
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

  useEffect(() => {
    void loadMoodTrend(moodTrendRange);
  }, [loadMoodTrend, moodTrendRange]);

  useEffect(() => {
    void loadWeeklySummary();
  }, [loadWeeklySummary]);

  useEffect(() => {
    void loadTests();
  }, [loadTests]);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

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

  const safetyState = useMemo(() => {
    if (shellPhase === "loading") {
      return {
        tone: "loading" as SafetyTone,
        label: "安全空间载入中",
        detail: "正在检查陪伴空间与安全入口。",
      };
    }

    if (shellPhase === "error") {
      return {
        tone: "error" as SafetyTone,
        label: "安全状态暂不可用",
        detail: "先停一下，我们重新恢复安全入口。",
      };
    }

    if (highRiskSafety) {
      return {
        tone: highRiskSafety.eventStatus === "error" ? ("error" as SafetyTone) : ("support" as SafetyTone),
        label: highRiskSafety.riskLevel === "L3" ? "高风险支持已优先打开" : "安全支持已优先打开",
        detail:
          highRiskSafety.eventStatus === "recorded"
            ? "已记录本次安全事件，请优先查看右侧支持资源。"
            : highRiskSafety.eventStatus === "recording"
              ? "正在记录安全事件，请优先联系现实中的支持。"
              : highRiskSafety.error || "安全事件记录失败，但支持入口仍然可用。",
      };
    }

    if (isSafetyEntryOpen) {
      return {
        tone: "support" as SafetyTone,
        label: "安全支持已展开",
        detail: "你现在可以直接查看支持资源和提醒。",
      };
    }

    if (messages.length >= 3) {
      return {
        tone: "watch" as SafetyTone,
        label: "安全状态留意中",
        detail: "如果你想暂停一下，也可以随时打开安全入口。",
      };
    }

    return {
      tone: "stable" as SafetyTone,
      label: "安全陪伴在线",
      detail: "这里保持可见，随时可以打开支持入口。",
    };
  }, [highRiskSafety, isSafetyEntryOpen, messages.length, shellPhase]);

  const displayName = currentUser?.nickname || currentUser?.username || "正在倾听你";
  const hasRecordedMoodToday = useMemo(
    () =>
      hasMoodCheckInForToday({
        recordedDay: recordedMoodCheckInDay,
        latestMoodLog,
        moodTrend,
      }),
    [latestMoodLog, moodTrend, recordedMoodCheckInDay],
  );
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
  const homeSuggestions = useMemo(
    () =>
      buildDailyOpeningSuggestions({
        userMode,
        memoryMode,
        isNight,
        latestMoodLog,
        moodTrend,
        weeklySummary,
        hasRecordedMoodToday,
      }),
    [hasRecordedMoodToday, isNight, latestMoodLog, memoryMode, moodTrend, weeklySummary, userMode],
  );
  const visibleHomeSuggestions = isDailyOpeningSuggestionsVisible ? homeSuggestions : [];
  const statusTags = useMemo(
    () => [
      userModeLabels[userMode],
      ageModeProfile.ageLabel,
      ageModeProfile.description,
      memoryModeLabels[memoryMode],
    ],
    [
      memoryMode,
      ageModeProfile.ageLabel,
      ageModeProfile.description,
      userMode,
    ],
  );

  const handleToggleSafetyEntry = () => {
    setIsSafetyEntryOpen((current) => !current);
  };

  const handleRetrySafetyState = () => {
    setHighRiskSafety(null);
    setShellPhase("loading");
    window.setTimeout(() => {
      setShellPhase("ready");
    }, 720);
  };

  const handleHighRiskChatResponse = useCallback(
    async ({
      threadId,
      riskLevel,
      detectedSignals,
    }: {
      threadId: string;
      riskLevel: RiskLevel | string | null | undefined;
      detectedSignals: string[];
    }) => {
      if (!isHighRiskLevel(riskLevel)) return;

      setIsSafetyEntryOpen(true);
      setHighRiskSafety({
        riskLevel,
        threadId,
        eventStatus: "recording",
      });

      try {
        const response = await api.createCrisisEvent({
          thread_id: threadId,
          risk_level: riskLevel,
          detected_signals: detectedSignals.filter(Boolean),
          action_taken: ["show_sos", "crisis_response"],
        });
        setHighRiskSafety({
          riskLevel,
          threadId,
          eventStatus: "recorded",
          eventId: response.event_id,
        });
      } catch (error) {
        setHighRiskSafety({
          riskLevel,
          threadId,
          eventStatus: "error",
          error: error instanceof Error ? error.message : "安全事件记录失败。",
        });
      }
    },
    [],
  );

  const updateMessage = useCallback((messageId: string, updater: (message: Message) => Message) => {
    setMessages((current) => current.map((message) => (message.id === messageId ? updater(message) : message)));
  }, []);

  const handleSelectConversationEntry = useCallback((entry: ConversationListEntry) => {
    if (entry.kind === "draft") {
      activateDraft();
      return;
    }

    if (!entry.threadId) {
      return;
    }

    sendOperationRef.current = null;
    draftCreationRef.current = null;
    activeConversationRef.current = { kind: "thread", threadId: entry.threadId };
    activeThreadIdRef.current = entry.threadId;
    setChatStreamStatus("idle");
    setChatStreamError(null);
    setCreateThreadStatus("success");
    setCreateThreadError(null);
    setStreamStatusDetail(null);
    setGraphUpdates([]);
    setMessages([]);
    setMessageListError(null);
    setActiveConversation({ kind: "thread", threadId: entry.threadId });
  }, [activateDraft]);

  const ensureThreadForSend = useCallback(async (): Promise<string | null> => {
    if (activeThreadId) {
      return activeThreadId;
    }

    if (!isDraftActive) {
      return null;
    }

    const draftCreationId = crypto.randomUUID();
    draftCreationRef.current = draftCreationId;
    setCreateThreadStatus("loading");
    setCreateThreadError(null);

    try {
      const thread = await api.startThread({
        mode: "companion",
        title: draftThread?.title ?? "新的陪伴对话",
      });
      if (
        draftCreationRef.current !== draftCreationId ||
        activeConversationRef.current?.kind !== "draft" ||
        activeThreadIdRef.current !== null
      ) {
        return null;
      }

      const threadItem = toThreadListItemFromStartThread(thread);
      setDraftThread(null);
      draftCreationRef.current = null;
      activeThreadIdRef.current = threadItem.thread_id;
      activateThread(threadItem, { clearMessages: false, skipMessageLoad: true });
      setCreateThreadStatus("success");
      return threadItem.thread_id;
    } catch (error) {
      if (draftCreationRef.current !== draftCreationId || activeConversationRef.current?.kind !== "draft") {
        return null;
      }

      draftCreationRef.current = null;
      setCreateThreadStatus("error");
      setCreateThreadError(error instanceof Error ? error.message : "新对话暂时没创建成功，可以稍后重试。");
      return null;
    }
  }, [activeThreadId, activateThread, draftThread?.title, isDraftActive]);

  const handleSend = async (content: string): Promise<boolean> => {
    if (chatStreamStatus === "streaming" || createThreadStatus === "loading" || draftCreationRef.current) return false;

    const resolvedThreadId = await ensureThreadForSend();
    if (!resolvedThreadId) {
      if (activeConversationRef.current?.kind !== "thread" && activeThreadIdRef.current === null) {
        setChatStreamStatus("error");
        setChatStreamError(isDraftActive ? "新对话暂时没创建成功，可以稍后重试。" : "请先从左侧开始一段新对话，再发送消息。");
      }
      return false;
    }

    const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const assistantMessageId = crypto.randomUUID();
    const clientMessageId = crypto.randomUUID();
    const payload: SendMessageRequest = {
      client_message_id: clientMessageId,
      content,
      input_type: "text",
      user_mode: userMode,
    };
    const sendOperationId = crypto.randomUUID();
    sendOperationRef.current = sendOperationId;

    setChatStreamStatus("streaming");
    setChatStreamError(null);
    setStreamStatusDetail("正在把你的话送到宁语...");
    setGraphUpdates([]);
    setMessages((current) => [
      ...current,
      {
        id: clientMessageId,
        role: "user",
        content,
        timestamp: now,
      },
      {
        id: assistantMessageId,
        role: "assistant",
        content: "正在整理回应...",
        timestamp: now,
        isStreaming: true,
      },
    ]);

    let hasReceivedStreamEvent = false;

    void (async () => {
    try {
      await api.streamMessage(resolvedThreadId, payload, (eventName, data) => {
        if (sendOperationRef.current !== sendOperationId || activeThreadIdRef.current !== resolvedThreadId) {
          return;
        }

        hasReceivedStreamEvent = true;
        const typedEvent = eventName as ChatStreamEventName;

        if (typedEvent === "accepted") {
          const accepted = data as unknown as ChatStreamAcceptedEvent;
          setStreamStatusDetail(accepted.turn_status ? `已接收 · ${accepted.turn_status}` : "已接收，正在轻轻整理...");
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    turnId: accepted.turn_id ?? message.turnId,
                    turnStatus: accepted.turn_status,
                    metadata: { ...message.metadata, accepted, turn_id: accepted.turn_id ?? message.turnId },
                  }
                : message,
            ),
          );
          return;
        }

        if (typedEvent === "graph_update") {
          const update = data as unknown as ChatStreamGraphUpdateEvent;
          const graphTrace = traceTimingFromSummary({
            node: update.node,
            duration_ms: update.duration_ms,
            retrieved_memory_count: update.retrieved_memory_count,
            retrieved_example_count: update.retrieved_example_count,
            rag_used: update.rag_used,
            rag_skipped_reason: update.rag_skipped_reason,
            rag_trace_summary: update.rag_trace_summary,
          });
          setGraphUpdates((current) => [...current.slice(-4), mapGraphUpdate(update)]);
          if (graphTrace) {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantMessageId && message.isStreaming
                  ? { ...message, trace: { ...message.trace, ...graphTrace } }
                  : message,
              ),
            );
          }
          setStreamStatusDetail(update.status ? `${update.node} · ${update.status}` : `${update.node} 正在处理`);
          return;
        }

        if (typedEvent === "heartbeat") {
          const heartbeat = data as unknown as ChatStreamHeartbeatEvent;
          setStreamStatusDetail(`仍在生成 · ${(heartbeat.elapsed_ms / 1000).toFixed(1)}s`);
          return;
        }

        if (typedEvent === "token") {
          const token = data as unknown as ChatStreamTokenEvent;
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    content: message.content === "正在整理回应..." ? token.text : `${message.content}${token.text}`,
                    isStreaming: true,
                  }
                : message,
            ),
          );
          return;
        }

        if (typedEvent === "final") {
          const final = data as unknown as ChatStreamFinalEvent;
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    id: final.assistant_message_id || final.message_id || message.id,
                    content: final.assistant_text || message.content,
                    riskLevel: final.risk_level,
                    suggestedActions: final.suggested_actions,
                    isStreaming: false,
                    deliveryStatus: final.delivery_status,
                    intent: final.intent,
                    sessionSummary: final.session_summary,
                    turnStatus: final.turn_status,
                    failureReason: final.failure_reason,
                    turnId: final.turn_id ?? message.turnId,
                    assistantMessageId: final.assistant_message_id ?? final.message_id ?? message.assistantMessageId,
                    trace: traceTimingFromSummary(final.trace_summary) ?? message.trace,
                    metadata: {
                      ...message.metadata,
                      final,
                      turn_id: final.turn_id ?? message.turnId,
                      assistant_message_id: final.assistant_message_id ?? final.message_id ?? message.assistantMessageId,
                      trace_summary: final.trace_summary,
                    },
                  }
                : message,
            ),
          );
          setStreamStatusDetail(final.delivery_status ? `完成 · ${final.delivery_status}` : "回复已完成");
          setChatStreamStatus("success");
          void handleHighRiskChatResponse({
            threadId: final.thread_id || resolvedThreadId,
            riskLevel: final.risk_level,
            detectedSignals: [
              final.intent,
              final.delivery_status,
              final.turn_status,
              ...(final.risk_reasons ?? []),
              ...(final.suggested_actions ?? []),
            ],
          });
          return;
        }

        if (typedEvent === "error") {
          const streamError = data as unknown as ChatStreamErrorEvent;
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    content: streamError.message || "这次回复中断了，请稍后再试。",
                    isStreaming: false,
                    turnStatus: streamError.turn_status,
                    failureReason: streamError.message,
                  }
                : message,
            ),
          );
          setChatStreamError(streamError.message || "流式回复失败，请稍后再试。");
          setChatStreamStatus("error");
        }
      });

      if (sendOperationRef.current !== sendOperationId || activeThreadIdRef.current !== resolvedThreadId) {
        return;
      }

      setMessages((current) =>
        current.map((message) => (message.id === assistantMessageId ? { ...message, isStreaming: false } : message)),
      );
      setChatStreamStatus((current) => (current === "streaming" ? "success" : current));
      setStreamStatusDetail((current) => current ?? "回复已完成");
    } catch (error) {
      if (sendOperationRef.current !== sendOperationId || activeThreadIdRef.current !== resolvedThreadId) {
        return;
      }

      const message = error instanceof Error ? error.message : "流式回复失败，请稍后再试。";

      if (!hasReceivedStreamEvent) {
        setStreamStatusDetail("流式连接未开始，正在切换到普通发送...");

        try {
          const fallback = await api.sendMessage(resolvedThreadId, payload);
          if (sendOperationRef.current !== sendOperationId || activeThreadIdRef.current !== resolvedThreadId) {
            return;
          }

          const assistant = fallback.assistant_message;

          setMessages((current) =>
            current.map((item) => {
              if (item.id === clientMessageId) {
                return {
                  ...item,
                  id: fallback.message_id || item.id,
                  metadata: { ...item.metadata, fallback },
                };
              }

              if (item.id === assistantMessageId) {
                return {
                  ...item,
                  id: fallback.assistant_message_id || assistant?.id || item.id,
                  content: assistant?.assistant_text || assistant?.content || "普通发送已完成，但暂时没有返回可展示的回复。",
                  isStreaming: false,
                  riskLevel: assistant?.risk_level ?? null,
                  suggestedActions: assistant?.suggested_actions ?? [],
                  deliveryStatus: fallback.delivery_status,
                  intent: assistant?.intent,
                  sessionSummary: assistant?.session_summary,
                  turnStatus: fallback.turn_status,
                  failureReason: fallback.failure_reason,
                  turnId: fallback.turn_id ?? item.turnId,
                  assistantMessageId: fallback.assistant_message_id ?? assistant?.id ?? item.assistantMessageId,
                  metadata: {
                    ...item.metadata,
                    fallback,
                    turn_id: fallback.turn_id ?? item.turnId,
                    assistant_message_id: fallback.assistant_message_id ?? assistant?.id ?? item.assistantMessageId,
                  },
                };
              }

              return item;
            }),
          );
          setChatStreamStatus("success");
          setChatStreamError(null);
          setStreamStatusDetail(fallback.delivery_status ? `已用普通发送完成 · ${fallback.delivery_status}` : "已用普通发送完成");
          void handleHighRiskChatResponse({
            threadId: fallback.thread_id || resolvedThreadId,
            riskLevel: assistant?.risk_level ?? null,
            detectedSignals: [
              assistant?.intent,
              fallback.delivery_status,
              fallback.turn_status,
              ...(assistant?.suggested_actions ?? []),
            ].filter((item): item is string => typeof item === "string" && item.length > 0),
          });
          return;
        } catch (fallbackError) {
          if (sendOperationRef.current !== sendOperationId || activeThreadIdRef.current !== resolvedThreadId) {
            return;
          }

          const fallbackMessage = fallbackError instanceof Error ? fallbackError.message : "普通发送也失败了，请稍后再试。";
          setChatStreamError(fallbackMessage);
          setStreamStatusDetail("普通发送回退失败");
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantMessageId
                ? {
                    ...item,
                    content: "这次回复还没能开始生成，请稍后再试。",
                    isStreaming: false,
                    failureReason: fallbackMessage,
                  }
                : item,
            ),
          );
          setChatStreamStatus("error");
          return;
        }
      }

      setChatStreamStatus("error");
      setChatStreamError(message);
      setStreamStatusDetail("流式回复已中断");
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantMessageId
            ? {
                ...item,
                content: item.content === "正在整理回应..." ? "这次回复还没能开始生成，请稍后再试。" : item.content,
                isStreaming: false,
                failureReason: message,
              }
            : item,
        ),
      );
    }
    })();

    return true;
  };

  const handleMessageFeedback = useCallback(
    async (message: Message, feedback: ConversationFeedbackValue) => {
      if (!activeThreadId || message.role !== "assistant" || !message.turnId) return;
      if (message.feedbackState?.status === "submitting" || message.feedbackState?.status === "submitted") return;

      updateMessage(message.id, (current) => ({
        ...current,
        feedbackState: { value: feedback, status: "submitting" },
      }));

      try {
        await api.submitConversationQualityFeedback({
          thread_id: activeThreadId,
          turn_id: message.turnId,
          feedback,
        });
        updateMessage(message.id, (current) => ({
          ...current,
          feedbackState: { value: feedback, status: "submitted" },
        }));
      } catch {
        updateMessage(message.id, (current) => ({
          ...current,
          feedbackState: { value: feedback, status: "failed" },
        }));
      }
    },
    [activeThreadId, updateMessage],
  );

  const handleQuickAction = async (action: QuickAction) => {
    if (chatStreamStatus === "streaming" || createThreadStatus === "loading" || draftCreationRef.current) return;
    if (!isDailyOpeningSuggestionsVisible) return;

    setActiveQuickActionId(action.id);
    setQuickActionError(null);
    setQuickActionResult(null);
    setQuickActionStatus("success");

    markDailyOpeningSuggestionsSeenToday(getDailyOpeningSuggestionStorage(), dailyOpeningSuggestionOwnerId);
    dismissDailyOpeningSuggestionsForSession({
      ownerId: dailyOpeningSuggestionOwnerId,
      sessionKeys: dailyOpeningSuggestionSessionKeys,
    });
    setIsDailyOpeningSuggestionsVisible(false);
    activateDraft();
    setDraftInputSeed({ id: crypto.randomUUID(), text: action.title });
    setActiveQuickActionId(null);
  };

  const handleStartNewThread = () => {
    if (chatStreamStatus === "streaming" || createThreadStatus === "loading") return;
    activateDraft();
  };

  const handleMoodTagToggle = (tagId: string) => {
    setMoodStatus("idle");
    setMoodError(null);
    setMoodTags((current) =>
      current.includes(tagId) ? current.filter((item) => item !== tagId) : [...current, tagId],
    );
  };

  const handleMoodSubmit = async () => {
    if (moodStatus === "submitting" || hasRecordedMoodToday) return;

    setMoodStatus("submitting");
    setMoodError(null);

    try {
      const response = await api.createMoodLog({
        mood_score: moodScore,
        mood_tags: moodTags,
        note: moodNote.trim() ? moodNote.trim() : null,
      });
      setLatestMoodLog(response);
      setRecordedMoodCheckInDay(markMoodCheckInRecordedToday(getMoodCheckInStorage(), moodCheckInOwnerId));
      setMoodStatus("success");
      setMoodNote("");
      await loadMoodTrend(moodTrendRange);
      await loadWeeklySummary();
    } catch (error) {
      setMoodStatus("error");
      setMoodError(error instanceof Error ? error.message : "情绪记录提交失败，请稍后再试。");
    }
  };

  return (
    <div className={`ningyu-transition ${isNight ? "is-night" : "is-day"}`}>
      <div className={`ningyu-shell ${isNight ? "is-night" : "is-day"}`}>
        <Background isNight={isNight} />
        <Header
          isNight={isNight}
          displayName={displayName}
          userModeLabel={userModeLabels[userMode]}
          safetyState={safetyState}
          onToggleNight={toggleThemeMode}
          onToggleSafetyEntry={handleToggleSafetyEntry}
          isSafetyEntryOpen={isSafetyEntryOpen}
        />
        <main className="ningyu-shell__body">
          <FloatingEdgeControls
            activePanel={activeEdgePanel}
            createThreadStatus={createThreadStatus}
            isSafetyEntryOpen={isSafetyEntryOpen}
            shouldReduceMotion={shouldReduceMotion}
            onPanelChange={handleEdgePanelChange}
            onStartNewThread={handleStartNewThread}
            onToggleSafetyEntry={handleToggleSafetyEntry}
          />
          <AnimatePresence>
            {activeEdgePanel === "history" ? (
              <AccessibleLayer
                className="ningyu-edge-panel ningyu-edge-panel--left"
                id="ningyu-history-panel"
                key="history"
                label="History panel"
                shouldReduceMotion={shouldReduceMotion}
                slideDirection="left"
                onClose={closeEdgePanel}
              >
                <button className="ningyu-edge-panel__close" type="button" onClick={closeEdgePanel} aria-label="Close history panel">
                  x
                </button>
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
              </AccessibleLayer>
            ) : null}
          </AnimatePresence>
          <ChatWorkspace
            isNight={isNight}
            shouldReduceMotion={shouldReduceMotion}
            primarySuggestion={homeSuggestions[0]?.label ?? ""}
            primarySupportLabel={supportResources[1].title}
            messages={messages}
            messageListStatus={messageListStatus}
            messageListError={messageListError}
            activeThreadId={activeThreadId}
            isInputDisabled={chatStreamStatus === "streaming" || createThreadStatus === "loading"}
            chatStreamStatus={chatStreamStatus}
            chatStreamError={chatStreamError}
            graphUpdates={graphUpdates}
            streamStatusDetail={streamStatusDetail}
            draftInputSeed={draftInputSeed}
            onSend={handleSend}
            onMessageFeedback={handleMessageFeedback}
          />
          <AnimatePresence>
            {activeEdgePanel === "tools" ? (
              <AccessibleLayer
                className="ningyu-edge-panel ningyu-edge-panel--right"
                id="ningyu-tools-panel"
                key="tools"
                label="Tools panel"
                shouldReduceMotion={shouldReduceMotion}
                slideDirection="right"
                onClose={closeEdgePanel}
              >
                <button className="ningyu-edge-panel__close" type="button" onClick={closeEdgePanel} aria-label="Close tools panel">
                  x
                </button>
                <RightPanel
                  isNight={isNight}
                  currentUserLabel={displayName}
                  userMode={userMode}
                  statusTags={statusTags}
                  suggestions={visibleHomeSuggestions}
                  supportResources={supportResources}
                  safetyState={safetyState}
                  isSafetyEntryOpen={isSafetyEntryOpen}
                  highRiskSafety={highRiskSafety}
                  moodScore={moodScore}
                  moodTags={moodTags}
                  moodNote={moodNote}
                  moodStatus={moodStatus}
                  moodError={moodError}
                  latestMoodLog={latestMoodLog}
                  hasRecordedMoodToday={hasRecordedMoodToday}
                  moodTrendRange={moodTrendRange}
                  moodTrendStatus={moodTrendStatus}
                  moodTrendError={moodTrendError}
                  moodTrend={moodTrend}
                  weeklySummaryStatus={weeklySummaryStatus}
                  weeklySummaryError={weeklySummaryError}
                  weeklySummary={weeklySummary}
                  quickActionStatus={quickActionStatus}
                  activeQuickActionId={activeQuickActionId}
                  quickActionError={quickActionError}
                  quickActionResult={quickActionResult}
                  tests={tests}
                  testListStatus={testListStatus}
                  testListError={testListError}
                  onMoodScoreChange={setMoodScore}
                  onMoodTagToggle={handleMoodTagToggle}
                  onMoodNoteChange={setMoodNote}
                  onMoodSubmit={handleMoodSubmit}
                  onMoodTrendRangeChange={setMoodTrendRange}
                  onQuickAction={handleQuickAction}
                  onToggleSafetyEntry={handleToggleSafetyEntry}
                  onRetrySafetyState={handleRetrySafetyState}
                />
              </AccessibleLayer>
            ) : null}
          </AnimatePresence>
          <AnimatePresence>
            {isSafetyEntryOpen ? (
              <SafetySupportLayer
                key="safety-layer"
                userMode={userMode}
                safetyState={safetyState}
                highRiskSafety={highRiskSafety}
                supportResources={supportResources}
                shouldReduceMotion={shouldReduceMotion}
                onClose={closeSafetyLayer}
                onRetrySafetyState={handleRetrySafetyState}
              />
            ) : null}
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}

function AccessibleLayer({
  children,
  className,
  id,
  label,
  shouldReduceMotion,
  slideDirection,
  onClose,
}: {
  children: ReactNode;
  className: string;
  id: string;
  label: string;
  shouldReduceMotion: boolean;
  slideDirection: "left" | "right";
  onClose: () => void;
}) {
  const layerRef = useRef<HTMLDivElement>(null);
  const offset = slideDirection === "left" ? -28 : 28;

  useEffect(() => {
    const target = layerRef.current?.querySelector<HTMLElement>(focusableSelector) ?? layerRef.current;
    target?.focus();
  }, []);

  return (
    <motion.div
      ref={layerRef}
      className={className}
      id={id}
      role="dialog"
      aria-modal="false"
      aria-label={label}
      tabIndex={-1}
      initial={shouldReduceMotion ? false : { opacity: 0, x: offset }}
      animate={{ opacity: 1, x: 0 }}
      exit={shouldReduceMotion ? undefined : { opacity: 0, x: offset / 2 }}
      transition={{ duration: 0.24, ease: "easeOut" }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      {children}
    </motion.div>
  );
}

function SafetySupportLayer({
  userMode,
  safetyState,
  highRiskSafety,
  supportResources,
  shouldReduceMotion,
  onClose,
  onRetrySafetyState,
}: {
  userMode: UserMode;
  safetyState: { tone: SafetyTone; label: string; detail: string };
  highRiskSafety: HighRiskSafetyState | null;
  supportResources: HomeSupportResource[];
  shouldReduceMotion: boolean;
  onClose: () => void;
  onRetrySafetyState: () => void;
}) {
  const layerRef = useRef<HTMLDivElement>(null);
  const isHighRisk = Boolean(highRiskSafety);

  useEffect(() => {
    const target = layerRef.current?.querySelector<HTMLElement>(focusableSelector) ?? layerRef.current;
    target?.focus();
  }, []);

  return (
    <motion.div
      className="ningyu-safety-layer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ningyu-safety-layer-title"
      initial={shouldReduceMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={shouldReduceMotion ? undefined : { opacity: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <button className="ningyu-safety-layer__backdrop" type="button" tabIndex={-1} aria-label="Close safety support" onClick={onClose} />
      <motion.div
        ref={layerRef}
        className={`ningyu-safety-layer__sheet ${isHighRisk ? "is-high-risk" : ""}`}
        tabIndex={-1}
        initial={shouldReduceMotion ? false : { opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={shouldReduceMotion ? undefined : { opacity: 0, y: 12, scale: 0.98 }}
        transition={{ duration: 0.24, ease: "easeOut" }}
      >
        <div className="ningyu-safety-layer__header">
          <span>
            <Icon name="shield" />
          </span>
          <div>
            <small>{isHighRisk ? "High priority safety layer" : "Safety support"}</small>
            <h2 id="ningyu-safety-layer-title">{isHighRisk ? "Put safety first right now" : "Safety support is ready"}</h2>
            <p>{safetyState.detail}</p>
          </div>
          <button className="ningyu-safety-layer__close" type="button" onClick={onClose} aria-label="Close safety support">
            x
          </button>
        </div>

        <div className="ningyu-safety-layer__status" aria-live="polite">
          <strong>{safetyState.label}</strong>
          <span>
            {highRiskSafety
              ? highRiskSafety.eventStatus === "recorded"
                ? `Crisis event recorded${highRiskSafety.eventId ? ` · ${highRiskSafety.eventId}` : ""}`
                : highRiskSafety.eventStatus === "recording"
                  ? "Recording crisis event..."
                  : highRiskSafety.error || "Crisis event record failed, but support remains available."
              : "No high-risk event is currently active."}
          </span>
        </div>

        <SafetyGuidanceCard userMode={userMode} highRiskSafety={highRiskSafety} />

        <div className="ningyu-safety-layer__resources" aria-label="Safety resources">
          {supportResources.map((resource) => (
            <button className="ningyu-support-card" key={resource.id} type="button">
              <Icon name={resource.icon} />
              <span>
                <small>{resource.label}</small>
                {resource.title}
              </span>
            </button>
          ))}
        </div>

        <div className="ningyu-safety-layer__actions">
          <button type="button" onClick={onRetrySafetyState}>
            Recheck safety status
          </button>
          <button type="button" onClick={onClose}>
            Return to chat
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

function Background({ isNight }: { isNight: boolean }) {
  return (
    <div className="ningyu-bg" aria-hidden="true">
      <img className={`ningyu-bg__image ${isNight ? "is-hidden" : ""}`} src={bgDay} alt="" />
      <img className={`ningyu-bg__image ${isNight ? "" : "is-hidden"}`} src={bgNight} alt="" />
      <div className="ningyu-bg__wash" />
    </div>
  );
}

function GentleLoginTransition({ children, isNight }: { children: React.ReactNode; isNight: boolean }) {
  const [isFinished, setIsFinished] = useState(false);

  return (
    <div className={`ningyu-transition ${isNight ? "is-night" : "is-day"}`}>
      {children}
      {!isFinished ? (
        <div className="ningyu-login" aria-labelledby="ningyu-login-title">
          <div className="ningyu-login__mist" />
          <section className="ningyu-login__box">
            <div className="ningyu-login__logo">
              <img src={logo} alt="宁语 Logo" />
            </div>
            <h2 id="ningyu-login-title">深呼吸，感受微风</h2>
            <input type="text" placeholder="你的名字..." aria-label="你的名字" />
            <button type="button" onClick={() => setIsFinished(true)}>
              开启陪伴
            </button>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function Header({
  isNight,
  displayName,
  userModeLabel,
  safetyState,
  onToggleNight,
  onToggleSafetyEntry,
  isSafetyEntryOpen,
}: {
  isNight: boolean;
  displayName: string;
  userModeLabel: string;
  safetyState: { tone: SafetyTone; label: string; detail: string };
  onToggleNight: () => void;
  onToggleSafetyEntry: () => void;
  isSafetyEntryOpen: boolean;
}) {
  return (
    <header className="ningyu-header">
      <div className="ningyu-brand">
        <img src={logo} alt="宁语 Logo" />
        <div>
          <h1>宁语 · 心灵陪伴</h1>
          <p>
            <span className="ningyu-brand__dot" />
            微风正在倾听 · {displayName} · {userModeLabel}
          </p>
        </div>
      </div>
      <div className="ningyu-header__actions">
        <button
          className="ningyu-round-button"
          type="button"
          onClick={onToggleNight}
          aria-label={isNight ? "切换到日间模式" : "切换到夜间模式"}
        >
          <Icon name={isNight ? "moon" : "sun"} />
        </button>
        <SafetyIndicator
          isNight={isNight}
          safetyState={safetyState}
          isExpanded={isSafetyEntryOpen}
          onToggle={onToggleSafetyEntry}
        />
      </div>
    </header>
  );
}

function FloatingEdgeControls({
  activePanel,
  createThreadStatus,
  isSafetyEntryOpen,
  shouldReduceMotion,
  onPanelChange,
  onStartNewThread,
  onToggleSafetyEntry,
}: {
  activePanel: EdgePanel;
  createThreadStatus: CreateThreadStatus;
  isSafetyEntryOpen: boolean;
  shouldReduceMotion: boolean;
  onPanelChange: (panel: EdgePanel) => void;
  onStartNewThread: () => void;
  onToggleSafetyEntry: () => void;
}) {
  const openPanel = (panel: Exclude<EdgePanel, null>) => {
    onPanelChange(activePanel === panel ? null : panel);
  };

  return (
    <>
      <motion.div
        className="ningyu-floating-controls ningyu-floating-controls--left"
        initial={shouldReduceMotion ? false : { opacity: 0, x: -16 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.38, delay: 0.2, ease: "easeOut" }}
      >
        <button
          id="ningyu-history-trigger"
          className={activePanel === "history" ? "ningyu-edge-button is-active" : "ningyu-edge-button"}
          type="button"
          onClick={() => openPanel("history")}
          aria-expanded={activePanel === "history"}
          aria-controls="ningyu-history-panel"
          aria-label="Open history panel"
        >
          <Icon name="clock" />
          <span>History</span>
        </button>
        <button className="ningyu-edge-button" type="button" onClick={onStartNewThread} disabled={createThreadStatus === "loading"} aria-label="Start new chat">
          <Icon name="plus" />
          <span>New</span>
        </button>
      </motion.div>

      <motion.div
        className="ningyu-floating-controls ningyu-floating-controls--right"
        initial={shouldReduceMotion ? false : { opacity: 0, x: 16 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.38, delay: 0.28, ease: "easeOut" }}
      >
        <button
          id="ningyu-tools-trigger"
          className={activePanel === "tools" ? "ningyu-edge-button is-active" : "ningyu-edge-button"}
          type="button"
          onClick={() => openPanel("tools")}
          aria-expanded={activePanel === "tools"}
          aria-controls="ningyu-tools-panel"
          aria-label="Open tools panel"
        >
          <Icon name="spark" />
          <span>Tools</span>
        </button>
        <button
          id="ningyu-safety-trigger"
          className={isSafetyEntryOpen ? "ningyu-edge-button ningyu-edge-button--safety is-active" : "ningyu-edge-button ningyu-edge-button--safety"}
          type="button"
          onClick={onToggleSafetyEntry}
          aria-expanded={isSafetyEntryOpen}
          aria-label="Open safety support"
        >
          <Icon name="shield" />
          <span>SOS</span>
        </button>
      </motion.div>
    </>
  );
}

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
  return (
    <aside className="ningyu-sidebar ningyu-sidebar--left" aria-label="会话与功能入口">
      <div className="ningyu-sidebar__top">
        <span className="ningyu-sidebar__caption">对话工作台</span>
        <button
          className={createThreadStatus === "loading" ? "ningyu-new-chat is-loading" : "ningyu-new-chat"}
          type="button"
          onClick={onStartNewThread}
          disabled={createThreadStatus === "loading"}
        >
          <Icon name="plus" />
          {createThreadStatus === "loading" ? "正在创建..." : "开始新对话"}
        </button>
        {createThreadStatus === "error" ? <p className="ningyu-new-chat__error">{createThreadError}</p> : null}
      </div>

      <div className="ningyu-thread-list">
        <div className="ningyu-section-label">
          <Icon name="clock" />
          续聊与状态
        </div>
        {threadListStatus === "loading" ? <p className="ningyu-thread-list__state">正在加载最近对话...</p> : null}
        {threadListStatus === "error" ? <p className="ningyu-thread-list__state is-error">{threadListError}</p> : null}
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
          <p className="ningyu-thread-list__meta">还有 {overflowThreadCount} 条更早对话，后续接入历史分页。</p>
        ) : null}
      </div>

      <div className="ningyu-sidebar__bottom">
        <span className="ningyu-sidebar__caption">工具入口</span>
        <button type="button">
          <Icon name="spark" />
          情绪记录
        </button>
        <button type="button">
          <Icon name="settings" />
          设置
        </button>
      </div>
      <span className="ningyu-sidebar__mode">
        {isNight ? "夜间陪伴" : "日间陪伴"} · {userModeLabel} · {memoryModeLabel}
      </span>
    </aside>
  );
}

function ChatWorkspace({
  isNight,
  shouldReduceMotion,
  primarySuggestion,
  primarySupportLabel,
  messages,
  messageListStatus,
  messageListError,
  activeThreadId,
  isInputDisabled,
  chatStreamStatus,
  chatStreamError,
  graphUpdates,
  streamStatusDetail,
  draftInputSeed,
  onSend,
  onMessageFeedback,
}: {
  isNight: boolean;
  shouldReduceMotion: boolean;
  primarySuggestion: string;
  primarySupportLabel: string;
  messages: Message[];
  messageListStatus: MessageListStatus;
  messageListError: string | null;
  activeThreadId: string | null;
  isInputDisabled: boolean;
  chatStreamStatus: ChatStreamStatus;
  chatStreamError: string | null;
  graphUpdates: GraphUpdateItem[];
  streamStatusDetail: string | null;
  draftInputSeed: DraftInputSeed | null;
  onSend: SendMessageHandler;
  onMessageFeedback: (message: Message, feedback: ConversationFeedbackValue) => void | Promise<void>;
}) {
  return (
    <section className="ningyu-chat" aria-label="聊天工作区">
      <div className="ningyu-chat__scroll">
        <motion.div
          className="ningyu-chat__inner"
          initial={shouldReduceMotion ? false : { opacity: 0, y: 20, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.48, delay: 0.12, ease: "easeOut" }}
        >
          {messageListStatus === "loading" ? (
            <ChatStateMessage title="正在载入对话" detail="风正在把这段聊天记录带回来..." />
          ) : messageListStatus === "error" ? (
            <ChatStateMessage title="消息暂时没加载出来" detail={messageListError ?? "请稍后再试。"} tone="error" />
          ) : messages.length === 0 ? (
            <WelcomeState
              isNight={isNight}
              primarySuggestion={primarySuggestion}
              primarySupportLabel={primarySupportLabel}
              activeThreadId={activeThreadId}
            />
          ) : (
            <div className="ningyu-chat__messages">
              {messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  isNight={isNight}
                  onFeedback={onMessageFeedback}
                />
              ))}
              {graphUpdates.length || chatStreamStatus !== "idle" ? (
                <GraphUpdateTrail
                  status={chatStreamStatus}
                  error={chatStreamError}
                  detail={streamStatusDetail}
                  updates={graphUpdates}
                />
              ) : null}
            </div>
          )}
        </motion.div>
      </div>
      <div className="ningyu-chat__input">
        <ChatInput
          isNight={isNight}
          isSending={chatStreamStatus === "streaming"}
          isDisabled={isInputDisabled}
          draftInputSeed={draftInputSeed}
          onSend={onSend}
        />
      </div>
    </section>
  );
}

function WelcomeState({
  isNight,
  primarySuggestion,
  primarySupportLabel,
  activeThreadId,
}: {
  isNight: boolean;
  primarySuggestion: string;
  primarySupportLabel: string;
  activeThreadId: string | null;
}) {
  return (
    <div className="ningyu-welcome">
      <Icon name="leaf" className="ningyu-welcome__leaf ningyu-welcome__leaf--one" />
      <Icon name="leaf" className="ningyu-welcome__leaf ningyu-welcome__leaf--two" />
      <img src={logo} alt="" aria-hidden="true" />
      <h2>
        <Icon name="leaf" />
        宁语陪伴
        <Icon name="leaf" />
      </h2>
      <p>
        {activeThreadId
          ? "这段对话还安静地留着空白。你可以先在下方写一句想被听见的话。"
          : `先把世界的声音放轻一点。可以从「${primarySuggestion}」轻轻开口，也可以把此刻最想被听见的心事慢慢写下；如果需要更直接的支撑，右侧的 ${primarySupportLabel} 会一直为你留着一束光。`}
      </p>
      <span>
        <Icon name="spark" />
        {isNight ? "夜色很轻，慢慢说就好" : "随时可以开始"}
      </span>
    </div>
  );
}

function ChatStateMessage({ title, detail, tone = "default" }: { title: string; detail: string; tone?: "default" | "error" }) {
  return (
    <div className={`ningyu-chat-state is-${tone}`}>
      <Icon name={tone === "error" ? "shield" : "wind"} />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function ChatInput({
  isNight,
  isSending,
  isDisabled,
  draftInputSeed,
  onSend,
}: {
  isNight: boolean;
  isSending: boolean;
  isDisabled: boolean;
  draftInputSeed: DraftInputSeed | null;
  onSend: SendMessageHandler;
}) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (!draftInputSeed) {
      return;
    }

    setValue(draftInputSeed.text);
  }, [draftInputSeed]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextValue = value.trim();
    if (!nextValue || isDisabled) return;
    void (async () => {
      try {
        const accepted = await onSend(nextValue);
        if (accepted) {
          setValue("");
        }
      } catch {
        // Keep the draft text if sending fails before acceptance.
      }
    })();
  };

  return (
    <form className="ningyu-input" onSubmit={handleSubmit}>
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder={isSending ? "宁语正在回应..." : isNight ? "夜风很安静，慢慢写..." : "随便写点什么吧，风在听..."}
        aria-label="输入聊天内容"
        disabled={isDisabled}
        rows={1}
      />
      <button className={value.trim() ? "is-active" : ""} type="submit" disabled={!value.trim() || isDisabled} aria-label="发送">
        <Icon name="send" />
      </button>
    </form>
  );
}

function ChatMessage({
  message,
  isNight,
  onFeedback,
}: {
  message: Message;
  isNight: boolean;
  onFeedback: (message: Message, feedback: ConversationFeedbackValue) => void | Promise<void>;
}) {
  const isUser = message.role === "user";
  const metaLabel = message.role === "user" ? "你" : message.role === "system" ? "系统" : "宁语";
  const isAssistant = message.role === "assistant";
  const canSendFeedback = isAssistant && !message.isStreaming && Boolean(message.turnId);
  const feedbackStatus = message.feedbackState?.status;
  const feedbackDisabled = feedbackStatus === "submitting" || feedbackStatus === "submitted";

  return (
    <article className={`ningyu-message ${isUser ? "is-user" : "is-assistant"} ${isNight ? "is-night" : ""}`}>
      <div className="ningyu-message__meta">
        <span>{metaLabel}</span>
        {message.riskLevel && message.riskLevel !== "L0" ? <small>{message.riskLevel}</small> : null}
      </div>
      <div className="ningyu-message__bubble">
        <Icon name={isUser ? "leaf" : "wind"} />
        <p>{message.content}</p>
        {message.trace ? <TraceLine trace={message.trace} /> : null}
      </div>
      <div className="ningyu-message__footer">
        <time>{message.timestamp}</time>
        {canSendFeedback ? (
          <div className="ningyu-message-feedback" aria-label="消息反馈">
            {conversationFeedbackOptions.map((option) => {
              const selected = message.feedbackState?.value === option.value;

              return (
                <button
                  key={option.value}
                  className={selected ? "is-selected" : ""}
                  type="button"
                  onClick={() => onFeedback(message, option.value)}
                  disabled={feedbackDisabled}
                  aria-pressed={selected}
                >
                  {option.label}
                </button>
              );
            })}
            {feedbackStatus ? (
              <span aria-live="polite">
                {feedbackStatus === "submitting" ? "记录中" : feedbackStatus === "submitted" ? "已记录" : "未记录"}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function TraceLine({ trace }: { trace: TraceTiming }) {
  const totalDuration = formatDuration(trace.totalMs);
  const graphDuration = formatDuration(trace.totalGraphMs);
  const nodeDuration = formatDuration(trace.nodeMs);
  const slowestDuration = formatDuration(trace.slowestNodeMs);
  const ragDuration = formatDuration(trace.ragMs ?? trace.ragTotalMs);
  const hasRagInfo =
    trace.ragStatus ||
    trace.ragUsed !== undefined ||
    trace.retrievedMemoryCount !== undefined ||
    trace.retrievedExampleCount !== undefined ||
    trace.ragSkippedReason;
  const parts = [
    totalDuration ? `总耗时 ${totalDuration}` : null,
    graphDuration ? `图 ${graphDuration}` : null,
    trace.node && nodeDuration ? `节点 ${trace.node} ${nodeDuration}` : trace.node ? `节点 ${trace.node}` : null,
    hasRagInfo ? formatRagStatus(trace) : ragDuration ? `RAG ${ragDuration}` : null,
    trace.ragSkippedReason ? `原因 ${trace.ragSkippedReason}` : null,
    trace.slowestNode && slowestDuration ? `最慢 ${trace.slowestNode} ${slowestDuration}` : null,
  ].filter((part): part is string => Boolean(part));

  if (!parts.length) {
    return null;
  }

  return <span className="ningyu-trace-line">{parts.join(" · ")}</span>;
}

function GraphUpdateTrail({
  status,
  error,
  detail,
  updates,
}: {
  status: ChatStreamStatus;
  error: string | null;
  detail: string | null;
  updates: GraphUpdateItem[];
}) {
  return (
    <div className={`ningyu-graph-trail is-${status}`} aria-live="polite">
      <div className="ningyu-graph-trail__header">
        <span>{status === "streaming" ? "正在处理" : status === "error" ? "处理遇到问题" : "处理线索"}</span>
        {detail ? <small>{detail}</small> : null}
      </div>
      {error ? <p className="ningyu-graph-trail__error">{error}</p> : null}
      {updates.length ? (
        <div className="ningyu-graph-trail__items">
          {updates.map((update) => (
            <div className="ningyu-graph-step" key={update.id}>
              <span className="ningyu-graph-step__dot" />
              <span>
                <strong>{update.node}</strong>
                <small>{[update.status, update.riskLevel, update.intent].filter(Boolean).join(" · ") || "处理中"}</small>
                <em>{update.detail}</em>
              </span>
            </div>
          ))}
        </div>
      ) : status === "streaming" ? (
        <p className="ningyu-graph-trail__empty">正在等待第一段处理线索...</p>
      ) : null}
    </div>
  );
}

function RightPanel({
  isNight,
  currentUserLabel,
  userMode,
  statusTags,
  suggestions,
  supportResources,
  safetyState,
  isSafetyEntryOpen,
  highRiskSafety,
  moodScore,
  moodTags,
  moodNote,
  moodStatus,
  moodError,
  latestMoodLog,
  hasRecordedMoodToday,
  moodTrendRange,
  moodTrendStatus,
  moodTrendError,
  moodTrend,
  weeklySummaryStatus,
  weeklySummaryError,
  weeklySummary,
  quickActionStatus,
  activeQuickActionId,
  quickActionError,
  quickActionResult,
  tests,
  testListStatus,
  testListError,
  onMoodScoreChange,
  onMoodTagToggle,
  onMoodNoteChange,
  onMoodSubmit,
  onMoodTrendRangeChange,
  onQuickAction,
  onToggleSafetyEntry,
  onRetrySafetyState,
}: {
  isNight: boolean;
  currentUserLabel: string;
  userMode: UserMode;
  statusTags: string[];
  suggestions: QuickAction[];
  supportResources: HomeSupportResource[];
  safetyState: { tone: SafetyTone; label: string; detail: string };
  isSafetyEntryOpen: boolean;
  highRiskSafety: HighRiskSafetyState | null;
  moodScore: number;
  moodTags: string[];
  moodNote: string;
  moodStatus: MoodCheckInStatus;
  moodError: string | null;
  latestMoodLog: MoodLogResponse | null;
  hasRecordedMoodToday: boolean;
  moodTrendRange: MoodTrendRange;
  moodTrendStatus: MoodTrendStatus;
  moodTrendError: string | null;
  moodTrend: MoodTrendResponse | null;
  weeklySummaryStatus: WeeklySummaryStatus;
  weeklySummaryError: string | null;
  weeklySummary: WeeklySummaryResponse | null;
  quickActionStatus: QuickActionStatus;
  activeQuickActionId: string | null;
  quickActionError: string | null;
  quickActionResult: QuickActionResult | null;
  tests: TestListItem[];
  testListStatus: TestListStatus;
  testListError: string | null;
  onMoodScoreChange: (score: number) => void;
  onMoodTagToggle: (tagId: string) => void;
  onMoodNoteChange: (note: string) => void;
  onMoodSubmit: () => void;
  onMoodTrendRangeChange: (range: MoodTrendRange) => void;
  onQuickAction: (action: QuickAction) => void;
  onToggleSafetyEntry: () => void;
  onRetrySafetyState: () => void;
}) {
  const [activeToolSurface, setActiveToolSurface] = useState<"launcher" | "journey" | "actions" | "settings" | "safety">("launcher");
  const shouldShowGuidance = isSafetyEntryOpen || Boolean(highRiskSafety);

  useEffect(() => {
    if (shouldShowGuidance) {
      setActiveToolSurface("safety");
    }
  }, [shouldShowGuidance]);

  if (activeToolSurface === "launcher") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="Tools launcher">
        <section className="ningyu-panel-section ningyu-tool-launcher">
          <span className="ningyu-panel-section__caption">Quiet tools</span>
          <h2>
            <Icon name="spark" />
            Choose one gentle next step
          </h2>
          <div className="ningyu-tool-launcher__grid">
            <button type="button" onClick={() => setActiveToolSurface("journey")}>
              <Icon name="heart" />
              <span>
                <strong>Today's mood</strong>
                <small>Check in, trend, and weekly summary.</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("journey")}>
              <Icon name="leaf" />
              <span>
                <strong>My journey</strong>
                <small>A calm record of recent days.</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("actions")}>
              <Icon name="light" />
              <span>
                <strong>Suggested actions</strong>
                <small>Small prompts connected to chat.</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("settings")}>
              <Icon name="settings" />
              <span>
                <strong>Settings / tests</strong>
                <small>Published tests and placeholders.</small>
              </span>
            </button>
          </div>
        </section>
      </aside>
    );
  }

  if (activeToolSurface === "journey") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="My journey">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <section className="ningyu-panel-section ningyu-panel-section--mood">
          <span className="ningyu-panel-section__caption">My journey</span>
          <h2>
            <Icon name="heart" />
            Mood check-in
          </h2>
          <MoodCheckIn
            moodScore={moodScore}
            moodTags={moodTags}
            moodNote={moodNote}
            moodStatus={moodStatus}
            moodError={moodError}
            latestMoodLog={latestMoodLog}
            hasRecordedMoodToday={hasRecordedMoodToday}
            onMoodScoreChange={onMoodScoreChange}
            onMoodTagToggle={onMoodTagToggle}
            onMoodNoteChange={onMoodNoteChange}
            onMoodSubmit={onMoodSubmit}
          />
          <MoodTrendCard
            range={moodTrendRange}
            status={moodTrendStatus}
            error={moodTrendError}
            trend={moodTrend}
            onRangeChange={onMoodTrendRangeChange}
          />
          <WeeklySummaryCard status={weeklySummaryStatus} error={weeklySummaryError} summary={weeklySummary} />
        </section>
      </aside>
    );
  }

  if (activeToolSurface === "actions") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="Suggested actions">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <section className="ningyu-panel-section ningyu-panel-section--suggestions">
          <span className="ningyu-panel-section__caption">Suggested actions</span>
          <h2>
            <Icon name="light" />
            Nearby next steps
          </h2>
          <div className="ningyu-suggestions">
            {suggestions.length ? suggestions.map((suggestion) => (
              <button
                key={suggestion.id}
                className={activeQuickActionId === suggestion.id ? "is-loading" : ""}
                type="button"
                onClick={() => onQuickAction(suggestion)}
                disabled={quickActionStatus === "loading"}
              >
                {activeQuickActionId === suggestion.id ? "Working..." : suggestion.label}
              </button>
            )) : <p className="ningyu-tool-empty">No suggested action is waiting right now.</p>}
          </div>
          <QuickActionFeedback status={quickActionStatus} error={quickActionError} result={quickActionResult} />
        </section>
      </aside>
    );
  }

  if (activeToolSurface === "settings") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="Settings and tests">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <section className="ningyu-panel-section">
          <span className="ningyu-panel-section__caption">Settings / tests</span>
          <h2>
            <Icon name="settings" />
            {currentUserLabel}
          </h2>
          <div className="ningyu-tags">
            {statusTags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
          <TestListSurface tests={tests} status={testListStatus} error={testListError} />
          <div className="ningyu-placeholder-list" aria-label="Future settings">
            <span>Privacy controls are being prepared.</span>
            <span>Memory review will stay explicit and reversible.</span>
            <span>Knowledge settings will appear here when ready.</span>
          </div>
        </section>
      </aside>
    );
  }

  return (
    <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="状态、安全与建议">
      <section className={`ningyu-panel-section ningyu-panel-section--safety ${highRiskSafety ? "is-high-risk" : ""}`}>
        <span className="ningyu-panel-section__caption">优先级最高</span>
        <h2>
          <Icon name="wind" />
          安全入口
        </h2>
        <button
          className={`ningyu-safety-entry is-${safetyState.tone}`}
          type="button"
          onClick={onToggleSafetyEntry}
          aria-expanded={isSafetyEntryOpen}
        >
          <span className="ningyu-safety-entry__badge">
            <Icon name="shield" />
          </span>
          <span className="ningyu-safety-entry__content">
            <strong>{safetyState.label}</strong>
            <small>{safetyState.detail}</small>
          </span>
        </button>
        <div className="ningyu-safety-actions">
          <button type="button" onClick={onToggleSafetyEntry}>
            {isSafetyEntryOpen ? "收起支持" : "展开支持"}
          </button>
          <button type="button" onClick={onRetrySafetyState}>
            重新检查
          </button>
        </div>
        {shouldShowGuidance ? <SafetyGuidanceCard userMode={userMode} highRiskSafety={highRiskSafety} /> : null}
      </section>

      <section className={`ningyu-panel-section ${isSafetyEntryOpen ? "is-open" : ""}`}>
        <span className="ningyu-panel-section__caption">当前上下文</span>
        <h2>
          <Icon name="heart" />
          当前状态 · {currentUserLabel}
        </h2>
        <div className="ningyu-tags">
          {statusTags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </section>

      <section className="ningyu-panel-section ningyu-panel-section--mood">
        <span className="ningyu-panel-section__caption">一分钟 check-in</span>
        <h2>
          <Icon name="heart" />
          此刻心情
        </h2>
        <MoodCheckIn
          moodScore={moodScore}
          moodTags={moodTags}
          moodNote={moodNote}
          moodStatus={moodStatus}
          moodError={moodError}
          latestMoodLog={latestMoodLog}
          hasRecordedMoodToday={hasRecordedMoodToday}
          onMoodScoreChange={onMoodScoreChange}
          onMoodTagToggle={onMoodTagToggle}
          onMoodNoteChange={onMoodNoteChange}
          onMoodSubmit={onMoodSubmit}
        />
        <MoodTrendCard
          range={moodTrendRange}
          status={moodTrendStatus}
          error={moodTrendError}
          trend={moodTrend}
          onRangeChange={onMoodTrendRangeChange}
        />
        <WeeklySummaryCard status={weeklySummaryStatus} error={weeklySummaryError} summary={weeklySummary} />
      </section>

      <section className="ningyu-panel-section">
        <span className="ningyu-panel-section__caption">需要时可直接使用</span>
        <h2>
          <Icon name="heart" />
          安全支持
        </h2>
        {supportResources.map((resource) => (
          <button className="ningyu-support-card" key={resource.id} type="button">
            <Icon name={resource.icon} />
            <span>
              <small>{resource.label}</small>
              {resource.title}
            </span>
          </button>
        ))}
      </section>

      {suggestions.length ? (
        <section className="ningyu-panel-section ningyu-panel-section--suggestions">
          <span className="ningyu-panel-section__caption">今天第一次对话</span>
          <h2>
            <Icon name="light" />
            今日开场
          </h2>
          <div className="ningyu-suggestions">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion.id}
                className={activeQuickActionId === suggestion.id ? "is-loading" : ""}
                type="button"
                onClick={() => onQuickAction(suggestion)}
                disabled={quickActionStatus === "loading"}
              >
                {activeQuickActionId === suggestion.id ? "准备中..." : suggestion.label}
              </button>
            ))}
          </div>
          <QuickActionFeedback status={quickActionStatus} error={quickActionError} result={quickActionResult} />
        </section>
      ) : null}
      <span className="ningyu-sidebar__mode">
        {isNight ? "夜间保持安全入口可见" : "白天保持安全入口可见"}
      </span>
    </aside>
  );
}

function ToolBackButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="ningyu-tool-back" type="button" onClick={onClick}>
      <Icon name="wind" />
      Back to tools
    </button>
  );
}

function TestListSurface({
  tests,
  status,
  error,
}: {
  tests: TestListItem[];
  status: TestListStatus;
  error: string | null;
}) {
  return (
    <div className="ningyu-tests-surface">
      <div className="ningyu-tests-surface__header">
        <strong>Published tests</strong>
        <small>{status === "loading" ? "Loading" : `${tests.length} available`}</small>
      </div>
      {status === "error" ? <p className="ningyu-tool-empty is-error">{error}</p> : null}
      {status !== "loading" && status !== "error" && tests.length === 0 ? <p className="ningyu-tool-empty">No tests are available yet.</p> : null}
      <div className="ningyu-tests-list">
        {tests.map((test) => {
          const isPublished = test.status === "published";

          return (
            <button key={test.test_id} type="button" disabled={!isPublished} aria-disabled={!isPublished}>
              <span>
                <strong>{test.title}</strong>
                <small>
                  {test.test_type} · {test.estimated_minutes} min · {isPublished ? "published" : "not published"}
                </small>
              </span>
              <em>{isPublished ? "Ready" : "Locked"}</em>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SafetyGuidanceCard({
  userMode,
  highRiskSafety,
}: {
  userMode: UserMode;
  highRiskSafety: HighRiskSafetyState | null;
}) {
  const isHighRisk = Boolean(highRiskSafety);
  const riskLabel = highRiskSafety?.riskLevel === "L3" ? "L3 高风险" : highRiskSafety?.riskLevel === "L2" ? "L2 需要支持" : "安全支持";
  const statusLabel =
    highRiskSafety?.eventStatus === "recorded"
      ? "安全事件已记录"
      : highRiskSafety?.eventStatus === "recording"
        ? "正在记录安全事件"
        : highRiskSafety?.eventStatus === "error"
          ? "记录失败，支持入口仍可用"
          : "随时可以展开支持";
  const steps = isHighRisk
    ? ["先停下正在做的事，让自己离开危险物品或危险地点。", "如果有立即危险，请联系本地紧急服务，或让身边的人立刻陪你。", "把现在的情况用一句话告诉一个真实的人，不要独自扛着。"]
    : ["把注意力放回呼吸，先让身体慢下来。", "如果这份感受变得很重，可以打开紧急咨询或热线。", "你可以先说一句最真实的话，不需要整理得很完整。"];

  return (
    <div className={`ningyu-safety-guidance ${isHighRisk ? "is-high-risk" : ""}`}>
      <div className="ningyu-safety-guidance__header">
        <span>
          <Icon name="shield" />
        </span>
        <div>
          <strong>{isHighRisk ? "先把安全放在第一位" : "安全支持已准备好"}</strong>
          <small>
            {riskLabel} · {statusLabel}
          </small>
        </div>
      </div>
      <ol className="ningyu-safety-guidance__steps">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      {userMode === "teen" ? (
        <div className="ningyu-trusted-adult">
          <strong>可信任大人引导</strong>
          <span>优先联系监护人、老师、学校心理老师，或此刻能来到你身边的成年人。</span>
          <span>可以直接发：“我现在不太安全，需要你陪我一下。”</span>
        </div>
      ) : (
        <div className="ningyu-trusted-adult">
          <strong>现实支持</strong>
          <span>选择一个现在能回应你的人，发出简短求助，比独自处理更安全。</span>
        </div>
      )}
    </div>
  );
}

function QuickActionFeedback({
  status,
  error,
  result,
}: {
  status: QuickActionStatus;
  error: string | null;
  result: QuickActionResult | null;
}) {
  if (status === "idle" && !result) {
    return null;
  }

  if (status === "loading") {
    return <p className="ningyu-quick-action-feedback">正在准备入口...</p>;
  }

  if (status === "error") {
    return <p className="ningyu-quick-action-feedback is-error">{error}</p>;
  }

  if (!result) {
    return null;
  }

  return (
    <div className="ningyu-quick-action-feedback is-success">
      <strong>{result.title}</strong>
      <span>{result.detail}</span>
      <small>
        Thread {result.threadId}
      </small>
    </div>
  );
}

function MoodCheckIn({
  moodScore,
  moodTags,
  moodNote,
  moodStatus,
  moodError,
  latestMoodLog,
  hasRecordedMoodToday,
  onMoodScoreChange,
  onMoodTagToggle,
  onMoodNoteChange,
  onMoodSubmit,
}: {
  moodScore: number;
  moodTags: string[];
  moodNote: string;
  moodStatus: MoodCheckInStatus;
  moodError: string | null;
  latestMoodLog: MoodLogResponse | null;
  hasRecordedMoodToday: boolean;
  onMoodScoreChange: (score: number) => void;
  onMoodTagToggle: (tagId: string) => void;
  onMoodNoteChange: (note: string) => void;
  onMoodSubmit: () => void;
}) {
  const selectedTags = moodTagOptions.filter((tag) => moodTags.includes(tag.id)).map((tag) => tag.label);
  const latestSummary = hasRecordedMoodToday
    ? latestMoodLog
      ? `今日已记录：${latestMoodLog.mood_score}/5${selectedTags.length ? ` · ${selectedTags.join("、")}` : ""}`
      : "今天已经记录过心情了，明天再来轻轻更新。"
    : latestMoodLog
    ? `刚刚记录：${latestMoodLog.mood_score}/5${selectedTags.length ? ` · ${selectedTags.join("、")}` : ""}`
    : "选一个最接近此刻的分数就好，不需要解释得很完整。";
  const summaryTone = moodStatus === "error" ? "error" : hasRecordedMoodToday ? "success" : moodStatus;
  const showControls = shouldShowMoodCheckInControls({ hasRecordedMoodToday });

  return (
    <div className="ningyu-mood-checkin">
      {showControls ? (
        <>
          <div className="ningyu-mood-score" role="group" aria-label="选择心情分数">
            {[1, 2, 3, 4, 5].map((score) => (
              <button
                key={score}
                className={moodScore === score ? "is-active" : ""}
                type="button"
                onClick={() => onMoodScoreChange(score)}
                aria-pressed={moodScore === score}
              >
                <strong>{score}</strong>
                <span>{moodScoreLabels[score - 1]}</span>
              </button>
            ))}
          </div>

          <div className="ningyu-mood-tags" role="group" aria-label="选择心情标签">
            {moodTagOptions.map((tag) => (
              <button
                key={tag.id}
                className={moodTags.includes(tag.id) ? "is-active" : ""}
                type="button"
                onClick={() => onMoodTagToggle(tag.id)}
                aria-pressed={moodTags.includes(tag.id)}
              >
                {tag.label}
              </button>
            ))}
          </div>

          <textarea
            value={moodNote}
            onChange={(event) => onMoodNoteChange(event.target.value)}
            placeholder="想补一句也可以..."
            rows={2}
            aria-label="心情备注"
          />

          <div className="ningyu-mood-checkin__footer">
            <p className={`ningyu-mood-checkin__summary is-${summaryTone}`}>
              {moodStatus === "error" ? moodError : latestSummary}
            </p>
            <button type="button" onClick={onMoodSubmit} disabled={moodStatus === "submitting"}>
              {moodStatus === "submitting" ? "记录中..." : "记录心情"}
            </button>
          </div>
        </>
      ) : (
        <div className="ningyu-mood-checkin__recorded-state" aria-live="polite">
          <p className={`ningyu-mood-checkin__summary is-${summaryTone}`}>{latestSummary}</p>
          <button className="is-recorded" type="button" disabled>
            今日已记录
          </button>
        </div>
      )}
    </div>
  );
}

function MoodTrendCard({
  range,
  status,
  error,
  trend,
  onRangeChange,
}: {
  range: MoodTrendRange;
  status: MoodTrendStatus;
  error: string | null;
  trend: MoodTrendResponse | null;
  onRangeChange: (range: MoodTrendRange) => void;
}) {
  const dailyPoints = trend?.daily ?? [];
  const hasDailyPoints = dailyPoints.length > 0;
  const maxMoodScore = 5;

  return (
    <div className="ningyu-mood-trend">
      <div className="ningyu-mood-trend__header">
        <span>情绪趋势</span>
        <div className="ningyu-mood-trend__range" role="group" aria-label="选择情绪趋势范围">
          {(["7d", "30d"] as MoodTrendRange[]).map((item) => (
            <button
              key={item}
              className={range === item ? "is-active" : ""}
              type="button"
              onClick={() => onRangeChange(item)}
              aria-pressed={range === item}
            >
              {item === "7d" ? "7天" : "30天"}
            </button>
          ))}
        </div>
      </div>

      {status === "loading" ? <p className="ningyu-mood-trend__state">正在轻轻整理趋势...</p> : null}
      {status === "error" ? <p className="ningyu-mood-trend__state is-error">{error}</p> : null}
      {status !== "loading" && status !== "error" && !hasDailyPoints ? (
        <p className="ningyu-mood-trend__state">还没有足够记录，先从今天这一笔开始。</p>
      ) : null}

      {trend && hasDailyPoints ? (
        <>
          <div className="ningyu-mood-trend__summary">
            <strong>平均 {trend.avg_mood_score.toFixed(1)} / 5</strong>
            <span>{trend.summary}</span>
          </div>

          <div className="ningyu-mood-trend__bars" aria-label={`${range === "7d" ? "7天" : "30天"}情绪趋势`}>
            {dailyPoints.map((point) => {
              const heightPercent = Math.max(18, Math.min(100, (point.mood_score / maxMoodScore) * 100));

              return (
                <span className="ningyu-mood-trend__bar" key={point.date} title={`${point.date}：${point.mood_score}/5`}>
                  <i style={{ height: `${heightPercent}%` }} />
                </span>
              );
            })}
          </div>

          {trend.top_tags.length ? (
            <div className="ningyu-mood-trend__tags" aria-label="常见心情标签">
              {trend.top_tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function WeeklySummaryCard({
  status,
  error,
  summary,
}: {
  status: WeeklySummaryStatus;
  error: string | null;
  summary: WeeklySummaryResponse | null;
}) {
  const hasSummary = Boolean(summary?.summary);

  return (
    <div className="ningyu-weekly-summary">
      <div className="ningyu-weekly-summary__header">
        <span>本周小结</span>
        {summary?.generated_by ? <small>{summary.generated_by}</small> : null}
      </div>

      {status === "loading" ? <p className="ningyu-weekly-summary__state">正在整理这一周的情绪线索...</p> : null}
      {status === "error" ? <p className="ningyu-weekly-summary__state is-error">{error}</p> : null}
      {status !== "loading" && status !== "error" && !hasSummary ? (
        <p className="ningyu-weekly-summary__state">本周小结还在等待更多记录。</p>
      ) : null}

      {summary && hasSummary ? (
        <>
          <p className="ningyu-weekly-summary__text">{summary.summary}</p>

          {summary.top_tags.length ? (
            <div className="ningyu-weekly-summary__tags" aria-label="本周常见心情标签">
              {summary.top_tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          ) : null}

          {summary.suggested_actions.length ? (
            <div className="ningyu-weekly-summary__actions" aria-label="本周建议行动">
              {summary.suggested_actions.map((action) => (
                <button key={action} type="button">
                  {action}
                </button>
              ))}
            </div>
          ) : null}

          <small className="ningyu-weekly-summary__range">{summary.range}</small>
        </>
      ) : null}
    </div>
  );
}

function SafetyIndicator({
  isNight,
  safetyState,
  isExpanded,
  onToggle,
}: {
  isNight: boolean;
  safetyState: { tone: SafetyTone; label: string; detail: string };
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      className={`ningyu-safety is-${safetyState.tone} ${isExpanded ? "is-expanded" : ""}`}
      type="button"
      onClick={onToggle}
      aria-expanded={isExpanded}
      aria-label={isExpanded ? "收起安全入口" : "展开安全入口"}
    >
      <Icon name="shield" />
      <span className="ningyu-safety__content">
        <strong>{isNight ? "夜间安全陪伴" : "安全陪伴空间"}</strong>
        <small>{safetyState.label}</small>
      </span>
    </button>
  );
}

function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  const paths: Record<IconName, React.ReactNode> = {
    moon: <path d="M19.5 15.2A7.2 7.2 0 0 1 8.8 4.5 8 8 0 1 0 19.5 15.2Z" />,
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19" />
      </>
    ),
    shield: <path d="M12 22s7-3.5 7-10V5l-7-3-7 3v7c0 6.5 7 10 7 10Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    spark: <path d="m12 2 1.6 6.4L20 10l-6.4 1.6L12 18l-1.6-6.4L4 10l6.4-1.6L12 2Z" />,
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.4 3.1a7 7 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.4 3.1h5l.4-3.1a7 7 0 0 0 1.7-1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z" />
      </>
    ),
    heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z" />,
    phone: <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.4 19.4 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.5 3a2 2 0 0 1-.6 1.8L7.7 9.7a16 16 0 0 0 6.6 6.6l1.2-1.2a2 2 0 0 1 1.8-.6l3 .5a2 2 0 0 1 1.7 1.9Z" />,
    message: <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z" />,
    light: (
      <>
        <path d="M9 18h6" />
        <path d="M10 22h4" />
        <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2Z" />
      </>
    ),
    wind: <path d="M3 8h11a3 3 0 1 0-3-3M4 12h15a3 3 0 1 1-3 3M3 16h8" />,
    leaf: <path d="M5 21c7-1 13-7 14-14-7 1-13 7-14 14ZM5 21c2-4 6-8 10-10" />,
    send: <path d="m22 2-7 20-4-9-9-4 20-7Z" />,
  };

  return (
    <svg className={`ningyu-icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}
