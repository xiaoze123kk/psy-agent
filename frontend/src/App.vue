<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { ApiClient } from "./api/client";
import { CounselingApi } from "./api/endpoints";
import type {
  AgeRange,
  AskKnowledgeResponse,
  CompleteAttemptResponse,
  KnowledgeArticleResponse,
  KnowledgeSearchItem,
  MemoryItem,
  MessageItem,
  MoodTrendResponse,
  StartAttemptResponse,
  TestDetailResponse,
  TestHistoryItem,
  TestListItem,
  ThreadListItem,
  UserMode,
} from "./types/api";

type Stage = "auth" | "onboarding" | "app";
type Tab = "home" | "chat" | "tests" | "knowledge" | "profile";
type AgeOptionId = "13-15" | "16-17" | "18-24" | "25+";
type AuthMode = "login" | "register";
type ChatRole = "assistant" | "user";
type RiskLevel = "L0" | "L1" | "L2" | "L3";
type SafetyAction = "trusted" | "resources" | "breathing" | null;

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
const selectedHistoryIndex = ref(-1);

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
const activeThread = computed(() => threads.value.find((thread) => thread.thread_id === activeThreadId.value) ?? null);
const latestSummary = computed(() => activeThread.value?.last_summary || "可以从此刻最明显的感受开始。");
const testHeaderTitle = computed(() => {
  if (testView.value !== "result" || !testResult.value) return testView.value === "taking" && currentTest.value ? currentTest.value.title : "测试中心";
  return testResult.value.result_title;
});
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

  // 这里单独给演示模式做了一个分支，后续看看能不能合并

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
    testResult.value = currentTest.value?.test_id === "state-check-v1" ? { ...demoStateResult } : { ...demoTypeResult };
    testView.value = "result";
    return;
  }
  try {
    isTestLoading.value = true;
    testResult.value = await api.completeAttempt(currentAttemptId.value);
    testView.value = "result";
  } catch {
    testResult.value = currentTest.value?.test_id === "state-check-v1" ? { ...demoStateResult } : { ...demoTypeResult };
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
  selectedHistoryIndex.value = -1;
  loadTestHistory();
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

        <section v-else-if="activeTab === 'tests'" class="tab-page tests-page">
          <div v-if="testView === 'list' || testView === 'history'" class="test-category-tabs">
            <button :class="{ active: selectedTestCategory === 'state' && testView === 'list' }" type="button" @click="selectedTestCategory = 'state'; testView = 'list'">今日状态</button>
            <button :class="{ active: selectedTestCategory === 'personality' && testView === 'list' }" type="button" @click="selectedTestCategory = 'personality'; testView = 'list'">人格测试</button>
            <button :class="{ active: selectedTestCategory === 'anime' && testView === 'list' }" type="button" @click="selectedTestCategory = 'anime'; testView = 'list'">动漫人物匹配</button>
            <button :class="{ active: testView === 'history' }" type="button" @click="openTestHistory">历史</button>
          </div>
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

          <div v-else-if="testView === 'result' && testResult" class="tests-result">
            <article class="result-card">
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

              <section v-if="testResult.suggested_actions.length" class="result-section">
                <strong>建议行动</strong>
                <ul>
                  <li v-for="action in testResult.suggested_actions" :key="action">{{ action }}</li>
                </ul>
              </section>

              <section v-if="testResult.profile.companion_style" class="result-section">
                <strong>适合你的陪伴方式</strong>
                <p>{{ testResult.profile.companion_style }}</p>
              </section>
            </article>

            <footer class="sticky-actions">
              <button class="primary-action" type="button" @click="continueTestChat">继续聊聊这个结果</button>
              <button class="secondary-action" type="button" @click="backToTestList">返回测试列表</button>
            </footer>
          </div>

          <div v-else-if="testView === 'history'" class="tests-history">
            <p v-if="isHistoryLoading" class="empty-copy">加载中...</p>
            <div v-else-if="testHistory.length === 0" class="test-card-list">
              <p class="empty-copy">暂无测试记录</p>
              <button class="primary-action" type="button" @click="backToTestList">去做测试</button>
            </div>
            <div v-else class="test-card-list">
              <article
                v-for="(item, index) in testHistory"
                :key="item.attempt_id"
                class="test-card"
              >
                <h2>{{ item.test_title }}</h2>
                <p class="test-card__duration">完成于 {{ formatTestTime(item.completed_at) }}</p>
                <p class="test-card__result">{{ item.result_label }}</p>
                <button
                  class="secondary-action"
                  type="button"
                  @click="selectedHistoryIndex = selectedHistoryIndex === index ? -1 : index"
                >{{ selectedHistoryIndex === index ? '收起' : '查看结果' }}</button>
                <div v-if="selectedHistoryIndex === index" class="history-result-detail">
                  <p class="result-code">{{ item.result_code }}</p>
                </div>
              </article>
            </div>
          </div>
        </section>

        <section v-else-if="activeTab === 'knowledge'" class="tab-page knowledge-page">
          <section class="knowledge-agent">
            <div class="knowledge-agent__avatar">知</div>
            <div>
              <span>知识问答</span>
              <h2>今天想弄清楚什么？</h2>
            </div>
          </section>

          <div ref="knowledgeListRef" class="knowledge-chat" aria-label="知识问答消息">
            <article
              v-for="message in knowledgeMessages"
              :key="message.id"
              :class="['knowledge-message', message.role === 'user' ? 'knowledge-message--user' : 'knowledge-message--assistant']"
            >
              <p>{{ message.text }}</p>
              <template v-if="message.answer">
                <p class="knowledge-explanation">{{ message.answer.explanation_3min }}</p>
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
                <section v-if="message.relatedArticles?.length" class="knowledge-sources" aria-label="回答来源">
                  <span>来源</span>
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

          <div class="knowledge-prompts">
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
          <button :class="{ active: activeTab === 'tests' }" type="button" @click="activeTab = 'tests'">测试</button>
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
  grid-template-rows: auto 1fr auto auto auto;
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
}
</style>
