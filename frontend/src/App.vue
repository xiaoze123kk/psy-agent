﻿<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import html2canvas from "html2canvas";

import { ApiClient } from "./api/client";
import { CounselingApi } from "./api/endpoints";
import type {
  AgeRange,
  AskKnowledgeResponse,
  ChatStreamFinalEvent,
  ChatStreamGraphUpdateEvent,
  ChatStreamTokenEvent,
  CompleteAttemptResponse,
  FeedbackCreateRequest,
  FeedbackResponse,
  KnowledgeArticleResponse,
  KnowledgeQuizBankStatsResponse,
  KnowledgeQuizMode,
  KnowledgeQuizQuestion,
  KnowledgeQuizResultResponse,
  KnowledgeQuizSessionResponse,
  KnowledgeSearchItem,
  MemoryItem,
  MemoryMode,
  MemoryReference,
  MessageItem,
  MoodLogRequest,
  MoodTrendResponse,
  PersonalDataExport,
  PrivacyDataScope,
  PrivacySummaryResponse,
  SendMessageResponse,
  ShareCardData,
  StartAttemptResponse,
  TestDetailResponse,
  TestHistoryItem,
  TestListItem,
  ThreadListItem,
  UserMode,
  VoiceSessionResponse,
  WeeklySummaryResponse,
  WsServerEvent,
} from "./types/api";

type Stage = "auth" | "onboarding" | "app";
type Tab = "home" | "chat" | "tests" | "knowledge" | "profile";
type AgeOptionId = "13-15" | "16-17" | "18-24" | "25+";
type AuthMode = "login" | "register";
type ChatRole = "assistant" | "user";
type RiskLevel = "L0" | "L1" | "L2" | "L3";
type SafetyAction = "trusted" | "resources" | "breathing" | null;
type KnowledgePanel = "qa" | "quiz";
type MoodRange = "7d" | "30d";

interface SelectOption {
  id: string;
  label: string;
  description: string;
}

interface ChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  createdAt?: string;
  riskLevel?: RiskLevel | null;
  graphNode?: string | null;
  suggestedActions?: string[];
  referencedMemories?: MemoryReference[];
  memoryRefsExpanded?: boolean;
  streaming?: boolean;
  streamError?: boolean;
}

interface KnowledgeChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  answer?: AskKnowledgeResponse["answer"];
  relatedArticles?: KnowledgeSearchItem[];
  sourceRefs?: AskKnowledgeResponse["source_refs"];
  questionSuggestion?: AskKnowledgeResponse["question_suggestion"];
  coverageStatus?: AskKnowledgeResponse["coverage_status"];
  scopeStatus?: AskKnowledgeResponse["scope_status"];
  confidence?: AskKnowledgeResponse["confidence"];
  gapId?: string | null;
  riskLevel?: RiskLevel | null;
  streaming?: boolean;
}

interface LocalMoodLog {
  created_at: string;
  mood_score: number;
  mood_tags: string[];
}

const ACCESS_TOKEN_KEY = "counseling_access_token";
const REFRESH_TOKEN_KEY = "counseling_refresh_token";
const USER_ID_KEY = "counseling_user_id";
const USERNAME_KEY = "counseling_username";
const THREAD_ID_KEY = "counseling_thread_id";
const STYLE_KEY = "counseling_style";
const GOAL_KEY = "counseling_goal";
const NEW_THREAD_TITLE = "新的对话";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const ageOptions: Array<SelectOption & { id: AgeOptionId }> = [
  { id: "13-15", label: "13-15 岁", description: "青少年保护模式" },
  { id: "16-17", label: "16-17 岁", description: "青少年保护模式" },
  { id: "18-24", label: "18-24 岁", description: "标准陪伴模式" },
  { id: "25+", label: "25 岁及以上", description: "标准陪伴模式" },
];

const styleOptions: SelectOption[] = [
  { id: "gentle", label: "温柔安抚型", description: "先接住情绪，再慢慢放松。" },
  { id: "rational", label: "理性分析型", description: "把困扰拆开，理清头绪。" },
  { id: "reflective", label: "陪你梳理型", description: "一起整理感受和触发点。" },
  { id: "action", label: "轻量行动型", description: "给出一两个可执行步骤。" },
];

const goalOptions: SelectOption[] = [
  { id: "heard", label: "想先被听见", description: "需要一个不被打断的出口。" },
  { id: "anxiety", label: "想缓解焦虑", description: "先把身体和情绪稳定下来。" },
  { id: "sleep", label: "想改善作息", description: "最近睡眠或精力不太稳。" },
  { id: "relationships", label: "想理清关系", description: "关于家人、朋友或亲密关系。" },
];

const knowledgePromptChips = ["焦虑发作时怎么办", "睡前脑子停不下来", "什么是边界感", "我是不是太敏感了"];
const quizModeOptions: Array<{ id: KnowledgeQuizMode; label: string; description: string }> = [
  { id: "10", label: "10 题", description: "快测" },
  { id: "50", label: "50 题", description: "进阶" },
  { id: "100", label: "100 题", description: "授予头衔" },
];

const demoThreads: ThreadListItem[] = [
  {
    thread_id: "demo-sleep",
    title: "最近总是睡不好",
    mode: "companion",
    last_summary: "你提到晚上脑子停不下来，第二天也恢复不过来。",
    last_risk_level: "L0",
    updated_at: new Date().toISOString(),
  },
  {
    thread_id: "demo-anxiety",
    title: "开会前会很慌",
    mode: "companion",
    last_summary: "你希望找到一个能在 3 分钟内稳定下来的方式。",
    last_risk_level: "L1",
    updated_at: "2026-05-01T18:20:00+08:00",
  },
];

const demoMessages: Record<string, ChatMessage[]> = {
  "demo-sleep": [
    {
      id: 1,
      role: "assistant",
      text: "你好，我们先不急着把问题变小。最近最折磨你的，是入睡困难、半夜醒来，还是醒来后还是很累？",
      createdAt: new Date().toISOString(),
      riskLevel: "L0",
    },
    {
      id: 2,
      role: "user",
      text: "主要是脑子停不下来，越想早点睡越睡不着。",
      createdAt: new Date().toISOString(),
    },
    {
      id: 3,
      role: "assistant",
      text: "那我们先把目标从“立刻睡着”调成“让大脑慢下来一点”。你愿意先一起找出睡前最容易开始转动的那类念头吗？",
      createdAt: new Date().toISOString(),
      riskLevel: "L0",
      referencedMemories: [
        { memory_id: "m1", memory_type: "preference", content: "睡眠波动时更希望先被安抚，再进入分析。" },
      ],
    },
  ],
  "demo-anxiety": [
    {
      id: 1,
      role: "assistant",
      text: "开会前的慌张，常常是身体先进入警戒状态。我们可以先看身体信号，再看事情本身。",
      createdAt: "2026-05-01T18:05:00+08:00",
      riskLevel: "L1",
    },
  ],
};

const demoMemories: MemoryItem[] = [
  { memory_id: "m1", memory_type: "preference", content: "睡眠波动时更希望先被安抚，再进入分析。" },
  { memory_id: "m2", memory_type: "support_strategy", content: "高压场景前适合先做 60 秒呼吸。" },
];

const demoMoodTrend: MoodTrendResponse = {
  range: "7d",
  avg_mood_score: 3,
  top_tags: ["睡眠", "焦虑", "关系"],
  daily: [],
  summary: "最近压力主要集中在睡眠和会前焦虑，适合优先减负。",
};

type TestCategory = "state" | "personality" | "anime";
type TestView = "list" | "taking" | "result" | "history";

const testView = ref<TestView>("list");
const selectedTestCategory = ref<TestCategory>("state");
const testItems = ref<TestListItem[]>([]);
const currentTest = ref<TestDetailResponse | null>(null);
const currentAttemptId = ref("");
const currentQuestionIndex = ref(0);
const selectedOptionId = ref("");
const testAnswers = ref<Record<number, string>>({});
const testResult = ref<CompleteAttemptResponse | null>(null);
const isTestLoading = ref(false);
const isConfirmingResult = ref(false);
const isShowingIncomplete = ref(false);
const testHistory = ref<TestHistoryItem[]>([]);
const isHistoryLoading = ref(false);

const demoTests: TestListItem[] = [
  { test_id: "state-check-v1", code: "daily_state", title: "今日情绪状态自评", test_type: "state", estimated_minutes: 1, audience: "all", status: "published" },
  { test_id: "sixteen-type-v1", code: "sixteen_type", title: "16 型人格探索", test_type: "personality", estimated_minutes: 3, audience: "all", status: "published" },
  { test_id: "anime-match-v1", code: "anime_match", title: "测测你像哪个动漫角色", test_type: "anime", estimated_minutes: 5, audience: "all", status: "draft" },
];

const demoStateQuestions: TestDetailResponse = {
  test_id: "state-check-v1",
  code: "daily_state",
  title: "今日情绪状态自评",
  questions: [
    { index: 0, text: "过去一周你的情绪状态整体如何？", options: [{ id: "a", text: "大部分时间比较平稳", score: 4 }, { id: "b", text: "偶尔会低落，但还能应付", score: 3 }, { id: "c", text: "经常感到低落，影响做事", score: 2 }, { id: "d", text: "几乎每天都很难受", score: 1 }] },
    { index: 1, text: "过去一周你感到焦虑或紧张的程度？", options: [{ id: "a", text: "几乎没有明显焦虑", score: 4 }, { id: "b", text: "偶尔焦虑，但不影响日常", score: 3 }, { id: "c", text: "经常焦虑，开始影响睡眠或做事", score: 2 }, { id: "d", text: "大部分时间都很焦虑，难以放松", score: 1 }] },
    { index: 2, text: "过去一周你对生活的整体满意度？", options: [{ id: "a", text: "总体还算满意", score: 4 }, { id: "b", text: "有些方面不太满意", score: 3 }, { id: "c", text: "很多方面都不太满意", score: 2 }, { id: "d", text: "几乎没有什么让我满意的", score: 1 }] },
  ],
};

const demoTypeQuestions: TestDetailResponse = {
  test_id: "sixteen-type-v1",
  code: "sixteen_type",
  title: "16 型人格探索",
  questions: [
    { index: 0, text: "在社交场合中，你通常：", options: [{ id: "a", text: "认识新朋友让你精力充沛", score: 4 }, { id: "b", text: "可以和少数熟悉的人聊很久", score: 3 }, { id: "c", text: "更喜欢安静观察", score: 2 }, { id: "d", text: "人多会让你很疲惫", score: 1 }] },
    { index: 1, text: "周末你更倾向于：", options: [{ id: "a", text: "和朋友聚会或参加活动", score: 4 }, { id: "b", text: "约一两个好友小聚", score: 3 }, { id: "c", text: "在家做自己的事", score: 2 }, { id: "d", text: "一个人待着恢复能量", score: 1 }] },
    { index: 2, text: "你更相信：", options: [{ id: "a", text: "亲眼看到的事实和具体经验", score: 4 }, { id: "b", text: "更多基于实际经验", score: 3 }, { id: "c", text: "更相信直觉和可能性", score: 2 }, { id: "d", text: "对抽象模式和未来走向很敏感", score: 1 }] },
    { index: 3, text: "做决定时你更看重：", options: [{ id: "a", text: "逻辑分析和对错", score: 4 }, { id: "b", text: "先看逻辑再看人际关系", score: 3 }, { id: "c", text: "先考虑对周围人的影响", score: 2 }, { id: "d", text: "价值观与人的感受最重要", score: 1 }] },
    { index: 4, text: "你对日程安排的态度：", options: [{ id: "a", text: "喜欢提前计划，按步骤执行", score: 4 }, { id: "b", text: "有计划但也接受调整", score: 3 }, { id: "c", text: "大概有个方向就好", score: 2 }, { id: "d", text: "跟着感觉走，不喜欢被约束", score: 1 }] },
    { index: 5, text: "任务临近截止时你通常：", options: [{ id: "a", text: "早就做好了", score: 4 }, { id: "b", text: "按计划推进中", score: 3 }, { id: "c", text: "刚开始着手", score: 2 }, { id: "d", text: "在最后关头冲刺", score: 1 }] },
  ],
};

const demoStateResult: CompleteAttemptResponse = {
  attempt_id: "demo-state-attempt",
  test_code: "daily_state",
  result_code: "mild",
  result_title: "有些波动，留意自我照顾",
  summary: "最近你的情绪和焦虑有一些波动，还在可以调节的范围内。适当减负和规律作息会有帮助。",
  strengths: ["你能主动关注自己的状态"],
  blind_spots: ["别等到很累了才休息"],
  suggested_actions: ["减少不必要的任务和压力源", "每天留出15分钟给自己放松", "和信任的人聊聊最近的状态"],
  continue_chat_context: { mode: "test", context_type: "test_result" },
  profile: { traits: ["情绪偶有起伏", "焦虑开始影响日常但不严重"], strengths: ["你能主动关注自己的状态"], blind_spots: ["别等到很累了才休息"], companion_style: "gentle" },
};

const demoTypeResult: CompleteAttemptResponse = {
  attempt_id: "demo-type-attempt",
  test_code: "sixteen_type",
  result_code: "INFJ-like",
  result_title: "洞察型陪伴者",
  summary: "你对人的情绪很敏感，常常想得很深，也容易被他人情绪影响。这是自研非官方人格风格探索，把它当作了解自己的一面镜子，而不是一个固定的标签。",
  strengths: ["善于洞察他人需求", "忠诚且有耐心", "富有创造力"],
  blind_spots: ["容易忽略自己的需求", "过度反省", "难以拒绝别人"],
  suggested_actions: ["把这个结果当作一面镜子而非标签", "选择一个你想加强的方向开始练习", "在接下来的对话中聊聊这个发现"],
  continue_chat_context: { mode: "test", context_type: "test_result" },
  profile: {
    sixteen_type_code: "INFJ-like",
    sixteen_type_label: "洞察型陪伴者",
    traits: ["对他人的情绪很敏感", "容易想得很深", "压力下会过度消耗自己", "重视深层联结", "很有同理心"],
    strengths: ["善于洞察他人需求", "忠诚且有耐心", "富有创造力"],
    blind_spots: ["容易忽略自己的需求", "过度反省", "难以拒绝别人"],
    companion_style: "先接住情绪，再轻轻拓宽视角",
  },
};

const demoAnimeResult: CompleteAttemptResponse = {
  attempt_id: "demo-anime-attempt",
  test_code: "anime_match",
  test_type: "anime",
  result_code: "anime-draft",
  result_title: "暂未开放",
  summary: "动漫角色测试正在开发中，敬请期待。",
  strengths: [],
  blind_spots: [],
  suggested_actions: ["关注后续更新"],
  continue_chat_context: { mode: "test", context_type: "test_result" },
  profile: { traits: [], strengths: [], blind_spots: [], companion_style: "" },
};

const dayMs = 24 * 60 * 60 * 1000;
const demoMoodLogSeed: LocalMoodLog[] = [
  { created_at: new Date(Date.now() - 6 * dayMs).toISOString(), mood_score: 3, mood_tags: ["睡眠"] },
  { created_at: new Date(Date.now() - 4 * dayMs).toISOString(), mood_score: 2, mood_tags: ["焦虑", "疲惫"] },
  { created_at: new Date(Date.now() - 2 * dayMs).toISOString(), mood_score: 4, mood_tags: ["平静"] },
  { created_at: new Date(Date.now() - 1 * dayMs).toISOString(), mood_score: 3, mood_tags: ["关系", "焦虑"] },
];
const moodTagOptions = ["焦虑", "疲惫", "难过", "委屈", "平静", "睡眠", "关系", "学习"];
const moodRangeOptions: Array<{ id: MoodRange; label: string }> = [
  { id: "7d", label: "7天" },
  { id: "30d", label: "30天" },
];
const memoryModeOptions: Array<{ id: MemoryMode; label: string; description: string }> = [
  { id: "off", label: "关闭", description: "不读取也不新增可见记忆" },
  { id: "summary_only", label: "只记摘要", description: "只保存对话摘要" },
  { id: "long_term", label: "长期记忆", description: "保存偏好、触发点和支持方式" },
];
const privacyDeleteOptions: Array<{ id: PrivacyDataScope; label: string; description: string }> = [
  { id: "memories", label: "清除记忆", description: "删除可见和内部记忆，不影响账号。" },
  { id: "chat", label: "清除聊天", description: "归档会话并删除消息内容。" },
  { id: "moods", label: "清除情绪", description: "删除情绪记录和趋势来源。" },
  { id: "feedback", label: "清除反馈", description: "删除评分、标签和备注。" },
  { id: "voice", label: "清除语音", description: "删除语音会话元数据。" },
  { id: "all_non_account", label: "清除全部数据", description: "保留账号，清空主要个人数据。" },
];


function storageText(key: string) {
  return localStorage.getItem(key) ?? "";
}

function storageOption(key: string, options: SelectOption[]) {
  const value = localStorage.getItem(key);
  return value && options.some((option) => option.id === value) ? value : null;
}

const stage = ref<Stage>(storageText(ACCESS_TOKEN_KEY) ? "app" : "auth");
const activeTab = ref<Tab>("home");
const authMode = ref<AuthMode>("login");
const isDemoMode = ref(false);
const isBooting = ref(true);
const isAuthenticating = ref(false);
const isCaptchaLoading = ref(false);
const isLoadingApp = ref(false);
const isKnowledgeLoading = ref(false);
const isSending = ref(false);
const isMoodSubmitting = ref(false);
const isMoodTrendLoading = ref(false);
const isSafetyOpen = ref(false);
const isThreadDrawerOpen = ref(false);
const isCreatingThread = ref(false);

const accessToken = ref(storageText(ACCESS_TOKEN_KEY));
const refreshToken = ref(storageText(REFRESH_TOKEN_KEY));
const currentUserId = ref(storageText(USER_ID_KEY));
const username = ref(storageText(USERNAME_KEY));
const activeThreadId = ref(storageText(THREAD_ID_KEY));

const authUsername = ref("");
const authPassword = ref("");
const authSelectedAge = ref<AgeOptionId>("18-24");
const captchaId = ref("");
const captchaImageDataUrl = ref("");
const captchaCode = ref("");
const authError = ref("");
const apiError = ref("");
const apiNotice = ref("");

const selectedAge = ref<AgeOptionId | null>(null);
const selectedStyle = ref<string | null>(storageOption(STYLE_KEY, styleOptions));
const selectedGoal = ref<string | null>(storageOption(GOAL_KEY, goalOptions));

const threads = ref<ThreadListItem[]>([]);
const messages = ref<ChatMessage[]>([]);
const memories = ref<MemoryItem[]>([]);
const currentMemoryMode = ref<MemoryMode>("summary_only");
const saveVoiceAudio = ref(false);
const saveTranscript = ref(true);
const isMemoryDocOpen = ref(false);
const isMemoryDocLoading = ref(false);
const memoryDocContent = ref("");
const memoryDocError = ref("");
const memoryError = ref("");
const isSettingsSaving = ref(false);
const privacySummary = ref<PrivacySummaryResponse | null>(null);
const privacyExportPreview = ref("");
const privacyExportData = ref<PersonalDataExport | null>(null);
const isPrivacyExportOpen = ref(false);
const isPrivacyLoading = ref(false);
const privacyError = ref("");
const privacyNotice = ref("");
const pendingPrivacyScope = ref<PrivacyDataScope | null>(null);
const deleteAccountConfirm = ref("");
const moodTrend = ref<MoodTrendResponse | null>(null);
const moodRange = ref<MoodRange>("7d");
const moodDraft = ref<MoodLogRequest>({
  mood_score: 3,
  anxiety_score: 3,
  energy_score: 3,
  sleep_quality: 3,
  mood_tags: [],
  note: "",
});
const knowledgeItems = ref<KnowledgeSearchItem[]>([]);
const selectedKnowledgeArticle = ref<KnowledgeArticleResponse | null>(null);
const knowledgePanel = ref<KnowledgePanel>("qa");
const knowledgeMessages = ref<KnowledgeChatMessage[]>([
  {
    id: 1,
    role: "assistant",
    text: "今天想弄清楚哪件事？焦虑、睡眠、关系、情绪调节，都可以慢慢说。",
  },
]);
const quickActions = ref<string[]>(["继续听我说", "帮我理一理", "先听我说完"]);
const composerText = ref("");
const threadSearchQuery = ref("");
const knowledgeDraft = ref("");
const quizStats = ref<KnowledgeQuizBankStatsResponse | null>(null);
const quizMode = ref<KnowledgeQuizMode>("10");
const quizSession = ref<KnowledgeQuizSessionResponse | null>(null);
const quizResult = ref<KnowledgeQuizResultResponse | null>(null);
const quizAnswers = ref<Record<string, string>>({});
const activeQuizIndex = ref(0);
const activeReviewIndex = ref(0);
const isQuizLoading = ref(false);
const safetyAction = ref<SafetyAction>(null);
const messageSeed = ref(1);
const knowledgeMessageSeed = ref(2);

// --- Sprint 3: Voice ASR (Speech Recognition) ---
const xfWs = ref<WebSocket | null>(null);
const isRecording = ref(false);
const xfRecognizedText = ref("");
const xfRecognizing = ref(false);
const voiceError = ref("");
let xfAudioContext: AudioContext | null = null;
let xfMediaStream: MediaStream | null = null;
let xfScriptProcessor: ScriptProcessorNode | null = null;
let xfSourceNode: MediaStreamAudioSourceNode | null = null;

// --- Sprint 3: Share Card ---
const shareCardVisible = ref(false);
const shareCardData = ref<ShareCardData | null>(null);
const shareCardCopied = ref(false);
const shareCardSaving = ref(false);

// --- Sprint 3: Feedback ---
const feedbackVisible = ref(false);
const feedbackTargetType = ref<"assistant_message" | "knowledge_answer" | "test_result">("assistant_message");
const feedbackTargetId = ref<string>("");
const feedbackRating = ref(0);
const feedbackNote = ref("");
const isFeedbackSubmitting = ref(false);
const feedbackDone = ref(false);

// --- Sprint 3: Weekly Summary ---
const weeklySummary = ref<WeeklySummaryResponse | null>(null);
const isWeeklySummaryLoading = ref(false);
const isWeeklySummaryOpen = ref(false);
const messageListRef = ref<HTMLElement | null>(null);
const knowledgeListRef = ref<HTMLElement | null>(null);
const demoMessagesByThread = ref<Record<string, ChatMessage[]>>({});
const demoMoodLogs = ref<LocalMoodLog[]>([]);

