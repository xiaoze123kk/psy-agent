import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import bgDay from "../../imports/wcbg.png";
import bgNight from "../../imports/wcbg_night.png";
import logo from "../../imports/wind-chat-logo.png";
import { api } from "../../api";
import { useAppState } from "../state";
import { graphUpdateDetail } from "./conversationQuality";
import {
  buildDailyOpeningSuggestions,
  claimDailyOpeningSuggestionsForSession,
  dismissDailyOpeningSuggestionsForSession,
  getDailyOpeningSuggestionOwnerId,
  getDailyOpeningSuggestionStorage,
} from "./dailyOpeningSuggestions";
import {
  getMoodCheckInOwnerId,
  getMoodCheckInStorage,
  hasMoodCheckInForToday,
  markMoodCheckInRecordedToday,
  readRecordedMoodCheckInDay,
  shouldShowMoodCheckInControls,
} from "./moodCheckInFrequency";
import {
  buildConversationList,
  buildDraftThread,
  formatMessageTime,
  toThreadListItemFromStartThread,
  type ConversationListEntry,
} from "./threadList";
import "./NingyuAppShell.css";
import type {
  ChatStreamAcceptedEvent,
  ChatStreamErrorEvent,
  ChatStreamEventName,
  ChatStreamFinalEvent,
  ChatStreamGraphUpdateEvent,
  ChatStreamHeartbeatEvent,
  ChatStreamTokenEvent,
  MemoryMode,
  MessageItem,
  MoodLogResponse,
  MoodTrendResponse,
  RiskLevel,
  SendMessageRequest,
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
  isStreaming?: boolean;
  deliveryStatus?: string;
  intent?: string;
  sessionSummary?: string;
  turnStatus?: string;
  failureReason?: string | null;
}

type HomeEntry = ConversationListEntry;

interface HomeSupportResource {
  id: string;
  icon: "phone" | "message";
  label: string;
  title: string;
}

interface QuickAction {
  id: string;
  label: string;
  title: string;
  kind: "chat";
}

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

type MessageFeedback = "helpful" | "not_helpful";
type ShellPhase = "loading" | "ready" | "error";
type SafetyTone = "loading" | "stable" | "watch" | "support" | "error";
type MoodCheckInStatus = "idle" | "submitting" | "success" | "error";
type MoodTrendRange = "7d" | "30d";
type MoodTrendStatus = "idle" | "loading" | "success" | "error";
type WeeklySummaryStatus = "idle" | "loading" | "success" | "error";
type QuickActionStatus = "idle" | "loading" | "success" | "error";
type ThreadListStatus = "idle" | "loading" | "success" | "error";
type MessageListStatus = "idle" | "loading" | "success" | "error";
type CreateThreadStatus = "idle" | "loading" | "success" | "error";
type ChatStreamStatus = "idle" | "streaming" | "success" | "error";

interface SafetyStateDisplay {
  tone: SafetyTone;
  label: string;
  detail: string;
}

interface NingyuShellViewModel {
  isNight: boolean;
  displayName: string;
  userMode: UserMode;
  userModeLabel: string;
  memoryModeLabel: string;
  safetyState: SafetyStateDisplay;
  isSafetyEntryOpen: boolean;
  homeEntries: HomeEntry[];
  homeSuggestions: QuickAction[];
  statusTags: string[];
  activeThreadId: string | null;
  threadListStatus: ThreadListStatus;
  threadListError: string | null;
  createThreadStatus: CreateThreadStatus;
  createThreadError: string | null;
  messages: Message[];
  messageListStatus: MessageListStatus;
  messageListError: string | null;
  messageFeedback: Record<string, MessageFeedback>;
  chatStreamStatus: ChatStreamStatus;
  chatStreamError: string | null;
  graphUpdates: GraphUpdateItem[];
  streamStatusDetail: string | null;
  supportResources: HomeSupportResource[];
  highRiskSafety: HighRiskSafetyState | null;
  moodScore: number;
  moodTags: string[];
  moodNote: string;
  moodStatus: MoodCheckInStatus;
  moodError: string | null;
  latestMoodLog: MoodLogResponse | null;
  showMoodCheckInControls: boolean;
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
}

interface NingyuShellHandlers {
  onToggleNight: () => void;
  onToggleSafetyEntry: () => void;
  onSelectThread: (threadId: string) => void;
  onStartNewThread: () => void;
  onSend: (content: string) => void | Promise<void>;
  onMessageFeedback: (messageId: string, feedback: MessageFeedback) => void;
  onMoodScoreChange: (score: number) => void;
  onMoodTagToggle: (tagId: string) => void;
  onMoodNoteChange: (note: string) => void;
  onMoodSubmit: () => void;
  onMoodTrendRangeChange: (range: MoodTrendRange) => void;
  onQuickAction: (action: QuickAction) => void;
  onRetrySafetyState: () => void;
}

interface NingyuThreeColumnShellProps {
  viewModel: NingyuShellViewModel;
  handlers: NingyuShellHandlers;
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
  { id: "hotline", icon: "phone", label: "24小时热线", title: "400-xxx-xxxx" },
  { id: "urgent-chat", icon: "message", label: "紧急咨询", title: "立即连接" },
];
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

function extractSuggestedActions(metadata: Record<string, unknown>): string[] {
  const directActions = readStringArray(metadata.suggested_actions);
  if (directActions.length) return directActions;

  const nestedAssistant = metadata.assistant_message;
  if (nestedAssistant && typeof nestedAssistant === "object" && !Array.isArray(nestedAssistant)) {
    return readStringArray((nestedAssistant as Record<string, unknown>).suggested_actions);
  }

  return [];
}

function buildGraphUpdateDetail(update: ChatStreamGraphUpdateEvent): string {
  return graphUpdateDetail(update) || "正在整理这一步的上下文";
}

function mapGraphUpdate(update: ChatStreamGraphUpdateEvent): GraphUpdateItem {
  return {
    id: crypto.randomUUID(),
    node: update.node,
    status: update.status,
    riskLevel: update.risk_level,
    intent: update.intent,
    detail: buildGraphUpdateDetail(update),
  };
}

function isHighRiskLevel(riskLevel: RiskLevel | string | null | undefined): riskLevel is "L2" | "L3" {
  return riskLevel === "L2" || riskLevel === "L3";
}

function mapMessageItem(message: MessageItem): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    timestamp: formatMessageTime(message.created_at),
    riskLevel: message.risk_level,
    suggestedActions: extractSuggestedActions(message.metadata),
    metadata: message.metadata,
  };
}

