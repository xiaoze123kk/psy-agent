import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

import bgDay from "../../imports/wcbg.png";
import bgNight from "../../imports/wcbg_night.png";
import logo from "../../imports/wind-chat-logo.png";
import { api } from "../../api";
import { useAppState } from "../state";
import { useSession } from "../session";
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
  AskKnowledgeResponse,
  KnowledgeArticleResponse,
  KnowledgeSearchItem,
  CompleteAttemptResponse,
  MemoryItem,
  MemoryMode,
  MessageItem,
  MoodLogResponse,
  MoodTrendResponse,
  RiskLevel,
  SendMessageRequest,
  PersonalDataExport,
  PrivacyDataScope,
  PrivacyMutationResponse,
  PrivacySummaryResponse,
  StartAttemptResponse,
  TestDetailResponse,
  TestHistoryItem,
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

interface TestShareCardPayload {
  title: string;
  subtitle: string;
  summary: string;
  highlights: string[];
  disclaimer: string;
}

type ShellPhase = "loading" | "ready" | "error";
type SafetyTone = "loading" | "stable" | "watch" | "support" | "error";
type MoodCheckInStatus = "idle" | "submitting" | "success" | "error";
type MoodTrendRange = "7d" | "30d";
type MoodTrendStatus = "idle" | "loading" | "success" | "error";
type WeeklySummaryStatus = "idle" | "loading" | "success" | "error";
type QuickActionStatus = "idle" | "loading" | "success" | "error";
type KnowledgeSearchStatus = "idle" | "loading" | "success" | "error";
type KnowledgeArticleStatus = "idle" | "loading" | "success" | "error";
type KnowledgeAskStatus = "idle" | "loading" | "success" | "error";
type TestListStatus = "idle" | "loading" | "success" | "error";
type TestDetailStatus = "idle" | "loading" | "success" | "error";
type TestAttemptStatus = "idle" | "loading" | "success" | "error";
type TestAnswerStatus = "idle" | "loading" | "success" | "error";
type TestResultStatus = "idle" | "loading" | "success" | "error";
type TestHistoryStatus = "idle" | "loading" | "success" | "error";
type MemoryListStatus = "idle" | "loading" | "success" | "error";
type MemoryMutationStatus = "idle" | "loading" | "success" | "error";
type SettingsMutationStatus = "idle" | "loading" | "success" | "error";
type PrivacyStatus = "idle" | "loading" | "success" | "error";
type DataActionStatus = "idle" | "loading" | "success" | "error";
type FeedbackSubmitStatus = "idle" | "loading" | "success" | "error";
type ThreadListStatus = "idle" | "loading" | "success" | "error";
type MessageListStatus = "idle" | "loading" | "success" | "error";
type CreateThreadStatus = "idle" | "loading" | "success" | "error";
type ChatStreamStatus = "idle" | "streaming" | "success" | "error";
type ActiveConversation = { kind: "thread"; threadId: string } | { kind: "draft" } | null;
type SendMessageHandler = (content: string) => boolean | Promise<boolean>;
type DraftInputSeed = { id: string; text: string };
type EdgePanel = "history" | "tools" | null;
type ToolSurface = "launcher" | "journey" | "actions" | "knowledge" | "tests" | "settings" | "safety";

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

const knowledgeCategoryOptions = [
  { value: "", label: "全部分类" },
  { value: "emotion", label: "情绪" },
  { value: "stress", label: "压力" },
  { value: "sleep", label: "睡眠" },
  { value: "relationship", label: "关系" },
  { value: "self_help", label: "自助练习" },
  { value: "teen", label: "青少年主题" },
  { value: "safety", label: "安全支持" },
];

const knowledgeAudienceOptions = [
  { value: "", label: "全部人群" },
  { value: "all", label: "通用内容" },
  { value: "teen", label: "青少年" },
  { value: "adult", label: "成人" },
];

const knowledgeCategoryLabels: Record<string, string> = Object.fromEntries(
  knowledgeCategoryOptions.filter((option) => option.value).map((option) => [option.value, option.label]),
);
const knowledgeAudienceLabels: Record<string, string> = Object.fromEntries(
  knowledgeAudienceOptions.filter((option) => option.value).map((option) => [option.value, option.label]),
);
const knowledgeCoverageLabels: Record<string, string> = {
  sufficient: "覆盖充分",
  partial: "覆盖部分",
  insufficient: "覆盖不足",
  not_applicable: "不适用",
};
const knowledgeScopeLabels: Record<string, string> = {
  in_scope: "在知识范围内",
  out_of_scope: "超出知识范围",
};
const knowledgeConfidenceLabels: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};
const testTypeLabels: Record<string, string> = {
  state: "状态测试",
  personality: "个性测试",
  anime: "动漫偏好测试",
};
const privacyCountLabels: Record<string, string> = {
  memories: "记忆",
  chat_threads: "聊天会话",
  chat_messages: "聊天消息",
  mood_logs: "情绪记录",
  test_history: "测试历史",
  feedback: "反馈",
  risk_events: "安全事件",
};

const testResultDisclaimer = "本结果只用于自我理解和陪伴沟通，不是医疗诊断、治疗建议或临床评估。";
const privacyDeleteScopes: Array<{ value: PrivacyDataScope; label: string }> = [
  { value: "memories", label: "记忆" },
  { value: "chat", label: "聊天" },
  { value: "moods", label: "情绪记录" },
  { value: "feedback", label: "反馈" },
  { value: "all_non_account", label: "除账号外的全部个人数据" },
];

const feedbackTargetOptions = [
  { value: "assistant_message", label: "助手消息" },
  { value: "knowledge_answer", label: "知识回答" },
  { value: "test_result", label: "测试结果" },
] as const;