const apiClient = new ApiClient({
  baseUrl: apiBaseUrl,
  getAccessToken: () => accessToken.value || undefined,
  onUnauthorized: refreshAccessToken,
});
const api = new CounselingApi(apiClient);

const isTeenMode = computed(() => selectedAge.value === "13-15" || selectedAge.value === "16-17");
const modeLabel = computed(() => (isDemoMode.value ? "演示模式" : isTeenMode.value ? "青少年模式" : "标准模式"));
const userName = computed(() => username.value || "朋友");
const selectedAgeLabel = computed(() => ageOptions.find((option) => option.id === selectedAge.value)?.label ?? "未设置");
const selectedStyleLabel = computed(
  () => styleOptions.find((option) => option.id === selectedStyle.value)?.label ?? "未设置",
);
const selectedGoalLabel = computed(() => goalOptions.find((option) => option.id === selectedGoal.value)?.label ?? "未设置");
const memoryModeLabel = computed(() => memoryModeOptions.find((option) => option.id === currentMemoryMode.value)?.label ?? "只记摘要");
const privacyCounts = computed(() => privacySummary.value?.data_counts ?? {
  memories: memories.value.length,
  chat_threads: threads.value.length,
  chat_messages: messages.value.length,
  mood_logs: moodTrendPoints.value.length,
  test_history: testHistory.value.length,
  feedback: 0,
  voice_sessions: 0,
  risk_events: 0,
});
const privacyLatestActivity = computed(() =>
  privacySummary.value?.latest_activity_at ? formatMemoryDocumentTimestamp(privacySummary.value.latest_activity_at) : "暂无记录",
);
const canSubmitAuth = computed(
  () =>
    Boolean(authUsername.value.trim()) &&
    authPassword.value.length >= 6 &&
    Boolean(captchaId.value) &&
    Boolean(captchaCode.value.trim()),
);
const canSubmitMood = computed(
  () =>
    [moodDraft.value.mood_score, moodDraft.value.anxiety_score, moodDraft.value.energy_score, moodDraft.value.sleep_quality]
      .every((score) => typeof score === "number" && score >= 1 && score <= 5) && !isMoodSubmitting.value,
);
const canContinueOnboarding = computed(() => Boolean(selectedStyle.value && selectedGoal.value));
const shouldShowKnowledgePrompts = computed(() => !knowledgeMessages.value.some((message) => message.role === "user"));
const currentQuizQuestion = computed<KnowledgeQuizQuestion | null>(
  () => quizSession.value?.questions[activeQuizIndex.value] ?? null,
);
const quizAnsweredCount = computed(() => Object.keys(quizAnswers.value).length);
const quizProgressPercent = computed(() =>
  quizSession.value ? Math.round((quizAnsweredCount.value / quizSession.value.total) * 100) : 0,
);
const canSubmitQuiz = computed(() => Boolean(quizSession.value && quizAnsweredCount.value === quizSession.value.total));
const quizWrongCount = computed(() => quizResult.value?.review.filter((item) => !item.is_correct).length ?? 0);
const activeReviewItem = computed(() => quizResult.value?.review[activeReviewIndex.value] ?? null);
const activeThread = computed(() => threads.value.find((thread) => thread.thread_id === activeThreadId.value) ?? null);
const visibleThreads = computed(() => {
  let hasReusableNewThread = false;
  return threads.value.filter((thread) => {
    if (!isReusableNewThread(thread)) return true;
    if (hasReusableNewThread) return false;
    hasReusableNewThread = true;
    return true;
  });
});
const filteredThreads = computed(() => {
  const query = threadSearchQuery.value.trim().toLocaleLowerCase();
  if (!query) return visibleThreads.value;
  return visibleThreads.value.filter((thread) => {
    const searchable = `${thread.title} ${thread.last_summary ?? ""}`.toLocaleLowerCase();
    return searchable.includes(query);
  });
});
const latestSummary = computed(() => activeThread.value?.last_summary || "可以从此刻最明显的感受开始。");
const testHeaderTitle = computed(() => {
  if (testView.value !== "result" || !testResult.value) return testView.value === "taking" && currentTest.value ? currentTest.value.title : "测试中心";
  return testResult.value.result_title;
});
const moodSummary = computed(() => moodTrend.value?.summary || "还没有足够的状态数据，先从今天开始记录。");
const moodTrendPoints = computed(() => moodTrend.value?.daily ?? []);
const moodTrendTags = computed(() => moodTrend.value?.top_tags ?? []);
const hasTodayMoodLog = computed(() => moodTrendPoints.value.some((point) => point.date === toMoodDateKey(new Date())));
const contextText = computed(() =>
  [
    activeThread.value?.title,
    activeThread.value?.last_summary,
    ...messages.value.slice(-6).map((message) => message.text),
  ]
    .filter(Boolean)
    .join(" "),
);

watch(
  () => messages.value.map((message) => `${message.id}:${message.text}`).join("\n"),
  async () => {
    await nextTick();
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight;
    }
  },
);

watch(
  () => knowledgeMessages.value.map((message) => `${message.id}:${message.text}`).join("\n"),
  async () => {
    await nextTick();
    if (knowledgeListRef.value) {
      knowledgeListRef.value.scrollTop = knowledgeListRef.value.scrollHeight;
    }
  },
);

watch([selectedStyle, selectedGoal], ([style, goal]) => {
  style ? localStorage.setItem(STYLE_KEY, style) : localStorage.removeItem(STYLE_KEY);
  goal ? localStorage.setItem(GOAL_KEY, goal) : localStorage.removeItem(GOAL_KEY);
});

watch(activeTab, (tab) => {

  // 这里单独给演示模式做了一个分支，后续看看能不能合并

  if (tab !== "chat") closeThreadDrawer();
  if (tab === "tests" && testItems.value.length === 0) {
    if (isDemoMode.value || !accessToken.value) {
      testItems.value = demoTests;
    } else {
      void loadTestList();
    }
  }
  if (tab === "knowledge" && knowledgeItems.value.length === 0) {
    void searchKnowledge();
  }
  if (tab === "knowledge" && !quizStats.value) {
    void loadKnowledgeQuizStats();
  }
});

watch(authMode, () => {
  authError.value = "";
  captchaCode.value = "";
  void refreshCaptcha();
});

function toAgeRange(age: AgeOptionId | null): AgeRange {
  if (age === "13-15") return "13_15";
  if (age === "16-17") return "16_17";
  return "18_plus";
}

function applyAgeRange(ageRange: AgeRange) {
  selectedAge.value = ageRange === "13_15" ? "13-15" : ageRange === "16_17" ? "16-17" : "18-24";
  authSelectedAge.value = selectedAge.value;
}

function selectedUserMode(): UserMode {
  return isTeenMode.value ? "teen" : "adult";
}

function clearApiFeedback() {
  apiError.value = "";
  apiNotice.value = "";
}

function moodValueText(value?: number | null) {
  const labels = ["很低", "偏低", "一般", "还好", "很好"];
  return labels[Math.max(1, Math.min(5, value ?? 3)) - 1];
}

function formatMoodDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(value));
}

function toMoodDateKey(value: Date) {
  return value.toISOString().slice(0, 10);
}

function moodPointHeight(score: number) {
  return `${Math.max(10, Math.min(58, (score / 5) * 58))}px`;
}

function toggleMoodTag(tag: string) {
  const currentTags = moodDraft.value.mood_tags ?? [];
  moodDraft.value = {
    ...moodDraft.value,
    mood_tags: currentTags.includes(tag) ? currentTags.filter((item) => item !== tag) : [...currentTags, tag],
  };
}

function createMoodPayload(): MoodLogRequest {
  const note = moodDraft.value.note?.trim();
  return {
    mood_score: moodDraft.value.mood_score,
    anxiety_score: moodDraft.value.anxiety_score,
    energy_score: moodDraft.value.energy_score,
    sleep_quality: moodDraft.value.sleep_quality,
    mood_tags: [...(moodDraft.value.mood_tags ?? [])],
    note: note || null,
  };
}

function resetMoodDraft() {
  moodDraft.value = {
    mood_score: 3,
    anxiety_score: 3,
    energy_score: 3,
    sleep_quality: 3,
    mood_tags: [],
    note: "",
  };
}

function buildLocalMoodTrend(range: MoodRange, logs: LocalMoodLog[]): MoodTrendResponse {
  const days = range === "30d" ? 30 : 7;
  const since = Date.now() - days * dayMs;
  const scopedLogs = logs
    .filter((log) => new Date(log.created_at).getTime() >= since)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

  if (scopedLogs.length === 0) {
    return {
      range,
      avg_mood_score: 0,
      top_tags: [],
      daily: [],
      summary: "当前时间范围内还没有情绪记录。",
    };
  }

  const dailyScores = new Map<string, number[]>();
  const dailyTags = new Map<string, Map<string, number>>();
  const tagCounter = new Map<string, number>();

  scopedLogs.forEach((log) => {
    const day = new Date(log.created_at).toISOString().slice(0, 10);
    dailyScores.set(day, [...(dailyScores.get(day) ?? []), log.mood_score]);
    if (!dailyTags.has(day)) dailyTags.set(day, new Map());
    const dayTags = dailyTags.get(day);
    log.mood_tags.forEach((tag) => {
      const normalizedTag = tag.trim();
      if (!normalizedTag || !dayTags) return;
      tagCounter.set(normalizedTag, (tagCounter.get(normalizedTag) ?? 0) + 1);
      dayTags.set(normalizedTag, (dayTags.get(normalizedTag) ?? 0) + 1);
    });
  });

  const daily = [...dailyScores.entries()].map(([date, scores]) => ({
    date,
    mood_score: Number((scores.reduce((sum, score) => sum + score, 0) / scores.length).toFixed(2)),
    tags: [...(dailyTags.get(date)?.entries() ?? [])]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([tag]) => tag),
  }));
  const top_tags = [...tagCounter.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([tag]) => tag);
  const avg_mood_score = Number(
    (scopedLogs.reduce((sum, log) => sum + log.mood_score, 0) / scopedLogs.length).toFixed(2),
  );
  const summary = `最近 ${days} 天共记录 ${scopedLogs.length} 次情绪，平均情绪分为 ${avg_mood_score}。${
    top_tags.length ? ` 高频标签主要是：${top_tags.slice(0, 3).join("、")}。` : ""
  }`;

  return { range, avg_mood_score, top_tags, daily, summary };
}

function formatTime(value?: string | null) {
  if (!value) return "刚刚";
  const time = new Date(value).getTime();
  const diff = Date.now() - time;
  const hour = 60 * 60 * 1000;
  const day = 24 * hour;
  if (diff < hour) return "刚刚";
  if (diff < day) return `${Math.round(diff / hour)} 小时前`;
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(value));
}

function riskLabel(level?: RiskLevel | null) {
  if (level === "L3") return "立即支持";
  if (level === "L2") return "需要陪伴";
  if (level === "L1") return "多一点支持";
  return "平稳";
}

function riskClass(level?: RiskLevel | null) {
  if (level === "L3") return "risk--critical";
  if (level === "L2") return "risk--warning";
  if (level === "L1") return "risk--watch";
  return "risk--steady";
}

function normalizeRiskLevel(value: unknown): RiskLevel | null {
  return value === "L0" || value === "L1" || value === "L2" || value === "L3" ? value : null;
}

function normalizeStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function normalizeMemoryReferences(value: unknown): MemoryReference[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => isObjectRecord(item))
    .map((item) => ({
      memory_id: String(item.memory_id ?? ""),
      memory_type: String(item.memory_type ?? ""),
      content: String(item.content ?? "").trim(),
    }))
    .filter((item) => Boolean(item.memory_id && item.content));
}

function memoryTypeLabel(type: string) {
  const labels: Record<string, string> = {
    session_summary: "对话摘要",
    preference: "陪伴偏好",
    recurring_trigger: "触发点",
    support_strategy: "支持方式",
    state: "长期状态",
    relationship: "关系记忆",
  };
  return labels[type] ?? "记忆";
}

function graphStatusLabel(node?: string | null) {
  if (node === "risk_classifier") return "正在识别风险";
  if (node === "intent_classifier") return "正在理解意图";
  if (node === "memory_retrieval") return "正在整理上下文";
  if (node === "summary_memory_node") return "正在整理摘要";
  if (node) return "正在推进对话";
  return "";
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object");
}

function isTokenEventData(data: unknown): data is ChatStreamTokenEvent {
  return isObjectRecord(data) && typeof data.text === "string";
}

function isGraphUpdateEventData(data: unknown): data is ChatStreamGraphUpdateEvent {
  return isObjectRecord(data) && typeof data.node === "string";
}

function isFinalEventData(data: unknown): data is ChatStreamFinalEvent {
  return isObjectRecord(data) && typeof data.assistant_text === "string" && normalizeRiskLevel(data.risk_level) !== null;
}

function sortThreads(items: ThreadListItem[]) {
  return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
}

function setMessages(items: ChatMessage[]) {
  messages.value = items.map((message, index) => ({ ...message, id: index + 1 }));
  messageSeed.value = messages.value.length + 1;
}

function persistAuth(payload: { user_id: string; access_token: string; refresh_token: string }) {
  accessToken.value = payload.access_token;
  refreshToken.value = payload.refresh_token;
  currentUserId.value = payload.user_id;
  localStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token);
  localStorage.setItem(REFRESH_TOKEN_KEY, payload.refresh_token);
  localStorage.setItem(USER_ID_KEY, payload.user_id);
}

function clearSession() {
  accessToken.value = "";
  refreshToken.value = "";
  currentUserId.value = "";
  username.value = "";
  activeThreadId.value = "";
  currentMemoryMode.value = "summary_only";
  saveVoiceAudio.value = false;
  saveTranscript.value = true;
  isMemoryDocOpen.value = false;
  isMemoryDocLoading.value = false;
  memoryDocContent.value = "";
  memoryDocError.value = "";
  memoryError.value = "";
  isThreadDrawerOpen.value = false;
  threadSearchQuery.value = "";
  isCreatingThread.value = false;
  privacySummary.value = null;
  privacyExportPreview.value = "";
  privacyExportData.value = null;
  isPrivacyExportOpen.value = false;
  privacyError.value = "";
  privacyNotice.value = "";
  pendingPrivacyScope.value = null;
  deleteAccountConfirm.value = "";
  [ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY, USER_ID_KEY, USERNAME_KEY, THREAD_ID_KEY].forEach((key) => localStorage.removeItem(key));
}

async function refreshCaptcha() {
  if (isDemoMode.value) return;
  try {
    isCaptchaLoading.value = true;
    const captcha = await api.getCaptcha();
    captchaId.value = captcha.captcha_id;
    captchaImageDataUrl.value = captcha.image_data_url;
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "验证码加载失败。";
  } finally {
    isCaptchaLoading.value = false;
  }
}

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshToken.value) return false;
  const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken.value }),
  });
  if (!response.ok) {
    clearSession();
    return false;
  }
  persistAuth((await response.json()) as { user_id: string; access_token: string; refresh_token: string });
  return true;
}

function mapMessage(item: MessageItem): ChatMessage | null {
  if (item.role !== "assistant" && item.role !== "user") return null;
  return {
    id: 0,
    role: item.role,
    text: item.content,
    createdAt: item.created_at,
    riskLevel: item.risk_level,
    suggestedActions: normalizeStringList(item.metadata.suggested_actions),
    referencedMemories: normalizeMemoryReferences(item.metadata.referenced_memories),
  };
}

async function loadThreadMessages(threadId: string) {
  if (!threadId) {
    setMessages([]);
    return;
  }
  if (isDemoMode.value || threadId.startsWith("local-")) {
    setMessages(demoMessagesByThread.value[threadId] ?? []);
    return;
  }
  const response = await api.listMessages(threadId);
  setMessages(response.items.map(mapMessage).filter((item): item is ChatMessage => Boolean(item)));
}

async function loadApp() {
  if (!accessToken.value) {
    stage.value = "auth";
    return;
  }
  try {
    isLoadingApp.value = true;
    const [user, threadList, memoryList, mood, privacy] = await Promise.all([
      api.getCurrentUser(),
      api.listThreads(),
      api.listMemories(),
      api.getMoodTrend(moodRange.value),
      api.getPrivacySummary(),
    ]);
    username.value = user.nickname || user.username;
    localStorage.setItem(USERNAME_KEY, username.value);
    applyAgeRange(user.age_range);
    currentMemoryMode.value = user.memory_mode;
    saveVoiceAudio.value = user.save_voice_audio;
    saveTranscript.value = user.save_transcript;
    privacySummary.value = privacy;
    if (styleOptions.some((option) => option.id === user.companion_style)) {
      selectedStyle.value = user.companion_style;
    }
    threads.value = sortThreads(threadList.items);
    memories.value = memoryList.items;
    memoryError.value = "";
    privacyError.value = "";
    moodTrend.value = mood;
    activeThreadId.value = activeThreadId.value || threads.value[0]?.thread_id || "";
    if (activeThreadId.value) {
      localStorage.setItem(THREAD_ID_KEY, activeThreadId.value);
      await loadThreadMessages(activeThreadId.value);
    }
    stage.value = selectedStyle.value && selectedGoal.value ? "app" : "onboarding";
  } catch (error) {
    clearSession();
    authError.value = error instanceof Error ? error.message : "登录状态已失效，请重新登录。";
    stage.value = "auth";
    await refreshCaptcha();
  } finally {
    isLoadingApp.value = false;
  }
}

async function refreshMemories() {
  if (isDemoMode.value || !accessToken.value) return;
  const memoryList = await api.listMemories();
  memories.value = memoryList.items;
}

function buildLocalPrivacySummary(): PrivacySummaryResponse {
  return {
    user_id: currentUserId.value || "demo-user",
    user_mode: isTeenMode.value ? "teen" : "adult",
    settings: {
      memory_mode: currentMemoryMode.value,
      voice_enabled: true,
      save_voice_audio: saveVoiceAudio.value,
      save_transcript: saveTranscript.value,
    },
    data_counts: {
      memories: memories.value.length,
      chat_threads: threads.value.length,
      chat_messages: Object.values(demoMessagesByThread.value).reduce((count, items) => count + items.length, 0),
      mood_logs: demoMoodLogs.value.length,
      test_history: testHistory.value.length,
      feedback: 0,
      voice_sessions: 0,
      risk_events: 0,
    },
    latest_activity_at: new Date().toISOString(),
  };
}

async function refreshPrivacySummary() {
  if (isDemoMode.value || !accessToken.value) {
    privacySummary.value = buildLocalPrivacySummary();
    return;
  }
  try {
    privacySummary.value = await api.getPrivacySummary();
    privacyError.value = "";
  } catch (error) {
    privacyError.value = error instanceof Error ? error.message : "隐私数据加载失败。";
  }
}

async function changeMemoryMode(mode: MemoryMode) {
  if (mode === currentMemoryMode.value || isSettingsSaving.value) return;
  const previousMode = currentMemoryMode.value;
  currentMemoryMode.value = mode;
  memoryError.value = "";
  if (isDemoMode.value || !accessToken.value) {
    apiNotice.value = `记忆模式已切换为${memoryModeLabel.value}。`;
    return;
  }

  try {
    isSettingsSaving.value = true;
    const response = await api.updateSettings({ memory_mode: mode });
    currentMemoryMode.value = response.memory_mode;
    saveVoiceAudio.value = response.save_voice_audio;
    saveTranscript.value = response.save_transcript;
    await refreshPrivacySummary();
    apiNotice.value = `记忆模式已切换为${memoryModeLabel.value}。`;
  } catch (error) {
    currentMemoryMode.value = previousMode;
    memoryError.value = error instanceof Error ? error.message : "记忆模式更新失败。";
  } finally {
    isSettingsSaving.value = false;
  }
}