export function NingyuAppShell() {
  const {
    currentUser,
    ageModeProfile,
    userMode,
    memoryMode,
    privacySettings,
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
  const [weeklySummaryStatus, setWeeklySummaryStatus] = useState<WeeklySummaryStatus>("idle");
  const [weeklySummaryError, setWeeklySummaryError] = useState<string | null>(null);
  const [weeklySummary, setWeeklySummary] = useState<WeeklySummaryResponse | null>(null);
  const [quickActionStatus, setQuickActionStatus] = useState<QuickActionStatus>("idle");
  const [activeQuickActionId, setActiveQuickActionId] = useState<string | null>(null);
  const [quickActionError, setQuickActionError] = useState<string | null>(null);
  const [quickActionResult, setQuickActionResult] = useState<QuickActionResult | null>(null);
  const [threads, setThreads] = useState<ThreadListItem[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [threadListStatus, setThreadListStatus] = useState<ThreadListStatus>("idle");
  const [threadListError, setThreadListError] = useState<string | null>(null);
  const [messageListStatus, setMessageListStatus] = useState<MessageListStatus>("idle");
  const [messageListError, setMessageListError] = useState<string | null>(null);
  const [createThreadStatus, setCreateThreadStatus] = useState<CreateThreadStatus>("idle");
  const [createThreadError, setCreateThreadError] = useState<string | null>(null);
  const [messageFeedback, setMessageFeedback] = useState<Record<string, MessageFeedback>>({});
  const [chatStreamStatus, setChatStreamStatus] = useState<ChatStreamStatus>("idle");
  const [chatStreamError, setChatStreamError] = useState<string | null>(null);
  const [graphUpdates, setGraphUpdates] = useState<GraphUpdateItem[]>([]);
  const [streamStatusDetail, setStreamStatusDetail] = useState<string | null>(null);
  const [highRiskSafety, setHighRiskSafety] = useState<HighRiskSafetyState | null>(null);
  const dailyOpeningSessionKeysRef = useRef<Set<string>>(new Set());
  const skipNextMessageLoadThreadIdRef = useRef<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setShellPhase("ready");
    }, 720);

    return () => window.clearTimeout(timer);
  }, []);

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

  const loadThreads = useCallback(async () => {
    setThreadListStatus("loading");
    setThreadListError(null);

    try {
      const response = await api.listThreads();
      setThreads(response.items);
      setThreadListStatus("success");
      setActiveThreadId((current) => current ?? response.items[0]?.thread_id ?? null);
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
      setMessages(response.items.map(mapMessageItem));
      setMessageListStatus("success");
    } catch (error) {
      setMessageListStatus("error");
      setMessageListError(error instanceof Error ? error.message : "消息列表加载失败，请稍后再试。");
    }
  }, []);

  const activateThread = useCallback((thread: ThreadListItem, options: { clearMessages?: boolean } = {}) => {
    setThreads((current) => [thread, ...current.filter((item) => item.thread_id !== thread.thread_id)]);
    if (options.clearMessages) {
      skipNextMessageLoadThreadIdRef.current = thread.thread_id;
    }
    setActiveThreadId(thread.thread_id);
    setMessageListError(null);

    if (options.clearMessages) {
      setMessages([]);
      setMessageListStatus("success");
    }
  }, []);

  const ensureThreadForSend = async (content: string): Promise<string> => {
    if (activeThreadId) {
      return activeThreadId;
    }

    setCreateThreadStatus("loading");
    setCreateThreadError(null);

    const thread = await api.startThread({
      mode: "companion",
      title: content.trim().slice(0, 18) || "新的陪伴对话",
    });
    const threadItem = toThreadListItemFromStartThread(thread);
    skipNextMessageLoadThreadIdRef.current = threadItem.thread_id;
    activateThread(threadItem, { clearMessages: false });
    setCreateThreadStatus("success");
    return threadItem.thread_id;
  };

  useEffect(() => {
    void loadMoodTrend(moodTrendRange);
  }, [loadMoodTrend, moodTrendRange]);

  useEffect(() => {
    void loadWeeklySummary();
  }, [loadWeeklySummary]);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    if (!activeThreadId) {
      setMessageListStatus("idle");
      return;
    }

    if (skipNextMessageLoadThreadIdRef.current === activeThreadId) {
      skipNextMessageLoadThreadIdRef.current = null;
      return;
    }

    void loadMessages(activeThreadId);
  }, [activeThreadId, loadMessages]);

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
  const moodCheckInOwnerId = useMemo(() => getMoodCheckInOwnerId(currentUser?.user_id), [currentUser?.user_id]);
  const moodCheckInStorage = useMemo(() => getMoodCheckInStorage(), []);
  const recordedMoodCheckInDay = useMemo(
    () => readRecordedMoodCheckInDay(moodCheckInStorage, moodCheckInOwnerId),
    [moodCheckInOwnerId, moodCheckInStorage, latestMoodLog],
  );
  const hasRecordedMoodToday = useMemo(
    () =>
      hasMoodCheckInForToday({
        recordedDay: recordedMoodCheckInDay,
        latestMoodLog,
        moodTrend,
      }),
    [latestMoodLog, moodTrend, recordedMoodCheckInDay],
  );
  const showMoodCheckInControls = shouldShowMoodCheckInControls({ hasRecordedMoodToday });
  const conversationList = useMemo(
    () =>
      buildConversationList({
        threads,
        draft: activeThreadId ? null : buildDraftThread(),
        displayName,
        userMode,
        memoryMode,
      }),
    [activeThreadId, displayName, memoryMode, threads, userMode],
  );
  const homeEntries = useMemo(
    () => conversationList.sections.flatMap((section) => section.entries),
    [conversationList],
  );
  const dailyOpeningOwnerId = useMemo(
    () => getDailyOpeningSuggestionOwnerId(currentUser?.user_id),
    [currentUser?.user_id],
  );
  const homeSuggestions = useMemo(() => {
    const suggestions = buildDailyOpeningSuggestions({
      userMode,
      memoryMode,
      isNight,
      latestMoodLog,
      moodTrend,
      weeklySummary,
      hasRecordedMoodToday,
    });
    const claim = claimDailyOpeningSuggestionsForSession({
      storage: getDailyOpeningSuggestionStorage(),
      ownerId: dailyOpeningOwnerId,
      sessionKeys: dailyOpeningSessionKeysRef.current,
    });

    return claim.visible ? suggestions : [];
  }, [
    dailyOpeningOwnerId,
    hasRecordedMoodToday,
    isNight,
    latestMoodLog,
    memoryMode,
    moodTrend,
    userMode,
    weeklySummary,
  ]);
  useEffect(
    () => () => {
      dismissDailyOpeningSuggestionsForSession({
        ownerId: dailyOpeningOwnerId,
        sessionKeys: dailyOpeningSessionKeysRef.current,
      });
    },
    [dailyOpeningOwnerId],
  );
  const statusTags = useMemo(
    () => [
      userModeLabels[userMode],
      ageModeProfile.ageLabel,
      ageModeProfile.description,
      memoryModeLabels[memoryMode],
      privacySettings.saveTranscript ? "保存转写" : "不保存转写",
    ],
    [
      memoryMode,
      ageModeProfile.ageLabel,
      ageModeProfile.description,
      privacySettings.saveTranscript,
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

  const handleSend = async (content: string) => {
    if (chatStreamStatus === "streaming") return;

    let targetThreadId: string;
    try {
      targetThreadId = await ensureThreadForSend(content);
    } catch (error) {
      setChatStreamStatus("error");
      setChatStreamError(error instanceof Error ? error.message : "新对话创建失败，请稍后再试。");
      setCreateThreadStatus("error");
      setCreateThreadError(error instanceof Error ? error.message : "新对话创建失败，请稍后再试。");
      return;
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

    try {
      await api.streamMessage(targetThreadId, payload, (eventName, data) => {
        hasReceivedStreamEvent = true;
        const typedEvent = eventName as ChatStreamEventName;

        if (typedEvent === "accepted") {
          const accepted = data as unknown as ChatStreamAcceptedEvent;
          setStreamStatusDetail(accepted.turn_status ? `已接收 · ${accepted.turn_status}` : "已接收，正在轻轻整理...");
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? { ...message, turnStatus: accepted.turn_status, metadata: { ...message.metadata, accepted } }
                : message,
            ),
          );
          return;
        }

        if (typedEvent === "graph_update") {
          const update = data as unknown as ChatStreamGraphUpdateEvent;
          setGraphUpdates((current) => [...current.slice(-4), mapGraphUpdate(update)]);
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
                    metadata: { ...message.metadata, final },
                  }
                : message,
            ),
          );
          setStreamStatusDetail(final.delivery_status ? `完成 · ${final.delivery_status}` : "回复已完成");
          setChatStreamStatus("success");
          void handleHighRiskChatResponse({
            threadId: final.thread_id || targetThreadId,
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

      setMessages((current) =>
        current.map((message) => (message.id === assistantMessageId ? { ...message, isStreaming: false } : message)),
      );
      setChatStreamStatus((current) => (current === "streaming" ? "success" : current));
      setStreamStatusDetail((current) => current ?? "回复已完成");
    } catch (error) {
      const message = error instanceof Error ? error.message : "流式回复失败，请稍后再试。";

      if (!hasReceivedStreamEvent) {
        setStreamStatusDetail("流式连接未开始，正在切换到普通发送...");

        try {
          const fallback = await api.sendMessage(targetThreadId, payload);
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
                  metadata: { ...item.metadata, fallback },
                };
              }

              return item;
            }),
          );
          setChatStreamStatus("success");
          setChatStreamError(null);
          setStreamStatusDetail(fallback.delivery_status ? `已用普通发送完成 · ${fallback.delivery_status}` : "已用普通发送完成");
          void handleHighRiskChatResponse({
            threadId: fallback.thread_id || targetThreadId,
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
  };

  const addLocalAssistantMessage = (content: string, suggestedActions: string[] = []) => {
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content,
        timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
        suggestedActions,
      },
    ]);
  };

  const handleMessageFeedback = (messageId: string, feedback: MessageFeedback) => {
    setMessageFeedback((current) => ({
      ...current,
      [messageId]: feedback,
    }));
  };

  const handleQuickAction = async (action: QuickAction) => {
    if (quickActionStatus === "loading") return;

    setQuickActionStatus("loading");
    setActiveQuickActionId(action.id);
    setQuickActionError(null);

    try {
      const thread = await api.startThread({
        mode: "companion",
        title: action.title,
      });

      const result = {
        title: "对话入口已准备",
        detail: `已创建「${thread.title || action.title}」对话。`,
        threadId: thread.thread_id,
      };
      setQuickActionResult(result);
      addLocalAssistantMessage(`${result.detail} 你可以先在这里写下想说的话，后续聊天模块会接入完整消息流。`, [
        "我想从刚才那句话开始",
        "帮我把感受拆小一点",
      ]);

      activateThread(
        {
          ...toThreadListItemFromStartThread(thread),
          title: thread.title || action.title,
        },
        { clearMessages: false },
      );
      setQuickActionStatus("success");
    } catch (error) {
      setQuickActionStatus("error");
      setQuickActionError(error instanceof Error ? error.message : "快捷入口启动失败，请稍后再试。");
    } finally {
      setActiveQuickActionId(null);
    }
  };

  const handleStartNewThread = async () => {
    if (createThreadStatus === "loading") return;

    setCreateThreadStatus("loading");
    setCreateThreadError(null);

    try {
      const thread = await api.startThread({
        mode: "companion",
        title: "新的陪伴对话",
      });
      activateThread(toThreadListItemFromStartThread(thread), { clearMessages: true });
      setCreateThreadStatus("success");
    } catch (error) {
      setCreateThreadStatus("error");
      setCreateThreadError(error instanceof Error ? error.message : "新对话创建失败，请稍后再试。");
    }
  };

  const handleMoodTagToggle = (tagId: string) => {
    setMoodStatus("idle");
    setMoodError(null);
    setMoodTags((current) =>
      current.includes(tagId) ? current.filter((item) => item !== tagId) : [...current, tagId],
    );
  };

  const handleMoodSubmit = async () => {
    if (moodStatus === "submitting") return;

    setMoodStatus("submitting");
    setMoodError(null);

    try {
      const response = await api.createMoodLog({
        mood_score: moodScore,
        mood_tags: moodTags,
        note: moodNote.trim() ? moodNote.trim() : null,
      });
      markMoodCheckInRecordedToday(moodCheckInStorage, moodCheckInOwnerId);
      setLatestMoodLog(response);
      setMoodStatus("success");
      setMoodNote("");
      await loadMoodTrend(moodTrendRange);
      await loadWeeklySummary();
    } catch (error) {
      setMoodStatus("error");
      setMoodError(error instanceof Error ? error.message : "情绪记录提交失败，请稍后再试。");
    }
  };

  const shellViewModel: NingyuShellViewModel = {
    isNight,
    displayName,
    userMode,
    userModeLabel: userModeLabels[userMode],
    memoryModeLabel: memoryModeLabels[memoryMode],
    safetyState,
    isSafetyEntryOpen,
    homeEntries,
    homeSuggestions,
    statusTags,
    activeThreadId,
    threadListStatus,
    threadListError,
    createThreadStatus,
    createThreadError,
    messages,
    messageListStatus,
    messageListError,
    messageFeedback,
    chatStreamStatus,
    chatStreamError,
    graphUpdates,
    streamStatusDetail,
    supportResources,
    highRiskSafety,
    moodScore,
    moodTags,
    moodNote,
    moodStatus,
    moodError,
    latestMoodLog,
    showMoodCheckInControls,
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
  };

  const shellHandlers: NingyuShellHandlers = {
    onToggleNight: toggleThemeMode,
    onToggleSafetyEntry: handleToggleSafetyEntry,
    onSelectThread: setActiveThreadId,
    onStartNewThread: handleStartNewThread,
    onSend: handleSend,
    onMessageFeedback: handleMessageFeedback,
    onMoodScoreChange: setMoodScore,
    onMoodTagToggle: handleMoodTagToggle,
    onMoodNoteChange: setMoodNote,
    onMoodSubmit: handleMoodSubmit,
    onMoodTrendRangeChange: setMoodTrendRange,
    onQuickAction: handleQuickAction,
    onRetrySafetyState: handleRetrySafetyState,
  };

  return <ImmersiveNingyuShellSafe viewModel={shellViewModel} handlers={shellHandlers} />;
}