function buildTestShareCardPayload(result: CompleteAttemptResponse): TestShareCardPayload {
  return {
    title: result.result_title,
    subtitle: `${result.test_code} · ${result.result_code}`,
    summary: result.summary,
    highlights: [...result.strengths.slice(0, 2), ...result.suggested_actions.slice(0, 2)],
    disclaimer: testResultDisclaimer,
  };
}

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
    privacySettings,
    isNight,
    setMemoryMode,
    updatePrivacySettings,
    toggleThemeMode,
  } = useAppState();
  const { clearSession } = useSession();
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
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeCategory, setKnowledgeCategory] = useState("");
  const [knowledgeAudience, setKnowledgeAudience] = useState("");
  const [knowledgeSearchStatus, setKnowledgeSearchStatus] = useState<KnowledgeSearchStatus>("idle");
  const [knowledgeSearchError, setKnowledgeSearchError] = useState<string | null>(null);
  const [knowledgeResults, setKnowledgeResults] = useState<KnowledgeSearchItem[]>([]);
  const [knowledgeArticleStatus, setKnowledgeArticleStatus] = useState<KnowledgeArticleStatus>("idle");
  const [knowledgeArticleError, setKnowledgeArticleError] = useState<string | null>(null);
  const [knowledgeArticle, setKnowledgeArticle] = useState<KnowledgeArticleResponse | null>(null);
  const [knowledgeQuestion, setKnowledgeQuestion] = useState("");
  const [knowledgeAskStatus, setKnowledgeAskStatus] = useState<KnowledgeAskStatus>("idle");
  const [knowledgeAskError, setKnowledgeAskError] = useState<string | null>(null);
  const [knowledgeAnswer, setKnowledgeAnswer] = useState<AskKnowledgeResponse | null>(null);
  const [knowledgeRiskLevel, setKnowledgeRiskLevel] = useState<RiskLevel | null>(null);
  const [tests, setTests] = useState<TestListItem[]>([]);
  const [testListStatus, setTestListStatus] = useState<TestListStatus>("idle");
  const [testListError, setTestListError] = useState<string | null>(null);
  const [selectedTest, setSelectedTest] = useState<TestDetailResponse | null>(null);
  const [testDetailStatus, setTestDetailStatus] = useState<TestDetailStatus>("idle");
  const [testDetailError, setTestDetailError] = useState<string | null>(null);
  const [testAttempt, setTestAttempt] = useState<StartAttemptResponse | null>(null);
  const [testAttemptStatus, setTestAttemptStatus] = useState<TestAttemptStatus>("idle");
  const [testAttemptError, setTestAttemptError] = useState<string | null>(null);
  const [testAnswers, setTestAnswers] = useState<Record<number, string>>({});
  const [testAnswerStatus, setTestAnswerStatus] = useState<TestAnswerStatus>("idle");
  const [testAnswerError, setTestAnswerError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<CompleteAttemptResponse | null>(null);
  const [testResultStatus, setTestResultStatus] = useState<TestResultStatus>("idle");
  const [testResultError, setTestResultError] = useState<string | null>(null);
  const [testHistory, setTestHistory] = useState<TestHistoryItem[]>([]);
  const [testHistoryStatus, setTestHistoryStatus] = useState<TestHistoryStatus>("idle");
  const [testHistoryError, setTestHistoryError] = useState<string | null>(null);
  const [testShareCard, setTestShareCard] = useState<TestShareCardPayload | null>(null);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoryListStatus, setMemoryListStatus] = useState<MemoryListStatus>("idle");
  const [memoryListError, setMemoryListError] = useState<string | null>(null);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [memoryMutationStatus, setMemoryMutationStatus] = useState<MemoryMutationStatus>("idle");
  const [memoryMutationError, setMemoryMutationError] = useState<string | null>(null);
  const [settingsMemoryMode, setSettingsMemoryMode] = useState<MemoryMode>(memoryMode);
  const [settingsSaveTranscript, setSettingsSaveTranscript] = useState(privacySettings.saveTranscript);
  const [settingsStatus, setSettingsStatus] = useState<SettingsMutationStatus>("idle");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [privacySummary, setPrivacySummary] = useState<PrivacySummaryResponse | null>(null);
  const [privacyStatus, setPrivacyStatus] = useState<PrivacyStatus>("idle");
  const [privacyError, setPrivacyError] = useState<string | null>(null);
  const [dataExportStatus, setDataExportStatus] = useState<DataActionStatus>("idle");
  const [dataExportError, setDataExportError] = useState<string | null>(null);
  const [personalDataExport, setPersonalDataExport] = useState<PersonalDataExport | null>(null);
  const [deleteScope, setDeleteScope] = useState<PrivacyDataScope>("memories");
  const [dataDeleteStatus, setDataDeleteStatus] = useState<DataActionStatus>("idle");
  const [dataDeleteError, setDataDeleteError] = useState<string | null>(null);
  const [dataDeleteResult, setDataDeleteResult] = useState<PrivacyMutationResponse | null>(null);
  const [accountConfirmation, setAccountConfirmation] = useState("");
  const [accountDeleteStatus, setAccountDeleteStatus] = useState<DataActionStatus>("idle");
  const [accountDeleteError, setAccountDeleteError] = useState<string | null>(null);
  const [accountDeleteResult, setAccountDeleteResult] = useState<PrivacyMutationResponse | null>(null);
  const [feedbackTargetType, setFeedbackTargetType] = useState<(typeof feedbackTargetOptions)[number]["value"]>("knowledge_answer");
  const [feedbackTargetId, setFeedbackTargetId] = useState("");
  const [feedbackRating, setFeedbackRating] = useState(4);
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState<FeedbackSubmitStatus>("idle");
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
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
  const [activeToolSurface, setActiveToolSurface] = useState<ToolSurface>("launcher");
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
      setTestListError(error instanceof Error ? error.message : "测试列表暂时没有加载成功。");
    }
  }, []);

  const loadTestHistory = useCallback(async () => {
    setTestHistoryStatus("loading");
    setTestHistoryError(null);

    try {
      const response = await api.getTestHistory();
      setTestHistory(response.items);
      setTestHistoryStatus("success");
    } catch (error) {
      setTestHistoryStatus("error");
      setTestHistoryError(error instanceof Error ? error.message : "测试历史暂时没有加载成功。");
    }
  }, []);

  const loadMemories = useCallback(async () => {
    setMemoryListStatus("loading");
    setMemoryListError(null);

    try {
      const response = await api.listMemories();
      setMemories(response.items);
      setMemoryListStatus("success");
    } catch (error) {
      setMemoryListStatus("error");
      setMemoryListError(error instanceof Error ? error.message : "记忆中心暂时没有加载成功。");
    }
  }, []);

  const loadPrivacySummary = useCallback(async () => {
    setPrivacyStatus("loading");
    setPrivacyError(null);

    try {
      const response = await api.getPrivacySummary();
      setPrivacySummary(response);
      setSettingsMemoryMode(response.settings.memory_mode);
      setSettingsSaveTranscript(response.settings.save_transcript);
      setPrivacyStatus("success");
    } catch (error) {
      setPrivacyStatus("error");
      setPrivacyError(error instanceof Error ? error.message : "隐私摘要暂时没有加载成功。");
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
    void loadTestHistory();
  }, [loadTestHistory]);

  useEffect(() => {
    void loadMemories();
  }, [loadMemories]);

  useEffect(() => {
    void loadPrivacySummary();
  }, [loadPrivacySummary]);

  useEffect(() => {
    setSettingsMemoryMode(memoryMode);
    setSettingsSaveTranscript(privacySettings.saveTranscript);
  }, [memoryMode, privacySettings.saveTranscript]);

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

  const handleLogout = useCallback(async () => {
    clearSession();
  }, [clearSession]);

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

  const handleKnowledgeSearch = useCallback(async () => {
    const query = knowledgeQuery.trim();
    if (!query) {
      setKnowledgeSearchStatus("idle");
      setKnowledgeSearchError(null);
      setKnowledgeResults([]);
      return;
    }

    setKnowledgeSearchStatus("loading");
    setKnowledgeSearchError(null);

    try {
      const response = await api.searchKnowledge(query, {
        category: knowledgeCategory || undefined,
        audience: knowledgeAudience || undefined,
      });
      setKnowledgeResults(response.items);
      setKnowledgeSearchStatus("success");
    } catch (error) {
      setKnowledgeSearchStatus("error");
      setKnowledgeSearchError(error instanceof Error ? error.message : "知识搜索暂时没有成功，请稍后再试。");
    }
  }, [knowledgeAudience, knowledgeCategory, knowledgeQuery]);

  const handleKnowledgeArticleSelect = useCallback(async (articleId: string) => {
    setKnowledgeArticleStatus("loading");
    setKnowledgeArticleError(null);

    try {
      const response = await api.getKnowledgeArticle(articleId);
      setKnowledgeArticle(response);
      setKnowledgeArticleStatus("success");
    } catch (error) {
      setKnowledgeArticleStatus("error");
      setKnowledgeArticleError(error instanceof Error ? error.message : "文章详情暂时没有加载成功。");
    }
  }, []);

  const ensureThreadForKnowledgeSafety = useCallback(async (): Promise<string | null> => {
    if (activeThreadIdRef.current) {
      return activeThreadIdRef.current;
    }

    try {
      const thread = await api.startThread({
        mode: "companion",
        title: "知识问答安全支持",
      });
      const threadItem = toThreadListItemFromStartThread(thread);
      setDraftThread(null);
      draftCreationRef.current = null;
      activeThreadIdRef.current = threadItem.thread_id;
      activateThread(threadItem, { clearMessages: true, skipMessageLoad: true });
      return threadItem.thread_id;
    } catch {
      setIsSafetyEntryOpen(true);
      setHighRiskSafety({
        riskLevel: "L2",
        threadId: "knowledge",
        eventStatus: "error",
        error: "已打开安全支持，但知识问答暂时没有可记录的对话线程。",
      });
      return null;
    }
  }, [activateThread]);

  const handleKnowledgeAsk = useCallback(async () => {
    const question = knowledgeQuestion.trim();
    if (!question) {
      setKnowledgeAskStatus("idle");
      setKnowledgeAskError(null);
      setKnowledgeAnswer(null);
      setKnowledgeRiskLevel(null);
      return;
    }

    setKnowledgeAskStatus("loading");
    setKnowledgeAskError(null);
    setKnowledgeRiskLevel(null);

    try {
      const response = await api.askKnowledge({
        question,
        use_my_context: true,
        thread_id: activeThreadIdRef.current,
      });

      if (isHighRiskLevel(response.risk_level)) {
        setKnowledgeAnswer(null);
        setKnowledgeRiskLevel(response.risk_level);
        setKnowledgeAskStatus("success");
        const threadId = response.continue_chat_payload.thread_id ?? (await ensureThreadForKnowledgeSafety());
        if (threadId) {
          void handleHighRiskChatResponse({
            threadId,
            riskLevel: response.risk_level,
            detectedSignals: [
              "knowledge_ask",
              response.coverage_status,
              response.scope_status,
              response.confidence,
              response.question_suggestion?.matched_term,
              ...response.answer.seek_help_when,
            ].filter((item): item is string => typeof item === "string" && item.length > 0),
          });
        }
        return;
      }

      setKnowledgeAnswer(response);
      setKnowledgeAskStatus("success");
      setKnowledgeRiskLevel(response.risk_level);
    } catch (error) {
      setKnowledgeAskStatus("error");
      setKnowledgeAskError(error instanceof Error ? error.message : "知识问答暂时没有成功，请稍后再试。");
    }
  }, [ensureThreadForKnowledgeSafety, handleHighRiskChatResponse, knowledgeQuestion]);

  const handleKnowledgeContinueChat = useCallback(() => {
    const summary = knowledgeAnswer?.answer.summary_30s || knowledgeArticle?.summary_30s || knowledgeQuestion.trim();
    if (!summary) return;

    activateDraft();
    setDraftInputSeed({
      id: crypto.randomUUID(),
      text: `我想继续聊聊这个主题：${summary}`,
    });
    setActiveEdgePanel(null);
  }, [activateDraft, knowledgeAnswer, knowledgeArticle, knowledgeQuestion]);

  const handleTestSelect = useCallback(async (test: TestListItem) => {
    if (test.status !== "published") {
      setTestDetailStatus("error");
      setTestDetailError("这个测试还没有发布，暂时不能开始。");
      return;
    }

    setTestDetailStatus("loading");
    setTestDetailError(null);
    setSelectedTest(null);
    setTestAttempt(null);
    setTestAnswers({});
    setTestResult(null);
    setTestShareCard(null);

    try {
      const detail = await api.getTest(test.test_id);
      setSelectedTest(detail);
      setTestDetailStatus("success");
    } catch (error) {
      setTestDetailStatus("error");
      setTestDetailError(error instanceof Error ? error.message : "测试详情暂时没有加载成功。");
    }
  }, []);

  const handleTestStart = useCallback(async () => {
    if (!selectedTest || testAttemptStatus === "loading") return;

    setTestAttemptStatus("loading");
    setTestAttemptError(null);
    setTestAnswers({});
    setTestResult(null);
    setTestShareCard(null);

    try {
      const attempt = await api.startAttempt(selectedTest.test_id);
      setTestAttempt(attempt);
      setTestAttemptStatus("success");
    } catch (error) {
      setTestAttemptStatus("error");
      setTestAttemptError(error instanceof Error ? error.message : "测试暂时没有开始成功。");
    }
  }, [selectedTest, testAttemptStatus]);

  const handleTestAnswer = useCallback(
    async (questionIndex: number, optionId: string) => {
      if (!testAttempt || testAnswerStatus === "loading" || testResultStatus === "loading") return;

      setTestAnswerStatus("loading");
      setTestAnswerError(null);

      try {
        await api.submitAnswer(testAttempt.attempt_id, {
          question_index: questionIndex,
          option_id: optionId,
        });
        setTestAnswers((current) => ({ ...current, [questionIndex]: optionId }));
        setTestAnswerStatus("success");
      } catch (error) {
        setTestAnswerStatus("error");
        setTestAnswerError(error instanceof Error ? error.message : "这个答案暂时没有保存成功。");
      }
    },
    [testAnswerStatus, testAttempt, testResultStatus],
  );

  const handleTestComplete = useCallback(async () => {
    if (!testAttempt || testResultStatus === "loading") return;

    setTestResultStatus("loading");
    setTestResultError(null);

    try {
      const result = await api.completeAttempt(testAttempt.attempt_id);
      setTestResult(result);
      setTestShareCard(buildTestShareCardPayload(result));
      setTestResultStatus("success");
      void loadTestHistory();
    } catch (error) {
      setTestResultStatus("error");
      setTestResultError(error instanceof Error ? error.message : "测试结果暂时没有生成成功。");
    }
  }, [loadTestHistory, testAttempt, testResultStatus]);

  const handleTestHistorySelect = useCallback(async (attemptId: string) => {
    setTestResultStatus("loading");
    setTestResultError(null);

    try {
      const result = await api.getAttemptResult(attemptId);
      setTestResult(result);
      setTestShareCard(buildTestShareCardPayload(result));
      setTestResultStatus("success");
    } catch (error) {
      setTestResultStatus("error");
      setTestResultError(error instanceof Error ? error.message : "历史结果暂时没有加载成功。");
    }
  }, []);

  const handleTestContinueChat = useCallback(() => {
    if (!testResult) return;

    activateDraft();
    setDraftInputSeed({
      id: crypto.randomUUID(),
      text: `我想根据这个测试结果继续聊聊：${testResult.result_title}。${testResult.summary}`,
    });
    setActiveEdgePanel(null);
  }, [activateDraft, testResult]);

  const handleMemoryEditStart = useCallback((memory: MemoryItem) => {
    setEditingMemoryId(memory.memory_id);
    setMemoryDraft(memory.content);
    setMemoryMutationStatus("idle");
    setMemoryMutationError(null);
  }, []);

  const handleMemorySave = useCallback(async () => {
    if (!editingMemoryId || !memoryDraft.trim()) return;

    setMemoryMutationStatus("loading");
    setMemoryMutationError(null);

    try {
      const response = await api.updateMemory(editingMemoryId, { content: memoryDraft.trim() });
      setMemories((current) =>
        current.map((memory) =>
          memory.memory_id === editingMemoryId
            ? { ...memory, content: response.content ?? memoryDraft.trim() }
            : memory,
        ),
      );
      setEditingMemoryId(null);
      setMemoryDraft("");
      setMemoryMutationStatus("success");
    } catch (error) {
      setMemoryMutationStatus("error");
      setMemoryMutationError(error instanceof Error ? error.message : "记忆暂时没有保存成功。");
    }
  }, [editingMemoryId, memoryDraft]);

  const handleMemoryDelete = useCallback(async (memoryId: string) => {
    setMemoryMutationStatus("loading");
    setMemoryMutationError(null);

    try {
      await api.deleteMemory(memoryId);
      setMemories((current) => current.filter((memory) => memory.memory_id !== memoryId));
      if (editingMemoryId === memoryId) {
        setEditingMemoryId(null);
        setMemoryDraft("");
      }
      setMemoryMutationStatus("success");
    } catch (error) {
      setMemoryMutationStatus("error");
      setMemoryMutationError(error instanceof Error ? error.message : "记忆暂时没有删除成功。");
    }
  }, [editingMemoryId]);

  const handleMemoriesClear = useCallback(async () => {
    setMemoryMutationStatus("loading");
    setMemoryMutationError(null);

    try {
      await api.clearMemories();
      setMemories([]);
      setEditingMemoryId(null);
      setMemoryDraft("");
      setMemoryMutationStatus("success");
    } catch (error) {
      setMemoryMutationStatus("error");
      setMemoryMutationError(error instanceof Error ? error.message : "记忆暂时没有清空成功。");
    }
  }, []);

  const handleSettingsSave = useCallback(async () => {
    setSettingsStatus("loading");
    setSettingsError(null);

    try {
      const response = await api.updateSettings({
        memory_mode: settingsMemoryMode,
        save_transcript: settingsSaveTranscript,
      });
      setMemoryMode(response.memory_mode);
      updatePrivacySettings({ saveTranscript: response.save_transcript });
      setSettingsMemoryMode(response.memory_mode);
      setSettingsSaveTranscript(response.save_transcript);
      setSettingsStatus("success");
    } catch (error) {
      setSettingsStatus("error");
      setSettingsError(error instanceof Error ? error.message : "设置暂时没有保存成功。");
    }
  }, [settingsMemoryMode, settingsSaveTranscript, setMemoryMode, updatePrivacySettings]);

  const handleDataExport = useCallback(async () => {
    setDataExportStatus("loading");
    setDataExportError(null);

    try {
      const response = await api.exportPersonalData();
      setPersonalDataExport(response);
      setDataExportStatus("success");
    } catch (error) {
      setDataExportStatus("error");
      setDataExportError(error instanceof Error ? error.message : "个人数据暂时没有导出成功。");
    }
  }, []);

  const handleDataDelete = useCallback(async () => {
    setDataDeleteStatus("loading");
    setDataDeleteError(null);

    try {
      const response = await api.deletePersonalData({ scope: deleteScope });
      setDataDeleteResult(response);
      setDataDeleteStatus("success");
      void loadMemories();
      void loadPrivacySummary();
    } catch (error) {
      setDataDeleteStatus("error");
      setDataDeleteError(error instanceof Error ? error.message : "选定数据暂时没有删除成功。");
    }
  }, [deleteScope, loadMemories, loadPrivacySummary]);

  const handleAccountDelete = useCallback(async () => {
    if (accountConfirmation.trim() !== "注销账号") {
      setAccountDeleteStatus("error");
      setAccountDeleteError("请输入“注销账号”才能继续。");
      return;
    }

    setAccountDeleteStatus("loading");
    setAccountDeleteError(null);

    try {
      const response = await api.deleteAccount({ confirmation: "DELETE" });
      setAccountDeleteResult(response);
      setAccountDeleteStatus("success");
    } catch (error) {
      setAccountDeleteStatus("error");
      setAccountDeleteError(error instanceof Error ? error.message : "账号暂时没有注销成功。");
    }
  }, [accountConfirmation]);

  const handleFeedbackSubmit = useCallback(async () => {
    const targetId = feedbackTargetId.trim();
    if (!targetId) {
      setFeedbackStatus("error");
      setFeedbackError("请填写要反馈的内容编号。");
      return;
    }

    setFeedbackStatus("loading");
    setFeedbackError(null);

    try {
      await api.submitFeedback({
        target_type: feedbackTargetType,
        target_id: targetId,
        rating: feedbackRating,
        note: feedbackNote.trim() ? feedbackNote.trim() : null,
      });
      setFeedbackStatus("success");
      setFeedbackNote("");
    } catch (error) {
      setFeedbackStatus("error");
      setFeedbackError(error instanceof Error ? error.message : "反馈暂时没有提交成功，但不会影响主要流程。");
    }
  }, [feedbackNote, feedbackRating, feedbackTargetId, feedbackTargetType]);

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
          setStreamStatusDetail(`仍在生成 · ${(heartbeat.elapsed_ms / 1000).toFixed(1)}秒`);
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

  const handleOpenToolSurface = useCallback((surface: ToolSurface) => {
    setActiveToolSurface(surface);
    setActiveEdgePanel("tools");
  }, []);

  const handleSupportResourceClick = useCallback((resource: HomeSupportResource) => {
    window.alert(
      resource.id === "hotline"
        ? `本地调试提示：请直接拨打 ${resource.title}。`
        : "本地调试提示：紧急聊天入口还没有接入后端或第三方服务。",
    );
  }, []);

  const handleWeeklySuggestedAction = useCallback(
    (action: string) => {
      if (chatStreamStatus === "streaming" || createThreadStatus === "loading" || draftCreationRef.current) return;
      activateDraft();
      setDraftInputSeed({ id: crypto.randomUUID(), text: action });
      setActiveEdgePanel(null);
    },
    [activateDraft, chatStreamStatus, createThreadStatus],
  );

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
        <div className="ningyu-header-trigger" aria-hidden="true" />
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
          <AnimatePresence>
            {activeEdgePanel === "history" ? (
              <AccessibleLayer
                className="ningyu-edge-panel ningyu-edge-panel--left"
                id="ningyu-history-panel"
                key="history"
                label="历史面板"
                shouldReduceMotion={shouldReduceMotion}
                slideDirection="left"
                onClose={closeEdgePanel}
              >
                <button className="ningyu-edge-panel__close" type="button" onClick={closeEdgePanel} aria-label="关闭历史面板">
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
                  onOpenToolSurface={handleOpenToolSurface}
                />
              </AccessibleLayer>
            ) : null}
          </AnimatePresence>
          <div className="ningyu-paper-container">
            <FloatingEdgeControls
              side="left"
              activePanel={activeEdgePanel}
              createThreadStatus={createThreadStatus}
              isSafetyEntryOpen={isSafetyEntryOpen}
              shouldReduceMotion={shouldReduceMotion}
              onPanelChange={handleEdgePanelChange}
              onStartNewThread={handleStartNewThread}
              onToggleSafetyEntry={handleToggleSafetyEntry}
            />
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
            <FloatingEdgeControls
              side="right"
              activePanel={activeEdgePanel}
              createThreadStatus={createThreadStatus}
              isSafetyEntryOpen={isSafetyEntryOpen}
              shouldReduceMotion={shouldReduceMotion}
              onPanelChange={handleEdgePanelChange}
              onStartNewThread={handleStartNewThread}
              onToggleSafetyEntry={handleToggleSafetyEntry}
            />
          </div>
          <AnimatePresence>
            {activeEdgePanel === "tools" ? (
              <AccessibleLayer
                className="ningyu-edge-panel ningyu-edge-panel--right"
                id="ningyu-tools-panel"
                key="tools"
                label="工具面板"
                shouldReduceMotion={shouldReduceMotion}
                slideDirection="right"
                onClose={closeEdgePanel}
              >
                <button className="ningyu-edge-panel__close" type="button" onClick={closeEdgePanel} aria-label="关闭工具面板">
                  x
                </button>
                <RightPanel
                  isNight={isNight}
                  activeToolSurface={activeToolSurface}
                  setActiveToolSurface={setActiveToolSurface}
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
                  knowledgeQuery={knowledgeQuery}
                  knowledgeCategory={knowledgeCategory}
                  knowledgeAudience={knowledgeAudience}
                  knowledgeSearchStatus={knowledgeSearchStatus}
                  knowledgeSearchError={knowledgeSearchError}
                  knowledgeResults={knowledgeResults}
                  knowledgeArticleStatus={knowledgeArticleStatus}
                  knowledgeArticleError={knowledgeArticleError}
                  knowledgeArticle={knowledgeArticle}
                  knowledgeQuestion={knowledgeQuestion}
                  knowledgeAskStatus={knowledgeAskStatus}
                  knowledgeAskError={knowledgeAskError}
                  knowledgeAnswer={knowledgeAnswer}
                  knowledgeRiskLevel={knowledgeRiskLevel}
                  tests={tests}
                  testListStatus={testListStatus}
                  testListError={testListError}
                  selectedTest={selectedTest}
                  testDetailStatus={testDetailStatus}
                  testDetailError={testDetailError}
                  testAttempt={testAttempt}
                  testAttemptStatus={testAttemptStatus}
                  testAttemptError={testAttemptError}
                  testAnswers={testAnswers}
                  testAnswerStatus={testAnswerStatus}
                  testAnswerError={testAnswerError}
                  testResult={testResult}
                  testResultStatus={testResultStatus}
                  testResultError={testResultError}
                  testHistory={testHistory}
                  testHistoryStatus={testHistoryStatus}
                  testHistoryError={testHistoryError}
                  testShareCard={testShareCard}
                  memories={memories}
                  memoryListStatus={memoryListStatus}
                  memoryListError={memoryListError}
                  editingMemoryId={editingMemoryId}
                  memoryDraft={memoryDraft}
                  memoryMutationStatus={memoryMutationStatus}
                  memoryMutationError={memoryMutationError}
                  settingsMemoryMode={settingsMemoryMode}
                  settingsSaveTranscript={settingsSaveTranscript}
                  settingsStatus={settingsStatus}
                  settingsError={settingsError}
                  privacySummary={privacySummary}
                  privacyStatus={privacyStatus}
                  privacyError={privacyError}
                  dataExportStatus={dataExportStatus}
                  dataExportError={dataExportError}
                  personalDataExport={personalDataExport}
                  deleteScope={deleteScope}
                  dataDeleteStatus={dataDeleteStatus}
                  dataDeleteError={dataDeleteError}
                  dataDeleteResult={dataDeleteResult}
                  accountConfirmation={accountConfirmation}
                  accountDeleteStatus={accountDeleteStatus}
                  accountDeleteError={accountDeleteError}
                  accountDeleteResult={accountDeleteResult}
                  feedbackTargetType={feedbackTargetType}
                  feedbackTargetId={feedbackTargetId}
                  feedbackRating={feedbackRating}
                  feedbackNote={feedbackNote}
                  feedbackStatus={feedbackStatus}
                  feedbackError={feedbackError}
                  onMoodScoreChange={setMoodScore}
                  onMoodTagToggle={handleMoodTagToggle}
                  onMoodNoteChange={setMoodNote}
                  onMoodSubmit={handleMoodSubmit}
                  onMoodTrendRangeChange={setMoodTrendRange}
                  onWeeklySuggestedAction={handleWeeklySuggestedAction}
                  onQuickAction={handleQuickAction}
                  onSupportResourceClick={handleSupportResourceClick}
                  onKnowledgeQueryChange={setKnowledgeQuery}
                  onKnowledgeCategoryChange={setKnowledgeCategory}
                  onKnowledgeAudienceChange={setKnowledgeAudience}
                  onKnowledgeSearch={handleKnowledgeSearch}
                  onKnowledgeArticleSelect={handleKnowledgeArticleSelect}
                  onKnowledgeQuestionChange={setKnowledgeQuestion}
                  onKnowledgeAsk={handleKnowledgeAsk}
                  onKnowledgeContinueChat={handleKnowledgeContinueChat}
                  onTestSelect={handleTestSelect}
                  onTestStart={handleTestStart}
                  onTestAnswer={handleTestAnswer}
                  onTestComplete={handleTestComplete}
                  onTestHistorySelect={handleTestHistorySelect}
                  onTestContinueChat={handleTestContinueChat}
                  onMemoryEditStart={handleMemoryEditStart}
                  onMemoryDraftChange={setMemoryDraft}
                  onMemorySave={handleMemorySave}
                  onMemoryDelete={handleMemoryDelete}
                  onMemoriesClear={handleMemoriesClear}
                  onSettingsMemoryModeChange={setSettingsMemoryMode}
                  onSettingsSaveTranscriptChange={setSettingsSaveTranscript}
                  onSettingsSave={handleSettingsSave}
                  onDataExport={handleDataExport}
                  onDeleteScopeChange={setDeleteScope}
                  onDataDelete={handleDataDelete}
                  onAccountConfirmationChange={setAccountConfirmation}
                  onAccountDelete={handleAccountDelete}
                  onFeedbackTargetTypeChange={setFeedbackTargetType}
                  onFeedbackTargetIdChange={setFeedbackTargetId}
                  onFeedbackRatingChange={setFeedbackRating}
                  onFeedbackNoteChange={setFeedbackNote}
                  onFeedbackSubmit={handleFeedbackSubmit}
                  onToggleSafetyEntry={handleToggleSafetyEntry}
                  onRetrySafetyState={handleRetrySafetyState}
                  onLogout={handleLogout}
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
                onSupportResourceClick={handleSupportResourceClick}
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
  onSupportResourceClick,
  onClose,
  onRetrySafetyState,
}: {
  userMode: UserMode;
  safetyState: { tone: SafetyTone; label: string; detail: string };
  highRiskSafety: HighRiskSafetyState | null;
  supportResources: HomeSupportResource[];
  shouldReduceMotion: boolean;
  onSupportResourceClick: (resource: HomeSupportResource) => void;
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
      <button className="ningyu-safety-layer__backdrop" type="button" tabIndex={-1} aria-label="关闭安全支持" onClick={onClose} />
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
            <small>{isHighRisk ? "高优先级安全支持" : "安全支持"}</small>
            <h2 id="ningyu-safety-layer-title">{isHighRisk ? "现在先把安全放在第一位" : "安全支持已准备好"}</h2>
            <p>{safetyState.detail}</p>
          </div>
          <button className="ningyu-safety-layer__close" type="button" onClick={onClose} aria-label="关闭安全支持">
            ×
          </button>
        </div>

        <div className="ningyu-safety-layer__status" aria-live="polite">
          <strong>{safetyState.label}</strong>
          <span>
            {highRiskSafety
              ? highRiskSafety.eventStatus === "recorded"
                ? `安全事件已记录${highRiskSafety.eventId ? ` · ${highRiskSafety.eventId}` : ""}`
                : highRiskSafety.eventStatus === "recording"
                  ? "正在记录安全事件..."
                  : highRiskSafety.error || "安全事件记录失败，但支持入口仍然可用。"
              : "当前没有高风险事件。"}
          </span>
        </div>

        <SafetyGuidanceCard userMode={userMode} highRiskSafety={highRiskSafety} />

        <div className="ningyu-safety-layer__resources" aria-label="安全资源">
          {supportResources.map((resource) => (
            <button className="ningyu-support-card" key={resource.id} type="button" onClick={() => onSupportResourceClick(resource)}>
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
            重新检查安全状态
          </button>
          <button type="button" onClick={onClose}>
            回到聊天
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
              <img src={logo} alt="宁语标志" />
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
        <img src={logo} alt="宁语标志" />
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
  side,
  activePanel,
  createThreadStatus,
  isSafetyEntryOpen,
  shouldReduceMotion,
  onPanelChange,
  onStartNewThread,
  onToggleSafetyEntry,
}: {
  side: "left" | "right";
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
  const enterOffset = side === "left" ? -16 : 16;
  const buttonOffset = side === "left" ? -8 : 8;
  const enterDelay = side === "left" ? 0.55 : 0.65;
  const motionButtonProps = (index: number) => ({
    initial: shouldReduceMotion ? false : { opacity: 0, x: buttonOffset },
    animate: { opacity: 1, x: 0 },
    transition: { duration: 0.15, delay: enterDelay + index * 0.05, ease: "easeOut" as const },
  });

  if (side === "left") {
    return (
      <motion.div
        className="ningyu-paper-controls ningyu-paper-controls--left ningyu-floating-controls ningyu-floating-controls--left"
        initial={shouldReduceMotion ? false : { opacity: 0, x: enterOffset }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.15, delay: enterDelay, ease: "easeOut" }}
      >
        <motion.button
          {...motionButtonProps(0)}
          id="ningyu-history-trigger"
          className={activePanel === "history" ? "ningyu-edge-button is-active" : "ningyu-edge-button"}
          type="button"
          onClick={() => openPanel("history")}
          aria-expanded={activePanel === "history"}
          aria-controls="ningyu-history-panel"
          aria-label="打开历史面板"
        >
          <Icon name="clock" />
          <span>历史</span>
        </motion.button>
        <motion.button
          {...motionButtonProps(1)}
          className="ningyu-edge-button"
          type="button"
          onClick={onStartNewThread}
          disabled={createThreadStatus === "loading"}
          aria-label="开始新对话"
        >
          <Icon name="plus" />
          <span>新对话</span>
        </motion.button>
      </motion.div>
    );
  }

  return (
    <motion.div
      className="ningyu-paper-controls ningyu-paper-controls--right ningyu-floating-controls ningyu-floating-controls--right"
      initial={shouldReduceMotion ? false : { opacity: 0, x: enterOffset }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.15, delay: enterDelay, ease: "easeOut" }}
    >
      <motion.button
        {...motionButtonProps(0)}
        id="ningyu-tools-trigger"
        className={activePanel === "tools" ? "ningyu-edge-button is-active" : "ningyu-edge-button"}
        type="button"
        onClick={() => openPanel("tools")}
        aria-expanded={activePanel === "tools"}
        aria-controls="ningyu-tools-panel"
        aria-label="打开工具面板"
      >
        <Icon name="spark" />
        <span>工具</span>
      </motion.button>
      <motion.button
        {...motionButtonProps(1)}
        id="ningyu-safety-trigger"
        className={isSafetyEntryOpen ? "ningyu-edge-button ningyu-edge-button--safety is-active" : "ningyu-edge-button ningyu-edge-button--safety"}
        type="button"
        onClick={onToggleSafetyEntry}
        aria-expanded={isSafetyEntryOpen}
        aria-label="打开安全支持"
      >
        <Icon name="shield" />
        <span>求助</span>
      </motion.button>
    </motion.div>
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
  onOpenToolSurface,
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
  onOpenToolSurface: (surface: ToolSurface) => void;
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
        <button type="button" onClick={() => onOpenToolSurface("journey")}>
          <Icon name="spark" />
          情绪记录
        </button>
        <button type="button" onClick={() => onOpenToolSurface("settings")}>
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
  const chatPaperDate = useMemo(
    () =>
      new Intl.DateTimeFormat("zh-CN", {
        month: "long",
        day: "numeric",
        weekday: "long",
      }).format(new Date()),
    [],
  );

  return (
    <section className="ningyu-chat" aria-label="聊天工作区">
      <div className="ningyu-chat__scroll">
        <motion.div
          className="ningyu-chat__inner ningyu-chat-paper"
          initial={shouldReduceMotion ? false : { opacity: 0, y: 20, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.32, delay: 0.18, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="ningyu-chat-corner" aria-hidden="true" />
          <header className="ningyu-chat-header">
            <img className="ningyu-chat-seal" src={logo} alt="" aria-hidden="true" />
            <h1 className="ningyu-chat-title">宁语手记</h1>
            <p className="ningyu-chat-date">{chatPaperDate}</p>
          </header>
          <div className="ningyu-chat-paper__body">
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
          </div>
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
    hasRagInfo ? formatRagStatus(trace) : ragDuration ? `知识检索 ${ragDuration}` : null,
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
  activeToolSurface,
  setActiveToolSurface,
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
  knowledgeQuery,
  knowledgeCategory,
  knowledgeAudience,
  knowledgeSearchStatus,
  knowledgeSearchError,
  knowledgeResults,
  knowledgeArticleStatus,
  knowledgeArticleError,
  knowledgeArticle,
  knowledgeQuestion,
  knowledgeAskStatus,
  knowledgeAskError,
  knowledgeAnswer,
  knowledgeRiskLevel,
  tests,
  testListStatus,
  testListError,
  selectedTest,
  testDetailStatus,
  testDetailError,
  testAttempt,
  testAttemptStatus,
  testAttemptError,
  testAnswers,
  testAnswerStatus,
  testAnswerError,
  testResult,
  testResultStatus,
  testResultError,
  testHistory,
  testHistoryStatus,
  testHistoryError,
  testShareCard,
  memories,
  memoryListStatus,
  memoryListError,
  editingMemoryId,
  memoryDraft,
  memoryMutationStatus,
  memoryMutationError,
  settingsMemoryMode,
  settingsSaveTranscript,
  settingsStatus,
  settingsError,
  privacySummary,
  privacyStatus,
  privacyError,
  dataExportStatus,
  dataExportError,
  personalDataExport,
  deleteScope,
  dataDeleteStatus,
  dataDeleteError,
  dataDeleteResult,
  accountConfirmation,
  accountDeleteStatus,
  accountDeleteError,
  accountDeleteResult,
  feedbackTargetType,
  feedbackTargetId,
  feedbackRating,
  feedbackNote,
  feedbackStatus,
  feedbackError,
  onMoodScoreChange,
  onMoodTagToggle,
  onMoodNoteChange,
  onMoodSubmit,
  onMoodTrendRangeChange,
  onWeeklySuggestedAction,
  onQuickAction,
  onSupportResourceClick,
  onKnowledgeQueryChange,
  onKnowledgeCategoryChange,
  onKnowledgeAudienceChange,
  onKnowledgeSearch,
  onKnowledgeArticleSelect,
  onKnowledgeQuestionChange,
  onKnowledgeAsk,
  onKnowledgeContinueChat,
  onTestSelect,
  onTestStart,
  onTestAnswer,
  onTestComplete,
  onTestHistorySelect,
  onTestContinueChat,
  onMemoryEditStart,
  onMemoryDraftChange,
  onMemorySave,
  onMemoryDelete,
  onMemoriesClear,
  onSettingsMemoryModeChange,
  onSettingsSaveTranscriptChange,
  onSettingsSave,
  onDataExport,
  onDeleteScopeChange,
  onDataDelete,
  onAccountConfirmationChange,
  onAccountDelete,
  onFeedbackTargetTypeChange,
  onFeedbackTargetIdChange,
  onFeedbackRatingChange,
  onFeedbackNoteChange,
  onFeedbackSubmit,
  onToggleSafetyEntry,
  onRetrySafetyState,
  onLogout,
}: {
  isNight: boolean;
  activeToolSurface: ToolSurface;
  setActiveToolSurface: (surface: ToolSurface) => void;
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
  knowledgeQuery: string;
  knowledgeCategory: string;
  knowledgeAudience: string;
  knowledgeSearchStatus: KnowledgeSearchStatus;
  knowledgeSearchError: string | null;
  knowledgeResults: KnowledgeSearchItem[];
  knowledgeArticleStatus: KnowledgeArticleStatus;
  knowledgeArticleError: string | null;
  knowledgeArticle: KnowledgeArticleResponse | null;
  knowledgeQuestion: string;
  knowledgeAskStatus: KnowledgeAskStatus;
  knowledgeAskError: string | null;
  knowledgeAnswer: AskKnowledgeResponse | null;
  knowledgeRiskLevel: RiskLevel | null;
  tests: TestListItem[];
  testListStatus: TestListStatus;
  testListError: string | null;
  selectedTest: TestDetailResponse | null;
  testDetailStatus: TestDetailStatus;
  testDetailError: string | null;
  testAttempt: StartAttemptResponse | null;
  testAttemptStatus: TestAttemptStatus;
  testAttemptError: string | null;
  testAnswers: Record<number, string>;
  testAnswerStatus: TestAnswerStatus;
  testAnswerError: string | null;
  testResult: CompleteAttemptResponse | null;
  testResultStatus: TestResultStatus;
  testResultError: string | null;
  testHistory: TestHistoryItem[];
  testHistoryStatus: TestHistoryStatus;
  testHistoryError: string | null;
  testShareCard: TestShareCardPayload | null;
  memories: MemoryItem[];
  memoryListStatus: MemoryListStatus;
  memoryListError: string | null;
  editingMemoryId: string | null;
  memoryDraft: string;
  memoryMutationStatus: MemoryMutationStatus;
  memoryMutationError: string | null;
  settingsMemoryMode: MemoryMode;
  settingsSaveTranscript: boolean;
  settingsStatus: SettingsMutationStatus;
  settingsError: string | null;
  privacySummary: PrivacySummaryResponse | null;
  privacyStatus: PrivacyStatus;
  privacyError: string | null;
  dataExportStatus: DataActionStatus;
  dataExportError: string | null;
  personalDataExport: PersonalDataExport | null;
  deleteScope: PrivacyDataScope;
  dataDeleteStatus: DataActionStatus;
  dataDeleteError: string | null;
  dataDeleteResult: PrivacyMutationResponse | null;
  accountConfirmation: string;
  accountDeleteStatus: DataActionStatus;
  accountDeleteError: string | null;
  accountDeleteResult: PrivacyMutationResponse | null;
  feedbackTargetType: (typeof feedbackTargetOptions)[number]["value"];
  feedbackTargetId: string;
  feedbackRating: number;
  feedbackNote: string;
  feedbackStatus: FeedbackSubmitStatus;
  feedbackError: string | null;
  onMoodScoreChange: (score: number) => void;
  onMoodTagToggle: (tagId: string) => void;
  onMoodNoteChange: (note: string) => void;
  onMoodSubmit: () => void;
  onMoodTrendRangeChange: (range: MoodTrendRange) => void;
  onWeeklySuggestedAction: (action: string) => void;
  onQuickAction: (action: QuickAction) => void;
  onSupportResourceClick: (resource: HomeSupportResource) => void;
  onKnowledgeQueryChange: (query: string) => void;
  onKnowledgeCategoryChange: (category: string) => void;
  onKnowledgeAudienceChange: (audience: string) => void;
  onKnowledgeSearch: () => void;
  onKnowledgeArticleSelect: (articleId: string) => void;
  onKnowledgeQuestionChange: (question: string) => void;
  onKnowledgeAsk: () => void;
  onKnowledgeContinueChat: () => void;
  onTestSelect: (test: TestListItem) => void;
  onTestStart: () => void;
  onTestAnswer: (questionIndex: number, optionId: string) => void;
  onTestComplete: () => void;
  onTestHistorySelect: (attemptId: string) => void;
  onTestContinueChat: () => void;
  onMemoryEditStart: (memory: MemoryItem) => void;
  onMemoryDraftChange: (content: string) => void;
  onMemorySave: () => void;
  onMemoryDelete: (memoryId: string) => void;
  onMemoriesClear: () => void;
  onSettingsMemoryModeChange: (mode: MemoryMode) => void;
  onSettingsSaveTranscriptChange: (saveTranscript: boolean) => void;
  onSettingsSave: () => void;
  onDataExport: () => void;
  onDeleteScopeChange: (scope: PrivacyDataScope) => void;
  onDataDelete: () => void;
  onAccountConfirmationChange: (confirmation: string) => void;
  onAccountDelete: () => void;
  onFeedbackTargetTypeChange: (type: (typeof feedbackTargetOptions)[number]["value"]) => void;
  onFeedbackTargetIdChange: (targetId: string) => void;
  onFeedbackRatingChange: (rating: number) => void;
  onFeedbackNoteChange: (note: string) => void;
  onFeedbackSubmit: () => void;
  onToggleSafetyEntry: () => void;
  onRetrySafetyState: () => void;
  onLogout: () => void;
}) {
  const shouldShowGuidance = isSafetyEntryOpen || Boolean(highRiskSafety);

  useEffect(() => {
    if (shouldShowGuidance) {
      setActiveToolSurface("safety");
    }
  }, [shouldShowGuidance]);

  if (activeToolSurface === "launcher") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="工具入口">
        <section className="ningyu-panel-section ningyu-tool-launcher">
          <span className="ningyu-panel-section__caption">安静工具</span>
          <h2>
            <Icon name="spark" />
            选择一个轻一点的下一步
          </h2>
          <div className="ningyu-tool-launcher__grid">
            <button type="button" onClick={() => setActiveToolSurface("journey")}>
              <Icon name="heart" />
              <span>
                <strong>今天的心情</strong>
                <small>记录心情、趋势和每周小结。</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("journey")}>
              <Icon name="leaf" />
              <span>
                <strong>我的轨迹</strong>
                <small>安静查看最近几天的状态。</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("actions")}>
              <Icon name="light" />
              <span>
                <strong>建议行动</strong>
                <small>和聊天相连的小提示。</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("knowledge")}>
              <Icon name="leaf" />
              <span>
                <strong>知识库</strong>
                <small>搜索文章，或提出结构化问题。</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("tests")}>
              <Icon name="spark" />
              <span>
                <strong>测试</strong>
                <small>开始已发布测试并查看结果。</small>
              </span>
            </button>
            <button type="button" onClick={() => setActiveToolSurface("settings")}>
              <Icon name="settings" />
              <span>
                <strong>设置</strong>
                <small>隐私、记忆和产品边界。</small>
              </span>
            </button>
          </div>
        </section>
      </aside>
    );
  }

  if (activeToolSurface === "journey") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="我的轨迹">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <section className="ningyu-panel-section ningyu-panel-section--mood">
          <span className="ningyu-panel-section__caption">我的轨迹</span>
          <h2>
            <Icon name="heart" />
            心情打卡
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
          <WeeklySummaryCard
            status={weeklySummaryStatus}
            error={weeklySummaryError}
            summary={weeklySummary}
            onSuggestedAction={onWeeklySuggestedAction}
          />
        </section>
      </aside>
    );
  }

  if (activeToolSurface === "actions") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="建议行动">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <section className="ningyu-panel-section ningyu-panel-section--suggestions">
          <span className="ningyu-panel-section__caption">建议行动</span>
          <h2>
            <Icon name="light" />
            附近可以做的小事
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
                {activeQuickActionId === suggestion.id ? "准备中..." : suggestion.label}
              </button>
            )) : <p className="ningyu-tool-empty">现在没有等待处理的建议行动。</p>}
          </div>
          <QuickActionFeedback status={quickActionStatus} error={quickActionError} result={quickActionResult} />
        </section>
      </aside>
    );
  }

  if (activeToolSurface === "knowledge") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="知识库">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <KnowledgeSurface
          query={knowledgeQuery}
          category={knowledgeCategory}
          audience={knowledgeAudience}
          searchStatus={knowledgeSearchStatus}
          searchError={knowledgeSearchError}
          results={knowledgeResults}
          articleStatus={knowledgeArticleStatus}
          articleError={knowledgeArticleError}
          article={knowledgeArticle}
          question={knowledgeQuestion}
          askStatus={knowledgeAskStatus}
          askError={knowledgeAskError}
          answer={knowledgeAnswer}
          riskLevel={knowledgeRiskLevel}
          highRiskSafety={highRiskSafety}
          userMode={userMode}
          onQueryChange={onKnowledgeQueryChange}
          onCategoryChange={onKnowledgeCategoryChange}
          onAudienceChange={onKnowledgeAudienceChange}
          onSearch={onKnowledgeSearch}
          onArticleSelect={onKnowledgeArticleSelect}
          onQuestionChange={onKnowledgeQuestionChange}
          onAsk={onKnowledgeAsk}
          onContinueChat={onKnowledgeContinueChat}
        />
      </aside>
    );
  }

  if (activeToolSurface === "tests") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="测试">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <TestSurface
          tests={tests}
          listStatus={testListStatus}
          listError={testListError}
          selectedTest={selectedTest}
          detailStatus={testDetailStatus}
          detailError={testDetailError}
          attempt={testAttempt}
          attemptStatus={testAttemptStatus}
          attemptError={testAttemptError}
          answers={testAnswers}
          answerStatus={testAnswerStatus}
          answerError={testAnswerError}
          result={testResult}
          resultStatus={testResultStatus}
          resultError={testResultError}
          history={testHistory}
          historyStatus={testHistoryStatus}
          historyError={testHistoryError}
          shareCard={testShareCard}
          onSelectTest={onTestSelect}
          onStartAttempt={onTestStart}
          onAnswer={onTestAnswer}
          onComplete={onTestComplete}
          onSelectHistory={onTestHistorySelect}
          onContinueChat={onTestContinueChat}
        />
      </aside>
    );
  }

  if (activeToolSurface === "settings") {
    return (
      <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="设置、隐私和反馈">
        <ToolBackButton onClick={() => setActiveToolSurface("launcher")} />
        <SettingsPrivacySurface
          currentUserLabel={currentUserLabel}
          statusTags={statusTags}
          memories={memories}
          memoryListStatus={memoryListStatus}
          memoryListError={memoryListError}
          editingMemoryId={editingMemoryId}
          memoryDraft={memoryDraft}
          memoryMutationStatus={memoryMutationStatus}
          memoryMutationError={memoryMutationError}
          settingsMemoryMode={settingsMemoryMode}
          settingsSaveTranscript={settingsSaveTranscript}
          settingsStatus={settingsStatus}
          settingsError={settingsError}
          privacySummary={privacySummary}
          privacyStatus={privacyStatus}
          privacyError={privacyError}
          dataExportStatus={dataExportStatus}
          dataExportError={dataExportError}
          personalDataExport={personalDataExport}
          deleteScope={deleteScope}
          dataDeleteStatus={dataDeleteStatus}
          dataDeleteError={dataDeleteError}
          dataDeleteResult={dataDeleteResult}
          accountConfirmation={accountConfirmation}
          accountDeleteStatus={accountDeleteStatus}
          accountDeleteError={accountDeleteError}
          accountDeleteResult={accountDeleteResult}
          feedbackTargetType={feedbackTargetType}
          feedbackTargetId={feedbackTargetId}
          feedbackRating={feedbackRating}
          feedbackNote={feedbackNote}
          feedbackStatus={feedbackStatus}
          feedbackError={feedbackError}
          onMemoryEditStart={onMemoryEditStart}
          onMemoryDraftChange={onMemoryDraftChange}
          onMemorySave={onMemorySave}
          onMemoryDelete={onMemoryDelete}
          onMemoriesClear={onMemoriesClear}
          onSettingsMemoryModeChange={onSettingsMemoryModeChange}
          onSettingsSaveTranscriptChange={onSettingsSaveTranscriptChange}
          onSettingsSave={onSettingsSave}
          onDataExport={onDataExport}
          onDeleteScopeChange={onDeleteScopeChange}
          onDataDelete={onDataDelete}
          onAccountConfirmationChange={onAccountConfirmationChange}
          onAccountDelete={onAccountDelete}
          onFeedbackTargetTypeChange={onFeedbackTargetTypeChange}
          onFeedbackTargetIdChange={onFeedbackTargetIdChange}
          onFeedbackRatingChange={onFeedbackRatingChange}
          onFeedbackNoteChange={onFeedbackNoteChange}
          onFeedbackSubmit={onFeedbackSubmit}
        />
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
        <button className="ningyu-logout-button" type="button" onClick={onLogout}>
          退出登录
        </button>
      </section>

      <section className="ningyu-panel-section ningyu-panel-section--mood">
        <span className="ningyu-panel-section__caption">一分钟打卡</span>
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
        <WeeklySummaryCard
          status={weeklySummaryStatus}
          error={weeklySummaryError}
          summary={weeklySummary}
          onSuggestedAction={onWeeklySuggestedAction}
        />
      </section>

      <section className="ningyu-panel-section">
        <span className="ningyu-panel-section__caption">需要时可直接使用</span>
        <h2>
          <Icon name="heart" />
          安全支持
        </h2>
        {supportResources.map((resource) => (
          <button className="ningyu-support-card" key={resource.id} type="button" onClick={() => onSupportResourceClick(resource)}>
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
      返回工具
    </button>
  );
}

function KnowledgeSurface({
  query,
  category,
  audience,
  searchStatus,
  searchError,
  results,
  articleStatus,
  articleError,
  article,
  question,
  askStatus,
  askError,
  answer,
  riskLevel,
  highRiskSafety,
  userMode,
  onQueryChange,
  onCategoryChange,
  onAudienceChange,
  onSearch,
  onArticleSelect,
  onQuestionChange,
  onAsk,
  onContinueChat,
}: {
  query: string;
  category: string;
  audience: string;
  searchStatus: KnowledgeSearchStatus;
  searchError: string | null;
  results: KnowledgeSearchItem[];
  articleStatus: KnowledgeArticleStatus;
  articleError: string | null;
  article: KnowledgeArticleResponse | null;
  question: string;
  askStatus: KnowledgeAskStatus;
  askError: string | null;
  answer: AskKnowledgeResponse | null;
  riskLevel: RiskLevel | null;
  highRiskSafety: HighRiskSafetyState | null;
  userMode: UserMode;
  onQueryChange: (query: string) => void;
  onCategoryChange: (category: string) => void;
  onAudienceChange: (audience: string) => void;
  onSearch: () => void;
  onArticleSelect: (articleId: string) => void;
  onQuestionChange: (question: string) => void;
  onAsk: () => void;
  onContinueChat: () => void;
}) {
  const isHighRiskKnowledge = isHighRiskLevel(riskLevel);
  const coverageTone = answer?.coverage_status === "partial" || answer?.coverage_status === "insufficient" ? "is-partial" : "";

  return (
    <section className="ningyu-panel-section ningyu-knowledge-surface">
      <span className="ningyu-panel-section__caption">知识库</span>
      <h2>
        <Icon name="leaf" />
        自助支持知识库
      </h2>

      <form
        className="ningyu-knowledge-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <label>
          <span>搜索主题</span>
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="例如：焦虑、睡眠、和朋友吵架"
          />
        </label>
        <div className="ningyu-knowledge-filters">
          <label>
            <span>分类</span>
            <select value={category} onChange={(event) => onCategoryChange(event.target.value)}>
              {knowledgeCategoryOptions.map((option) => (
                <option key={option.value || "all"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>适用人群</span>
            <select value={audience} onChange={(event) => onAudienceChange(event.target.value)}>
              {knowledgeAudienceOptions.map((option) => (
                <option key={option.value || "all"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button type="submit" disabled={searchStatus === "loading"}>
          {searchStatus === "loading" ? "搜索中..." : "搜索"}
        </button>
      </form>

      {searchStatus === "error" ? <p className="ningyu-tool-empty is-error">{searchError}</p> : null}
      {searchStatus === "success" && results.length === 0 ? (
        <p className="ningyu-tool-empty">还没有找到匹配文章，可以换一个更日常的关键词，或直接向知识问答提问。</p>
      ) : null}
      {searchStatus === "idle" && results.length === 0 ? (
        <p className="ningyu-tool-empty">输入一个主题，宁语会只展示带分类和适用人群的知识卡片。</p>
      ) : null}

      {results.length ? (
        <div className="ningyu-knowledge-results" aria-label="知识搜索结果">
          {results.map((item) => (
            <button key={item.article_id} type="button" onClick={() => onArticleSelect(item.article_id)}>
              <span className="ningyu-knowledge-card__meta">
                {knowledgeCategoryLabels[item.category] ?? "其他分类"} · {knowledgeAudienceLabels[item.audience] ?? "其他人群"}
              </span>
              <strong>{item.title}</strong>
              <small>{item.summary_30s}</small>
              {item.tags.length ? (
                <em>
                  {item.tags.slice(0, 3).map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </em>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}

      <div className="ningyu-knowledge-article">
        {articleStatus === "loading" ? <p className="ningyu-tool-empty">正在打开文章...</p> : null}
        {articleStatus === "error" ? <p className="ningyu-tool-empty is-error">{articleError}</p> : null}
        {article ? (
          <article>
            <span className="ningyu-knowledge-card__meta">
              {knowledgeCategoryLabels[article.category] ?? "其他分类"} · {knowledgeAudienceLabels[article.audience] ?? "其他人群"}
            </span>
            <h3>{article.title}</h3>
            <p>{article.summary_30s}</p>
            <p>{article.explanation_3min}</p>
            {article.actions.length ? (
              <div>
                <strong>可以试试</strong>
                <ul>
                  {article.actions.slice(0, 4).map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {article.seek_help_when.length ? (
              <div className="ningyu-knowledge-warning">
                <strong>需要现实支持时</strong>
                <ul>
                  {article.seek_help_when.slice(0, 3).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </article>
        ) : null}
      </div>

      <form
        className="ningyu-knowledge-form"
        onSubmit={(event) => {
          event.preventDefault();
          onAsk();
        }}
      >
        <label>
          <span>提一个问题</span>
          <textarea
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            rows={3}
            placeholder="把想知道的事写下来，可以很短。"
          />
        </label>
        <button type="submit" disabled={askStatus === "loading"}>
          {askStatus === "loading" ? "回答中..." : "提问知识库"}
        </button>
      </form>

      {askStatus === "error" ? <p className="ningyu-tool-empty is-error">{askError}</p> : null}
      {isHighRiskKnowledge ? (
        <div className="ningyu-knowledge-risk">
          <strong>这个问题先转到安全支持</strong>
          <span>普通知识回答已暂停，宁语会优先展示安全提醒和现实支持入口。</span>
          <SafetyGuidanceCard userMode={userMode} highRiskSafety={highRiskSafety} />
        </div>
      ) : null}

      {answer && !isHighRiskKnowledge ? (
        <div className={`ningyu-knowledge-answer ${coverageTone}`}>
          <div className="ningyu-knowledge-answer__status">
            <span>{knowledgeCoverageLabels[answer.coverage_status] ?? "覆盖状态未知"}</span>
            <span>{knowledgeScopeLabels[answer.scope_status] ?? "范围状态未知"}</span>
            <span>可信度：{knowledgeConfidenceLabels[answer.confidence] ?? "未知"}</span>
          </div>
          {coverageTone ? (
            <p className="ningyu-knowledge-gap">
              这次回答覆盖不完整，可以把问题换成更具体的一句，或继续聊聊真实情境。
            </p>
          ) : null}
          {answer.question_suggestion ? (
            <p className="ningyu-knowledge-gap">
              也许你在问：{answer.question_suggestion.guessed_question}
            </p>
          ) : null}
          <h3>{answer.answer.summary_30s}</h3>
          <p>{answer.answer.explanation_3min}</p>
          {answer.answer.actions.length ? (
            <div>
              <strong>小行动</strong>
              <ul>
                {answer.answer.actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {answer.answer.seek_help_when.length ? (
            <div className="ningyu-knowledge-warning">
              <strong>请考虑寻求现实支持</strong>
              <ul>
                {answer.answer.seek_help_when.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {answer.source_refs.length ? (
            <div className="ningyu-knowledge-sources">
              <strong>来源</strong>
              {answer.source_refs.slice(0, 4).map((source) => (
                <span key={`${source.article_id}-${source.chunk_id ?? source.source_name}`}>
                  {source.article_title} · {source.source_name}
                </span>
              ))}
            </div>
          ) : null}
          {answer.related_articles.length ? (
            <div className="ningyu-knowledge-related">
              <strong>相关内容</strong>
              {answer.related_articles.slice(0, 3).map((item) => (
                <button key={item.article_id} type="button" onClick={() => onArticleSelect(item.article_id)}>
                  {item.title}
                </button>
              ))}
            </div>
          ) : null}
          <button className="ningyu-knowledge-continue" type="button" onClick={onContinueChat}>
            继续聊聊
          </button>
        </div>
      ) : null}
    </section>
  );
}

function TestSurface({
  tests,
  listStatus,
  listError,
  selectedTest,
  detailStatus,
  detailError,
  attempt,
  attemptStatus,
  attemptError,
  answers,
  answerStatus,
  answerError,
  result,
  resultStatus,
  resultError,
  history,
  historyStatus,
  historyError,
  shareCard,
  onSelectTest,
  onStartAttempt,
  onAnswer,
  onComplete,
  onSelectHistory,
  onContinueChat,
}: {
  tests: TestListItem[];
  listStatus: TestListStatus;
  listError: string | null;
  selectedTest: TestDetailResponse | null;
  detailStatus: TestDetailStatus;
  detailError: string | null;
  attempt: StartAttemptResponse | null;
  attemptStatus: TestAttemptStatus;
  attemptError: string | null;
  answers: Record<number, string>;
  answerStatus: TestAnswerStatus;
  answerError: string | null;
  result: CompleteAttemptResponse | null;
  resultStatus: TestResultStatus;
  resultError: string | null;
  history: TestHistoryItem[];
  historyStatus: TestHistoryStatus;
  historyError: string | null;
  shareCard: TestShareCardPayload | null;
  onSelectTest: (test: TestListItem) => void;
  onStartAttempt: () => void;
  onAnswer: (questionIndex: number, optionId: string) => void;
  onComplete: () => void;
  onSelectHistory: (attemptId: string) => void;
  onContinueChat: () => void;
}) {
  const questions = attempt?.questions ?? selectedTest?.questions ?? [];
  const answeredCount = Object.keys(answers).length;
  const canComplete = Boolean(attempt) && questions.length > 0 && answeredCount >= questions.length;

  return (
    <section className="ningyu-panel-section ningyu-tests-surface">
      <div className="ningyu-tests-surface__header">
        <strong>已发布测试</strong>
        <small>{listStatus === "loading" ? "加载中" : `${tests.length} 个可用`}</small>
      </div>
      {listStatus === "error" ? <p className="ningyu-tool-empty is-error">{listError}</p> : null}
      {listStatus !== "loading" && listStatus !== "error" && tests.length === 0 ? <p className="ningyu-tool-empty">暂时还没有可用测试。</p> : null}
      <div className="ningyu-tests-list">
        {tests.map((test) => {
          const isPublished = test.status === "published";

          return (
            <button
              key={test.test_id}
              type="button"
              disabled={!isPublished || detailStatus === "loading"}
              aria-disabled={!isPublished}
              onClick={() => onSelectTest(test)}
            >
              <span>
                <strong>{test.title}</strong>
                <small>
                  {testTypeLabels[test.test_type] ?? "测试"} · {test.estimated_minutes} 分钟 · {isPublished ? "已发布" : "未发布"}
                </small>
              </span>
              <em>{isPublished ? "可开始" : "未开放"}</em>
            </button>
          );
        })}
      </div>

      {detailStatus === "error" ? <p className="ningyu-tool-empty is-error">{detailError}</p> : null}
      {selectedTest ? (
        <div className="ningyu-test-detail">
          <div className="ningyu-test-detail__header">
            <strong>{selectedTest.title}</strong>
            <small>{selectedTest.questions.length} 道题</small>
          </div>
          <button type="button" onClick={onStartAttempt} disabled={attemptStatus === "loading"}>
            {attemptStatus === "loading" ? "正在开始..." : attempt ? "重新开始" : "开始测试"}
          </button>
          {attemptStatus === "error" ? <p className="ningyu-tool-empty is-error">{attemptError}</p> : null}
        </div>
      ) : null}

      {attempt ? (
        <div className="ningyu-test-attempt">
          <div className="ningyu-test-detail__header">
            <strong>答题进行中</strong>
            <small>
              已答 {answeredCount}/{questions.length}
            </small>
          </div>
          {questions.map((question) => (
            <fieldset key={question.index} className="ningyu-test-question">
              <legend>{question.text}</legend>
              {question.options.map((option) => (
                <button
                  key={option.id}
                  className={answers[question.index] === option.id ? "is-active" : ""}
                  type="button"
                  onClick={() => onAnswer(question.index, option.id)}
                  disabled={answerStatus === "loading" || resultStatus === "loading"}
                >
                  {option.text}
                </button>
              ))}
            </fieldset>
          ))}
          {answerStatus === "error" ? <p className="ningyu-tool-empty is-error">{answerError}</p> : null}
          <button className="ningyu-test-complete" type="button" onClick={onComplete} disabled={!canComplete || resultStatus === "loading"}>
            {resultStatus === "loading" ? "生成中..." : "完成测试"}
          </button>
          {!canComplete ? <p className="ningyu-tool-empty">答完全部题目后就可以生成结果。</p> : null}
        </div>
      ) : null}

      {resultStatus === "error" ? <p className="ningyu-tool-empty is-error">{resultError}</p> : null}
      {result ? (
        <div className="ningyu-test-result">
          <span className="ningyu-knowledge-card__meta">
            {result.test_code} · {result.result_code}
          </span>
          <h3>{result.result_title}</h3>
          <p>{result.summary}</p>
          <div>
            <strong>优势</strong>
            <ul>
              {result.strengths.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <strong>可能忽略的地方</strong>
            <ul>
              {result.blind_spots.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <strong>建议行动</strong>
            <ul>
              {result.suggested_actions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <p className="ningyu-test-disclaimer">{testResultDisclaimer}</p>
          {shareCard ? (
            <div className="ningyu-test-share">
              <strong>分享卡片数据</strong>
              <small>{shareCard.title}</small>
              <span>{shareCard.subtitle}</span>
              <span>{shareCard.summary}</span>
              <em>{shareCard.disclaimer}</em>
            </div>
          ) : null}
          <button className="ningyu-test-complete" type="button" onClick={onContinueChat}>
            继续聊天
          </button>
        </div>
      ) : null}

      <div className="ningyu-test-history">
        <div className="ningyu-tests-surface__header">
          <strong>历史记录</strong>
          <small>{historyStatus === "loading" ? "加载中" : `${history.length} 条记录`}</small>
        </div>
        {historyStatus === "error" ? <p className="ningyu-tool-empty is-error">{historyError}</p> : null}
        {historyStatus !== "loading" && historyStatus !== "error" && history.length === 0 ? (
          <p className="ningyu-tool-empty">还没有测试历史。</p>
        ) : null}
        {history.map((item) => (
          <button key={item.attempt_id} type="button" onClick={() => onSelectHistory(item.attempt_id)}>
            <span>
              <strong>{item.test_title}</strong>
              <small>
                {item.result_label} · {item.completed_at}
              </small>
            </span>
            <em>{item.result_code}</em>
          </button>
        ))}
      </div>
    </section>
  );
}

function SettingsPrivacySurface({
  currentUserLabel,
  statusTags,
  memories,
  memoryListStatus,
  memoryListError,
  editingMemoryId,
  memoryDraft,
  memoryMutationStatus,
  memoryMutationError,
  settingsMemoryMode,
  settingsSaveTranscript,
  settingsStatus,
  settingsError,
  privacySummary,
  privacyStatus,
  privacyError,
  dataExportStatus,
  dataExportError,
  personalDataExport,
  deleteScope,
  dataDeleteStatus,
  dataDeleteError,
  dataDeleteResult,
  accountConfirmation,
  accountDeleteStatus,
  accountDeleteError,
  accountDeleteResult,
  feedbackTargetType,
  feedbackTargetId,
  feedbackRating,
  feedbackNote,
  feedbackStatus,
  feedbackError,
  onMemoryEditStart,
  onMemoryDraftChange,
  onMemorySave,
  onMemoryDelete,
  onMemoriesClear,
  onSettingsMemoryModeChange,
  onSettingsSaveTranscriptChange,
  onSettingsSave,
  onDataExport,
  onDeleteScopeChange,
  onDataDelete,
  onAccountConfirmationChange,
  onAccountDelete,
  onFeedbackTargetTypeChange,
  onFeedbackTargetIdChange,
  onFeedbackRatingChange,
  onFeedbackNoteChange,
  onFeedbackSubmit,
}: {
  currentUserLabel: string;
  statusTags: string[];
  memories: MemoryItem[];
  memoryListStatus: MemoryListStatus;
  memoryListError: string | null;
  editingMemoryId: string | null;
  memoryDraft: string;
  memoryMutationStatus: MemoryMutationStatus;
  memoryMutationError: string | null;
  settingsMemoryMode: MemoryMode;
  settingsSaveTranscript: boolean;
  settingsStatus: SettingsMutationStatus;
  settingsError: string | null;
  privacySummary: PrivacySummaryResponse | null;
  privacyStatus: PrivacyStatus;
  privacyError: string | null;
  dataExportStatus: DataActionStatus;
  dataExportError: string | null;
  personalDataExport: PersonalDataExport | null;
  deleteScope: PrivacyDataScope;
  dataDeleteStatus: DataActionStatus;
  dataDeleteError: string | null;
  dataDeleteResult: PrivacyMutationResponse | null;
  accountConfirmation: string;
  accountDeleteStatus: DataActionStatus;
  accountDeleteError: string | null;
  accountDeleteResult: PrivacyMutationResponse | null;
  feedbackTargetType: (typeof feedbackTargetOptions)[number]["value"];
  feedbackTargetId: string;
  feedbackRating: number;
  feedbackNote: string;
  feedbackStatus: FeedbackSubmitStatus;
  feedbackError: string | null;
  onMemoryEditStart: (memory: MemoryItem) => void;
  onMemoryDraftChange: (content: string) => void;
  onMemorySave: () => void;
  onMemoryDelete: (memoryId: string) => void;
  onMemoriesClear: () => void;
  onSettingsMemoryModeChange: (mode: MemoryMode) => void;
  onSettingsSaveTranscriptChange: (saveTranscript: boolean) => void;
  onSettingsSave: () => void;
  onDataExport: () => void;
  onDeleteScopeChange: (scope: PrivacyDataScope) => void;
  onDataDelete: () => void;
  onAccountConfirmationChange: (confirmation: string) => void;
  onAccountDelete: () => void;
  onFeedbackTargetTypeChange: (type: (typeof feedbackTargetOptions)[number]["value"]) => void;
  onFeedbackTargetIdChange: (targetId: string) => void;
  onFeedbackRatingChange: (rating: number) => void;
  onFeedbackNoteChange: (note: string) => void;
  onFeedbackSubmit: () => void;
}) {
  const exportPreview = personalDataExport ? JSON.stringify(personalDataExport, null, 2).slice(0, 900) : "";

  return (
    <section className="ningyu-panel-section ningyu-settings-surface">
      <span className="ningyu-panel-section__caption">设置 / 隐私</span>
      <h2>
        <Icon name="settings" />
        {currentUserLabel}
      </h2>
      <div className="ningyu-tags">
        {statusTags.map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
      </div>

      <div className="ningyu-settings-block">
        <div className="ningyu-tests-surface__header">
          <strong>记忆中心</strong>
          <small>{memoryListStatus === "loading" ? "加载中" : `${memories.length} 条记忆`}</small>
        </div>
        {memoryListStatus === "error" ? <p className="ningyu-tool-empty is-error">{memoryListError}</p> : null}
        {memoryMutationStatus === "error" ? <p className="ningyu-tool-empty is-error">{memoryMutationError}</p> : null}
        {memoryListStatus !== "loading" && memories.length === 0 ? <p className="ningyu-tool-empty">还没有可展示的长期记忆。</p> : null}
        {memories.map((memory) => (
          <div className="ningyu-memory-item" key={memory.memory_id}>
            <span>{memory.memory_type}</span>
            {editingMemoryId === memory.memory_id ? (
              <textarea value={memoryDraft} onChange={(event) => onMemoryDraftChange(event.target.value)} rows={3} />
            ) : (
              <p>{memory.content}</p>
            )}
            <div>
              {editingMemoryId === memory.memory_id ? (
                <button type="button" onClick={onMemorySave} disabled={memoryMutationStatus === "loading"}>
                  保存
                </button>
              ) : (
                <button type="button" onClick={() => onMemoryEditStart(memory)}>
                  编辑
                </button>
              )}
              <button type="button" onClick={() => onMemoryDelete(memory.memory_id)} disabled={memoryMutationStatus === "loading"}>
                删除
              </button>
            </div>
          </div>
        ))}
        <button type="button" onClick={onMemoriesClear} disabled={memoryMutationStatus === "loading" || memories.length === 0}>
          清空全部记忆
        </button>
      </div>

      <div className="ningyu-settings-block">
        <strong>记忆与隐私设置</strong>
        <label>
          <span>记忆模式</span>
          <select value={settingsMemoryMode} onChange={(event) => onSettingsMemoryModeChange(event.target.value as MemoryMode)}>
            <option value="off">记忆关闭</option>
            <option value="summary_only">摘要记忆</option>
            <option value="long_term">长时记忆</option>
          </select>
        </label>
        <label className="ningyu-settings-toggle">
          <input
            type="checkbox"
            checked={settingsSaveTranscript}
            onChange={(event) => onSettingsSaveTranscriptChange(event.target.checked)}
          />
          <span>保存文字聊天记录</span>
        </label>
        <button type="button" onClick={onSettingsSave} disabled={settingsStatus === "loading"}>
          {settingsStatus === "loading" ? "保存中..." : "保存设置"}
        </button>
        {settingsStatus === "success" ? <p className="ningyu-tool-empty">设置已更新。</p> : null}
        {settingsStatus === "error" ? <p className="ningyu-tool-empty is-error">{settingsError}</p> : null}
      </div>

      <div className="ningyu-settings-block">
        <div className="ningyu-tests-surface__header">
          <strong>隐私摘要</strong>
          <small>{privacyStatus === "loading" ? "加载中" : privacySummary?.latest_activity_at ?? "暂无最近活动"}</small>
        </div>
        {privacyStatus === "error" ? <p className="ningyu-tool-empty is-error">{privacyError}</p> : null}
        {privacySummary ? (
          <div className="ningyu-privacy-counts">
            {Object.entries(privacySummary.data_counts).map(([key, value]) => (
              <span key={key}>
                <strong>{value}</strong>
                {privacyCountLabels[key] ?? "其他数据"}
              </span>
            ))}
          </div>
        ) : null}
        <button type="button" onClick={onDataExport} disabled={dataExportStatus === "loading"}>
          {dataExportStatus === "loading" ? "导出中..." : "导出个人数据"}
        </button>
        {dataExportStatus === "error" ? <p className="ningyu-tool-empty is-error">{dataExportError}</p> : null}
        {exportPreview ? <pre className="ningyu-data-export">{exportPreview}</pre> : null}
      </div>

      <div className="ningyu-settings-block">
        <strong>删除数据</strong>
        <label>
          <span>范围</span>
          <select value={deleteScope} onChange={(event) => onDeleteScopeChange(event.target.value as PrivacyDataScope)}>
            {privacyDeleteScopes.map((scope) => (
              <option key={scope.value} value={scope.value}>
                {scope.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={onDataDelete} disabled={dataDeleteStatus === "loading"}>
          {dataDeleteStatus === "loading" ? "删除中..." : "删除选定数据"}
        </button>
        {dataDeleteStatus === "error" ? <p className="ningyu-tool-empty is-error">{dataDeleteError}</p> : null}
        {dataDeleteResult ? (
          <p className="ningyu-tool-empty">
            已处理：{privacyDeleteScopes.find((scope) => scope.value === dataDeleteResult.scope)?.label ?? "选定范围"}
          </p>
        ) : null}
      </div>

      <div className="ningyu-settings-block">
        <strong>注销账号</strong>
        <input
          value={accountConfirmation}
          onChange={(event) => onAccountConfirmationChange(event.target.value)}
          placeholder="输入“注销账号”确认"
        />
        <button type="button" onClick={onAccountDelete} disabled={accountDeleteStatus === "loading"}>
          {accountDeleteStatus === "loading" ? "注销中..." : "注销账号"}
        </button>
        {accountDeleteStatus === "error" ? <p className="ningyu-tool-empty is-error">{accountDeleteError}</p> : null}
        {accountDeleteResult ? <p className="ningyu-tool-empty">账号注销请求已完成：{accountDeleteResult.status}</p> : null}
      </div>

      <div className="ningyu-settings-block">
        <strong>反馈</strong>
        <label>
          <span>反馈对象类型</span>
          <select value={feedbackTargetType} onChange={(event) => onFeedbackTargetTypeChange(event.target.value as typeof feedbackTargetType)}>
            {feedbackTargetOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <input value={feedbackTargetId} onChange={(event) => onFeedbackTargetIdChange(event.target.value)} placeholder="内容编号" />
        <label>
          <span>评分：{feedbackRating}</span>
          <input
            type="range"
            min="1"
            max="5"
            value={feedbackRating}
            onChange={(event) => onFeedbackRatingChange(Number(event.target.value))}
          />
        </label>
        <textarea value={feedbackNote} onChange={(event) => onFeedbackNoteChange(event.target.value)} rows={2} placeholder="可选说明" />
        <button type="button" onClick={onFeedbackSubmit} disabled={feedbackStatus === "loading"}>
          {feedbackStatus === "loading" ? "提交中..." : "提交反馈"}
        </button>
        {feedbackStatus === "success" ? <p className="ningyu-tool-empty">反馈已提交，谢谢你帮宁语变好。</p> : null}
        {feedbackStatus === "error" ? <p className="ningyu-tool-empty is-error">{feedbackError}</p> : null}
      </div>

      <div className="ningyu-settings-block ningyu-about-block">
        <strong>关于 / 开源</strong>
        <p>宁语是面向陪伴与自助理解的网页端项目，不提供医疗诊断，也不能替代心理治疗或紧急救助。</p>
        <p>当前前端为新版网页端，保留开源协作边界和清晰的数据控制入口。</p>
        <p>如果你或身边的人处于立即危险中，请优先联系当地紧急服务或可信任的现实支持者。</p>
      </div>
    </section>
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
  const riskLabel = highRiskSafety?.riskLevel === "L3" ? "三级高风险" : highRiskSafety?.riskLevel === "L2" ? "二级需要支持" : "安全支持";
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
        对话 {result.threadId}
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
  onSuggestedAction,
}: {
  status: WeeklySummaryStatus;
  error: string | null;
  summary: WeeklySummaryResponse | null;
  onSuggestedAction: (action: string) => void;
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
                <button key={action} type="button" onClick={() => onSuggestedAction(action)}>
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