function formatMemoryDocumentTimestamp(value: Date | string) {
  const date = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatMarkdownBullet(content: string) {
  const normalized = content.trim().replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized ? normalized.split("\n") : ["(空)"];
  return [`- ${lines[0]}`, ...lines.slice(1).map((line) => `  ${line}`)];
}

function buildMemoryDocumentMarkdown(items: MemoryItem[]) {
  const lines = ["# 记忆文档", "", `生成时间：${formatMemoryDocumentTimestamp(new Date())}`, `记忆模式：${memoryModeLabel.value}`, ""];
  if (items.length === 0) {
    lines.push("当前没有可见记忆。");
    return `${lines.join("\n")}\n`;
  }

  const grouped = new Map<string, MemoryItem[]>();
  items.forEach((item) => {
    grouped.set(item.memory_type, [...(grouped.get(item.memory_type) ?? []), item]);
  });

  const knownOrder = ["session_summary", "preference", "recurring_trigger", "support_strategy", "state", "relationship", "safety_summary"];
  const knownTypes = knownOrder.filter((type) => grouped.has(type));
  const unknownTypes = [...grouped.keys()].filter((type) => !knownOrder.includes(type)).sort();

  [...knownTypes, ...unknownTypes].forEach((type) => {
    const list = grouped.get(type) ?? [];
    if (list.length === 0) return;
    lines.push(`## ${memoryTypeLabel(type)}`);
    list
      .slice()
      .sort((a, b) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime())
      .forEach((item) => {
        lines.push(...formatMarkdownBullet(item.content));
        lines.push(`  - 更新时间：${formatMemoryDocumentTimestamp(item.updated_at || item.created_at || new Date())}`);
      });
    lines.push("");
  });

  return `${lines.join("\n").trim()}\n`;
}

async function fetchMemoryDocument() {
  memoryDocError.value = "";
  if (isDemoMode.value || !accessToken.value) {
    return buildMemoryDocumentMarkdown(memories.value);
  }
  try {
    return await api.getMemoryDocument();
  } catch (error) {
    memoryDocError.value = error instanceof Error ? error.message : "记忆文档加载失败。";
    return "";
  }
}

async function openMemoryDocument() {
  if (isMemoryDocLoading.value) return;
  isMemoryDocOpen.value = true;
  isMemoryDocLoading.value = true;
  memoryDocContent.value = "";
  const content = await fetchMemoryDocument();
  memoryDocContent.value = content;
  isMemoryDocLoading.value = false;
}

function closeMemoryDocument() {
  isMemoryDocOpen.value = false;
  memoryDocError.value = "";
  memoryDocContent.value = "";
}

async function downloadMemoryDocument() {
  if (isMemoryDocLoading.value) return;
  let content = memoryDocContent.value;
  if (!content) {
    isMemoryDocLoading.value = true;
    content = await fetchMemoryDocument();
    isMemoryDocLoading.value = false;
    memoryDocContent.value = content;
  }
  if (!content) return;
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `memories-${new Date().toISOString().slice(0, 10)}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function buildPrivacyExportMarkdown(data: PersonalDataExport | null) {
  const summary = privacySummary.value ?? buildLocalPrivacySummary();
  const counts = summary.data_counts;
  const lines = [
    "# 个人数据摘要",
    "",
    `生成时间：${formatMemoryDocumentTimestamp(new Date())}`,
    `用户模式：${summary.user_mode === "teen" ? "青少年模式" : "标准模式"}`,
    "",
    "## 保存设置",
    `- 记忆模式：${memoryModeLabel.value}`,
    `- 保存语音转写：${saveTranscript.value ? "开启" : "关闭"}`,
    `- 保存原始音频：${saveVoiceAudio.value ? "开启" : "关闭"}`,
    "",
    "## 数据数量",
    `- 可见记忆：${counts.memories}`,
    `- 会话：${counts.chat_threads}`,
    `- 消息：${counts.chat_messages}`,
    `- 情绪记录：${counts.mood_logs}`,
    `- 测试历史：${counts.test_history}`,
    `- 反馈记录：${counts.feedback}`,
    `- 语音会话：${counts.voice_sessions}`,
    `- 安全事件：${counts.risk_events}`,
  ];
  if (data) {
    lines.push("", "JSON 导出已准备好，下载文件中包含更完整的个人数据。");
  }
  return `${lines.join("\n")}\n`;
}

function buildDemoPersonalDataExport(): PersonalDataExport {
  return {
    exported_at: new Date().toISOString(),
    account: { user_id: currentUserId.value || "demo-user", username: username.value, status: "demo" },
    profile: { nickname: username.value, user_mode: isTeenMode.value ? "teen" : "adult" },
    settings: {
      memory_mode: currentMemoryMode.value,
      save_voice_audio: saveVoiceAudio.value,
      save_transcript: saveTranscript.value,
    },
    memories: memories.value,
    chat_threads: threads.value,
    mood_logs: demoMoodLogs.value,
    test_history: testHistory.value,
    feedback: [],
    voice_sessions: [],
  };
}

async function openPrivacyExport() {
  if (isPrivacyLoading.value) return;
  isPrivacyLoading.value = true;
  privacyError.value = "";
  privacyNotice.value = "";
  try {
    const data = isDemoMode.value || !accessToken.value ? buildDemoPersonalDataExport() : await api.exportPersonalData();
    privacyExportData.value = data;
    privacyExportPreview.value = buildPrivacyExportMarkdown(data);
    isPrivacyExportOpen.value = true;
    await refreshPrivacySummary();
  } catch (error) {
    privacyError.value = error instanceof Error ? error.message : "个人数据导出失败。";
  } finally {
    isPrivacyLoading.value = false;
  }
}

function closePrivacyExport() {
  isPrivacyExportOpen.value = false;
}

function downloadPrivacyJson() {
  const data = privacyExportData.value ?? buildDemoPersonalDataExport();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `personal-data-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function reloadPrivacyAffectedData() {
  if (isDemoMode.value || !accessToken.value) {
    privacySummary.value = buildLocalPrivacySummary();
    return;
  }
  const [threadList, memoryList, mood] = await Promise.all([
    api.listThreads(),
    api.listMemories(),
    api.getMoodTrend(moodRange.value),
  ]);
  threads.value = sortThreads(threadList.items);
  memories.value = memoryList.items;
  moodTrend.value = mood;
  if (!threads.value.some((thread) => thread.thread_id === activeThreadId.value)) {
    activeThreadId.value = threads.value[0]?.thread_id ?? "";
    if (activeThreadId.value) localStorage.setItem(THREAD_ID_KEY, activeThreadId.value);
    else localStorage.removeItem(THREAD_ID_KEY);
  }
  if (activeThreadId.value) await loadThreadMessages(activeThreadId.value);
  else setMessages([]);
  await refreshPrivacySummary();
}

async function deletePrivacyScope(scope: PrivacyDataScope) {
  if (pendingPrivacyScope.value !== scope) {
    pendingPrivacyScope.value = scope;
    privacyNotice.value = "再次点击同一按钮确认清除。";
    privacyError.value = "";
    return;
  }

  isPrivacyLoading.value = true;
  privacyError.value = "";
  privacyNotice.value = "";
  try {
    if (isDemoMode.value || !accessToken.value) {
      if (scope === "memories" || scope === "all_non_account") memories.value = [];
      if (scope === "chat" || scope === "all_non_account") {
        threads.value = [];
        demoMessagesByThread.value = {};
        activeThreadId.value = "";
        setMessages([]);
      }
      if (scope === "moods" || scope === "all_non_account") {
        demoMoodLogs.value = [];
        moodTrend.value = buildLocalMoodTrend(moodRange.value, []);
      }
      privacyNotice.value = "演示数据已清除。";
    } else {
      const response = await api.deletePersonalData({ scope });
      const total = Object.values(response.affected_counts).reduce((sum, count) => sum + count, 0);
      privacyNotice.value = `已清除 ${total} 项数据。`;
      await reloadPrivacyAffectedData();
    }
  } catch (error) {
    privacyError.value = error instanceof Error ? error.message : "数据清除失败。";
  } finally {
    pendingPrivacyScope.value = null;
    isPrivacyLoading.value = false;
    await refreshPrivacySummary();
  }
}

async function updatePrivacySetting(payload: { save_voice_audio?: boolean; save_transcript?: boolean }) {
  if (isSettingsSaving.value) return;
  const previousSaveAudio = saveVoiceAudio.value;
  const previousSaveTranscript = saveTranscript.value;
  if (typeof payload.save_voice_audio === "boolean") saveVoiceAudio.value = payload.save_voice_audio;
  if (typeof payload.save_transcript === "boolean") saveTranscript.value = payload.save_transcript;
  privacyError.value = "";

  if (isDemoMode.value || !accessToken.value) {
    if (isTeenMode.value) saveVoiceAudio.value = false;
    privacySummary.value = buildLocalPrivacySummary();
    return;
  }

  try {
    isSettingsSaving.value = true;
    const response = await api.updateSettings(payload);
    saveVoiceAudio.value = response.save_voice_audio;
    saveTranscript.value = response.save_transcript;
    currentMemoryMode.value = response.memory_mode;
    await refreshPrivacySummary();
  } catch (error) {
    saveVoiceAudio.value = previousSaveAudio;
    saveTranscript.value = previousSaveTranscript;
    privacyError.value = error instanceof Error ? error.message : "隐私设置更新失败。";
  } finally {
    isSettingsSaving.value = false;
  }
}

async function deleteCurrentAccount() {
  if (deleteAccountConfirm.value !== "DELETE" || isPrivacyLoading.value) return;
  isPrivacyLoading.value = true;
  privacyError.value = "";
  try {
    if (!isDemoMode.value && accessToken.value) {
      await api.deleteAccount({ confirmation: "DELETE" });
    }
    clearSession();
    isDemoMode.value = false;
    selectedAge.value = null;
    selectedStyle.value = null;
    selectedGoal.value = null;
    threads.value = [];
    memories.value = [];
    moodTrend.value = null;
    demoMoodLogs.value = [];
    setMessages([]);
    stage.value = "auth";
    await refreshCaptcha();
  } catch (error) {
    privacyError.value = error instanceof Error ? error.message : "账号注销失败。";
  } finally {
    isPrivacyLoading.value = false;
  }
}

function toggleMemoryReferences(messageId: number) {
  messages.value = messages.value.map((message) =>
    message.id === messageId ? { ...message, memoryRefsExpanded: !message.memoryRefsExpanded } : message,
  );
}

async function loadMoodTrend(range: MoodRange = moodRange.value) {
  moodRange.value = range;
  if (isDemoMode.value || !accessToken.value) {
    moodTrend.value = demoMoodLogs.value.length > 0 ? buildLocalMoodTrend(range, demoMoodLogs.value) : { ...demoMoodTrend, range };
    return;
  }

  try {
    isMoodTrendLoading.value = true;
    moodTrend.value = await api.getMoodTrend(range);
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "情绪趋势加载失败。";
  } finally {
    isMoodTrendLoading.value = false;
  }
}

async function switchMoodRange(range: MoodRange) {
  if (range === moodRange.value && moodTrend.value?.range === range) return;
  await loadMoodTrend(range);
}

async function submitMoodCheckIn() {
  if (!canSubmitMood.value) return;
  try {
    isMoodSubmitting.value = true;
    clearApiFeedback();
    const payload = createMoodPayload();

    if (isDemoMode.value || !accessToken.value) {
      demoMoodLogs.value = [
        ...demoMoodLogs.value,
        {
          created_at: new Date().toISOString(),
          mood_score: payload.mood_score,
          mood_tags: payload.mood_tags ?? [],
        },
      ];
      apiNotice.value = "今日状态已记录。";
      resetMoodDraft();
      await loadMoodTrend(moodRange.value);
      await refreshPrivacySummary();
      return;
    }

    await api.createMoodLog(payload);
    apiNotice.value = "今日状态已记录。";
    resetMoodDraft();
    await loadMoodTrend(moodRange.value);
    await refreshPrivacySummary();
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "情绪记录提交失败。";
  } finally {
    isMoodSubmitting.value = false;
  }
}

async function submitAuth() {
  if (!canSubmitAuth.value || isAuthenticating.value) return;
  try {
    isAuthenticating.value = true;
    authError.value = "";
    const authPayload = {
      username: authUsername.value.trim(),
      password: authPassword.value,
      captcha_id: captchaId.value,
      captcha_code: captchaCode.value.trim(),
    };
    if (authMode.value === "register") {
      const response = await api.register({ ...authPayload, age_range: toAgeRange(authSelectedAge.value) });
      persistAuth(response);
      username.value = authPayload.username;
      selectedAge.value = authSelectedAge.value;
      stage.value = "onboarding";
    } else {
      const response = await api.login(authPayload);
      persistAuth(response);
      await loadApp();
    }
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "认证失败，请检查输入。";
    captchaCode.value = "";
    await refreshCaptcha();
  } finally {
    isAuthenticating.value = false;
  }
}

function enterDemoMode() {
  isDemoMode.value = true;
  username.value = "小林";
  selectedAge.value = "18-24";
  selectedStyle.value ||= "gentle";
  selectedGoal.value ||= "anxiety";
  currentMemoryMode.value = "summary_only";
  saveVoiceAudio.value = false;
  saveTranscript.value = true;
  memoryError.value = "";
  privacyError.value = "";
  privacyNotice.value = "";
  isMemoryDocOpen.value = false;
  isMemoryDocLoading.value = false;
  memoryDocContent.value = "";
  memoryDocError.value = "";
  threads.value = sortThreads(demoThreads.map((thread) => ({ ...thread })));
  demoMessagesByThread.value = Object.fromEntries(Object.entries(demoMessages).map(([key, value]) => [key, [...value]]));
  memories.value = demoMemories.map((item) => ({ ...item }));
  demoMoodLogs.value = demoMoodLogSeed.map((item) => ({ ...item }));
  moodTrend.value = buildLocalMoodTrend(moodRange.value, demoMoodLogs.value);
  activeThreadId.value = threads.value[0]?.thread_id ?? "";
  setMessages(demoMessagesByThread.value[activeThreadId.value] ?? []);
  privacySummary.value = buildLocalPrivacySummary();
  stage.value = "onboarding";
}

function finishOnboarding(skip = false) {
  if (!skip && !canContinueOnboarding.value) return;
  stage.value = "app";
  activeTab.value = "home";
}

async function selectThread(threadId: string) {
  activeThreadId.value = threadId;
  localStorage.setItem(THREAD_ID_KEY, threadId);
  activeTab.value = "chat";
  await loadThreadMessages(threadId);
  quickActions.value = [...fallbackQuickActions];
}

function openThreadDrawer() {
  activeTab.value = "chat";
  isThreadDrawerOpen.value = true;
}

function closeThreadDrawer() {
  isThreadDrawerOpen.value = false;
  threadSearchQuery.value = "";
}

async function selectThreadFromDrawer(threadId: string) {
  await selectThread(threadId);
  closeThreadDrawer();
}

function isReusableNewThread(thread: ThreadListItem) {
  return thread.title.trim() === NEW_THREAD_TITLE && !thread.last_summary?.trim();
}

function findReusableNewThread() {
  return threads.value.find(isReusableNewThread);
}

async function createThread(title = NEW_THREAD_TITLE) {
  if (isDemoMode.value || !accessToken.value) {
    const threadId = `local-${Date.now()}`;
    threads.value = sortThreads([
      {
        thread_id: threadId,
        title,
        mode: "companion",
        last_summary: null,
        last_risk_level: "L0",
        updated_at: new Date().toISOString(),
      },
      ...threads.value,
    ]);
    demoMessagesByThread.value = { ...demoMessagesByThread.value, [threadId]: [] };
    activeThreadId.value = threadId;
    setMessages([]);
    return;
  }
  const thread = await api.startThread({ mode: "companion", title });
  threads.value = sortThreads([
    {
      thread_id: thread.thread_id,
      title: thread.title,
      mode: thread.mode,
      last_summary: null,
      last_risk_level: "L0",
      updated_at: thread.updated_at,
    },
    ...threads.value,
  ]);
  activeThreadId.value = thread.thread_id;
  localStorage.setItem(THREAD_ID_KEY, thread.thread_id);
  setMessages([]);
}

async function createChatThread() {
  if (isCreatingThread.value) return;
  try {
    isCreatingThread.value = true;
    clearApiFeedback();
    composerText.value = "";
    const reusableThread = findReusableNewThread();
    if (reusableThread) {
      await selectThread(reusableThread.thread_id);
    } else {
      await createThread();
    }
    quickActions.value = [...fallbackQuickActions];
    threadSearchQuery.value = "";
    activeTab.value = "chat";
    closeThreadDrawer();
  } catch (error) {
    apiError.value = error instanceof Error ? `新建会话失败：${error.message}` : "新建会话失败。";
  } finally {
    isCreatingThread.value = false;
  }
}

function addMessage(role: ChatRole, text: string, riskLevel: RiskLevel | null = null, streaming = false) {
  const id = messageSeed.value;
  messages.value = [...messages.value, { id, role, text, riskLevel, streaming, createdAt: new Date().toISOString() }];
  messageSeed.value += 1;
  return id;
}

function updateMessage(id: number, patch: Partial<Omit<ChatMessage, "id">>) {
  messages.value = messages.value.map((message) => (message.id === id ? { ...message, ...patch } : message));
}

function appendMessageText(id: number, text: string) {
  messages.value = messages.value.map((message) =>
    message.id === id ? { ...message, text: `${message.text}${text}` } : message,
  );
}

function inferRisk(message: string): RiskLevel | null {
  if (message.includes("自杀") || message.includes("不想活") || message.includes("结束自己")) return "L3";
  if (message.includes("不安全") || message.includes("撑不住") || message.includes("伤害自己")) return "L2";
  if (message.includes("崩溃") || message.includes("绝望")) return "L1";
  return null;
}

const fallbackQuickActions = ["继续听我说", "帮我理一理", "先听我说完"];

function buildReply(message: string) {
  if (message.includes("睡")) return "睡不好的时候，很多情绪都会被放大。我们先不急着解决全部，只分开看看：是入睡难、半夜醒，还是醒来后很累？";
  if (message.includes("焦虑") || message.includes("慌")) return "焦虑来的时候，身体常常比想法更快。我们先让身体退一步，再看事情本身。";
  if (message.includes("关系") || message.includes("家人")) return "关系里的难受，通常不只是一句话，而是那句话碰到了你很在意的东西。你最怕哪种感受被忽略？";
  if (message.includes("呼吸")) return "现在先把注意力放回身体。吸气四拍，停一拍，呼气六拍。先做三轮，不用追求标准。";
  return "我在这里。你不用一下子说得很完整，先把压在胸口最重的那一小块说出来就够了。";
}

function syncLocalThread(summary: string, risk: RiskLevel | null) {
  if (!activeThreadId.value) return;
  threads.value = sortThreads(
    threads.value.map((thread) =>
      thread.thread_id === activeThreadId.value
        ? { ...thread, last_summary: summary, last_risk_level: risk ?? thread.last_risk_level, updated_at: new Date().toISOString() }
        : thread,
    ),
  );
  demoMessagesByThread.value = { ...demoMessagesByThread.value, [activeThreadId.value]: messages.value.map((message) => ({ ...message })) };
}

function applySendMessageResponse(assistantId: number, userContent: string, response: SendMessageResponse) {
  const assistant = response.assistant_message;
  const risk = normalizeRiskLevel(assistant.risk_level) ?? "L0";
  const reply = assistant.assistant_text || assistant.content;
  const actions = assistant.suggested_actions.length ? assistant.suggested_actions : fallbackQuickActions;
  updateMessage(assistantId, {
    text: reply,
    riskLevel: risk,
    graphNode: null,
    suggestedActions: actions,
    referencedMemories: assistant.referenced_memories ?? [],
    streaming: false,
    streamError: false,
  });
  quickActions.value = actions.slice(0, 3);
  syncLocalThread(reply, risk);
  if (assistant.should_write_memory) void refreshMemories();
  if (risk === "L2" || risk === "L3") openSafety();
}

async function submitMessage(text = composerText.value) {
  const content = text.trim();
  if (!content || isSending.value) return;
  composerText.value = "";
  clearApiFeedback();
  activeTab.value = "chat";
  if (!activeThreadId.value) await createThread(content.slice(0, 12) || "新的对话");
  addMessage("user", content);
  const localRisk = inferRisk(content);
  quickActions.value = [...fallbackQuickActions];

  if (isDemoMode.value || !accessToken.value || activeThreadId.value.startsWith("local-")) {
    const reply = buildReply(content);
    addMessage("assistant", reply, localRisk);
    syncLocalThread(reply, localRisk);
    if (localRisk === "L2" || localRisk === "L3") openSafety();
    return;
  }

  const payload = { user_id: currentUserId.value, content, input_type: "text" as const, user_mode: selectedUserMode() };
  const assistantId = addMessage("assistant", "", null, true);
  let streamed = "";
  let risk: RiskLevel | null = null;
  let receivedStreamEvent = false;
  let receivedFinalEvent = false;
  try {
    isSending.value = true;
    await api.streamMessage(
      activeThreadId.value,
      payload,
      (event, data) => {
        if (event === "graph_update" && isGraphUpdateEventData(data)) {
          receivedStreamEvent = true;
          const graphRisk = normalizeRiskLevel(data.risk_level);
          risk = graphRisk ?? risk;
          updateMessage(assistantId, {
            graphNode: data.node,
            riskLevel: graphRisk ?? risk,
            streamError: false,
          });
        }

        if (event === "token" && isTokenEventData(data)) {
          receivedStreamEvent = true;
          streamed += data.text;
          appendMessageText(assistantId, data.text);
        }
        if (event === "final") {
          receivedStreamEvent = true;
          receivedFinalEvent = true;
          risk = normalizeRiskLevel(data.risk_level) ?? "L0";
          const actions = normalizeStringList(data.suggested_actions);
          const finalActions = actions.length ? actions : fallbackQuickActions;
          quickActions.value = finalActions.slice(0, 3);
          if (!streamed && isFinalEventData(data)) streamed = data.assistant_text;
          updateMessage(assistantId, {
            text: streamed,
            riskLevel: risk,
            graphNode: null,
            suggestedActions: finalActions,
            referencedMemories: normalizeMemoryReferences(data.referenced_memories),
            streaming: false,
            streamError: false,
          });
          if (Boolean(data.should_write_memory)) void refreshMemories();
        }
      },
    );

    if (receivedStreamEvent && !receivedFinalEvent) {
      apiNotice.value = "流式连接提前结束，已刷新服务端记录。";
      updateMessage(assistantId, { streaming: false, streamError: true });
      await loadThreadMessages(activeThreadId.value);
      return;
    }

    if (!receivedStreamEvent) {
      apiNotice.value = "流式连接无返回，已切换到稳定发送。";
      const response = await api.sendMessage(activeThreadId.value, payload);
      applySendMessageResponse(assistantId, content, response);
      return;
    }

    if (!streamed) {
      streamed = buildReply(content);
      updateMessage(assistantId, { text: streamed, riskLevel: risk });
    }
    syncLocalThread(streamed, risk);
    if (risk === "L2" || risk === "L3") openSafety();
  } catch (error) {
    if (receivedStreamEvent) {
      apiNotice.value = error instanceof Error ? `流式连接中断，已刷新服务端记录：${error.message}` : "流式连接中断，已刷新服务端记录。";
      updateMessage(assistantId, { streaming: false, streamError: true });
      await loadThreadMessages(activeThreadId.value);
      return;
    }

    try {
      apiNotice.value = "流式连接失败，已切换到稳定发送。";
      const response = await api.sendMessage(activeThreadId.value, payload);
      applySendMessageResponse(assistantId, content, response);
    } catch (fallbackError) {
      apiError.value =
        fallbackError instanceof Error ? `发送失败，已使用本地回复：${fallbackError.message}` : "发送失败，已使用本地回复。";
      const reply = buildReply(content);
      quickActions.value = [...fallbackQuickActions];
      updateMessage(assistantId, {
        text: reply,
        riskLevel: localRisk,
        graphNode: null,
        suggestedActions: fallbackQuickActions,
        streaming: false,
        streamError: true,
      });
      syncLocalThread(reply, localRisk);
      if (localRisk === "L2" || localRisk === "L3") openSafety();
    }
  } finally {
    updateMessage(assistantId, { streaming: false });
    isSending.value = false;
    await refreshPrivacySummary();
  }
}

async function startQuickCheckIn() {
  await createThread("我想倾诉");
  await submitMessage("我现在有点难受，想倾诉");
}

function addKnowledgeMessage(message: Omit<KnowledgeChatMessage, "id">) {
  const id = knowledgeMessageSeed.value;
  knowledgeMessages.value = [...knowledgeMessages.value, { ...message, id }];
  knowledgeMessageSeed.value += 1;
  return id;
}

function updateKnowledgeMessage(id: number, patch: Partial<KnowledgeChatMessage>) {
  knowledgeMessages.value = knowledgeMessages.value.map((message) => (message.id === id ? { ...message, ...patch } : message));
}

async function searchKnowledge(query = "焦虑") {
  try {
    isKnowledgeLoading.value = true;
    clearApiFeedback();
    const response = await api.searchKnowledge(query.trim());
    knowledgeItems.value = response.items;
    if (!response.items[0]) {
      selectedKnowledgeArticle.value = null;
    }
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "知识库加载失败。";
  } finally {
    isKnowledgeLoading.value = false;
  }
}

async function openKnowledgeArticle(articleId: string) {
  try {
    isKnowledgeLoading.value = true;
    clearApiFeedback();
    selectedKnowledgeArticle.value = await api.getKnowledgeArticle(articleId);
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "知识详情加载失败。";
  } finally {
    isKnowledgeLoading.value = false;
  }
}

function quizTypeLabel(type: KnowledgeQuizQuestion["type"]) {
  if (type === "single_choice") return "ABCD";
  if (type === "true_false") return "判断";
  return "图片题";
}

function quizAnswerLabel(question: KnowledgeQuizQuestion, answerKey: string | null | undefined) {
  if (!answerKey) return "未作答";
  return question.options.find((option) => option.key === answerKey)?.text ?? answerKey;
}

function reviewAnswerLabel(answerKey: string | null | undefined) {
  const item = activeReviewItem.value;
  return item ? quizAnswerLabel(item.question, answerKey) : "未作答";
}

function selectQuizMode(mode: KnowledgeQuizMode) {
  quizMode.value = mode;
}

function switchKnowledgePanel(panel: KnowledgePanel) {
  if (panel === "quiz" && knowledgePanel.value !== "quiz" && (quizSession.value || quizResult.value)) {
    resetKnowledgeQuiz();
  }
  knowledgePanel.value = panel;
}

async function loadKnowledgeQuizStats() {
  try {
    quizStats.value = await api.getKnowledgeQuizStats();
  } catch {
    quizStats.value = null;
  }
}

async function startKnowledgeQuiz(mode = quizMode.value) {
  try {
    isQuizLoading.value = true;
    clearApiFeedback();
    quizMode.value = mode;
    quizResult.value = null;
    quizAnswers.value = {};
    activeQuizIndex.value = 0;
    quizSession.value = await api.startKnowledgeQuiz({ mode });
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "趣味问答加载失败。";
  } finally {
    isQuizLoading.value = false;
  }
}

function chooseQuizAnswer(questionId: string, answer: string) {
  quizAnswers.value = { ...quizAnswers.value, [questionId]: answer };
}

function goQuizQuestion(offset: number) {
  if (!quizSession.value) return;
  activeQuizIndex.value = Math.min(Math.max(activeQuizIndex.value + offset, 0), quizSession.value.total - 1);
}

async function submitKnowledgeQuiz() {
  if (!quizSession.value || !canSubmitQuiz.value) return;
  try {
    isQuizLoading.value = true;
    clearApiFeedback();
    quizResult.value = await api.submitKnowledgeQuiz({
      session_id: quizSession.value.session_id,
      answers: Object.entries(quizAnswers.value).map(([question_id, answer]) => ({ question_id, answer })),
    });
    activeReviewIndex.value = 0;
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "趣味问答提交失败。";
  } finally {
    isQuizLoading.value = false;
  }
}

function resetKnowledgeQuiz() {
  quizSession.value = null;
  quizResult.value = null;
  quizAnswers.value = {};
  activeQuizIndex.value = 0;
  activeReviewIndex.value = 0;
}

async function askKnowledge(questionText = knowledgeDraft.value) {
  const question = questionText.trim();
  if (!question) return;
  knowledgeDraft.value = "";
  addKnowledgeMessage({ role: "user", text: question });
  const assistantId = addKnowledgeMessage({ role: "assistant", text: "我先查一下知识库。", streaming: true });
  try {
    isKnowledgeLoading.value = true;
    clearApiFeedback();
    const response = await api.askKnowledge({
      question,
      use_my_context: Boolean(accessToken.value),
      thread_id: activeThreadId.value || null,
    });
    knowledgeItems.value = response.related_articles;
    updateKnowledgeMessage(assistantId, {
      text: response.answer.summary_30s,
      answer: response.answer,
      relatedArticles: response.related_articles,
      sourceRefs: response.source_refs,
      questionSuggestion: response.question_suggestion,
      coverageStatus: response.coverage_status,
      scopeStatus: response.scope_status,
      confidence: response.confidence,
      gapId: response.gap_id,
      riskLevel: response.risk_level,
      streaming: false,
    });
    if (response.risk_level === "L2" || response.risk_level === "L3") {
      openSafety();
    }
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "知识问答失败。";
    updateKnowledgeMessage(assistantId, {
      text: "这次没有拿到稳定的知识库回答，可以换个更具体的问题再试一次。",
      streaming: false,
    });
  } finally {
    isKnowledgeLoading.value = false;
  }
}

async function continueKnowledgeChat() {
  const topic =
    [...knowledgeMessages.value]
      .reverse()
      .find((message) => message.role === "user")
      ?.text.trim() ||
    selectedKnowledgeArticle.value?.title ||
    "";
  if (!topic.trim()) return;
  await submitMessage(`我想继续聊聊这个心理知识：${topic}`);
}

async function loadTestList() {
  try {
    isTestLoading.value = true;
    const response = await api.listTests();
    testItems.value = response.items;
  } catch {
    apiError.value = "测试列表加载失败。";
  } finally {
    isTestLoading.value = false;
  }
}

function filteredTests(): TestListItem[] {
  return testItems.value.filter((t) => t.test_type === selectedTestCategory.value);
}

async function startTest(testId: string) {
  if (isDemoMode.value || !accessToken.value) {
    currentTest.value = testId === "state-check-v1" ? demoStateQuestions : demoTypeQuestions;
    currentAttemptId.value = `local-${testId}-${Date.now()}`;
    testAnswers.value = {};
    currentQuestionIndex.value = 0;
    selectedOptionId.value = "";
    testView.value = "taking";
    return;
  }
  try {
    isTestLoading.value = true;
    const response = await api.startAttempt(testId);
    currentTest.value = { test_id: response.test_id, code: "", title: "", questions: response.questions };
    currentAttemptId.value = response.attempt_id;
    testAnswers.value = {};
    currentQuestionIndex.value = 0;
    selectedOptionId.value = "";
    testView.value = "taking";
  } catch {
    currentTest.value = testId === "state-check-v1" ? demoStateQuestions : demoTypeQuestions;
    currentAttemptId.value = `local-${testId}-${Date.now()}`;
    testAnswers.value = {};
    currentQuestionIndex.value = 0;
    testView.value = "taking";
  } finally {
    isTestLoading.value = false;
  }
}

function selectOption(optionId: string) {
  selectedOptionId.value = optionId;
}

function goToPrevQuestion() {
  if (currentQuestionIndex.value > 0) {
    currentQuestionIndex.value -= 1;
    selectedOptionId.value = testAnswers.value[currentQuestionIndex.value] || "";
  }
}

function goToNextQuestion() {
  if (!currentTest.value) return;
  testAnswers.value[currentQuestionIndex.value] = selectedOptionId.value;
  if (!isDemoMode.value && accessToken.value) {
    api.submitAnswer(currentAttemptId.value, { question_index: currentQuestionIndex.value, option_id: selectedOptionId.value }).catch(() => {});
  }
  if (currentQuestionIndex.value < currentTest.value.questions.length - 1) {
    currentQuestionIndex.value += 1;
    selectedOptionId.value = testAnswers.value[currentQuestionIndex.value] || "";
  } else {
    const unanswered = currentTest.value.questions.findIndex((q) => !testAnswers.value[q.index]);
    if (unanswered !== -1) {
      isShowingIncomplete.value = true;
      return;
    }
    isConfirmingResult.value = true;
  }
}

function jumpToUnanswered() {
  if (!currentTest.value) return;
  isShowingIncomplete.value = false;
  const unanswered = currentTest.value.questions.findIndex((q) => !testAnswers.value[q.index]);
  currentQuestionIndex.value = unanswered !== -1 ? unanswered : 0;
  selectedOptionId.value = testAnswers.value[currentQuestionIndex.value] || "";
}

function confirmCompleteTest() {
  isConfirmingResult.value = false;
  completeTest();
}

function cancelCompleteTest() {
  isConfirmingResult.value = false;
}

async function completeTest() {
  if (isDemoMode.value || !accessToken.value || currentAttemptId.value.startsWith("local-")) {
    const testItem = testItems.value.find(t => t.test_id === currentTest.value?.test_id);
    if (testItem?.test_type === "personality") {
      testResult.value = { ...demoTypeResult };
    } else if (testItem?.test_type === "anime") {
      testResult.value = { ...demoAnimeResult };
    } else {
      testResult.value = { ...demoStateResult };
    }
    testView.value = "result";
    return;
  }
  try {
    isTestLoading.value = true;
    testResult.value = await api.completeAttempt(currentAttemptId.value);
    testView.value = "result";
  } catch {
    const testItem = testItems.value.find(t => t.test_id === currentTest.value?.test_id);
    if (testItem?.test_type === "personality") {
      testResult.value = { ...demoTypeResult };
    } else if (testItem?.test_type === "anime") {
      testResult.value = { ...demoAnimeResult };
    } else {
      testResult.value = { ...demoStateResult };
    }
    testView.value = "result";
  } finally {
    isTestLoading.value = false;
  }
}

function backToTestList() {
  testView.value = "list";
  testResult.value = null;
  currentTest.value = null;
  currentAttemptId.value = "";
  testAnswers.value = {};
  currentQuestionIndex.value = 0;
}

function formatTestTime(isoStr: string): string {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day} ${h}:${min}`;
}

function stateLevelLabel(code: string): string {
  switch (code) {
    case "stable": return "状态稳定";
    case "mild": return "轻度波动";
    case "burdened": return "负担较重";
    default: return "";
  }
}

function riskNoteForCode(code: string): string {
  switch (code) {
    case "stable": return "当前状态整体平稳，继续保持自我照顾的节奏。若有突发压力事件，情绪可能出现短期波动。";
    case "mild": return "情绪有一些波动，在正常范围内。留意是否持续加重，适当减负。";
    case "burdened": return "当前负担较重，这不是你的错。建议优先照顾自己，并考虑联系现实中的支持。如果持续影响睡眠或日常生活，可以联系专业支持。";
    default: return "";
  }
}

// --- Sprint 3: Voice MVP ---

const wsBaseUrl = computed(() => {
  const url = apiBaseUrl.replace(/^http/, "ws");
  return url.endsWith("/") ? url.slice(0, -1) : url;
});

// --- Sprint 3: Speech Recording (Xunfei / Browser Speech) ---

// Cleans up all recording resources
function cleanupRecording(): void {
  isRecording.value = false;
  xfRecognizedText.value = "";
  xfRecognizing.value = false;
  stopBrowserSpeech();
  if (xfWs.value) {
    try { xfWs.value.close(); } catch {}
    xfWs.value = null;
  }
  try {
    xfScriptProcessor?.disconnect();
    xfSourceNode?.disconnect();
    xfAudioContext?.close();
  } catch {}
  xfScriptProcessor = null;
  xfSourceNode = null;
  xfAudioContext = null;
  xfMediaStream?.getTracks().forEach((t) => t.stop());
  xfMediaStream = null;
}

// Start recording via browser Web Speech API (or Xunfei if configured)
async function startSpeechRecording(): Promise<void> {
  if (isRecording.value) return;

  const apiKey = import.meta.env.VITE_XF_API_KEY as string;
  const apiSecret = import.meta.env.VITE_XF_API_SECRET as string;

  if (apiKey && apiSecret) {
    await startXfRecording();
  } else {
    startBrowserSpeech();
  }
}

function stopSpeechRecording(): void {
  cleanupRecording();
}
// Falls back to browser Web Speech API if no Xunfei credentials configured

async function buildXfAuthUrl(): Promise<string> {
  const apiKey = import.meta.env.VITE_XF_API_KEY as string;
  const apiSecret = import.meta.env.VITE_XF_API_SECRET as string;

  const host = "iat-api.xfyun.cn";
  const path = "/v2/iat";
  const date = new Date().toUTCString();
  const signatureOrigin = `host: ${host}\ndate: ${date}\nGET ${path} HTTP/1.1`;

  const encoder = new TextEncoder();
  const keyData = encoder.encode(apiSecret);
  const messageData = encoder.encode(signatureOrigin);

  return crypto.subtle.importKey("raw", keyData, { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
    .then((key) => crypto.subtle.sign("HMAC", key, messageData))
    .then((signature) => {
      const sigStr = btoa(String.fromCharCode(...new Uint8Array(signature)));
      const authorizationOrigin = `api_key="${apiKey}", algorithm="hmac-sha256", headers="host date request-line", signature="${sigStr}"`;
      const auth = btoa(authorizationOrigin);
      return `wss://${host}${path}?authorization=${encodeURIComponent(auth)}&date=${encodeURIComponent(date)}&host=${host}`;
    });
}