type ImmersiveToolPanel = "toolMood" | "toolJourney" | "toolSuggestions" | "toolSettings";
type ImmersivePanel = "history" | "tools" | "toolsDashboard" | ImmersiveToolPanel;

const immersivePanelLabels: Record<ImmersivePanel, string> = {
  history: "History panel",
  tools: "Tools launcher",
  toolsDashboard: "Tools panel",
  toolMood: "\u4eca\u5929\u7684\u5fc3\u60c5",
  toolJourney: "\u6211\u7684\u65c5\u7a0b",
  toolSuggestions: "\u5efa\u8bae\u884c\u52a8",
  toolSettings: "\u8bbe\u7f6e\u4e0e\u6d4b\u8bd5",
};

function isImmersiveToolPanel(panel: ImmersivePanel | null): panel is ImmersiveToolPanel {
  return panel === "toolMood" || panel === "toolJourney" || panel === "toolSuggestions" || panel === "toolSettings";
}

function ImmersiveNingyuShellSafe({ viewModel, handlers }: NingyuThreeColumnShellProps) {
  const [activePanel, setActivePanel] = useState<ImmersivePanel | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const openPanel = useCallback((panel: ImmersivePanel, trigger?: HTMLElement) => {
    if (trigger) {
      restoreFocusRef.current = trigger;
    }
    setActivePanel(panel);
  }, []);
  const closePanel = useCallback(() => {
    const focusTarget = restoreFocusRef.current;
    setActivePanel(null);
    window.setTimeout(() => {
      if (focusTarget && document.contains(focusTarget)) {
        focusTarget.focus();
      }
    }, 0);
  }, []);
  const openSafetyPanel = (trigger?: HTMLElement) => {
    openPanel("toolsDashboard", trigger);
    if (!viewModel.isSafetyEntryOpen) {
      handlers.onToggleSafetyEntry();
    }
  };

  useEffect(() => {
    if (!activePanel) return;

    const getFocusableElements = () => {
      const panel = panelRef.current;
      if (!panel) return [];

      return Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.offsetParent !== null);
    };

    const focusFirstElement = window.requestAnimationFrame(() => {
      const firstFocusable = getFocusableElements()[0];
      firstFocusable?.focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closePanel();
        return;
      }

      if (event.key === "Tab") {
        const focusableElements = getFocusableElements();
        if (!focusableElements.length) return;

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];
        const activeElement = document.activeElement;

        if (event.shiftKey && activeElement === firstElement) {
          event.preventDefault();
          lastElement.focus();
          return;
        }

        if (!event.shiftKey && activeElement === lastElement) {
          event.preventDefault();
          firstElement.focus();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFirstElement);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [activePanel, closePanel]);

  return (
    <div className={`ningyu-transition ${viewModel.isNight ? "is-night" : "is-day"}`}>
      <div className={`ningyu-shell ningyu-immersive ${viewModel.isNight ? "is-night" : "is-day"}`}>
        <Background isNight={viewModel.isNight} />
        <header className="ningyu-immersive__topbar">
          <div className="ningyu-immersive-brand">
            <img src={logo} alt="Ningyu Logo" />
            <div>
              <h1>{"\u5b81\u8bed"}</h1>
              <p>
                <span className="ningyu-brand__dot" />
                {viewModel.displayName} / {viewModel.userModeLabel}
              </p>
            </div>
          </div>
          <div className="ningyu-immersive-status" aria-live="polite">
            <span className={`ningyu-immersive-status__tone is-${viewModel.safetyState.tone}`} />
            <strong>{viewModel.safetyState.label}</strong>
            <small>{viewModel.memoryModeLabel}</small>
          </div>
        </header>

        <main className="ningyu-immersive__main">
          <div className="ningyu-immersive-paper">
            <ChatWorkspace
              isNight={viewModel.isNight}
              displayName={viewModel.displayName}
              userModeLabel={viewModel.userModeLabel}
              primarySuggestion={viewModel.homeSuggestions[0]?.label ?? ""}
              primarySupportLabel={viewModel.supportResources[1].title}
              messages={viewModel.messages}
              messageListStatus={viewModel.messageListStatus}
              messageListError={viewModel.messageListError}
              activeThreadId={viewModel.activeThreadId}
              messageFeedback={viewModel.messageFeedback}
              chatStreamStatus={viewModel.chatStreamStatus}
              chatStreamError={viewModel.chatStreamError}
              graphUpdates={viewModel.graphUpdates}
              streamStatusDetail={viewModel.streamStatusDetail}
              onSend={handlers.onSend}
              onMessageFeedback={handlers.onMessageFeedback}
            />
          </div>
        </main>

        <div className="ningyu-immersive-edge ningyu-immersive-edge--left" aria-label="Floating navigation">
          <button type="button" onClick={handlers.onStartNewThread} disabled={viewModel.createThreadStatus === "loading"} aria-label="Start new chat">
            <Icon name="plus" />
          </button>
          <button
            type="button"
            onClick={(event) => openPanel("history", event.currentTarget)}
            aria-controls="ningyu-immersive-active-panel"
            aria-expanded={activePanel === "history"}
            aria-haspopup="dialog"
            aria-label="Chat history"
            title="Chat history"
          >
            <Icon name="clock" />
          </button>
        </div>

        <div className="ningyu-immersive-edge ningyu-immersive-edge--right" aria-label="Floating tools">
          <button type="button" onClick={handlers.onToggleNight} aria-label={viewModel.isNight ? "Switch to day mode" : "Switch to night mode"} title={viewModel.isNight ? "Switch to day mode" : "Switch to night mode"}>
            <Icon name={viewModel.isNight ? "moon" : "sun"} />
          </button>
          <button
            className={`is-safety is-${viewModel.safetyState.tone}`}
            type="button"
            onClick={(event) => openSafetyPanel(event.currentTarget)}
            aria-controls="ningyu-immersive-active-panel"
            aria-expanded={activePanel === "toolsDashboard"}
            aria-haspopup="dialog"
            aria-label="Safety support"
            title="Safety support"
          >
            <Icon name="shield" />
          </button>
          <button
            type="button"
            onClick={(event) => openPanel("tools", event.currentTarget)}
            aria-controls="ningyu-immersive-active-panel"
            aria-expanded={activePanel === "tools" || isImmersiveToolPanel(activePanel)}
            aria-haspopup="dialog"
            aria-label="Tools"
            title="Tools"
          >
            <Icon name="spark" />
          </button>
        </div>

        {activePanel ? (
          <div className={`ningyu-immersive-overlay is-${activePanel}`}>
            <button className="ningyu-immersive-overlay__scrim" type="button" onClick={closePanel} aria-label="Close panel" />
            <aside
              id="ningyu-immersive-active-panel"
              ref={panelRef}
              className={`ningyu-immersive-panel ningyu-immersive-panel--${activePanel} ${isImmersiveToolPanel(activePanel) ? "ningyu-immersive-panel--toolDetail" : ""}`}
              role="dialog"
              aria-modal="true"
              aria-label={immersivePanelLabels[activePanel]}
            >
              <button className="ningyu-immersive-panel__close" type="button" onClick={closePanel} aria-label="Close panel" title="Close panel" data-autofocus="true">
                <Icon name="plus" />
              </button>
              {activePanel === "history" ? (
                <LeftSidebar
                  isNight={viewModel.isNight}
                  entries={viewModel.homeEntries}
                  activeThreadId={viewModel.activeThreadId}
                  threadListStatus={viewModel.threadListStatus}
                  threadListError={viewModel.threadListError}
                  createThreadStatus={viewModel.createThreadStatus}
                  createThreadError={viewModel.createThreadError}
                  userModeLabel={viewModel.userModeLabel}
                  memoryModeLabel={viewModel.memoryModeLabel}
                  onSelectThread={(threadId) => {
                    handlers.onSelectThread(threadId);
                    closePanel();
                  }}
                  onStartNewThread={handlers.onStartNewThread}
                />
              ) : activePanel === "tools" ? (
                <ToolsLauncher
                  onSelectTool={(panel) => setActivePanel(panel)}
                />
              ) : isImmersiveToolPanel(activePanel) ? (
                <ToolDetailPanel
                  panel={activePanel}
                  viewModel={viewModel}
                  handlers={handlers}
                  onBack={() => setActivePanel("tools")}
                />
              ) : (
                <RightPanel
                  isNight={viewModel.isNight}
                  currentUserLabel={viewModel.displayName}
                  userMode={viewModel.userMode}
                  statusTags={viewModel.statusTags}
                  suggestions={viewModel.homeSuggestions}
                  supportResources={viewModel.supportResources}
                  safetyState={viewModel.safetyState}
                  isSafetyEntryOpen={viewModel.isSafetyEntryOpen}
                  highRiskSafety={viewModel.highRiskSafety}
                  moodScore={viewModel.moodScore}
                  moodTags={viewModel.moodTags}
                  moodNote={viewModel.moodNote}
                  moodStatus={viewModel.moodStatus}
                  moodError={viewModel.moodError}
                  latestMoodLog={viewModel.latestMoodLog}
                  showMoodCheckInControls={viewModel.showMoodCheckInControls}
                  moodTrendRange={viewModel.moodTrendRange}
                  moodTrendStatus={viewModel.moodTrendStatus}
                  moodTrendError={viewModel.moodTrendError}
                  moodTrend={viewModel.moodTrend}
                  weeklySummaryStatus={viewModel.weeklySummaryStatus}
                  weeklySummaryError={viewModel.weeklySummaryError}
                  weeklySummary={viewModel.weeklySummary}
                  quickActionStatus={viewModel.quickActionStatus}
                  activeQuickActionId={viewModel.activeQuickActionId}
                  quickActionError={viewModel.quickActionError}
                  quickActionResult={viewModel.quickActionResult}
                  onMoodScoreChange={handlers.onMoodScoreChange}
                  onMoodTagToggle={handlers.onMoodTagToggle}
                  onMoodNoteChange={handlers.onMoodNoteChange}
                  onMoodSubmit={handlers.onMoodSubmit}
                  onMoodTrendRangeChange={handlers.onMoodTrendRangeChange}
                  onQuickAction={handlers.onQuickAction}
                  onToggleSafetyEntry={handlers.onToggleSafetyEntry}
                  onRetrySafetyState={handlers.onRetrySafetyState}
                />
              )}
            </aside>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ToolsLauncher({
  onSelectTool,
}: {
  onSelectTool: (panel: ImmersiveToolPanel) => void;
}) {
  const entries: Array<{ id: string; panel: ImmersiveToolPanel; icon: IconName; title: string; detail: string }> = [
    {
      id: "mood",
      panel: "toolMood",
      icon: "heart",
      title: "\u4eca\u5929\u7684\u5fc3\u60c5",
      detail: "\u8bb0\u5f55\u6b64\u523b\u72b6\u6001\uff0c\u4e0d\u6253\u5f00\u5b8c\u6574\u4eea\u8868\u76d8",
    },
    {
      id: "journey",
      panel: "toolJourney",
      icon: "leaf",
      title: "\u6211\u7684\u65c5\u7a0b",
      detail: "\u67e5\u770b\u8d8b\u52bf\u548c\u672c\u5468\u5c0f\u7ed3",
    },
    {
      id: "suggestions",
      panel: "toolSuggestions",
      icon: "light",
      title: "\u5efa\u8bae\u884c\u52a8",
      detail: "\u6253\u5f00\u53ef\u6267\u884c\u7684\u4f4e\u538b\u5efa\u8bae",
    },
    {
      id: "settings",
      panel: "toolSettings",
      icon: "settings",
      title: "\u8bbe\u7f6e / \u6d4b\u8bd5",
      detail: "\u67e5\u770b\u8bb0\u5fc6\u3001\u9690\u79c1\u548c\u6d4b\u8bd5\u5165\u53e3",
    },
  ];

  return (
    <section className="ningyu-tools-launcher" aria-labelledby="ningyu-tools-launcher-title">
      <div className="ningyu-tools-launcher__header">
        <span>
          <Icon name="spark" />
        </span>
        <div>
          <p>{"\u5de5\u5177"}</p>
          <h2 id="ningyu-tools-launcher-title">{"\u5148\u9009\u4e00\u4e2a\u5165\u53e3"}</h2>
        </div>
      </div>
      <div className="ningyu-tools-launcher__grid">
        {entries.map((entry) => (
          <button key={entry.id} type="button" onClick={() => onSelectTool(entry.panel)}>
            <Icon name={entry.icon} />
            <span>
              <strong>{entry.title}</strong>
              <small>{entry.detail}</small>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ToolDetailPanel({
  panel,
  viewModel,
  handlers,
  onBack,
}: {
  panel: ImmersiveToolPanel;
  viewModel: NingyuShellViewModel;
  handlers: NingyuShellHandlers;
  onBack: () => void;
}) {
  const panelMeta: Record<ImmersiveToolPanel, { icon: IconName; eyebrow: string; title: string; detail: string }> = {
    toolMood: {
      icon: "heart",
      eyebrow: "\u5f53\u4e0b\u8bb0\u5f55",
      title: "\u4eca\u5929\u7684\u5fc3\u60c5",
      detail: "\u5148\u628a\u6b64\u523b\u7684\u611f\u53d7\u653e\u4e0b\u6765\uff0c\u4e0d\u9700\u8981\u7acb\u523b\u5206\u6790\u5b83\u3002",
    },
    toolJourney: {
      icon: "leaf",
      eyebrow: "\u8f7b\u91cf\u56de\u770b",
      title: "\u6211\u7684\u65c5\u7a0b",
      detail: "\u8fd9\u91cc\u4fdd\u7559\u8d8b\u52bf\u548c\u672c\u5468\u5c0f\u7ed3\uff0c\u540e\u7eed\u4f1a\u7ee7\u7eed\u6536\u655b\u6210\u66f4\u5b89\u9759\u7684\u624b\u8d26\u5c42\u3002",
    },
    toolSuggestions: {
      icon: "light",
      eyebrow: "\u4e0b\u4e00\u5c0f\u6b65",
      title: "\u5efa\u8bae\u884c\u52a8",
      detail: "\u9009\u4e00\u4e2a\u5f53\u4e0b\u80fd\u505a\u7684\u5c0f\u52a8\u4f5c\uff0c\u5b83\u4f1a\u7ee7\u7eed\u8d70\u539f\u6709\u5feb\u6377\u884c\u52a8\u903b\u8f91\u3002",
    },
    toolSettings: {
      icon: "settings",
      eyebrow: "\u8bbe\u7f6e\u4e0e\u6d4b\u8bd5",
      title: "\u8bbe\u7f6e / \u6d4b\u8bd5",
      detail: "\u4fdd\u7559\u8bb0\u5fc6\u3001\u9690\u79c1\u3001\u6d4b\u8bd5\u7b49\u5165\u53e3\u7684\u53ef\u8fbe\u6027\uff0c\u672a\u5b8c\u6574\u8fc1\u79fb\u7684\u529f\u80fd\u5148\u660e\u786e\u6807\u6ce8\u3002",
    },
  };
  const meta = panelMeta[panel];

  return (
    <section className="ningyu-tool-detail" aria-labelledby={`ningyu-${panel}-title`}>
      <div className="ningyu-tool-detail__header">
        <button className="ningyu-tool-detail__back" type="button" onClick={onBack}>
          <Icon name="clock" />
          <span>{"\u8fd4\u56de"}</span>
        </button>
        <span className="ningyu-tool-detail__icon">
          <Icon name={meta.icon} />
        </span>
        <div>
          <p>{meta.eyebrow}</p>
          <h2 id={`ningyu-${panel}-title`}>{meta.title}</h2>
          <small>{meta.detail}</small>
        </div>
      </div>

      {panel === "toolMood" ? (
        <div className="ningyu-tool-detail__content">
          <MoodCheckIn
            moodScore={viewModel.moodScore}
            moodTags={viewModel.moodTags}
            moodNote={viewModel.moodNote}
            moodStatus={viewModel.moodStatus}
            moodError={viewModel.moodError}
            latestMoodLog={viewModel.latestMoodLog}
            showControls={viewModel.showMoodCheckInControls}
            onMoodScoreChange={handlers.onMoodScoreChange}
            onMoodTagToggle={handlers.onMoodTagToggle}
            onMoodNoteChange={handlers.onMoodNoteChange}
            onMoodSubmit={handlers.onMoodSubmit}
          />
        </div>
      ) : null}

      {panel === "toolJourney" ? (
        <div className="ningyu-tool-detail__content">
          <MoodTrendCard
            range={viewModel.moodTrendRange}
            status={viewModel.moodTrendStatus}
            error={viewModel.moodTrendError}
            trend={viewModel.moodTrend}
            onRangeChange={handlers.onMoodTrendRangeChange}
          />
          <WeeklySummaryCard
            status={viewModel.weeklySummaryStatus}
            error={viewModel.weeklySummaryError}
            summary={viewModel.weeklySummary}
          />
        </div>
      ) : null}

      {panel === "toolSuggestions" ? (
        <div className="ningyu-tool-detail__content">
          <div className="ningyu-tool-detail__actions" aria-label={meta.title}>
            {viewModel.homeSuggestions.map((suggestion) => (
              <button
                key={suggestion.id}
                className={viewModel.activeQuickActionId === suggestion.id ? "is-loading" : ""}
                type="button"
                onClick={() => handlers.onQuickAction(suggestion)}
                disabled={viewModel.quickActionStatus === "loading"}
              >
                <strong>{viewModel.activeQuickActionId === suggestion.id ? "\u51c6\u5907\u4e2d..." : suggestion.label}</strong>
                <small>{suggestion.title}</small>
              </button>
            ))}
          </div>
          <QuickActionFeedback
            status={viewModel.quickActionStatus}
            error={viewModel.quickActionError}
            result={viewModel.quickActionResult}
          />
        </div>
      ) : null}

      {panel === "toolSettings" ? (
        <div className="ningyu-tool-detail__content">
          <div className="ningyu-tool-detail__status">
            <span>{viewModel.userModeLabel}</span>
            <span>{viewModel.memoryModeLabel}</span>
            {viewModel.statusTags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
          <div className="ningyu-tool-detail__placeholder-list">
            <div>
              <strong>{"\u6d4b\u8bd5\u5217\u8868"}</strong>
              <small>{"\u5c06\u5728 7.x \u8fc1\u79fb\uff0c\u4fdd\u7559 published gate \u4e0e attempt API \u7ea6\u675f\u3002"}</small>
            </div>
            <div>
              <strong>{"\u8bb0\u5fc6\u4e0e\u9690\u79c1"}</strong>
              <small>{"\u5f53\u524d\u72b6\u6001\u4ecd\u53ef\u67e5\u770b\uff0c\u672a\u5236\u9020\u53ef\u70b9\u51fb\u7684\u5047\u529f\u80fd\u3002"}</small>
            </div>
            <div>
              <strong>{"\u8bed\u97f3\u4e0e\u77e5\u8bc6\u5e93"}</strong>
              <small>{"\u4fdd\u7559\u540e\u7eed\u5165\u53e3\u4f4d\u7f6e\uff0c\u5b8c\u6574\u80fd\u529b\u5c06\u5728\u5bf9\u5e94\u4efb\u52a1\u4e2d\u63a5\u5165\u3002"}</small>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/*
function ImmersiveNingyuShell({ viewModel, handlers }: NingyuThreeColumnShellProps) {
  return (
    <div className={`ningyu-transition ${viewModel.isNight ? "is-night" : "is-day"}`}>
      <div className={`ningyu-shell ningyu-immersive ${viewModel.isNight ? "is-night" : "is-day"}`}>
        <Background isNight={viewModel.isNight} />
        <header className="ningyu-immersive__topbar">
          <div className="ningyu-immersive-brand">
            <img src={logo} alt="ç€¹ä½½î‡¢ Logo" />
            <div>
              <h1>ç€¹ä½½î‡¢</h1>
              <p>
                <span className="ningyu-brand__dot" />
                {viewModel.displayName} è·¯ {viewModel.userModeLabel}
              </p>
            </div>
          </div>
          <div className="ningyu-immersive-status" aria-live="polite">
            <span className={`ningyu-immersive-status__tone is-${viewModel.safetyState.tone}`} />
            <strong>{viewModel.safetyState.label}</strong>
            <small>{viewModel.memoryModeLabel}</small>
          </div>
        </header>

        <main className="ningyu-immersive__main">
          <div className="ningyu-immersive-paper">
            <ChatWorkspace
              isNight={viewModel.isNight}
              displayName={viewModel.displayName}
              userModeLabel={viewModel.userModeLabel}
              primarySuggestion={viewModel.homeSuggestions[0]?.label ?? ""}
              primarySupportLabel={viewModel.supportResources[1].title}
              messages={viewModel.messages}
              messageListStatus={viewModel.messageListStatus}
              messageListError={viewModel.messageListError}
              activeThreadId={viewModel.activeThreadId}
              messageFeedback={viewModel.messageFeedback}
              chatStreamStatus={viewModel.chatStreamStatus}
              chatStreamError={viewModel.chatStreamError}
              graphUpdates={viewModel.graphUpdates}
              streamStatusDetail={viewModel.streamStatusDetail}
              onSend={handlers.onSend}
              onMessageFeedback={handlers.onMessageFeedback}
            />
          </div>
        </main>

        <div className="ningyu-immersive-edge ningyu-immersive-edge--left" aria-label="æµ®åŠ¨å¯¼èˆª">
          <button type="button" onClick={handlers.onStartNewThread} disabled={viewModel.createThreadStatus === "loading"} aria-label="å¼€å§‹æ–°å¯¹è¯">
            <Icon name="plus" />
          </button>
          <button type="button" aria-label="åŽ†å²å¯¹è¯">
            <Icon name="clock" />
          </button>
        </div>

        <div className="ningyu-immersive-edge ningyu-immersive-edge--right" aria-label="æµ®åŠ¨å·¥å…·">
          <button type="button" onClick={handlers.onToggleNight} aria-label={viewModel.isNight ? "åˆ‡æ¢åˆ°æ—¥é—´" : "åˆ‡æ¢åˆ°å¤œé—´"}>
            <Icon name={viewModel.isNight ? "moon" : "sun"} />
          </button>
          <button
            className={`is-safety is-${viewModel.safetyState.tone}`}
            type="button"
            onClick={handlers.onToggleSafetyEntry}
            aria-expanded={viewModel.isSafetyEntryOpen}
            aria-label="ç€¹å¤Šåé€îˆ›å¯”"
          >
            <Icon name="shield" />
          </button>
          <button type="button" aria-label="å·¥å…·">
            <Icon name="spark" />
          </button>
        </div>
      </div>
    </div>
  );
}

*/
function NingyuThreeColumnShell({ viewModel, handlers }: NingyuThreeColumnShellProps) {
  return (
    <div className={`ningyu-transition ${viewModel.isNight ? "is-night" : "is-day"}`}>
      <div className={`ningyu-shell ${viewModel.isNight ? "is-night" : "is-day"}`}>
        <Background isNight={viewModel.isNight} />
        <Header
          isNight={viewModel.isNight}
          displayName={viewModel.displayName}
          userModeLabel={viewModel.userModeLabel}
          safetyState={viewModel.safetyState}
          onToggleNight={handlers.onToggleNight}
          onToggleSafetyEntry={handlers.onToggleSafetyEntry}
          isSafetyEntryOpen={viewModel.isSafetyEntryOpen}
        />
        <div className="ningyu-shell__body">
          <LeftSidebar
            isNight={viewModel.isNight}
            entries={viewModel.homeEntries}
            activeThreadId={viewModel.activeThreadId}
            threadListStatus={viewModel.threadListStatus}
            threadListError={viewModel.threadListError}
            createThreadStatus={viewModel.createThreadStatus}
            createThreadError={viewModel.createThreadError}
            userModeLabel={viewModel.userModeLabel}
            memoryModeLabel={viewModel.memoryModeLabel}
            onSelectThread={handlers.onSelectThread}
            onStartNewThread={handlers.onStartNewThread}
          />
          <ChatWorkspace
            isNight={viewModel.isNight}
            displayName={viewModel.displayName}
            userModeLabel={viewModel.userModeLabel}
            primarySuggestion={viewModel.homeSuggestions[0]?.label ?? ""}
            primarySupportLabel={viewModel.supportResources[1].title}
            messages={viewModel.messages}
            messageListStatus={viewModel.messageListStatus}
            messageListError={viewModel.messageListError}
            activeThreadId={viewModel.activeThreadId}
            messageFeedback={viewModel.messageFeedback}
            chatStreamStatus={viewModel.chatStreamStatus}
            chatStreamError={viewModel.chatStreamError}
            graphUpdates={viewModel.graphUpdates}
            streamStatusDetail={viewModel.streamStatusDetail}
            onSend={handlers.onSend}
            onMessageFeedback={handlers.onMessageFeedback}
          />
          <RightPanel
            isNight={viewModel.isNight}
            currentUserLabel={viewModel.displayName}
            userMode={viewModel.userMode}
            statusTags={viewModel.statusTags}
            suggestions={viewModel.homeSuggestions}
            supportResources={viewModel.supportResources}
            safetyState={viewModel.safetyState}
            isSafetyEntryOpen={viewModel.isSafetyEntryOpen}
            highRiskSafety={viewModel.highRiskSafety}
            moodScore={viewModel.moodScore}
            moodTags={viewModel.moodTags}
            moodNote={viewModel.moodNote}
            moodStatus={viewModel.moodStatus}
            moodError={viewModel.moodError}
            latestMoodLog={viewModel.latestMoodLog}
            showMoodCheckInControls={viewModel.showMoodCheckInControls}
            moodTrendRange={viewModel.moodTrendRange}
            moodTrendStatus={viewModel.moodTrendStatus}
            moodTrendError={viewModel.moodTrendError}
            moodTrend={viewModel.moodTrend}
            weeklySummaryStatus={viewModel.weeklySummaryStatus}
            weeklySummaryError={viewModel.weeklySummaryError}
            weeklySummary={viewModel.weeklySummary}
            quickActionStatus={viewModel.quickActionStatus}
            activeQuickActionId={viewModel.activeQuickActionId}
            quickActionError={viewModel.quickActionError}
            quickActionResult={viewModel.quickActionResult}
            onMoodScoreChange={handlers.onMoodScoreChange}
            onMoodTagToggle={handlers.onMoodTagToggle}
            onMoodNoteChange={handlers.onMoodNoteChange}
            onMoodSubmit={handlers.onMoodSubmit}
            onMoodTrendRangeChange={handlers.onMoodTrendRangeChange}
            onQuickAction={handlers.onQuickAction}
            onToggleSafetyEntry={handlers.onToggleSafetyEntry}
            onRetrySafetyState={handlers.onRetrySafetyState}
          />
        </div>
      </div>
    </div>
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
        {entries.map((entry) => (
          <button
            className={`ningyu-thread ${entry.threadId && entry.threadId === activeThreadId ? "is-active" : ""}`}
            key={entry.id}
            type="button"
            onClick={entry.threadId ? () => onSelectThread(entry.threadId as string) : undefined}
            disabled={!entry.threadId}
          >
            <span className="ningyu-thread__dot" />
            <span className="ningyu-thread__content">
              <strong>{entry.title}</strong>
              <span>{entry.preview}</span>
              <small>{entry.time}</small>
            </span>
            {entry.riskLevel || entry.mode ? (
              <span className="ningyu-thread__meta">
                {entry.riskLevel ? <small>{entry.riskLevel}</small> : null}
                {entry.mode ? <small>{entry.mode}</small> : null}
              </span>
            ) : null}
          </button>
        ))}
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
  displayName,
  userModeLabel,
  primarySuggestion,
  primarySupportLabel,
  messages,
  messageListStatus,
  messageListError,
  activeThreadId,
  messageFeedback,
  chatStreamStatus,
  chatStreamError,
  graphUpdates,
  streamStatusDetail,
  onSend,
  onMessageFeedback,
}: {
  isNight: boolean;
  displayName: string;
  userModeLabel: string;
  primarySuggestion: string;
  primarySupportLabel: string;
  messages: Message[];
  messageListStatus: MessageListStatus;
  messageListError: string | null;
  activeThreadId: string | null;
  messageFeedback: Record<string, MessageFeedback>;
  chatStreamStatus: ChatStreamStatus;
  chatStreamError: string | null;
  graphUpdates: GraphUpdateItem[];
  streamStatusDetail: string | null;
  onSend: (content: string) => void | Promise<void>;
  onMessageFeedback: (messageId: string, feedback: MessageFeedback) => void;
}) {
  const [draftSuggestion, setDraftSuggestion] = useState<{ id: string; text: string } | null>(null);
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const suggestedActions = latestAssistant?.suggestedActions?.length
    ? latestAssistant.suggestedActions
    : messages.length
      ? ["把刚才的话说得更具体一点", "帮我整理成一个小步骤"]
      : [];

  const handleSuggestedAction = (action: string) => {
    setDraftSuggestion({ id: crypto.randomUUID(), text: action });
  };

  return (
    <section className="ningyu-chat" aria-label="聊天工作区">
      <div className="ningyu-chat__scroll">
        <div className="ningyu-chat__inner">
          {messageListStatus === "loading" ? (
            <ChatStateMessage title="正在载入对话" detail="风正在把这段聊天记录带回来..." />
          ) : messageListStatus === "error" ? (
            <ChatStateMessage title="消息暂时没加载出来" detail={messageListError ?? "请稍后再试。"} tone="error" />
          ) : messages.length === 0 ? (
            <WelcomeState
              isNight={isNight}
              displayName={displayName}
              userModeLabel={userModeLabel}
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
                  feedback={messageFeedback[message.id]}
                  onFeedback={onMessageFeedback}
                />
              ))}
              {suggestedActions.length ? (
                <SuggestedActionChips actions={suggestedActions} onSelect={handleSuggestedAction} />
              ) : null}
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
        </div>
      </div>
      <div className="ningyu-chat__input">
        <ChatInput
          isNight={isNight}
          draftSuggestion={draftSuggestion}
          isSending={chatStreamStatus === "streaming"}
          onSend={onSend}
        />
      </div>
    </section>
  );
}

function WelcomeState({
  isNight,
  displayName,
  userModeLabel,
  primarySuggestion,
  primarySupportLabel,
  activeThreadId,
}: {
  isNight: boolean;
  displayName: string;
  userModeLabel: string;
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
          ? "这段对话暂时还没有消息。你可以先在下方写一句想说的话。"
          : `${displayName}，这里已经进入${userModeLabel}。你可以从左侧续聊入口继续，也可以先试试「${primarySuggestion}」；如果此刻需要更直接的支持，右侧的 ${primarySupportLabel} 会一直保持可见。`}
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
  draftSuggestion,
  isSending,
  onSend,
}: {
  isNight: boolean;
  draftSuggestion: { id: string; text: string } | null;
  isSending: boolean;
  onSend: (content: string) => void | Promise<void>;
}) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (draftSuggestion) {
      setValue(draftSuggestion.text);
    }
  }, [draftSuggestion]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextValue = value.trim();
    if (!nextValue) return;
    void onSend(nextValue);
    setValue("");
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
        disabled={isSending}
        rows={1}
      />
      <button className={value.trim() ? "is-active" : ""} type="submit" disabled={!value.trim() || isSending} aria-label="发送">
        <Icon name="send" />
      </button>
    </form>
  );
}

function ChatMessage({
  message,
  isNight,
  feedback,
  onFeedback,
}: {
  message: Message;
  isNight: boolean;
  feedback?: MessageFeedback;
  onFeedback: (messageId: string, feedback: MessageFeedback) => void;
}) {
  const isUser = message.role === "user";
  const metaLabel = message.role === "user" ? "你" : message.role === "system" ? "系统" : "宁语";
  const isAssistant = message.role === "assistant";

  return (
    <article className={`ningyu-message ${isUser ? "is-user" : "is-assistant"} ${isNight ? "is-night" : ""}`}>
      <div className="ningyu-message__meta">
        <span>{metaLabel}</span>
        {message.riskLevel && message.riskLevel !== "L0" ? <small>{message.riskLevel}</small> : null}
      </div>
      <div className="ningyu-message__bubble">
        <Icon name={isUser ? "leaf" : "wind"} />
        <p>{message.content}</p>
      </div>
      <div className="ningyu-message__footer">
        <time>{message.timestamp}</time>
        {isAssistant ? (
          <div className="ningyu-message-feedback" aria-label="消息反馈">
            <button
              className={feedback === "helpful" ? "is-selected" : ""}
              type="button"
              onClick={() => onFeedback(message.id, "helpful")}
            >
              有帮助
            </button>
            <button
              className={feedback === "not_helpful" ? "is-selected" : ""}
              type="button"
              onClick={() => onFeedback(message.id, "not_helpful")}
            >
              不适合
            </button>
            {feedback ? <span>已记录</span> : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function SuggestedActionChips({ actions, onSelect }: { actions: string[]; onSelect: (action: string) => void }) {
  return (
    <div className="ningyu-chat-suggestions" aria-label="建议行动">
      <span>可以接着试试</span>
      <div>
        {actions.slice(0, 4).map((action) => (
          <button key={action} type="button" onClick={() => onSelect(action)}>
            {action}
          </button>
        ))}
      </div>
    </div>
  );
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
  showMoodCheckInControls,
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
  showMoodCheckInControls: boolean;
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
  onMoodScoreChange: (score: number) => void;
  onMoodTagToggle: (tagId: string) => void;
  onMoodNoteChange: (note: string) => void;
  onMoodSubmit: () => void;
  onMoodTrendRangeChange: (range: MoodTrendRange) => void;
  onQuickAction: (action: QuickAction) => void;
  onToggleSafetyEntry: () => void;
  onRetrySafetyState: () => void;
}) {
  const shouldShowGuidance = isSafetyEntryOpen || Boolean(highRiskSafety);

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
          showControls={showMoodCheckInControls}
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

      <section className="ningyu-panel-section ningyu-panel-section--suggestions">
        <span className="ningyu-panel-section__caption">低优先级建议</span>
        <h2>
          <Icon name="light" />
          可以试试
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
      <span className="ningyu-sidebar__mode">
        {isNight ? "夜间保持安全入口可见" : "白天保持安全入口可见"}
      </span>
    </aside>
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
  showControls,
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
  showControls: boolean;
  onMoodScoreChange: (score: number) => void;
  onMoodTagToggle: (tagId: string) => void;
  onMoodNoteChange: (note: string) => void;
  onMoodSubmit: () => void;
}) {
  const selectedTags = moodTagOptions.filter((tag) => moodTags.includes(tag.id)).map((tag) => tag.label);
  const latestSummary = latestMoodLog
    ? `刚刚记录：${latestMoodLog.mood_score}/5${selectedTags.length ? ` · ${selectedTags.join("、")}` : ""}`
    : "选一个最接近此刻的分数就好，不需要解释得很完整。";

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
        </>
      ) : null}

      <div className="ningyu-mood-checkin__footer">
        <p className={`ningyu-mood-checkin__summary is-${moodStatus}`}>
          {moodStatus === "error" ? moodError : latestSummary}
        </p>
        {showControls ? (
          <button type="button" onClick={onMoodSubmit} disabled={moodStatus === "submitting"}>
            {moodStatus === "submitting" ? "记录中..." : "记录心情"}
          </button>
        ) : null}
      </div>
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
