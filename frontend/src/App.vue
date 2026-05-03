<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { ApiClient } from "./api/client";
import { CounselingApi } from "./api/endpoints";
import type {
  AgeRange,
  AskKnowledgeResponse,
  KnowledgeArticleResponse,
  KnowledgeQuizBankStatsResponse,
  KnowledgeQuizMode,
  KnowledgeQuizQuestion,
  KnowledgeQuizResultResponse,
  KnowledgeQuizSessionResponse,
  KnowledgeSearchItem,
  MemoryItem,
  MessageItem,
  MoodTrendResponse,
  ThreadListItem,
  UserMode,
} from "./types/api";

type Stage = "auth" | "onboarding" | "app";
type Tab = "home" | "chat" | "knowledge" | "profile";
type AgeOptionId = "13-15" | "16-17" | "18-24" | "25+";
type AuthMode = "login" | "register";
type ChatRole = "assistant" | "user";
type RiskLevel = "L0" | "L1" | "L2" | "L3";
type SafetyAction = "trusted" | "resources" | "breathing" | null;
type KnowledgePanel = "qa" | "quiz";

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
  streaming?: boolean;
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

const ACCESS_TOKEN_KEY = "counseling_access_token";
const REFRESH_TOKEN_KEY = "counseling_refresh_token";
const USER_ID_KEY = "counseling_user_id";
const USERNAME_KEY = "counseling_username";
const THREAD_ID_KEY = "counseling_thread_id";
const STYLE_KEY = "counseling_style";
const GOAL_KEY = "counseling_goal";

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

const defaultQuickActions = ["继续听我说", "帮我梳理", "给我一点建议", "先做个呼吸"];
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
  { memory_id: "m2", memory_type: "support", content: "高压场景前适合先做 60 秒呼吸。" },
];

const demoMoodTrend: MoodTrendResponse = {
  range: "7d",
  avg_mood_score: 3,
  top_tags: ["睡眠", "焦虑", "关系"],
  daily: [],
  summary: "最近压力主要集中在睡眠和会前焦虑，适合优先减负。",
};

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
const isSafetyOpen = ref(false);

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

const selectedAge = ref<AgeOptionId | null>(null);
const selectedStyle = ref<string | null>(storageOption(STYLE_KEY, styleOptions));
const selectedGoal = ref<string | null>(storageOption(GOAL_KEY, goalOptions));

const threads = ref<ThreadListItem[]>([]);
const messages = ref<ChatMessage[]>([]);
const memories = ref<MemoryItem[]>([]);
const moodTrend = ref<MoodTrendResponse | null>(null);
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
const quickActions = ref([...defaultQuickActions]);
const composerText = ref("");
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
const messageListRef = ref<HTMLElement | null>(null);
const knowledgeListRef = ref<HTMLElement | null>(null);
const demoMessagesByThread = ref<Record<string, ChatMessage[]>>({});

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
const canSubmitAuth = computed(
  () =>
    Boolean(authUsername.value.trim()) &&
    authPassword.value.length >= 6 &&
    Boolean(captchaId.value) &&
    Boolean(captchaCode.value.trim()),
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
const latestSummary = computed(() => activeThread.value?.last_summary || "可以从此刻最明显的感受开始。");
const moodSummary = computed(() => moodTrend.value?.summary || "还没有足够的状态数据，先从今天开始记录。");
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
    const [user, threadList, memoryList, mood] = await Promise.all([
      api.getCurrentUser(),
      api.listThreads(),
      api.listMemories(),
      api.getMoodTrend("7d"),
    ]);
    username.value = user.nickname || user.username;
    localStorage.setItem(USERNAME_KEY, username.value);
    applyAgeRange(user.age_range);
    threads.value = sortThreads(threadList.items);
    memories.value = memoryList.items;
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
  threads.value = sortThreads(demoThreads.map((thread) => ({ ...thread })));
  demoMessagesByThread.value = Object.fromEntries(Object.entries(demoMessages).map(([key, value]) => [key, [...value]]));
  memories.value = demoMemories.map((item) => ({ ...item }));
  moodTrend.value = { ...demoMoodTrend };
  activeThreadId.value = threads.value[0]?.thread_id ?? "";
  setMessages(demoMessagesByThread.value[activeThreadId.value] ?? []);
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
  quickActions.value = inferContextualActions();
}