async function startXfRecording(): Promise<void> {
  if (isRecording.value) return;

  const apiKey = import.meta.env.VITE_XF_API_KEY as string;
  const apiSecret = import.meta.env.VITE_XF_API_SECRET as string;

  // If no Xunfei credentials, use browser Web Speech API directly
  if (!apiKey || !apiSecret) {
    startBrowserSpeech();
    return;
  }

  try {
    const wsUrl = await buildXfAuthUrl();
    xfRecognizedText.value = "";
    xfRecognizing.value = false;
    voiceError.value = "";

    xfMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    xfAudioContext = new AudioContext({ sampleRate: 16000 });
    const source = xfAudioContext.createMediaStreamSource(xfMediaStream);

    xfScriptProcessor = xfAudioContext.createScriptProcessor(4096, 1, 1);
    xfSourceNode = source;

    source.connect(xfScriptProcessor);
    xfScriptProcessor.connect(xfAudioContext.destination);

    xfWs.value = new WebSocket(wsUrl);

    xfWs.value.onopen = () => {
      isRecording.value = true;
      const appId = import.meta.env.VITE_XF_APP_ID as string;
      xfWs.value!.send(JSON.stringify({
        common: { app_id: appId },
        business: {
          language: "zh_cn",
          domain: "iat",
          accent: "mandarin",
          vad_eos: 3000,
          dwa: "wpgs",
          ptt: 0,
        },
        data: { status: 0, format: "audio/L16;rate=16000", encoding: "raw", audio: "" },
      }));
    };

    xfWs.value.onmessage = (event) => {
      try {
        const resp = JSON.parse(event.data as string);
        if (resp.code !== 0) {
          voiceError.value = `讯飞识别错误: ${resp.message || "未知错误"} (code=${resp.code})`;
          cleanupRecording();
          return;
        }
        if (resp.data?.result) {
          const ws = resp.data.result.ws || [];
          const words = ws.map((w: any) => (w.cw || []).map((c: any) => c.w).join("")).join("");
          if (words) {
            xfRecognizedText.value = words;
            xfRecognizing.value = true;
            if (resp.data.status === 2) {
              xfRecognizing.value = false;
              cleanupRecording();
              submitMessage(words);
            }
          }
        }
      } catch {
        // ignore
      }
    };

    xfWs.value.onerror = () => {
      voiceError.value = "讯飞连接失败，请手动输入文字。";
      cleanupRecording();
    };

    xfWs.value.onclose = () => {
      if (isRecording.value) {
        cleanupRecording();
      }
    };

    xfScriptProcessor.onaudioprocess = (event) => {
      if (!isRecording.value || !xfWs.value || xfWs.value.readyState !== WebSocket.OPEN) return;
      const inputData = event.inputBuffer.getChannelData(0);
      const pcm = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      xfWs.value.send(JSON.stringify({
        data: { status: 1, format: "audio/L16;rate=16000", encoding: "raw", audio: btoa(String.fromCharCode(...new Uint8Array(pcm.buffer))) },
      }));
    };

  } catch (err: any) {
    if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
      voiceError.value = "麦克风权限被拒绝，请允许麦克风访问或手动输入文字。";
    } else {
      startBrowserSpeech();
    }
    cleanupRecording();
  }
}

function startBrowserSpeech(): void {
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SpeechRecognition) {
    voiceError.value = "浏览器不支持语音识别，请使用 Chrome 或 Edge，或手动输入文字。";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    isRecording.value = true;
    xfRecognizedText.value = "";
    xfRecognizing.value = true;
    voiceError.value = "";
  };

  recognition.onresult = (event: any) => {
    let final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        final += result[0].transcript;
      } else {
        xfRecognizedText.value += result[0].transcript;
      }
    }
    if (final) {
      xfRecognizing.value = false;
      // Send recognized text directly to the chat pipeline
      cleanupRecording();
      submitMessage(final);
    }
  };

  recognition.onerror = (event: any) => {
    if (event.error === "not-allowed") {
      voiceError.value = "麦克风权限被拒绝，请允许麦克风访问或手动输入文字。";
    } else if (event.error !== "aborted") {
      voiceError.value = `语音识别失败: ${event.error}`;
    }
    cleanupRecording();
  };

  recognition.onend = () => {
    if (isRecording.value) {
      cleanupRecording();
    }
  };

  recognition.start();
  (window as any).__xfRecognition = recognition;
}

function stopBrowserSpeech(): void {
  const rec = (window as any).__xfRecognition;
  if (rec) {
    try { rec.stop(); } catch {}
    (window as any).__xfRecognition = null;
  }
}

// --- Sprint 3: Share Card ---

function generateShareCard() {
  if (!testResult.value) return;
  const r = testResult.value;
  const testType = r.test_type === "state" ? "mood_check" as const : "sixteen_type" as const;
  const title = testType === "mood_check" ? "我的今日状态观察" : "我的16型人格镜像";
  const highlights = [
    ...r.strengths.slice(0, 2),
    ...r.blind_spots.slice(0, 1),
  ];
  shareCardData.value = {
    testType,
    title,
    subtitle: "这是一面镜子，不是诊断",
    resultLabel: r.result_title,
    summary: r.summary,
    highlights,
    disclaimer: "结果仅供自我观察，不代表临床诊断或心理治疗结论。",
    sixteenTypeCode: r.profile.sixteen_type_code ?? null,
  };
  shareCardVisible.value = true;
  shareCardCopied.value = false;
}

function closeShareCard() {
  shareCardVisible.value = false;
  shareCardData.value = null;
}

async function copyShareCard() {
  if (!shareCardData.value) return;
  const d = shareCardData.value;
  const lines = [
    `${d.title} · ${d.resultLabel}`,
    `—— ${d.subtitle}`,
    "",
    d.summary,
    d.highlights.length > 0 ? `要点：${d.highlights.join(" / ")}` : "",
    "",
    d.disclaimer,
  ].filter(Boolean);
  const text = lines.join("\n");
  try {
    await navigator.clipboard.writeText(text);
    shareCardCopied.value = true;
    setTimeout(() => { shareCardCopied.value = false; }, 2000);
  } catch {
    // Clipboard API not available
  }
}

async function downloadShareImage() {
  if (!shareCardData.value) return;
  shareCardSaving.value = true;
  const el = document.querySelector(".share-card") as HTMLElement | null;
  if (!el) {
    shareCardSaving.value = false;
    return;
  }
  try {
    const canvas = await html2canvas(el, {
      scale: 2,
      backgroundColor: null,
      useCORS: true,
      logging: false,
    });
    const dataUrl = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.download = `share-${shareCardData.value.testType}-${Date.now()}.png`;
    link.href = dataUrl;
    link.click();
  } catch {
    // html2canvas failed silently
  } finally {
    shareCardSaving.value = false;
  }
}

// --- Sprint 3: Feedback ---

function openFeedback(type: "assistant_message" | "knowledge_answer" | "test_result", targetId: string) {
  feedbackTargetType.value = type;
  feedbackTargetId.value = targetId;
  feedbackRating.value = 0;
  feedbackNote.value = "";
  feedbackDone.value = false;
  feedbackVisible.value = true;
}

async function submitFeedback() {
  if (feedbackRating.value < 1 || feedbackRating.value > 5) return;
  isFeedbackSubmitting.value = true;
  try {
    const payload: FeedbackCreateRequest = {
      target_type: feedbackTargetType.value,
      target_id: feedbackTargetId.value,
      rating: feedbackRating.value,
      note: feedbackNote.value || null,
    };
    await api.submitFeedback(payload);
    feedbackDone.value = true;
    await refreshPrivacySummary();
  } catch {
    // silently fail
  } finally {
    isFeedbackSubmitting.value = false;
  }
}

function closeFeedback() {
  feedbackVisible.value = false;
}

// --- Sprint 3: Weekly Summary ---

async function loadWeeklySummary() {
  isWeeklySummaryLoading.value = true;
  isWeeklySummaryOpen.value = true;
  const rangeLabel = moodRange.value === "30d" ? "30天" : "近7天";
  try {
    if (isDemoMode.value || !accessToken.value) {
      weeklySummary.value = {
        range: rangeLabel,
        summary: moodTrend.value?.summary || "这周你记录了情绪变化，继续关照自己。",
        top_tags: moodTrend.value?.top_tags || [],
        suggested_actions: ["试试记下今天的情绪", "给自己一个轻松的时段"],
        generated_by: "fallback",
      };
      return;
    }
    const result = await api.getWeeklySummary();
    weeklySummary.value = {
      ...result,
      range: rangeLabel,
    };
  } catch {
    weeklySummary.value = {
      range: rangeLabel,
      summary: "暂时无法生成周小结，请稍后再试。",
      top_tags: [],
      suggested_actions: [],
      generated_by: "fallback",
    };
  } finally {
    isWeeklySummaryLoading.value = false;
  }
}

function closeWeeklySummary() {
  isWeeklySummaryOpen.value = false;
}

// --- End Sprint 3 ---

async function loadTestHistory() {
  isHistoryLoading.value = true;
  try {
    if (isDemoMode.value || !accessToken.value) {
      testHistory.value = [];
      return;
    }
    const resp = await api.getTestHistory();
    testHistory.value = resp.items;
  } catch {
    testHistory.value = [];
  } finally {
    isHistoryLoading.value = false;
  }
}

function openTestHistory() {
  testView.value = "history";
  loadTestHistory();
}

async function viewHistoryResult(attemptId: string) {
  if (isDemoMode.value || !accessToken.value) return;
  isTestLoading.value = true;
  try {
    testResult.value = await api.getAttemptResult(attemptId);
    testView.value = "result";
  } catch {
    // silently fail
  } finally {
    isTestLoading.value = false;
  }
}

function continueTestChat() {
  if (!testResult.value) return;
  const resultText = `我完成了一个测试：${testResult.value.result_title}。结果摘要：${testResult.value.summary}。我想继续聊聊这个结果。`;
  void (async () => {
    await createThread(testResult.value?.result_title || "测试结果");
    await submitMessage(resultText);
    activeTab.value = "chat";
  })();
}

function currentQuestion() {
  return currentTest.value?.questions[currentQuestionIndex.value] ?? null;
}

function isLastQuestion() {
  if (!currentTest.value) return false;
  return currentQuestionIndex.value >= currentTest.value.questions.length - 1;
}

function openSafety() {
  safetyAction.value = null;
  isSafetyOpen.value = true;
}

function closeSafety() {
  safetyAction.value = null;
  isSafetyOpen.value = false;
}

async function logout() {
  if (!isDemoMode.value && refreshToken.value) {
    try {
      await api.logout({ refresh_token: refreshToken.value });
    } catch {
      // Local cleanup is still required when the server session is expired.
    }
  }
  clearSession();
  isDemoMode.value = false;
  selectedAge.value = null;
  selectedStyle.value = null;
  selectedGoal.value = null;
  threads.value = [];
  memories.value = [];
  moodTrend.value = null;
  demoMoodLogs.value = [];
  moodRange.value = "7d";
  resetMoodDraft();
  setMessages([]);
  stage.value = "auth";
  await refreshCaptcha();
}

onMounted(async () => {
  try {
    if (!accessToken.value && refreshToken.value) await refreshAccessToken();
    if (accessToken.value) await loadApp();
    else await refreshCaptcha();
  } finally {
    isBooting.value = false;
  }
});
</script>

<template>
  <main class="app-canvas">
    <section class="phone-shell" :class="{ 'phone-shell--modal': isSafetyOpen }">
      <div v-if="isBooting" class="boot-screen">
        <span class="brand-dot">宁语</span>
        <h1>正在进入</h1>
        <p>把最近的会话和状态放回原位。</p>
      </div>

      <section v-else-if="stage === 'auth'" class="app-screen auth-screen">
        <header class="auth-hero">
          <span class="brand-dot">宁语</span>
          <h1>今晚想先聊哪一点？</h1>
          <p>登录后继续你的会话；也可以先进入演示模式看完整 App 流程。</p>
        </header>

        <div class="segmented">
          <button :class="{ active: authMode === 'login' }" type="button" @click="authMode = 'login'">登录</button>
          <button :class="{ active: authMode === 'register' }" type="button" @click="authMode = 'register'">注册</button>
        </div>

        <form class="auth-form" @submit.prevent="submitAuth">
          <label class="field">
            <span>用户名</span>
            <input v-model="authUsername" type="text" autocomplete="username" placeholder="请输入用户名" />
          </label>

          <label class="field">
            <span>密码</span>
            <input v-model="authPassword" type="password" autocomplete="current-password" placeholder="至少 6 位" />
          </label>

          <div v-if="authMode === 'register'" class="age-list">
            <button
              v-for="option in ageOptions"
              :key="option.id"
              :class="['age-option', { active: authSelectedAge === option.id }]"
              type="button"
              @click="authSelectedAge = option.id"
            >
              <strong>{{ option.label }}</strong>
              <span>{{ option.description }}</span>
            </button>
          </div>

          <label class="field">
            <span>验证码</span>
            <div class="captcha-line">
              <button class="captcha-image" type="button" :disabled="isCaptchaLoading" @click="refreshCaptcha">
                <img v-if="captchaImageDataUrl" :src="captchaImageDataUrl" alt="验证码" />
                <span v-else>{{ isCaptchaLoading ? "加载中" : "刷新" }}</span>
              </button>
              <input v-model="captchaCode" type="text" autocomplete="off" placeholder="验证码" />
            </div>
          </label>

          <p v-if="authError" class="notice notice--error">{{ authError }}</p>

          <button class="primary-action" type="submit" :disabled="!canSubmitAuth || isAuthenticating">
            {{ isAuthenticating ? "处理中..." : authMode === "login" ? "登录" : "创建账户" }}
          </button>
          <button class="secondary-action" type="button" @click="enterDemoMode">先看演示</button>
        </form>
      </section>

      <section v-else-if="stage === 'onboarding'" class="app-screen onboarding-screen">
        <header class="screen-header">
          <span class="top-label">{{ selectedAgeLabel }} · {{ modeLabel }}</span>
          <h1>你希望我怎么陪你？</h1>
          <p>先选一种交流语气，再选一个这段时间更需要的方向。</p>
        </header>

        <div class="choice-section">
          <h2>陪伴风格</h2>
          <button
            v-for="option in styleOptions"
            :key="option.id"
            :class="['choice-row', { active: selectedStyle === option.id }]"
            type="button"
            @click="selectedStyle = option.id"
          >
            <strong>{{ option.label }}</strong>
            <span>{{ option.description }}</span>
          </button>
        </div>

        <div class="choice-section">
          <h2>当前目标</h2>
          <button
            v-for="option in goalOptions"
            :key="option.id"
            :class="['choice-row', { active: selectedGoal === option.id }]"
            type="button"
            @click="selectedGoal = option.id"
          >
            <strong>{{ option.label }}</strong>
            <span>{{ option.description }}</span>
          </button>
        </div>

        <footer class="sticky-actions">
          <button class="primary-action" type="button" :disabled="!canContinueOnboarding" @click="finishOnboarding()">
            进入首页
          </button>
          <button class="text-action" type="button" @click="finishOnboarding(true)">以后再选</button>
        </footer>
      </section>

      <section v-else class="app-screen main-screen">
        <header class="app-header">
          <div>
            <span class="top-label">{{ modeLabel }}</span>
            <h1 v-if="activeTab === 'home'">晚上好，{{ userName }}</h1>
            <h1 v-else-if="activeTab === 'chat'">{{ activeThread?.title || "对话" }}</h1>
            <h1 v-else-if="activeTab === 'tests'">{{ testHeaderTitle }}</h1>
            <h1 v-else-if="activeTab === 'knowledge'">知识问答</h1>
            <h1 v-else>我的</h1>
          </div>
          <button class="sos-button" type="button" @click="openSafety">SOS</button>
        </header>

        <p v-if="apiNotice" class="notice notice--info">{{ apiNotice }}</p>
        <p v-if="apiError" class="notice notice--error">{{ apiError }}</p>

        <section v-if="activeTab === 'home'" class="tab-page">
          <form v-if="!hasTodayMoodLog" class="mood-checkin-card" @submit.prevent="submitMoodCheckIn">
            <div class="card-title">
              <div>
                <span>今日状态</span>
                <h2>你现在感觉怎么样？</h2>
              </div>
              <strong>{{ moodDraft.mood_score }}分</strong>
            </div>

            <div class="mood-scale-list">
              <label class="mood-scale">
                <span>心情 <strong>{{ moodValueText(moodDraft.mood_score) }}</strong></span>
                <input v-model.number="moodDraft.mood_score" type="range" min="1" max="5" step="1" />
              </label>
              <label class="mood-scale">
                <span>焦虑 <strong>{{ moodValueText(moodDraft.anxiety_score) }}</strong></span>
                <input v-model.number="moodDraft.anxiety_score" type="range" min="1" max="5" step="1" />
              </label>
              <label class="mood-scale">
                <span>精力 <strong>{{ moodValueText(moodDraft.energy_score) }}</strong></span>
                <input v-model.number="moodDraft.energy_score" type="range" min="1" max="5" step="1" />
              </label>
              <label class="mood-scale">
                <span>睡眠 <strong>{{ moodValueText(moodDraft.sleep_quality) }}</strong></span>
                <input v-model.number="moodDraft.sleep_quality" type="range" min="1" max="5" step="1" />
              </label>
            </div>

            <div class="mood-tags" aria-label="情绪标签">
              <button
                v-for="tag in moodTagOptions"
                :key="tag"
                :class="{ active: moodDraft.mood_tags?.includes(tag) }"
                type="button"
                @click="toggleMoodTag(tag)"
              >
                {{ tag }}
              </button>
            </div>

            <textarea v-model="moodDraft.note" class="mood-note" rows="3" maxlength="180" placeholder="一句话记录今天的触发点或感受"></textarea>

            <button class="primary-action" type="submit" :disabled="!canSubmitMood">
              {{ isMoodSubmitting ? "记录中..." : "记录今日状态" }}
            </button>
          </form>

          <button class="mood-card" type="button" @click="startQuickCheckIn">
            <span>现在开始</span>
            <strong>我有点难受，想倾诉</strong>
            <small>点一下进入对话，我会先听你说。</small>
          </button>

          <section class="summary-card trend-card">
            <div class="card-title">
              <h2>状态趋势</h2>
              <div class="range-switch" role="group" aria-label="趋势范围">
                <button
                  v-for="option in moodRangeOptions"
                  :key="option.id"
                  :class="{ active: moodRange === option.id }"
                  type="button"
                  :disabled="isMoodTrendLoading"
                  @click="switchMoodRange(option.id)"
                >
                  {{ option.label }}
                </button>
              </div>
            </div>
            <p>{{ moodSummary }}</p>
            <div v-if="moodTrendPoints.length > 0" class="trend-bars" aria-label="情绪趋势点">
              <div v-for="point in moodTrendPoints" :key="point.date" class="trend-bar">
                <i :style="{ height: moodPointHeight(point.mood_score) }"></i>
                <span>{{ formatMoodDate(point.date) }}</span>
              </div>
            </div>
            <div v-if="moodTrendTags.length > 0" class="trend-tags">
              <span v-for="tag in moodTrendTags" :key="tag">{{ tag }}</span>
            </div>
            <small v-if="moodTrendPoints.length === 0" class="empty-copy">暂无趋势数据。</small>
            <button class="text-action weekly-summary-btn" type="button" :disabled="isWeeklySummaryLoading" @click="loadWeeklySummary">
              {{ isWeeklySummaryLoading ? '加载中...' : moodRange === '30d' ? '查看近30天小结' : '查看本周情绪小结' }}
            </button>
          </section>

          <section class="section-block">
            <div class="section-title">
              <h2>继续聊</h2>
              <button type="button" :disabled="isCreatingThread" @click="createChatThread">新建</button>
            </div>
            <button
              v-for="thread in visibleThreads"
              :key="thread.thread_id"
              class="thread-card"
              type="button"
              @click="selectThread(thread.thread_id)"
            >
              <div>
                <strong>{{ thread.title }}</strong>
                <p>{{ thread.last_summary || "还没有摘要，打开后继续。" }}</p>
              </div>
              <span :class="['risk-pill', riskClass(thread.last_risk_level)]">{{ riskLabel(thread.last_risk_level) }}</span>
            </button>
            <p v-if="visibleThreads.length === 0" class="empty-copy">还没有会话，先从一段倾诉开始。</p>
          </section>
        </section>

        <section v-else-if="activeTab === 'chat'" class="tab-page chat-page">
          <div class="chat-thread-toolbar" role="group" aria-label="会话操作">
            <button class="thread-menu-button" type="button" @click="openThreadDrawer">
              会话
            </button>
            <button class="thread-new-button" type="button" :disabled="isCreatingThread" @click="createChatThread">
              {{ isCreatingThread ? "创建中..." : "新建" }}
            </button>
          </div>

          <div ref="messageListRef" class="message-list">
            <div v-if="messages.length === 0" class="empty-chat">
              <h2>从一句话开始</h2>
              <p>把此刻最明显的感受写下来就可以。</p>
            </div>
            <article
              v-for="message in messages"
              :key="message.id"
              :class="['message', message.role === 'user' ? 'message--user' : 'message--assistant']"
            >
              <p>{{ message.text || "..." }}</p>
              <div
                v-if="message.role === 'assistant' && (message.riskLevel || message.graphNode || message.streamError)"
                class="message-meta"
              >
                <span v-if="message.riskLevel" :class="['risk-pill', riskClass(message.riskLevel)]">
                  {{ riskLabel(message.riskLevel) }}
                </span>
                <span v-if="message.graphNode && message.streaming" class="graph-status">
                  {{ graphStatusLabel(message.graphNode) }}
                </span>
                <span v-if="message.streamError" class="stream-status">已切换到稳定回复</span>
              </div>
              <div v-if="message.role === 'assistant' && message.referencedMemories?.length" class="memory-reference">
                <button type="button" @click="toggleMemoryReferences(message.id)">
                  引用了 {{ message.referencedMemories.length }} 条记忆
                </button>
                <div v-if="message.memoryRefsExpanded" class="memory-reference__list">
                  <span v-for="memory in message.referencedMemories" :key="`${message.id}-${memory.memory_id}`">
                    {{ memoryTypeLabel(memory.memory_type) }}：{{ memory.content }}
                  </span>
                </div>
              </div>
              <div
                v-if="message.role === 'assistant' && message.suggestedActions?.length"
                class="message-actions"
              >
                <button
                  v-for="action in message.suggestedActions"
                  :key="`${message.id}-${action}`"
                  type="button"
                  :disabled="isSending"
                  @click="submitMessage(action)"
                >
                  {{ action }}
                </button>
              </div>
              <div v-if="message.role === 'assistant'" class="message-feedback">
                <button type="button" class="feedback-btn" title="有帮助" @click="openFeedback('assistant_message', String(message.id))">有帮助</button>
              </div>
              <span v-if="message.streaming" class="typing-dot"></span>
            </article>
          </div>

          <div class="quick-actions">
            <button v-for="action in quickActions" :key="action" type="button" :disabled="isSending" @click="submitMessage(action)">
              {{ action }}
            </button>
          </div>

          <form class="composer" @submit.prevent="submitMessage()">
            <input v-model="composerText" type="text" :placeholder="isRecording ? '正在录音...' : '写下此刻的感受...'" />
            <button
              v-if="!isRecording"
              type="button"
              class="voice-record-btn"
              title="语音输入"
              @click="startSpeechRecording"
            >语音</button>
            <button
              v-else
              type="button"
              class="voice-record-btn voice-record-btn--active"
              title="停止录音"
              @click="stopSpeechRecording"
            >停止</button>
            <button type="submit" :disabled="(!composerText.trim() && !isRecording) || isSending">{{ isSending ? "..." : "发送" }}</button>
          </form>
          <div v-if="xfRecognizing || voiceError" class="voice-status-bar">
            <template v-if="xfRecognizing">
              <span class="voice-status-bar__dot voice-status-bar__dot--active"></span>
              <span>{{ xfRecognizedText || '正在听...' }}</span>
            </template>
            <template v-else-if="voiceError">
              <span>{{ voiceError }}</span>
            </template>
          </div>
        </section>

          <!-- 以下是测试中心页面 -->
        
        <section v-else-if="activeTab === 'tests'" class="tab-page tests-page">
          <div v-if="testView === 'list' || testView === 'history'" class="test-category-tabs">
            <!-- 测试分类的选项卡 -->
            <button :class="{ active: selectedTestCategory === 'state' && testView === 'list' }" type="button" @click="selectedTestCategory = 'state'; testView = 'list'">状态</button>
            <button :class="{ active: selectedTestCategory === 'personality' && testView === 'list' }" type="button" @click="selectedTestCategory = 'personality'; testView = 'list'">人格</button>
            <button :class="{ active: selectedTestCategory === 'anime' && testView === 'list' }" type="button" @click="selectedTestCategory = 'anime'; testView = 'list'">动漫</button>
            <button :class="{ active: testView === 'history' }" type="button" @click="openTestHistory">历史</button>
          </div>
          <!-- 测试项目的对外信息 -->
          <div v-if="testView === 'list'" class="tests-list">
            <div class="test-card-list">
              <article v-for="test in filteredTests()" :key="test.test_id" class="test-card">
                <h2>{{ test.title }}</h2>
                <p class="test-card__duration">约 {{ test.estimated_minutes }} 分钟</p>
                <button
                  v-if="test.status === 'published'"
                  class="primary-action"
                  type="button"
                  :disabled="isTestLoading"
                  @click="startTest(test.test_id)"
                >
                  开始测试
                </button>
                <span v-else class="test-card__soon">即将推出</span>
              </article>
              <p v-if="filteredTests().length === 0 && !isTestLoading" class="empty-copy">该分类下暂时没有测试。</p>
            </div>
          </div>

          <div v-else-if="testView === 'taking' && currentTest" class="tests-taking">
            <div class="test-progress">
              <span>{{ currentQuestionIndex + 1 }} / {{ currentTest.questions.length }}</span>
              <button class="text-action" type="button" @click="backToTestList">退出</button>
            </div>
            <article class="test-question">
              <h2>{{ currentQuestion()?.text }}</h2>
              <div class="test-options">
                <button
                  v-for="option in currentQuestion()?.options"
                  :key="option.id"
                  :class="['test-option', { active: selectedOptionId === option.id }]"
                  type="button"
                  @click="selectOption(option.id)"
                >
                  {{ option.text }}
                </button>
              </div>
            </article>
            <div class="test-nav">
              <button type="button" :disabled="currentQuestionIndex === 0" @click="goToPrevQuestion">上一题</button>
              <button
                type="button"
                :class="{ 'primary-action': isLastQuestion() }"
                :disabled="!selectedOptionId || isTestLoading"
                @click="goToNextQuestion"
              >{{ isLastQuestion() ? '查看结果' : '下一题' }}</button>
            </div>

            <!-- 确认提交的弹窗 -->
            <div v-if="isConfirmingResult" class="confirm-overlay" @click.self="cancelCompleteTest">
              <div class="confirm-dialog">
                <h2>确认提交</h2>
                <p>提交后作答情况无法修改，确定要提交吗？</p>
                <div class="confirm-actions">
                  <button class="secondary-action" type="button" @click="cancelCompleteTest">返回</button>
                  <button class="primary-action" type="button" @click="confirmCompleteTest">提交</button>
                </div>
              </div>
            </div>

            <div v-if="isShowingIncomplete" class="confirm-overlay" @click.self="isShowingIncomplete = false">
              <div class="confirm-dialog">
                <h2>未完成作答</h2>
                <p>还有题目未完成，请完成后再查看结果</p>
                <div class="confirm-actions">
                  <button class="secondary-action" type="button" @click="isShowingIncomplete = false">返回</button>
                  <button class="primary-action" type="button" @click="jumpToUnanswered">跳转</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 以下是测试结果的展示页 -->
          <div v-else-if="testView === 'result' && testResult" class="tests-result">
            <article v-if="testResult.test_type === 'state'" class="result-card result-card--state">
              <div class="state-result-header">
                <span class="state-level-badge" :class="'state-level--' + testResult.result_code">{{ stateLevelLabel(testResult.result_code) }}</span>
              </div>
              <h1>{{ testResult.result_title }}</h1>
              <p class="result-disclaimer">这不是对你的定义，而是一面镜子。</p>
              <p class="result-summary">{{ testResult.summary }}</p>

              <section class="result-section result-section--risk">
                <strong>风险提示</strong>
                <p>{{ riskNoteForCode(testResult.result_code) }}</p>
              </section>

              <section v-if="testResult.suggested_actions.length" class="result-section">
                <strong>建议行动</strong>
                <ul>
                  <li v-for="action in testResult.suggested_actions" :key="action">{{ action }}</li>
                </ul>
              </section>
            </article>

            <article v-else-if="testResult.test_type === 'personality'" class="result-card">
              <h1>{{ testResult.profile.sixteen_type_code ? `${testResult.profile.sixteen_type_code} · ` : '' }}{{ testResult.result_title }}</h1>
              <p class="result-disclaimer">这不是对你的定义，而是一面镜子。</p>
              <p class="result-summary">{{ testResult.summary }}</p>

              <section v-if="testResult.profile.traits.length" class="result-section">
                <strong>核心特征</strong>
                <ul>
                  <li v-for="trait in testResult.profile.traits" :key="trait">{{ trait }}</li>
                </ul>
              </section>

              <section v-if="testResult.strengths.length" class="result-section">
                <strong>优势</strong>
                <ul>
                  <li v-for="s in testResult.strengths" :key="s">{{ s }}</li>
                </ul>
              </section>

              <section v-if="testResult.blind_spots.length" class="result-section">
                <strong>盲点</strong>
                <ul>
                  <li v-for="b in testResult.blind_spots" :key="b">{{ b }}</li>
                </ul>
              </section>

              <section v-if="testResult.profile.companion_style" class="result-section">
                <strong>适合你的陪伴方式</strong>
                <p>{{ testResult.profile.companion_style }}</p>
              </section>

              <section v-if="testResult.suggested_actions.length" class="result-section">
                <strong>建议行动</strong>
                <ul>
                  <li v-for="action in testResult.suggested_actions" :key="action">{{ action }}</li>
                </ul>
              </section>
            </article>

            <article v-else-if="testResult.test_type === 'anime'" class="result-card result-card--anime">
              <h1>{{ testResult.result_title }}</h1>
              <p class="anime-similarity" v-if="testResult.profile.sixteen_type_label">{{ testResult.profile.sixteen_type_label }}</p>
              <p class="result-disclaimer">这不是对你的定义，而是一面镜子。</p>
              <p class="result-summary">{{ testResult.summary }}</p>

              <section v-if="testResult.profile.traits.length" class="result-section">
                <strong>你们像在哪里？</strong>
                <ul>
                  <li v-for="trait in testResult.profile.traits" :key="trait">{{ trait }}</li>
                </ul>
              </section>

              <section v-if="testResult.profile.strengths.length" class="result-section">
                <strong>top 3</strong>
                <ol>
                  <li v-for="s in testResult.profile.strengths" :key="s">{{ s }}</li>
                </ol>
              </section>

              <section v-if="testResult.blind_spots.length" class="result-section">
                <strong>哪里不像？</strong>
                <ul>
                  <li v-for="b in testResult.blind_spots" :key="b">{{ b }}</li>
                </ul>
              </section>
            </article>

            <article v-else class="result-card">
              <h1>{{ testResult.result_title }}</h1>
              <p class="result-disclaimer">这不是对你的定义，而是一面镜子。</p>
              <p class="result-summary">{{ testResult.summary }}</p>
              <section v-if="testResult.suggested_actions.length" class="result-section">
                <strong>建议行动</strong>
                <ul>
                  <li v-for="action in testResult.suggested_actions" :key="action">{{ action }}</li>
                </ul>
              </section>
            </article>

            <footer class="sticky-actions">
              <button class="primary-action" type="button" @click="continueTestChat">继续聊聊这个结果</button>
              <button class="secondary-action" type="button" @click="generateShareCard()">生成分享卡</button>
              <button class="secondary-action" type="button" @click="backToTestList">返回测试列表</button>
              <button class="text-action" type="button" @click="openFeedback('test_result', testResult?.attempt_id ?? null)">评价结果</button>
            </footer>
          </div>

          <!-- 在这里新增测试结果展示页 -->

          <!-- 以上是测试结果的展示页 -->
          <!-- 以下是测试历史的展示页 -->

          <div v-else-if="testView === 'history'" class="tests-history">
            <p v-if="isHistoryLoading" class="empty-copy">加载中...</p>
            <div v-else-if="testHistory.length === 0" class="test-card-list">
              <p class="empty-copy">暂无测试记录</p>
              <button class="primary-action" type="button" @click="backToTestList">去做测试</button>
            </div>
            <div v-else class="test-card-list">
              <article
                v-for="item in testHistory"
                :key="item.attempt_id"
                class="test-card"
              >
                <h2>{{ item.test_title }}</h2>
                <p class="test-card__duration">完成于 {{ formatTestTime(item.completed_at) }}</p>
                <p class="test-card__result">{{ item.result_label }}</p>
                <button
                  class="secondary-action"
                  type="button"
                  @click="viewHistoryResult(item.attempt_id)"
                >查看结果</button>
              </article>
            </div>
          </div>
        </section>

          <!-- 以上是测试历史的展示页 -->

        <section v-else-if="activeTab === 'knowledge'" class="tab-page knowledge-page">
          <section class="knowledge-agent">
            <div class="knowledge-agent__avatar">知</div>
            <div>
              <span>知识问答</span>
              <h2>今天想弄清楚什么？</h2>
            </div>
          </section>

          <div class="segmented knowledge-mode-switch">
            <button :class="{ active: knowledgePanel === 'qa' }" type="button" @click="switchKnowledgePanel('qa')">直接问答</button>
            <button :class="{ active: knowledgePanel === 'quiz' }" type="button" @click="switchKnowledgePanel('quiz')">趣味闯关</button>
          </div>

          <template v-if="knowledgePanel === 'qa'">
          <div ref="knowledgeListRef" class="knowledge-chat" aria-label="知识问答消息">
            <article
              v-for="message in knowledgeMessages"
              :key="message.id"
              :class="['knowledge-message', message.role === 'user' ? 'knowledge-message--user' : 'knowledge-message--assistant']"
            >
              <p>{{ message.text }}</p>
              <template v-if="message.answer">
                <div v-if="message.questionSuggestion" class="knowledge-guess">
                  <span>猜你想问</span>
                  <strong>{{ message.questionSuggestion.guessed_question }}</strong>
                  <small>已按这个问题回答</small>
                </div>
                <div v-if="message.scopeStatus === 'out_of_scope'" class="knowledge-coverage knowledge-coverage--out-of-scope">
                  <span>范围外</span>
                  <small>心理知识限定</small>
                </div>
                <div v-else-if="message.coverageStatus" :class="['knowledge-coverage', `knowledge-coverage--${message.coverageStatus}`]">
                  <span>{{ message.coverageStatus === "sufficient" ? "资料充分" : message.coverageStatus === "partial" ? "资料有限" : "资料不足" }}</span>
                  <small>{{ message.confidence === "high" ? "高置信度" : message.confidence === "medium" ? "中置信度" : "低置信度" }}</small>
                </div>
                <p class="knowledge-explanation">{{ message.answer.explanation_3min }}</p>
                <p v-if="message.coverageStatus === 'insufficient' && message.gapId" class="knowledge-gap-note">
                  已记录为待补充主题：{{ message.gapId.slice(0, 8) }}
                </p>
                <section v-if="message.answer.actions.length" class="knowledge-section">
                  <strong>可以先做</strong>
                  <ul>
                    <li v-for="action in message.answer.actions" :key="action">{{ action }}</li>
                  </ul>
                </section>
                <section v-if="message.answer.seek_help_when.length" class="knowledge-section knowledge-section--safety">
                  <strong>需要现实支持时</strong>
                  <ul>
                    <li v-for="item in message.answer.seek_help_when" :key="item">{{ item }}</li>
                  </ul>
                </section>
                <section v-if="message.sourceRefs?.length" class="knowledge-sources" aria-label="回答来源">
                  <span>来源</span>
                  <button
                    v-for="item in message.sourceRefs"
                    :key="item.chunk_id || item.article_id"
                    type="button"
                    @click="openKnowledgeArticle(item.article_id)"
                  >
                    {{ item.article_title }} · {{ item.license || "未标注许可" }}
                  </button>
                </section>
                <section v-else-if="message.relatedArticles?.length" class="knowledge-sources" aria-label="相关条目">
                  <span>相关</span>
                  <button
                    v-for="item in message.relatedArticles"
                    :key="item.article_id"
                    type="button"
                    @click="openKnowledgeArticle(item.article_id)"
                  >
                    {{ item.title }}
                  </button>
                </section>
                <button class="text-action knowledge-feedback" type="button" @click="openFeedback('knowledge_answer', String(message.id))">评价答案</button>
                <button class="text-action knowledge-continue" type="button" @click="continueKnowledgeChat">
                  带到咨询对话里聊
                </button>
              </template>
              <span v-if="message.streaming" class="typing-dot"></span>
            </article>
          </div>

          <div v-if="shouldShowKnowledgePrompts" class="knowledge-prompts">
            <button
              v-for="prompt in knowledgePromptChips"
              :key="prompt"
              type="button"
              :disabled="isKnowledgeLoading"
              @click="askKnowledge(prompt)"
            >
              {{ prompt }}
            </button>
          </div>

          <article v-if="selectedKnowledgeArticle" class="knowledge-drawer">
            <div class="card-title">
              <h2>{{ selectedKnowledgeArticle.title }}</h2>
              <button type="button" @click="selectedKnowledgeArticle = null">收起</button>
            </div>
            <p>{{ selectedKnowledgeArticle.summary_30s }}</p>
            <p>{{ selectedKnowledgeArticle.explanation_3min }}</p>
          </article>

          <form class="knowledge-composer" @submit.prevent="askKnowledge()">
            <input v-model="knowledgeDraft" type="text" placeholder="直接问：我最近总是焦虑怎么办？" />
            <button type="submit" :disabled="!knowledgeDraft.trim() || isKnowledgeLoading">
              {{ isKnowledgeLoading ? "..." : "发送" }}
            </button>
          </form>
          </template>

          <template v-else>
            <section v-if="!quizSession && !quizResult" class="quiz-home">
              <div class="quiz-bank">
                <span>题库</span>
                <strong>{{ quizStats?.total ?? 2000 }} 题</strong>
                <small>ABCD · 判断 · 图片题</small>
              </div>
              <div class="quiz-modes">
                <button
                  v-for="option in quizModeOptions"
                  :key="option.id"
                  :class="['quiz-mode-card', { active: quizMode === option.id }]"
                  type="button"
                  @click="selectQuizMode(option.id)"
                >
                  <strong>{{ option.label }}</strong>
                  <span>{{ option.description }}</span>
                </button>
              </div>
              <button class="primary-action" type="button" :disabled="isQuizLoading" @click="startKnowledgeQuiz()">
                {{ isQuizLoading ? "出题中..." : "开始闯关" }}
              </button>
            </section>

            <section v-else-if="quizSession && !quizResult && currentQuizQuestion" class="quiz-play">
              <div class="quiz-progress">
                <div class="quiz-progress__head">
                  <div>
                    <span>{{ activeQuizIndex + 1 }} / {{ quizSession.total }}</span>
                    <strong>{{ currentQuizQuestion.topic }}</strong>
                    <small>{{ quizTypeLabel(currentQuizQuestion.type) }} · 难度 {{ currentQuizQuestion.difficulty }}</small>
                  </div>
                  <button class="quiz-reset-action" type="button" @click="resetKnowledgeQuiz">重新开始</button>
                </div>
                <div class="quiz-progress__bar"><i :style="{ width: `${quizProgressPercent}%` }"></i></div>
              </div>

              <article class="quiz-question">
                <div v-if="currentQuizQuestion.visual" class="quiz-visual" :class="`quiz-visual--${currentQuizQuestion.visual.kind}`">
                  <strong>{{ currentQuizQuestion.visual.title }}</strong>
                  <span v-for="line in currentQuizQuestion.visual.lines" :key="line">{{ line }}</span>
                </div>
                <h2>{{ currentQuizQuestion.stem }}</h2>
                <div class="quiz-options">
                  <button
                    v-for="option in currentQuizQuestion.options"
                    :key="option.key"
                    :class="{ active: quizAnswers[currentQuizQuestion.question_id] === option.key }"
                    type="button"
                    @click="chooseQuizAnswer(currentQuizQuestion.question_id, option.key)"
                  >
                    <span>{{ option.key }}</span>
                    <strong>{{ option.text }}</strong>
                  </button>
                </div>
              </article>

              <div class="quiz-actions">
                <button class="secondary-action" type="button" :disabled="activeQuizIndex === 0" @click="goQuizQuestion(-1)">上一题</button>
                <button
                  v-if="activeQuizIndex < quizSession.total - 1"
                  class="primary-action"
                  type="button"
                  :disabled="!quizAnswers[currentQuizQuestion.question_id]"
                  @click="goQuizQuestion(1)"
                >
                  下一题
                </button>
                <button
                  v-else
                  class="primary-action"
                  type="button"
                  :disabled="!canSubmitQuiz || isQuizLoading"
                  @click="submitKnowledgeQuiz"
                >
                  {{ isQuizLoading ? "判分中..." : "交卷" }}
                </button>
              </div>
            </section>

            <section v-else-if="quizResult" class="quiz-result">
              <div class="quiz-title-card">
                <span>{{ quizResult.correct }} / {{ quizResult.total }}</span>
                <h2>{{ quizResult.title }}</h2>
                <p>{{ quizResult.title_description }}</p>
              </div>
              <div class="quiz-result-meta">
                <span>正确率 {{ Math.round(quizResult.accuracy * 100) }}%</span>
                <span>错题 {{ quizWrongCount }} 道</span>
              </div>
              <div class="quiz-review-grid" aria-label="题号总览">
                <button
                  v-for="(item, index) in quizResult.review"
                  :key="item.question_id"
                  :class="['quiz-review-number', { active: activeReviewIndex === index, correct: item.is_correct, wrong: !item.is_correct }]"
                  type="button"
                  @click="activeReviewIndex = index"
                >
                  {{ index + 1 }}
                </button>
              </div>
              <article v-if="activeReviewItem" class="quiz-review-detail">
                <div class="quiz-review-detail__head">
                  <span :class="activeReviewItem.is_correct ? 'correct' : 'wrong'">
                    第 {{ activeReviewIndex + 1 }} 题 · {{ activeReviewItem.is_correct ? "答对" : "答错" }}
                  </span>
                  <small>{{ activeReviewItem.question.topic }} · {{ quizTypeLabel(activeReviewItem.question.type) }}</small>
                </div>
                <div v-if="activeReviewItem.question.visual" class="quiz-visual" :class="`quiz-visual--${activeReviewItem.question.visual.kind}`">
                  <strong>{{ activeReviewItem.question.visual.title }}</strong>
                  <span v-for="line in activeReviewItem.question.visual.lines" :key="line">{{ line }}</span>
                </div>
                <h3>{{ activeReviewItem.question.stem }}</h3>
                <div class="quiz-review-options">
                  <div
                    v-for="option in activeReviewItem.question.options"
                    :key="option.key"
                    :class="{
                      correct: option.key === activeReviewItem.correct_answer,
                      wrong: option.key === activeReviewItem.user_answer && !activeReviewItem.is_correct,
                    }"
                  >
                    <span>{{ option.key }}</span>
                    <strong>{{ option.text }}</strong>
                  </div>
                </div>
                <div class="quiz-answer-compare">
                  <p>你的答案：{{ reviewAnswerLabel(activeReviewItem.user_answer) }}</p>
                  <p>正确答案：{{ reviewAnswerLabel(activeReviewItem.correct_answer) }}</p>
                </div>
                <section class="quiz-explanation">
                  <strong>本题讲解</strong>
                  <p>{{ activeReviewItem.explanation }}</p>
                  <small>{{ activeReviewItem.source_title }}</small>
                </section>
              </article>
              <div class="quiz-actions">
                <button class="secondary-action" type="button" @click="resetKnowledgeQuiz">返回模式选择</button>
                <button class="primary-action" type="button" @click="startKnowledgeQuiz(quizResult.mode)">再来一轮</button>
              </div>
            </section>
          </template>
        </section>

        <section v-else class="tab-page profile-page">
          <section class="profile-card">
            <div class="avatar">{{ userName.slice(0, 1) }}</div>
            <div>
              <h2>{{ userName }}</h2>
              <p>{{ selectedAgeLabel }} · {{ modeLabel }}</p>
            </div>
          </section>

          <section class="summary-card">
            <div class="card-title">
              <h2>陪伴设置</h2>
              <span>自动保存</span>
            </div>
            <p>{{ selectedStyleLabel }} · {{ selectedGoalLabel }}</p>
          </section>

          <div class="choice-section compact">
            <h2>风格</h2>
            <button
              v-for="option in styleOptions"
              :key="option.id"
              :class="['choice-row', { active: selectedStyle === option.id }]"
              type="button"
              @click="selectedStyle = option.id"
            >
              <strong>{{ option.label }}</strong>
              <span>{{ option.description }}</span>
            </button>
          </div>

          <section class="section-block memory-center">
            <div class="section-title">
              <h2>记忆中心</h2>
              <span>{{ memoryModeLabel }}</span>
            </div>

            <div class="memory-mode-control" role="radiogroup" aria-label="记忆模式">
              <button
                v-for="option in memoryModeOptions"
                :key="option.id"
                :class="{ active: currentMemoryMode === option.id }"
                type="button"
                :disabled="isSettingsSaving"
                @click="changeMemoryMode(option.id)"
              >
                <strong>{{ option.label }}</strong>
                <span>{{ option.description }}</span>
              </button>
            </div>

            <p v-if="memoryError" class="notice notice--error">{{ memoryError }}</p>

            <article class="memory-document-card">
              <div class="memory-document-main">
                <h3>记忆文档</h3>
                <p>把当前可见的记忆集中在一个文档里查看与下载。</p>
                <small v-if="memories.length">当前可见记忆：{{ memories.length }} 条</small>
                <small v-else>当前没有可见记忆。</small>
              </div>
              <div class="memory-document-actions">
                <button class="secondary-action" type="button" :disabled="isMemoryDocLoading" @click="openMemoryDocument">
                  查看
                </button>
                <button class="text-action" type="button" :disabled="isMemoryDocLoading" @click="downloadMemoryDocument">
                  下载 .md
                </button>
              </div>
            </article>
          </section>

          <section class="section-block privacy-center">
            <div class="section-title">
              <h2>隐私与数据</h2>
              <span>{{ privacyLatestActivity }}</span>
            </div>

            <div class="privacy-settings-grid">
              <article class="privacy-setting-card">
                <strong>语音转写</strong>
                <span>{{ saveTranscript ? "保存" : "不保存" }}</span>
                <button
                  class="text-action"
                  type="button"
                  :disabled="isSettingsSaving"
                  @click="updatePrivacySetting({ save_transcript: !saveTranscript })"
                >
                  {{ saveTranscript ? "关闭" : "开启" }}
                </button>
              </article>
              <article class="privacy-setting-card">
                <strong>原始音频</strong>
                <span>{{ isTeenMode ? "青少年默认关闭" : saveVoiceAudio ? "保存" : "不保存" }}</span>
                <button
                  class="text-action"
                  type="button"
                  :disabled="isSettingsSaving || isTeenMode"
                  @click="updatePrivacySetting({ save_voice_audio: !saveVoiceAudio })"
                >
                  {{ saveVoiceAudio ? "关闭" : "开启" }}
                </button>
              </article>
            </div>

            <div class="privacy-count-grid">
              <span>记忆 {{ privacyCounts.memories }}</span>
              <span>会话 {{ privacyCounts.chat_threads }}</span>
              <span>消息 {{ privacyCounts.chat_messages }}</span>
              <span>情绪 {{ privacyCounts.mood_logs }}</span>
              <span>测试 {{ privacyCounts.test_history }}</span>
              <span>反馈 {{ privacyCounts.feedback }}</span>
              <span>语音 {{ privacyCounts.voice_sessions }}</span>
              <span>安全 {{ privacyCounts.risk_events }}</span>
            </div>

            <article class="privacy-export-card">
              <div>
                <h3>个人数据导出</h3>
                <p>JSON 文件包含账号资料、记忆、聊天、情绪、测试历史、反馈和语音会话元数据。</p>
              </div>
              <button class="secondary-action" type="button" :disabled="isPrivacyLoading" @click="openPrivacyExport">
                导出
              </button>
            </article>

            <div class="privacy-delete-grid">
              <button
                v-for="option in privacyDeleteOptions"
                :key="option.id"
                type="button"
                :class="['privacy-delete-btn', { confirm: pendingPrivacyScope === option.id }]"
                :disabled="isPrivacyLoading"
                @click="deletePrivacyScope(option.id)"
              >
                <strong>{{ pendingPrivacyScope === option.id ? '确认清除' : option.label }}</strong>
                <span>{{ option.description }}</span>
              </button>
            </div>

            <div class="account-delete-card">
              <div>
                <h3>注销账号</h3>
                <p>输入 DELETE 后注销账号并退出登录。</p>
              </div>
              <input v-model="deleteAccountConfirm" type="text" autocomplete="off" placeholder="DELETE" />
              <button
                class="danger-action"
                type="button"
                :disabled="deleteAccountConfirm !== 'DELETE' || isPrivacyLoading"
                @click="deleteCurrentAccount"
              >
                注销
              </button>
            </div>

            <p v-if="privacyNotice" class="notice">{{ privacyNotice }}</p>
            <p v-if="privacyError" class="notice notice--error">{{ privacyError }}</p>
          </section>

          <button class="secondary-action logout-action" type="button" @click="logout">
            {{ isDemoMode ? "退出演示" : "退出登录" }}
          </button>
        </section>

        <nav class="bottom-nav" aria-label="底部导航">
          <button :class="{ active: activeTab === 'home' }" type="button" @click="activeTab = 'home'">首页</button>
          <button :class="{ active: activeTab === 'chat' }" type="button" @click="activeTab = 'chat'">对话</button>
          <button :class="{ active: activeTab === 'tests' }" type="button" @click="activeTab = 'tests'">测试</button>
          <button :class="{ active: activeTab === 'knowledge' }" type="button" @click="activeTab = 'knowledge'">知识</button>
          <button :class="{ active: activeTab === 'profile' }" type="button" @click="activeTab = 'profile'">我的</button>
        </nav>
      </section>

      <section
        v-if="isThreadDrawerOpen"
        class="thread-drawer-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="会话列表"
        @click.self="closeThreadDrawer"
      >
        <aside class="thread-drawer">
          <header class="thread-drawer__header">
            <div>
              <h2>会话</h2>
              <span>{{ visibleThreads.length }} 个会话</span>
            </div>
            <button class="thread-drawer__close" type="button" @click="closeThreadDrawer">关闭</button>
          </header>

          <input
            v-model="threadSearchQuery"
            class="thread-search-input"
            type="search"
            placeholder="搜索会话"
            aria-label="搜索会话"
          />

          <button class="thread-drawer__new" type="button" :disabled="isCreatingThread" @click="createChatThread">
            {{ isCreatingThread ? "创建中..." : "新建会话" }}
          </button>

          <div class="thread-drawer__list">
            <p v-if="visibleThreads.length === 0" class="thread-drawer__empty">还没有会话</p>
            <p v-else-if="filteredThreads.length === 0" class="thread-drawer__empty">没有找到相关会话</p>
            <button
              v-for="thread in filteredThreads"
              :key="thread.thread_id"
              :class="['thread-drawer__item', { active: activeThreadId === thread.thread_id }]"
              type="button"
              @click="selectThreadFromDrawer(thread.thread_id)"
            >
              <span class="thread-drawer__item-main">
                <strong>{{ thread.title }}</strong>
                <span>{{ thread.last_summary || "还没有摘要，打开后继续。" }}</span>
              </span>
              <span class="thread-drawer__item-meta">
                <small>{{ formatTime(thread.updated_at) }}</small>
                <span :class="['risk-pill', riskClass(thread.last_risk_level)]">
                  {{ riskLabel(thread.last_risk_level) }}
                </span>
              </span>
            </button>
          </div>
        </aside>
      </section>

      <section v-if="isMemoryDocOpen" class="memory-document-viewer" role="dialog" aria-modal="true">
        <div class="memory-document-panel">
          <header class="memory-document-header">
            <div>
              <h3>记忆文档</h3>
              <small>{{ memoryModeLabel }}</small>
            </div>
            <button class="text-action" type="button" @click="closeMemoryDocument">关闭</button>
          </header>
          <div class="memory-document-body">
            <p v-if="isMemoryDocLoading" class="empty-copy">正在生成记忆文档...</p>
            <p v-else-if="memoryDocError" class="notice notice--error">{{ memoryDocError }}</p>
            <pre v-else class="memory-document-content">{{ memoryDocContent }}</pre>
          </div>
          <footer class="memory-document-footer">
            <button class="secondary-action" type="button" :disabled="isMemoryDocLoading" @click="downloadMemoryDocument">
              下载 .md
            </button>
          </footer>
        </div>
      </section>

      <section v-if="isPrivacyExportOpen" class="memory-document-viewer" role="dialog" aria-modal="true">
        <div class="memory-document-panel">
          <header class="memory-document-header">
            <div>
              <h3>个人数据摘要</h3>
              <small>JSON 导出</small>
            </div>
            <button class="text-action" type="button" @click="closePrivacyExport">关闭</button>
          </header>
          <div class="memory-document-body">
            <pre class="memory-document-content">{{ privacyExportPreview }}</pre>
          </div>
          <footer class="memory-document-footer">
            <button class="secondary-action" type="button" @click="downloadPrivacyJson">
              下载 .json
            </button>
          </footer>
        </div>
      </section>

      <!-- 分享卡弹层 -->
      <section v-if="shareCardVisible && shareCardData" class="share-card-overlay" role="dialog" aria-modal="true" @click.self="closeShareCard">
        <div class="share-card" :class="'share-card--' + shareCardData.testType">
          <header class="share-card__header">
            <h2 class="share-card__title">{{ shareCardData.resultLabel }}</h2>
            <p class="share-card__subtitle">{{ shareCardData.title }}</p>
          </header>
          <p class="share-card__tagline">—— {{ shareCardData.subtitle }}</p>
          <p class="share-card__type-badge" v-if="shareCardData.sixteenTypeCode">{{ shareCardData.sixteenTypeCode }}</p>
          <p class="share-card__summary">{{ shareCardData.summary }}</p>
          <div v-if="shareCardData.highlights.length" class="share-card__highlights">
            <span v-for="h in shareCardData.highlights" :key="h">{{ h }}</span>
          </div>
          <p class="share-card__disclaimer">{{ shareCardData.disclaimer }}</p>
          <div class="share-card__actions">
            <button class="primary-action" type="button" :disabled="shareCardSaving" @click="downloadShareImage">
              {{ shareCardSaving ? '生成中...' : '保存图片' }}
            </button>
            <button class="secondary-action" type="button" @click="copyShareCard">
              {{ shareCardCopied ? '已复制' : '复制文案' }}
            </button>
            <button class="text-action" type="button" @click="closeShareCard">关闭</button>
          </div>
        </div>
      </section>

      <!-- 反馈弹层 -->
      <section v-if="feedbackVisible" class="feedback-overlay" role="dialog" aria-modal="true" @click.self="closeFeedback">
        <div class="feedback-panel">
          <h2>{{ feedbackDone ? '感谢反馈' : '给这个回复评分' }}</h2>
          <template v-if="!feedbackDone">
            <div class="feedback-stars" aria-label="评分">
              <button
                v-for="n in 5"
                :key="n"
                :class="{ active: feedbackRating >= n }"
                type="button"
                @click="feedbackRating = n"
              >
                {{ feedbackRating >= n ? '★' : '☆' }}
              </button>
            </div>
            <textarea v-model="feedbackNote" class="feedback-note" rows="3" maxlength="300" placeholder="补充说明（选填）"></textarea>
            <div class="feedback-actions">
              <button class="primary-action" type="button" :disabled="feedbackRating === 0" @click="submitFeedback">
                提交
              </button>
              <button class="text-action" type="button" @click="closeFeedback">取消</button>
            </div>
          </template>
          <template v-else>
            <p class="feedback-done-msg">你的反馈帮助我做得更好。</p>
            <button class="text-action" type="button" @click="closeFeedback">关闭</button>
          </template>
        </div>
      </section>

      <!-- 每周情绪小结弹层 -->
      <section v-if="isWeeklySummaryOpen && weeklySummary" class="weekly-summary-overlay" role="dialog" aria-modal="true" @click.self="closeWeeklySummary">
        <div class="weekly-summary-panel">
          <h2>{{ moodRange === '30d' ? '近30天情绪小结' : '本周情绪小结' }}</h2>
          <p class="weekly-summary__range">{{ weeklySummary.range }} 回顾</p>
          <p class="weekly-summary__text">{{ weeklySummary.summary }}</p>
          <div v-if="weeklySummary.top_tags.length" class="weekly-summary__tags">
            <span>最常出现</span>
            <div>
              <span v-for="tag in weeklySummary.top_tags" :key="tag" class="weekly-summary-tag">{{ tag }}</span>
            </div>
          </div>
          <div v-if="weeklySummary.suggested_actions.length" class="weekly-summary__actions">
            <span>建议</span>
            <ul>
              <li v-for="action in weeklySummary.suggested_actions" :key="action">{{ action }}</li>
            </ul>
          </div>
          <button class="text-action" type="button" @click="closeWeeklySummary">关闭</button>
        </div>
      </section>

      <section v-if="isSafetyOpen" class="safety-screen" role="dialog" aria-modal="true">
        <header>
          <button class="text-action" type="button" @click="closeSafety">返回</button>
          <span>SOS</span>
        </header>
        <div class="safety-content">
          <h1>如果你现在觉得不安全，请不要一个人扛着。</h1>
          <p>先联系现实中的人。你不需要独自处理这一刻。</p>
          <button class="alert-action" type="button" @click="safetyAction = 'trusted'">联系可信任的人</button>
          <button class="secondary-action" type="button" @click="safetyAction = 'resources'">查看本地求助资源</button>
          <button class="secondary-action" type="button" @click="safetyAction = 'breathing'">做 60 秒稳定呼吸</button>

          <article v-if="safetyAction" class="safety-note">
            <template v-if="safetyAction === 'trusted'">
              <strong>可以直接发出这句话</strong>
              <p>“我现在状态不太好，能不能陪我一下？我想现在就联系你。”</p>
            </template>
            <template v-else-if="safetyAction === 'resources'">
              <strong>优先考虑现实支持</strong>
              <p>家人、可信任的大人、学校心理老师、当地急救或心理援助热线。</p>
            </template>
            <template v-else>
              <strong>60 秒节奏</strong>
              <p>吸气 4 秒，停 1 秒，呼气 6 秒，重复 3 次。</p>
            </template>
          </article>
        </div>
      </section>
    </section>
  </main>