async function createThread(title = "新的对话") {
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

function addMessage(role: ChatRole, text: string, riskLevel: RiskLevel | null = null, streaming = false) {
  const id = messageSeed.value;
  messages.value = [...messages.value, { id, role, text, riskLevel, streaming, createdAt: new Date().toISOString() }];
  messageSeed.value += 1;
  return id;
}

function updateMessage(id: number, patch: Partial<Pick<ChatMessage, "text" | "riskLevel" | "streaming">>) {
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

function inferActions(message: string, risk: RiskLevel | null) {
  if (risk === "L2" || risk === "L3") return ["打开 SOS", "联系可信任的人", "陪我撑过 10 分钟", "离开危险环境"];
  if (message.includes("睡")) return ["找睡不着的原因", "睡前放松", "明天怎么恢复", "继续聊睡眠"];
  if (message.includes("焦虑") || message.includes("慌")) return ["稳定 60 秒", "找触发点", "给我小步骤", "陪我待一会"];
  return [...defaultQuickActions];
}

function inferContextualActions(message = "", risk: RiskLevel | null = null) {
  if (risk === "L2" || risk === "L3") {
    return ["打开 SOS", "联系可信任的人", "陪我撑过 10 分钟", "离开危险环境"];
  }

  const joinedContext = `${contextText.value} ${message}`;

  if (joinedContext.includes("开会") || joinedContext.includes("发言") || joinedContext.includes("被点名")) {
    if (message.includes("梳理")) {
      return ["拆成会前步骤", "找最怕的场景", "准备一句开口", "先稳住身体"];
    }

    if (message.includes("建议")) {
      return ["会前 3 分钟怎么做", "准备备用句子", "降低发言压力", "会后怎么恢复"];
    }

    return ["先稳住身体", "找最怕的场景", "准备一句发言", "拆成会前步骤"];
  }

  if (joinedContext.includes("睡") || joinedContext.includes("失眠") || joinedContext.includes("睡不着")) {
    if (message.includes("梳理")) {
      return ["找睡前触发点", "分清担心和事实", "写下明天待办", "做睡前收尾"];
    }

    return ["找睡不着的原因", "睡前放松", "明天怎么恢复", "继续聊睡眠"];
  }

  if (joinedContext.includes("关系") || joinedContext.includes("家人") || joinedContext.includes("朋友")) {
    return ["理清对方的话", "说出我的感受", "准备一句边界", "看我真正想要什么"];
  }

  if (joinedContext.includes("焦虑") || joinedContext.includes("慌") || joinedContext.includes("紧张")) {
    return ["稳定 60 秒", "找触发点", "给我小步骤", "陪我待一会"];
  }

  return inferActions(message, risk);
}

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

async function submitMessage(text = composerText.value) {
  const content = text.trim();
  if (!content || isSending.value) return;
  composerText.value = "";
  activeTab.value = "chat";
  if (!activeThreadId.value) await createThread(content.slice(0, 12) || "新的对话");
  addMessage("user", content);
  const localRisk = inferRisk(content);
  quickActions.value = inferContextualActions(content, localRisk);

  if (isDemoMode.value || !accessToken.value || activeThreadId.value.startsWith("local-")) {
    const reply = buildReply(content);
    addMessage("assistant", reply, localRisk);
    syncLocalThread(reply, localRisk);
    if (localRisk === "L2" || localRisk === "L3") openSafety();
    return;
  }

  let assistantId: number | null = null;
  let streamed = "";
  let risk: RiskLevel | null = null;
  try {
    isSending.value = true;
    assistantId = addMessage("assistant", "", null, true);
    await api.streamMessage(
      activeThreadId.value,
      { user_id: currentUserId.value, content, input_type: "text", user_mode: selectedUserMode() },
      (event, data) => {
        if (event === "token" && typeof data.text === "string") {
          streamed += data.text;
          appendMessageText(assistantId as number, data.text);
        }
        if (event === "final") {
          risk = data.risk_level === "L1" || data.risk_level === "L2" || data.risk_level === "L3" ? data.risk_level : "L0";
          const actions = Array.isArray(data.suggested_actions) ? data.suggested_actions.filter((item): item is string => typeof item === "string") : [];
          quickActions.value = actions.length ? actions.slice(0, 4) : inferContextualActions(content, risk);
          if (!streamed && typeof data.assistant_text === "string") {
            streamed = data.assistant_text;
            updateMessage(assistantId as number, { text: streamed, riskLevel: risk });
          }
        }
      },
    );
    if (!streamed && assistantId) {
      streamed = buildReply(content);
      updateMessage(assistantId, { text: streamed, riskLevel: risk });
    }
    syncLocalThread(streamed, risk);
    if (risk === "L2" || risk === "L3") openSafety();
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "发送失败，已使用本地回复。";
    const reply = buildReply(content);
    quickActions.value = inferContextualActions(content, localRisk);
    if (assistantId) updateMessage(assistantId, { text: reply, riskLevel: localRisk });
    else addMessage("assistant", reply, localRisk);
    syncLocalThread(reply, localRisk);
    if (localRisk === "L2" || localRisk === "L3") openSafety();
  } finally {
    if (assistantId) updateMessage(assistantId, { streaming: false });
    isSending.value = false;
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
    apiError.value = "";
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
    apiError.value = "";
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
    apiError.value = "";
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
    apiError.value = "";
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
    apiError.value = "";
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
            <h1 v-else-if="activeTab === 'knowledge'">知识问答</h1>
            <h1 v-else>我的</h1>
          </div>
          <button class="sos-button" type="button" @click="openSafety">SOS</button>
        </header>

        <p v-if="apiError" class="notice notice--error">{{ apiError }}</p>

        <section v-if="activeTab === 'home'" class="tab-page">
          <button class="mood-card" type="button" @click="startQuickCheckIn">
            <span>现在开始</span>
            <strong>我有点难受，想倾诉</strong>
            <small>点一下进入对话，我会先听你说。</small>
          </button>

          <section class="summary-card">
            <div class="card-title">
              <h2>最近状态</h2>
              <span>{{ moodTrend?.top_tags?.join(" / ") || "暂无标签" }}</span>
            </div>
            <p>{{ moodSummary }}</p>
          </section>

          <section class="section-block">
            <div class="section-title">
              <h2>继续聊</h2>
              <button type="button" @click="createThread()">新建</button>
            </div>
            <button
              v-for="thread in threads"
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
            <p v-if="threads.length === 0" class="empty-copy">还没有会话，先从一段倾诉开始。</p>
          </section>
        </section>

        <section v-else-if="activeTab === 'chat'" class="tab-page chat-page">
          <div v-if="threads.length > 0" class="thread-tabs">
            <button
              v-for="thread in threads"
              :key="thread.thread_id"
              :class="{ active: activeThreadId === thread.thread_id }"
              type="button"
              @click="selectThread(thread.thread_id)"
            >
              {{ thread.title }}
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
              <span v-if="message.streaming" class="typing-dot"></span>
            </article>
          </div>

          <div class="quick-actions">
            <button v-for="action in quickActions" :key="action" type="button" @click="submitMessage(action)">
              {{ action }}
            </button>
          </div>

          <form class="composer" @submit.prevent="submitMessage()">
            <input v-model="composerText" type="text" placeholder="写下此刻的感受..." />
            <button type="submit" :disabled="!composerText.trim() || isSending">{{ isSending ? "..." : "发送" }}</button>
          </form>
        </section>

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

          <section class="section-block">
            <div class="section-title">
              <h2>记忆摘要</h2>
            </div>
            <article v-for="item in memories" :key="item.memory_id" class="memory-item">{{ item.content }}</article>
            <p v-if="memories.length === 0" class="empty-copy">还没有记忆摘要。</p>
          </section>

          <button class="secondary-action logout-action" type="button" @click="logout">
            {{ isDemoMode ? "退出演示" : "退出登录" }}
          </button>
        </section>

        <nav class="bottom-nav" aria-label="底部导航">
          <button :class="{ active: activeTab === 'home' }" type="button" @click="activeTab = 'home'">首页</button>
          <button :class="{ active: activeTab === 'chat' }" type="button" @click="activeTab = 'chat'">对话</button>
          <button :class="{ active: activeTab === 'knowledge' }" type="button" @click="activeTab = 'knowledge'">知识</button>
          <button :class="{ active: activeTab === 'profile' }" type="button" @click="activeTab = 'profile'">我的</button>
        </nav>
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
.memory-item {
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

.summary-card,
.profile-card,
.thread-card,
.memory-item {
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
  grid-template-rows: auto 1fr auto auto;
}

.thread-tabs,
.quick-actions,
.knowledge-prompts {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.thread-tabs,
.quick-actions,
.knowledge-prompts {
  scrollbar-width: none;
}

.thread-tabs::-webkit-scrollbar,
.quick-actions::-webkit-scrollbar,
.knowledge-prompts::-webkit-scrollbar {
  display: none;
}

.thread-tabs button,
.quick-actions button {
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
}

.message p {
  margin: 0;
  line-height: 1.65;
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
  grid-template-columns: 1fr auto;
  gap: 8px;
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

.logout-action {
  margin-top: 4px;
}

.bottom-nav {
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: 14px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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

@keyframes blink {
  from {
    opacity: 0.35;
  }
  to {
    opacity: 1;
  }
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
}
</style>