</template>

<style>
.app-canvas {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 20% 0%, rgba(213, 235, 226, 0.8), transparent 28%),
    linear-gradient(180deg, #f7f6f1 0%, #edf3ef 100%);
}

.phone-shell {
  position: relative;
  width: min(100%, 430px);
  height: min(100vh, 900px);
  min-height: 760px;
  overflow: hidden;
  background: var(--app-bg);
  color: var(--text-main);
  box-shadow: 0 24px 70px rgba(38, 57, 52, 0.18);
}

.app-screen,
.boot-screen,
.safety-screen {
  height: 100%;
  overflow-y: auto;
}

.boot-screen {
  display: grid;
  place-content: center;
  gap: 14px;
  padding: 32px;
  text-align: center;
}

.brand-dot,
.top-label {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  padding: 7px 10px;
  border-radius: 999px;
  background: var(--mint-soft);
  color: var(--teal-dark);
  font-size: 12px;
  font-weight: 800;
}

.auth-screen,
.onboarding-screen {
  padding: 28px 22px;
}

.auth-hero {
  display: grid;
  gap: 12px;
  margin-bottom: 24px;
}

.auth-hero h1,
.screen-header h1,
.app-header h1,
.safety-content h1 {
  margin: 0;
  font-size: 32px;
  line-height: 1.16;
  letter-spacing: 0;
}

.auth-hero p,
.screen-header p,
.summary-card p,
.thread-card p,
.profile-card p,
.safety-content p,
.empty-copy,
.empty-chat p,
.memory-document-card {
  margin: 0;
  color: var(--text-muted);
  line-height: 1.65;
}

.segmented {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 6px;
  border-radius: 18px;
  background: var(--surface-muted);
  margin-bottom: 18px;
}

.segmented button,
.bottom-nav button {
  min-height: 44px;
  border-radius: 14px;
  background: transparent;
  color: var(--text-muted);
  font-weight: 700;
}

.segmented button.active,
.bottom-nav button.active {
  background: #ffffff;
  color: var(--teal-dark);
  box-shadow: var(--shadow-soft);
}

.auth-form,
.choice-section,
.tab-page,
.section-block {
  display: grid;
  gap: 14px;
}

.field {
  display: grid;
  gap: 8px;
}

.field span,
.choice-section h2,
.section-title h2,
.card-title h2 {
  margin: 0;
  color: var(--text-main);
  font-size: 15px;
  font-weight: 800;
}

.field input,
.composer input,
.knowledge-composer input {
  min-height: 52px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: #ffffff;
  padding: 0 14px;
  color: var(--text-main);
}

.captcha-line {
  display: grid;
  grid-template-columns: 124px 1fr;
  gap: 10px;
}

.captcha-image {
  min-height: 52px;
  border-radius: 16px;
  background: #ffffff;
  border: 1px solid var(--line);
}

.captcha-image img {
  max-width: 112px;
  max-height: 44px;
}

.age-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.age-option,
.choice-row {
  min-height: 76px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #ffffff;
  padding: 14px;
  display: grid;
  gap: 5px;
  text-align: left;
}

.age-option.active,
.choice-row.active {
  border-color: var(--teal);
  background: var(--mint-soft);
}

.age-option strong,
.choice-row strong,
.thread-card strong {
  color: var(--text-main);
  font-size: 15px;
}

.age-option span,
.choice-row span {
  color: var(--text-muted);
  font-size: 12px;
}

.primary-action,
.secondary-action,
.alert-action {
  min-height: 52px;
  border-radius: 17px;
  padding: 0 16px;
  font-weight: 800;
}

.primary-action {
  background: var(--teal);
  color: #ffffff;
}

.primary-action:disabled {
  background: #c7d5cf;
  color: #f8faf8;
  cursor: not-allowed;
}

.secondary-action {
  background: #ffffff;
  color: var(--text-main);
  border: 1px solid var(--line);
}

.alert-action {
  background: var(--amber);
  color: #4b3215;
}

.text-action {
  width: fit-content;
  background: transparent;
  color: var(--teal-dark);
  font-weight: 800;
}

.notice {
  margin: 0;
  border-radius: 14px;
  padding: 11px 12px;
  font-size: 13px;
  line-height: 1.5;
}

.notice--error {
  background: #fff1e7;
  color: #9a4a25;
}

.notice--info {
  background: #edf7ef;
  color: var(--teal-dark);
}

.screen-header {
  display: grid;
  gap: 12px;
  margin-bottom: 22px;
}

.choice-section.compact {
  gap: 10px;
}

.sticky-actions {
  position: sticky;
  bottom: 0;
  display: grid;
  gap: 10px;
  padding-top: 12px;
  background: linear-gradient(180deg, rgba(250, 249, 246, 0), var(--app-bg) 28%);
}

.main-screen {
  padding: 20px 18px 96px;
}

.app-header {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.app-header h1 {
  margin-top: 9px;
  font-size: 28px;
}

.sos-button {
  min-width: 56px;
  height: 40px;
  border-radius: 999px;
  background: #fff2d7;
  color: #9b5d12;
  font-weight: 900;
}

.mood-checkin-card {
  border: 1px solid rgba(15, 118, 110, 0.14);
  border-radius: 22px;
  background: #ffffff;
  padding: 16px;
  display: grid;
  gap: 14px;
  box-shadow: var(--shadow-soft);
}

.mood-checkin-card .card-title {
  align-items: flex-start;
}

.mood-checkin-card .card-title > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.mood-checkin-card .card-title h2 {
  margin: 0;
  color: var(--text-main);
  font-size: 18px;
  line-height: 1.25;
}

.mood-checkin-card .card-title strong {
  min-width: 50px;
  border-radius: 14px;
  padding: 8px 10px;
  background: #fff6e4;
  color: #8a5517;
  text-align: center;
  font-size: 14px;
}

.mood-scale-list {
  display: grid;
  gap: 10px;
}

.mood-scale {
  display: grid;
  gap: 7px;
}

.mood-scale span {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 900;
}

.mood-scale strong {
  color: var(--teal-dark);
}

.mood-scale input {
  width: 100%;
  accent-color: var(--teal);
}

.mood-tags,
.trend-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mood-tags button,
.trend-tags span {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #f8fbf8;
  color: var(--text-muted);
  padding: 7px 10px;
  font-size: 12px;
  font-weight: 900;
}

.mood-tags button.active,
.trend-tags span {
  border-color: rgba(15, 118, 110, 0.2);
  background: var(--mint-soft);
  color: var(--teal-dark);
}

.mood-note {
  width: 100%;
  min-height: 74px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: #ffffff;
  padding: 12px 14px;
  color: var(--text-main);
  outline: none;
}

.mood-card {
  min-height: 164px;
  border-radius: 28px;
  padding: 22px;
  text-align: left;
  display: grid;
  align-content: center;
  gap: 9px;
  background: linear-gradient(135deg, #dff3ec, #f0f7e7);
  color: var(--text-main);
  box-shadow: var(--shadow-soft);
}

.mood-card span,
.mood-card small {
  color: var(--teal-dark);
  font-weight: 800;
}

.mood-card strong {
  font-size: 24px;
  line-height: 1.2;
}

.trend-card {
  display: grid;
  gap: 12px;
}

.range-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(44px, 1fr));
  gap: 4px;
  border-radius: 999px;
  background: var(--surface-muted);
  padding: 4px;
}

.range-switch button {
  min-height: 30px;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  padding: 0 9px;
  font-size: 12px;
  font-weight: 900;
}

.range-switch button.active {
  background: #ffffff;
  color: var(--teal-dark);
  box-shadow: 0 5px 14px rgba(38, 57, 52, 0.1);
}

.range-switch button:disabled {
  opacity: 0.58;
  cursor: not-allowed;
}

.trend-bars {
  min-height: 88px;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(34px, 1fr);
  gap: 8px;
  align-items: end;
  overflow-x: auto;
  padding-top: 4px;
}

.trend-bar {
  min-width: 34px;
  display: grid;
  justify-items: center;
  gap: 6px;
}

.trend-bar i {
  width: 16px;
  border-radius: 999px 999px 6px 6px;
  background: linear-gradient(180deg, var(--teal), #f0c66f);
}

.trend-bar span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.summary-card,
.profile-card,
.thread-card,
.memory-document-card {
  border-radius: 22px;
  background: #ffffff;
  padding: 16px;
  box-shadow: var(--shadow-soft);
}

.card-title,
.section-title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.card-title span,
.section-title span,
.section-title button {
  color: var(--text-muted);
  background: transparent;
  font-size: 12px;
  font-weight: 800;
}

.thread-card {
  width: 100%;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  text-align: left;
}

.thread-card p {
  margin-top: 5px;
  font-size: 13px;
}

.risk-pill {
  align-self: start;
  border-radius: 999px;
  padding: 6px 8px;
  font-size: 11px;
  font-weight: 900;
}

.thread-drawer-overlay {
  position: absolute;
  inset: 0;
  z-index: 19;
  display: flex;
  align-items: stretch;
  background: rgba(15, 20, 18, 0.42);
}

.thread-drawer {
  width: min(90%, 360px);
  height: 100%;
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  gap: 12px;
  padding: 20px 14px;
  background: #fbfdfb;
  box-shadow: 18px 0 42px rgba(38, 57, 52, 0.2);
  animation: threadDrawerIn 0.18s ease-out;
}

.thread-drawer__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.thread-drawer__header h2 {
  margin: 0 0 4px;
  color: var(--text-main);
  font-size: 20px;
}

.thread-drawer__header span,
.thread-drawer__item-main span,
.thread-drawer__item-meta small,
.thread-drawer__empty {
  color: var(--text-muted);
}

.thread-drawer__header span,
.thread-drawer__item-meta small {
  font-size: 12px;
  font-weight: 800;
}

.thread-drawer__close {
  flex: 0 0 auto;
  min-height: 34px;
  border-radius: 12px;
  padding: 0 12px;
  background: var(--surface-muted);
  color: var(--text-main);
  font-size: 12px;
  font-weight: 900;
}

.thread-search-input {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #ffffff;
  padding: 0 12px;
  color: var(--text-main);
}

.thread-drawer__new {
  min-height: 44px;
  border-radius: 14px;
  background: var(--teal);
  color: #ffffff;
  font-weight: 900;
}

.thread-drawer__list {
  min-height: 0;
  overflow-y: auto;
  display: grid;
  align-content: start;
  gap: 8px;
  padding-right: 2px;
}

.thread-drawer__item {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  border: 1px solid transparent;
  border-radius: 14px;
  background: transparent;
  padding: 11px 10px;
  text-align: left;
}

.thread-drawer__item.active {
  border-color: rgba(15, 118, 110, 0.26);
  background: var(--mint-soft);
}

.thread-drawer__item-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.thread-drawer__item-main strong,
.thread-drawer__item-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thread-drawer__item-main strong {
  color: var(--text-main);
  font-size: 14px;
  line-height: 1.35;
}

.thread-drawer__item-main span {
  font-size: 12px;
  line-height: 1.45;
}

.thread-drawer__item-meta {
  display: grid;
  justify-items: end;
  gap: 6px;
}

.thread-drawer__empty {
  margin: 20px 4px 0;
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}

.risk--steady {
  background: #e8f4ee;
  color: #28745d;
}

.risk--watch {
  background: #edf0d9;
  color: #7a6d26;
}

.risk--warning {
  background: #fff2d7;
  color: #9b5d12;
}

.risk--critical {
  background: #ffe7dd;
  color: #a33d21;
}

.chat-page {
  height: calc(100dvh - 268px);
  min-height: 440px;
  grid-template-rows: auto minmax(0, 1fr) auto auto auto;
}

.chat-thread-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.thread-menu-button,
.thread-new-button {
  min-height: 38px;
  border-radius: 14px;
  padding: 0 15px;
  font-size: 13px;
  font-weight: 900;
}

.thread-menu-button {
  flex: 1;
  min-width: 0;
  background: #ffffff;
  color: var(--text-main);
  border: 1px solid var(--line);
  text-align: left;
}

.thread-new-button {
  flex: 0 0 auto;
  background: var(--teal);
  color: #ffffff;
}

.thread-new-button:disabled,
.thread-drawer__new:disabled {
  background: #c7d5cf;
  color: #f8faf8;
  cursor: not-allowed;
}

.quick-actions {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 10px 0 4px;
}

.quick-actions::-webkit-scrollbar {
  display: none;
}

.quick-actions button {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 6px 14px;
  background: #ffffff;
  color: var(--text-muted);
  border: 1px solid var(--line);
  font-weight: 500;
  font-size: 12px;
  white-space: nowrap;
}

.quick-actions button:active {
  background: var(--mint-soft);
  color: var(--teal-dark);
  border-color: var(--teal);
}

.quick-actions button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.thread-tabs {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}

.thread-tabs::-webkit-scrollbar {
  display: none;
}

.thread-tabs button {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 9px 12px;
  background: #ffffff;
  color: var(--text-muted);
  border: 1px solid var(--line);
  font-weight: 800;
  font-size: 12px;
}

.thread-tabs button.active {
  color: var(--teal-dark);
  background: var(--mint-soft);
  border-color: var(--teal);
}

.message-list {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 2px;
}

.message {
  position: relative;
  max-width: 84%;
  border-radius: 22px;
  padding: 13px 15px;
  display: grid;
  gap: 9px;
}

.message p {
  margin: 0;
  line-height: 1.65;
  white-space: pre-wrap;
}

.message-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: center;
}

.graph-status,
.stream-status {
  border-radius: 999px;
  padding: 6px 8px;
  background: #f4f7f5;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 900;
}

.stream-status {
  background: #fff6ed;
  color: #9a4a25;
}

.memory-reference {
  display: grid;
  gap: 7px;
  border-radius: 14px;
  background: #f5faf7;
  border: 1px solid rgba(30, 118, 103, 0.14);
  padding: 8px;
}

.memory-reference button {
  justify-self: start;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid var(--line);
  color: var(--teal-dark);
  padding: 6px 9px;
  font-size: 12px;
  font-weight: 900;
}

.memory-reference__list {
  display: grid;
  gap: 6px;
}

.memory-reference__list span {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.message-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.message-actions button {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #f8fbf8;
  color: var(--teal-dark);
  padding: 7px 9px;
  font-size: 12px;
  font-weight: 900;
}

.message-actions button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.message--assistant {
  align-self: flex-start;
  background: #ffffff;
  border-top-left-radius: 7px;
}

.message--user {
  align-self: flex-end;
  background: var(--teal);
  color: #ffffff;
  border-top-right-radius: 7px;
}

.typing-dot {
  position: absolute;
  right: 10px;
  bottom: 8px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--teal);
  animation: blink 0.8s infinite alternate;
}

.composer {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 6px;
}

.composer button {
  min-width: 64px;
  border-radius: 16px;
  background: var(--teal);
  color: #ffffff;
  font-weight: 900;
}

.composer button:disabled {
  background: #c7d5cf;
}

.knowledge-page {
  height: calc(100dvh - 268px);
  min-height: 440px;
  grid-template-rows: auto auto minmax(0, 1fr) auto auto;
  gap: 10px;
}

.knowledge-agent {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid rgba(30, 118, 103, 0.14);
  border-radius: 20px;
  padding: 13px;
  background: linear-gradient(135deg, #ffffff, #edf7ef);
}

.knowledge-agent__avatar {
  width: 48px;
  height: 48px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  background: #174f48;
  color: #ffffff;
  font-size: 22px;
  font-weight: 900;
}

.knowledge-agent span,
.knowledge-sources span {
  color: var(--teal-dark);
  font-size: 12px;
  font-weight: 900;
}

.knowledge-agent h2 {
  margin: 2px 0 0;
  font-size: 18px;
  line-height: 1.25;
}

.knowledge-mode-switch {
  align-self: start;
  margin-bottom: 0;
}

.knowledge-mode-switch button {
  min-height: 40px;
}

.knowledge-chat {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 2px;
}

.knowledge-message {
  position: relative;
  max-width: 92%;
  border-radius: 20px;
  padding: 13px 14px;
  box-shadow: var(--shadow-soft);
}

.knowledge-message p {
  margin: 0;
  line-height: 1.65;
}

.knowledge-message--assistant {
  align-self: flex-start;
  background: #ffffff;
  border-top-left-radius: 7px;
}

.knowledge-message--user {
  align-self: flex-end;
  background: var(--teal);
  color: #ffffff;
  border-top-right-radius: 7px;
}

.knowledge-explanation {
  margin-top: 8px !important;
  color: var(--text-muted);
}

.knowledge-guess {
  margin-top: 10px;
  display: grid;
  gap: 3px;
  border: 1px solid rgba(30, 118, 103, 0.16);
  border-radius: 14px;
  padding: 9px 10px;
  background: #f4faf6;
}

.knowledge-guess span {
  color: var(--teal-dark);
  font-size: 12px;
  font-weight: 900;
}

.knowledge-guess strong {
  color: var(--text-main);
  font-size: 14px;
  line-height: 1.45;
}

.knowledge-guess small {
  color: var(--text-muted);
  font-size: 12px;
}

.knowledge-coverage {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 10px 0 0;
  border-radius: 999px;
  padding: 6px 8px;
  font-size: 12px;
  font-weight: 900;
}

.knowledge-coverage small {
  font-size: 11px;
  color: inherit;
  opacity: 0.74;
}

.knowledge-coverage--sufficient {
  background: #e5f4ed;
  color: #247057;
}

.knowledge-coverage--partial {
  background: #fff2d7;
  color: #8a5517;
}

.knowledge-coverage--insufficient {
  background: #ffece2;
  color: #9a4a25;
}

.knowledge-coverage--out-of-scope {
  background: #edf0f3;
  color: #46515c;
}

.knowledge-gap-note {
  margin-top: 8px !important;
  border-radius: 12px;
  padding: 9px 10px;
  background: #fff6ed;
  color: #9a4a25;
  font-size: 13px;
}

.knowledge-section {
  margin-top: 10px;
  display: grid;
  gap: 6px;
}

.knowledge-section strong {
  font-size: 13px;
  color: var(--text-main);
}

.knowledge-section ul {
  margin: 0;
  padding-left: 18px;
  color: var(--text-muted);
  line-height: 1.65;
}

.knowledge-section--safety {
  border-top: 1px solid var(--line);
  padding-top: 10px;
}

.knowledge-sources {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}

.knowledge-sources button,
.knowledge-prompts button {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #f8fbf8;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 800;
}

.knowledge-sources button {
  padding: 7px 9px;
}

.knowledge-continue {
  margin-top: 10px;
}

.knowledge-prompts {
  min-width: 0;
}

.knowledge-prompts button {
  flex: 0 0 auto;
  padding: 9px 12px;
}

.knowledge-prompts button:disabled {
  opacity: 0.58;
}

.knowledge-drawer {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #ffffff;
  padding: 14px;
  box-shadow: var(--shadow-soft);
}

.knowledge-drawer p {
  margin: 0;
  color: var(--text-muted);
  line-height: 1.65;
}

.knowledge-drawer button {
  background: transparent;
  color: var(--teal-dark);
  font-size: 12px;
  font-weight: 900;
}

.knowledge-composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}

.knowledge-composer input {
  min-width: 0;
}

.knowledge-composer button {
  min-width: 64px;
  border-radius: 16px;
  background: var(--teal);
  color: #ffffff;
  font-weight: 900;
}

.knowledge-composer button:disabled {
  background: #c7d5cf;
}

.quiz-home,
.quiz-play,
.quiz-result {
  min-height: 0;
  display: grid;
  gap: 10px;
}

.quiz-play {
  grid-template-rows: auto auto auto;
  align-content: start;
}

.quiz-bank,
.quiz-progress,
.quiz-question,
.quiz-title-card,
.quiz-review article {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #ffffff;
  padding: 14px;
  box-shadow: var(--shadow-soft);
}

.quiz-bank {
  display: grid;
  gap: 4px;
}

.quiz-bank span,
.quiz-progress span,
.quiz-title-card span {
  color: var(--teal-dark);
  font-size: 12px;
  font-weight: 900;
}

.quiz-bank strong,
.quiz-title-card h2 {
  color: var(--text-main);
  font-size: 24px;
  line-height: 1.15;
}

.quiz-bank small,
.quiz-progress small,
.quiz-review small {
  color: var(--text-muted);
  font-size: 12px;
}

.quiz-modes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.quiz-mode-card {
  min-height: 78px;
  border: 1px solid var(--line);
  border-radius: 16px;
  display: grid;
  gap: 4px;
  align-content: center;
  background: #ffffff;
  color: var(--text-main);
}

.quiz-mode-card.active {
  border-color: var(--teal);
  background: var(--mint-soft);
}

.quiz-mode-card strong {
  font-size: 16px;
}

.quiz-mode-card span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 800;
}

.quiz-progress {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
}

.quiz-progress__head {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: start;
}

.quiz-progress__head > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.quiz-progress strong {
  font-size: 17px;
}

.quiz-reset-action {
  min-height: 32px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #ffffff;
  color: var(--teal-dark);
  padding: 0 10px;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.quiz-progress__bar {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #edf0f3;
}

.quiz-progress__bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--teal);
}

.quiz-question {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
}

.quiz-question h2 {
  margin: 0;
  font-size: 16px;
  line-height: 1.35;
}

.quiz-visual {
  min-height: 82px;
  border-radius: 16px;
  padding: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-content: center;
  background: linear-gradient(135deg, #eaf6f1, #fff7e8);
}

.quiz-visual strong {
  flex: 0 0 100%;
  color: var(--teal-dark);
  font-size: 15px;
}

.quiz-visual span {
  width: fit-content;
  border-radius: 999px;
  padding: 6px 9px;
  background: rgba(255, 255, 255, 0.78);
  color: var(--text-main);
  font-size: 12px;
  font-weight: 800;
}

.quiz-options {
  display: grid;
  gap: 6px;
}

.quiz-options button {
  min-height: 48px;
  border: 1px solid var(--line);
  border-radius: 13px;
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 8px;
  align-items: center;
  background: #fbfdfb;
  padding: 6px 10px;
  text-align: left;
}

.quiz-options button.active {
  border-color: var(--teal);
  background: #e8f4ee;
}

.quiz-options button span {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: #ffffff;
  color: var(--teal-dark);
  font-weight: 900;
}

.quiz-options button strong {
  color: var(--text-main);
  font-size: 12px;
  line-height: 1.35;
}

.quiz-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.quiz-actions .primary-action,
.quiz-actions .secondary-action {
  min-height: 46px;
  border-radius: 15px;
}

.quiz-result {
  overflow-y: auto;
}

.quiz-title-card {
  display: grid;
  gap: 7px;
  background: linear-gradient(135deg, #ffffff, #edf7ef);
}

.quiz-title-card h2,
.quiz-title-card p {
  margin: 0;
}

.quiz-title-card p {
  color: var(--text-muted);
  line-height: 1.6;
}

.quiz-result-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.quiz-result-meta span {
  border-radius: 14px;
  padding: 10px;
  background: #ffffff;
  color: var(--text-main);
  text-align: center;
  font-weight: 900;
  box-shadow: var(--shadow-soft);
}

.quiz-review {
  display: grid;
  gap: 8px;
}

.quiz-review-grid {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 6px;
}

.quiz-review-number {
  min-width: 0;
  height: 32px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: #ffffff;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 900;
}

.quiz-review-number.correct {
  background: #e8f4ee;
  color: #247057;
}

.quiz-review-number.wrong {
  background: #fff0e8;
  color: #9a4a25;
}

.quiz-review-number.active {
  border-color: var(--teal);
  box-shadow: 0 0 0 2px rgba(30, 118, 103, 0.12);
}

.quiz-review-detail {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: #ffffff;
  padding: 14px;
  box-shadow: var(--shadow-soft);
}

.quiz-review-detail__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.quiz-review-detail__head span {
  font-size: 12px;
  font-weight: 900;
}

.quiz-review-detail__head span.correct {
  color: #247057;
}

.quiz-review-detail__head span.wrong {
  color: #9a4a25;
}

.quiz-review-detail__head small,
.quiz-explanation small {
  color: var(--text-muted);
  font-size: 12px;
}

.quiz-review-detail h3 {
  margin: 0;
  color: var(--text-main);
  font-size: 15px;
  line-height: 1.45;
}

.quiz-review-options {
  display: grid;
  gap: 6px;
}

.quiz-review-options div {
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 12px;
  display: grid;
  grid-template-columns: 26px 1fr;
  gap: 8px;
  align-items: center;
  padding: 6px 9px;
  background: #fbfdfb;
}

.quiz-review-options div.correct {
  border-color: rgba(36, 112, 87, 0.38);
  background: #e8f4ee;
}

.quiz-review-options div.wrong {
  border-color: rgba(154, 74, 37, 0.34);
  background: #fff0e8;
}

.quiz-review-options span {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: #ffffff;
  color: var(--teal-dark);
  font-weight: 900;
}

.quiz-review-options strong,
.quiz-explanation strong {
  color: var(--text-main);
  font-size: 13px;
  line-height: 1.55;
}

.quiz-answer-compare {
  display: grid;
  gap: 5px;
  border-radius: 12px;
  padding: 9px 10px;
  background: #f7faf8;
}

.quiz-answer-compare p,
.quiz-explanation p {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.quiz-explanation {
  display: grid;
  gap: 6px;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}

.empty-chat {
  margin: auto;
  text-align: center;
}

.profile-card {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar {
  width: 58px;
  height: 58px;
  border-radius: 22px;
  display: grid;
  place-items: center;
  background: var(--teal);
  color: #ffffff;
  font-size: 24px;
  font-weight: 900;
}

.profile-card h2 {
  margin: 0 0 4px;
}

.memory-center {
  padding-bottom: 4px;
}

.memory-mode-control {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.memory-mode-control button {
  min-width: 0;
  display: grid;
  gap: 4px;
  align-content: start;
  min-height: 78px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: #ffffff;
  color: var(--text-muted);
  padding: 10px;
  text-align: left;
}

.memory-mode-control button.active {
  border-color: var(--teal);
  background: var(--mint-soft);
  color: var(--teal-dark);
}

.memory-mode-control button:disabled,
.memory-document-actions button:disabled,
.memory-document-footer button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.memory-mode-control strong {
  color: inherit;
  font-size: 13px;
  line-height: 1.3;
}

.memory-mode-control span {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.35;
}

.memory-document-card {
  border-radius: 22px;
  background: #ffffff;
  padding: 16px;
  display: grid;
  gap: 12px;
  box-shadow: var(--shadow-soft);
}

.memory-document-main {
  display: grid;
  gap: 6px;
}

.memory-document-main h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-main);
}

.memory-document-main p,
.memory-document-main small {
  margin: 0;
  color: var(--text-muted);
  line-height: 1.6;
}

.memory-document-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.memory-document-actions .secondary-action {
  min-height: 44px;
}

.memory-document-viewer {
  position: absolute;
  inset: 0;
  z-index: 18;
  display: grid;
  align-items: center;
  padding: 18px;
  background: rgba(15, 20, 18, 0.38);
}

.memory-document-panel {
  width: 100%;
  max-height: min(82dvh, 760px);
  border-radius: 22px;
  background: #ffffff;
  padding: 16px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 12px;
  box-shadow: var(--shadow-soft);
}

.memory-document-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.memory-document-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-main);
}

.memory-document-header small {
  display: block;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
}

.memory-document-body {
  min-height: 0;
  display: grid;
}

.memory-document-content {
  width: 100%;
  height: 100%;
  min-height: 240px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fbfdfb;
  padding: 12px 14px;
  color: var(--text-main);
  font: inherit;
  line-height: 1.6;
  margin: 0;
  white-space: pre-wrap;
  overflow: auto;
}

.memory-document-footer {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  padding-top: 6px;
  border-top: 1px solid var(--line);
  background: #ffffff;
}

.privacy-center {
  display: grid;
  gap: 14px;
  padding-bottom: 6px;
}

.privacy-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.privacy-setting-card,
.privacy-export-card,
.account-delete-card {
  border-radius: 18px;
  background: #ffffff;
  padding: 14px;
  box-shadow: var(--shadow-soft);
}

.privacy-setting-card {
  display: grid;
  gap: 6px;
}

.privacy-setting-card strong,
.privacy-export-card h3,
.account-delete-card h3 {
  margin: 0;
  color: var(--text-main);
  font-size: 15px;
}

.privacy-setting-card span,
.privacy-export-card p,
.account-delete-card p {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.55;
}

.privacy-count-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.privacy-count-grid span {
  min-height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: var(--surface-muted);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 800;
}

.privacy-export-card {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  align-items: center;
}

.privacy-delete-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.privacy-delete-btn {
  min-width: 0;
  min-height: 72px;
  display: grid;
  gap: 4px;
  align-content: start;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: #ffffff;
  padding: 10px;
  text-align: left;
}

.privacy-delete-btn strong {
  color: var(--text-main);
  font-size: 13px;
}

.privacy-delete-btn span {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}

.privacy-delete-btn.confirm {
  border-color: rgba(154, 74, 37, 0.36);
  background: #fff0e8;
}

.account-delete-card {
  display: grid;
  gap: 10px;
}

.account-delete-card input {
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0 12px;
  color: var(--text-main);
  font: inherit;
}

.danger-action {
  min-height: 44px;
  border-radius: 14px;
  background: #9a4a25;
  color: #ffffff;
  font-weight: 800;
}

.danger-action:disabled,
.privacy-delete-btn:disabled,
.privacy-setting-card button:disabled,
.privacy-export-card button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.logout-action {
  margin-top: 4px;
}

.bottom-nav {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 14px;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  padding: 8px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(18px);
  box-shadow: 0 16px 40px rgba(38, 57, 52, 0.12);
}

.safety-screen {
  position: absolute;
  inset: 0;
  z-index: 20;
  background: var(--safety-bg);
  padding: 22px;
}

.safety-screen header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 900;
  color: #8a5517;
}

.safety-content {
  min-height: calc(100% - 42px);
  display: grid;
  align-content: center;
  gap: 14px;
}

.safety-note {
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.72);
  padding: 16px;
}

.safety-note p {
  margin-bottom: 0;
}

button:focus-visible,
input:focus-visible {
  outline: 2px solid rgba(15, 118, 110, 0.45);
  outline-offset: 2px;
}

@keyframes threadDrawerIn {
  from {
    transform: translateX(-16px);
    opacity: 0.88;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

@keyframes blink {
  from {
    opacity: 0.35;
  }
  to {
    opacity: 1;
  }
}

.tests-page {
  padding: 0 0 80px;
}

.test-category-tabs {
  display: flex;
  gap: 0;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
}

.test-category-tabs button {
  flex: 1;
  min-height: 36px;
  border-radius: 10px;
  background: transparent;
  color: var(--text-muted);
  font-weight: 700;
  font-size: 15px;
}

.test-category-tabs button.active {
  background: var(--mint-soft);
  color: var(--teal-dark);
}

.test-card-list {
  display: grid;
  gap: 14px;
  padding: 16px 22px;
}

.test-card {
  display: grid;
  gap: 8px;
  padding: 20px;
  border-radius: 18px;
  background: var(--surface-muted);
}

.test-card h2 {
  margin: 0;
  font-size: 18px;
}

.test-card__duration {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.test-card__soon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 0 18px;
  border-radius: 14px;
  background: #f0f0ed;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 700;
}

.test-card .primary-action {
  width: fit-content;
}

.tests-history {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.test-card__result {
  color: var(--text-muted);
  font-size: 15px;
  margin: 4px 0;
}

.result-code {
  color: var(--text-muted);
  font-size: 13px;
}

.history-result-detail {
  margin-top: 12px;
  padding: 12px;
  background: var(--surface-muted);
  border-radius: 8px;
}

.result-card--state {
  text-align: center;
}

.state-result-header {
  margin-bottom: 8px;
}

.state-level-badge {
  display: inline-block;
  padding: 6px 20px;
  border-radius: 20px;
  font-size: 15px;
  font-weight: 700;
}

.state-level--stable {
  background: #ecfdf5;
  color: #065f46;
}

.state-level--mild {
  background: #fffbeb;
  color: #92400e;
}

.state-level--burdened {
  background: #fef2f2;
  color: #991b1b;
}

.result-section--risk {
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--safety-bg);
}

.result-section--risk strong {
  color: var(--text-main);
}

.result-section--risk p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 14px;
}

.result-card--anime {
  text-align: center;
}

.result-card--anime .result-section {
  text-align: left;
}

.anime-similarity {
  margin: -8px 0 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--teal-dark);
}

.result-card ol {
  margin: 0;
  padding-inline-start: 22px;
  display: grid;
  gap: 4px;
  color: var(--text-muted);
  line-height: 1.6;
}

.tests-taking {
  display: grid;
  gap: 20px;
  padding: 16px 22px;
}

.test-progress {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  color: var(--text-muted);
}

.test-question h2 {
  margin: 0 0 16px;
  font-size: 20px;
  line-height: 1.5;
}

.test-options {
  display: grid;
  gap: 10px;
}

.test-option {
  display: block;
  width: 100%;
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--surface-muted);
  color: var(--text-main);
  font-size: 15px;
  text-align: left;
  line-height: 1.5;
}

.test-option.active {
  background: var(--mint-soft);
  color: var(--teal-dark);
  font-weight: 700;
}

.test-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 8px;
}

.test-nav button {
  min-height: 44px;
  border-radius: 14px;
  background: var(--surface-muted);
  color: var(--text-main);
  font-weight: 700;
  font-size: 15px;
}

.test-nav button:disabled {
  opacity: 0.4;
}

.tests-result {
  padding: 24px 22px 120px;
}

.result-card {
  display: grid;
  gap: 16px;
}

.result-card h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  color: var(--teal-dark);
}

.result-disclaimer {
  margin: 0;
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--safety-bg);
  color: var(--text-muted);
  font-size: 13px;
}

.result-summary {
  margin: 0;
  color: var(--text-main);
  line-height: 1.7;
}

.result-section {
  display: grid;
  gap: 8px;
}

.result-section strong {
  font-size: 15px;
}

.result-section ul {
  margin: 0;
  padding-inline-start: 18px;
  display: grid;
  gap: 4px;
  color: var(--text-muted);
  line-height: 1.6;
}

.result-section p {
  margin: 0;
  color: var(--text-muted);
  line-height: 1.6;
}

.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(18, 18, 18, 0.45);
}

.confirm-dialog {
  width: min(calc(100% - 48px), 360px);
  display: grid;
  gap: 16px;
  padding: 28px 24px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(38, 57, 52, 0.22);
}

.confirm-dialog h2 {
  margin: 0;
  font-size: 20px;
}

.confirm-dialog p {
  margin: 0;
  color: var(--text-muted);
  line-height: 1.6;
}

.confirm-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 520px) {
  .app-canvas {
    display: block;
  }

  .phone-shell {
    width: 100%;
    height: 100vh;
    min-height: 100vh;
    box-shadow: none;
  }

  .chat-page,
  .knowledge-page {
    height: calc(100dvh - 268px);
  }

  .memory-document-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .memory-document-viewer {
    align-items: end;
  }
}

/* ==================== Sprint 3: Voice/ASR inline ==================== */

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.voice-record-btn {
  min-height: 44px;
  min-width: 56px;
  border-radius: 14px;
  padding: 0 12px;
  font-weight: 700;
  font-size: 14px;
  background: var(--surface-muted);
  color: var(--text-main);
  flex-shrink: 0;
  transition: background 0.2s;
}

.voice-record-btn:hover:not(:disabled) {
  background: var(--mint-soft);
  color: var(--teal-dark);
}

.voice-record-btn--active {
  background: #ef4444;
  color: #fff;
  animation: pulse 1.2s infinite;
}

.voice-record-btn--active:hover {
  background: #dc2626;
  color: #fff;
}

.voice-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding: 8px 14px;
  border-radius: 10px;
  background: var(--surface-muted);
  font-size: 13px;
  color: var(--text-muted);
}

.voice-status-bar__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
}

.voice-status-bar__dot--active {
  background: #22c55e;
  animation: pulse 1.2s infinite;
}

/* ==================== Sprint 3: Share Card ==================== */

.share-card-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: grid;
  place-items: center;
  z-index: 200;
  padding: 24px;
}

.share-card {
  max-width: 380px;
  width: 100%;
  padding: 32px 26px 26px;
  border-radius: 20px;
  color: #fff;
  display: grid;
  gap: 14px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.share-card--mood_check {
  background: linear-gradient(145deg, #0d9488 0%, #0f766e 55%, #115e59 100%);
}

.share-card--sixteen_type {
  background: linear-gradient(145deg, #667eea 0%, #764ba2 100%);
}

.share-card__header {
  display: grid;
  gap: 6px;
}

.share-card__title {
  margin: 0;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: 0.02em;
}

.share-card__subtitle {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  opacity: 0.75;
  letter-spacing: 0.04em;
}

.share-card__tagline {
  margin: 0;
  font-size: 13px;
  font-style: italic;
  opacity: 0.8;
  border-left: 3px solid rgba(255, 255, 255, 0.45);
  padding-left: 10px;
}

.share-card__type-badge {
  margin: 0;
  display: inline-block;
  font-size: 36px;
  font-weight: 900;
  letter-spacing: 0.08em;
  opacity: 0.3;
  justify-self: end;
  line-height: 1;
}

.share-card__summary {
  margin: 0;
  font-size: 14.5px;
  line-height: 1.7;
  opacity: 0.95;
}

.share-card__highlights {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.share-card__highlights span {
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.share-card__disclaimer {
  margin: 6px 0 0;
  font-size: 11.5px;
  opacity: 0.65;
  line-height: 1.55;
  border-top: 1px solid rgba(255, 255, 255, 0.2);
  padding-top: 14px;
}

.share-card__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.share-card__actions .primary-action {
  flex: 1;
  min-width: 90px;
  padding: 10px 18px;
  border-radius: 14px;
  font-weight: 700;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.95);
  color: #1e293b;
}

.share-card__actions .secondary-action {
  padding: 10px 16px;
  border-radius: 14px;
  font-weight: 600;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}

.share-card__actions .text-action {
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-weight: 600;
}

/* ==================== Sprint 3: Feedback ==================== */

.message-feedback {
  padding: 4px 0 8px;
}

.feedback-btn {
  font-size: 12px;
  color: var(--text-muted);
  background: var(--surface-muted);
  padding: 4px 10px;
  border-radius: 8px;
  font-weight: 600;
}

.feedback-btn:hover {
  background: var(--mint-soft);
  color: var(--teal-dark);
}

.feedback-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: grid;
  place-items: center;
  z-index: 200;
  padding: 24px;
}

.feedback-panel {
  max-width: 340px;
  width: 100%;
  padding: 28px 24px;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 18px 50px rgba(38, 57, 52, 0.22);
  display: grid;
  gap: 18px;
}

.feedback-panel h2 {
  margin: 0;
  font-size: 20px;
  color: var(--text-main);
}

.feedback-stars {
  display: flex;
  justify-content: center;
  gap: 8px;
}

.feedback-stars button {
  font-size: 36px;
  background: none;
  color: #d1d5db;
  transition: color 0.15s;
  padding: 0;
}

.feedback-stars button.active {
  color: var(--amber);
}

.feedback-note {
  min-height: 64px;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 10px 14px;
  font-size: 14px;
  resize: vertical;
  color: var(--text-main);
  font-family: inherit;
}

.feedback-actions {
  display: flex;
  gap: 10px;
}

.feedback-actions .primary-action {
  flex: 1;
}

.feedback-done-msg {
  margin: 0;
  color: var(--text-muted);
  text-align: center;
  line-height: 1.6;
}

/* ==================== Sprint 3: Weekly Summary ==================== */

.weekly-summary-btn {
  display: block;
  width: 100%;
  text-align: center;
  padding: 10px 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--teal);
}

.weekly-summary-btn:disabled {
  opacity: 0.5;
}

.weekly-summary-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: grid;
  place-items: center;
  z-index: 200;
  padding: 24px;
}

.weekly-summary-panel {
  max-width: 360px;
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  padding: 28px 24px;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 18px 50px rgba(38, 57, 52, 0.22);
  display: grid;
  gap: 16px;
}

.weekly-summary-panel h2 {
  margin: 0;
  font-size: 22px;
  color: var(--text-main);
}

.weekly-summary__range {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 600;
}

.weekly-summary__text {
  margin: 0;
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-main);
}

.weekly-summary__tags {
  display: grid;
  gap: 6px;
}

.weekly-summary__tags > span {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
}

.weekly-summary__tags div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.weekly-summary-tag {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--mint-soft);
  color: var(--teal-dark);
  font-weight: 600;
}

.weekly-summary__actions {
  display: grid;
  gap: 6px;
}

.weekly-summary__actions > span {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
}

.weekly-summary__actions ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
}

.weekly-summary__actions li {
  font-size: 14px;
  color: var(--text-main);
  line-height: 1.5;
}

</style>
