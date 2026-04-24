<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { ApiClient } from "./api/client";
import { CounselingApi } from "./api/endpoints";
import type { AgeRange, UserMode } from "./types/api";

type AgeOptionId = "13-15" | "16-17" | "18-24" | "25+";
type MainTab = "home" | "chat" | "profile";
type Screen = "auth" | "ageGate" | "onboarding" | MainTab | "safety";
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
  streaming?: boolean;
}

const ageOptions: Array<SelectOption & { id: AgeOptionId }> = [
  { id: "13-15", label: "13-15 岁", description: "自动启用青少年保护模式" },
  { id: "16-17", label: "16-17 岁", description: "自动启用青少年保护模式" },
  { id: "18-24", label: "18-24 岁", description: "进入标准陪伴模式" },
  { id: "25+", label: "25 岁及以上", description: "进入标准陪伴模式" },
];

const styleOptions: SelectOption[] = [
  { id: "gentle", label: "温柔安抚型", description: "先接住情绪，慢慢放松下来" },
  { id: "rational", label: "理性分析型", description: "把困扰拆开，理清头绪" },
  { id: "reflective", label: "陪你梳理型", description: "边听边整理感受和触发点" },
  { id: "action", label: "轻量行动型", description: "给出一两个可执行的小步骤" },
];

const goalOptions: SelectOption[] = [
  { id: "heard", label: "想先被听见", description: "需要一个安全、不被打断的出口" },
  { id: "anxiety", label: "想缓解焦虑", description: "先把身体和情绪稳定下来" },
  { id: "sleep", label: "想改善作息", description: "最近睡眠或精力状态不太稳" },
  { id: "relationships", label: "想理清关系", description: "关于家人、朋友或亲密关系" },
];

const defaultQuickActions = ["继续听我说", "帮我梳理", "给我一点建议", "先做个呼吸"];
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const storedAccessToken = localStorage.getItem("counseling_access_token") ?? "";
const storedRefreshToken = localStorage.getItem("counseling_refresh_token") ?? "";
const storedUserId = localStorage.getItem("counseling_user_id") ?? "";

const initialMessages: ChatMessage[] = [
  {
    id: 1,
    role: "assistant",
    text: "你好，我在这里。你可以慢慢说，我们先从今天最难受的那一刻开始。",
  },
  {
    id: 2,
    role: "user",
    text: "最近总是睡不好，白天也提不起精神。",
  },
  {
    id: 3,
    role: "assistant",
    text: "听起来你已经撑了一段时间了。我们可以先一起理一理，是入睡困难、容易醒，还是醒来后还是很累？",
  },
];

const currentScreen = ref<Screen>(storedAccessToken ? "home" : "auth");
const activeTab = ref<MainTab>("home");
const lastMainTab = ref<MainTab>("home");
const selectedAge = ref<AgeOptionId | null>(null);
const selectedStyle = ref<string | null>(null);
const selectedGoal = ref<string | null>(null);
const authMode = ref<AuthMode>("login");
const authUsername = ref("");
const authPassword = ref("");
const authSelectedAge = ref<AgeOptionId>("18-24");
const captchaId = ref("");
const captchaImageDataUrl = ref("");
const captchaCode = ref("");
const authError = ref("");
const isAuthenticating = ref(false);
const isCaptchaLoading = ref(false);
const composerText = ref("");
const safetyAction = ref<SafetyAction>(null);
const quickActions = ref([...defaultQuickActions]);
const messages = ref<ChatMessage[]>([...initialMessages]);
const messageSeed = ref(initialMessages.length + 1);
const messageListRef = ref<HTMLElement | null>(null);
const accessToken = ref(storedAccessToken);
const refreshToken = ref(storedRefreshToken);
const currentUserId = ref(storedUserId);
const currentUsername = ref(localStorage.getItem("counseling_username") ?? "");
const activeThreadId = ref(localStorage.getItem("counseling_thread_id") ?? "");
const apiError = ref("");
const isSending = ref(false);

const apiClient = new ApiClient({
  baseUrl: apiBaseUrl,
  getAccessToken: () => accessToken.value || undefined,
  onUnauthorized: refreshAccessToken,
});
const api = new CounselingApi(apiClient);

const isTeenMode = computed(() => selectedAge.value === "13-15" || selectedAge.value === "16-17");
const modeLabel = computed(() => (isTeenMode.value ? "青少年模式" : "标准模式"));
const userName = computed(() => currentUsername.value || "朋友");
const greeting = computed(() => {
  const hour = new Date().getHours();

  if (hour < 12) {
    return "早上好";
  }

  if (hour < 18) {
    return "下午好";
  }

  return "晚上好";
});
const canEnterHome = computed(() => Boolean(selectedStyle.value && selectedGoal.value));
const selectedAgeLabel = computed(
  () => ageOptions.find((option) => option.id === selectedAge.value)?.label ?? "未选择",
);
const selectedStyleLabel = computed(
  () => styleOptions.find((option) => option.id === selectedStyle.value)?.label ?? "未设置",
);
const selectedGoalLabel = computed(
  () => goalOptions.find((option) => option.id === selectedGoal.value)?.label ?? "未设置",
);
const currentPreferenceChips = computed(() =>
  [
    selectedStyle.value ? selectedStyleLabel.value : "",
    selectedGoal.value ? selectedGoalLabel.value : "",
  ].filter(Boolean),
);
const latestUserSummary = computed(() => {
  const latestUserMessage = [...messages.value].reverse().find((message) => message.role === "user");
  return latestUserMessage?.text ?? "上次你提到最近睡眠不太稳定...";
});

async function scrollMessageListToBottom() {
  await nextTick();

  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight;
  }
}

watch(
  () => messages.value.map((message) => `${message.id}:${message.text}`).join("\n"),
  scrollMessageListToBottom,
);

watch(authMode, () => {
  authError.value = "";
  captchaCode.value = "";
  void refreshCaptcha();
});

function persistAuthSession(payload: { user_id: string; access_token: string; refresh_token: string }) {
  accessToken.value = payload.access_token;
  refreshToken.value = payload.refresh_token;
  currentUserId.value = payload.user_id;
  localStorage.setItem("counseling_access_token", payload.access_token);
  localStorage.setItem("counseling_refresh_token", payload.refresh_token);
  localStorage.setItem("counseling_user_id", payload.user_id);
}

function clearAuthSession() {
  accessToken.value = "";
  refreshToken.value = "";
  currentUserId.value = "";
  currentUsername.value = "";
  activeThreadId.value = "";
  localStorage.removeItem("counseling_access_token");
  localStorage.removeItem("counseling_refresh_token");
  localStorage.removeItem("counseling_user_id");
  localStorage.removeItem("counseling_username");
  localStorage.removeItem("counseling_thread_id");
}

function toAgeRange(age: AgeOptionId | null): AgeRange {
  if (age === "13-15") {
    return "13_15";
  }

  if (age === "16-17") {
    return "16_17";
  }

  return "18_plus";
}

function applyAgeRange(ageRange: AgeRange) {
  if (ageRange === "13_15") {
    selectedAge.value = "13-15";
  } else if (ageRange === "16_17") {
    selectedAge.value = "16-17";
  } else {
    selectedAge.value = "18-24";
  }
}

async function refreshCaptcha() {
  try {
    isCaptchaLoading.value = true;
    const captcha = await api.getCaptcha();
    captchaId.value = captcha.captcha_id;
    captchaImageDataUrl.value = captcha.image_data_url;
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "验证码加载失败，请刷新重试。";
  } finally {
    isCaptchaLoading.value = false;
  }
}

function setAuthMode(mode: AuthMode) {
  authMode.value = mode;
}

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshToken.value) {
    clearAuthSession();
    currentScreen.value = "auth";
    void refreshCaptcha();
    return false;
  }

  const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken.value }),
  });

  if (!response.ok) {
    clearAuthSession();
    currentScreen.value = "auth";
    void refreshCaptcha();
    return false;
  }

  persistAuthSession((await response.json()) as { user_id: string; access_token: string; refresh_token: string });
  return true;
}

async function loadAuthenticatedUser(nextScreen: Screen = "home") {
  const user = await api.getCurrentUser();
  currentUserId.value = user.user_id;
  currentUsername.value = user.username;
  localStorage.setItem("counseling_user_id", user.user_id);
  localStorage.setItem("counseling_username", user.username);
  applyAgeRange(user.age_range);

  const threads = await api.listThreads();
  if (!activeThreadId.value && threads.items[0]) {
    activeThreadId.value = threads.items[0].thread_id;
    localStorage.setItem("counseling_thread_id", activeThreadId.value);
  }

  currentScreen.value = nextScreen;
}

onMounted(async () => {
  if (!accessToken.value && refreshToken.value) {
    await refreshAccessToken();
  }

  if (!accessToken.value) {
    currentScreen.value = "auth";
    await refreshCaptcha();
    return;
  }

  try {
    await loadAuthenticatedUser("home");
  } catch {
    clearAuthSession();
    currentScreen.value = "auth";
    await refreshCaptcha();
  }
});

function selectedUserMode(): UserMode {
  return isTeenMode.value ? "teen" : "adult";
}

async function submitAuth() {
  const username = authUsername.value.trim();
  const password = authPassword.value;
  const code = captchaCode.value.trim();

  if (!username || password.length < 6 || !captchaId.value || !code || isAuthenticating.value) {
    return;
  }

  try {
    authError.value = "";
    isAuthenticating.value = true;

    if (authMode.value === "register") {
      const registered = await api.register({
        username,
        password,
        age_range: toAgeRange(authSelectedAge.value),
        captcha_id: captchaId.value,
        captcha_code: code,
      });
      persistAuthSession(registered);
      currentUsername.value = username;
      localStorage.setItem("counseling_username", username);
      selectedAge.value = authSelectedAge.value;
      currentScreen.value = "onboarding";
      return;
    }

    const loggedIn = await api.login({
      username,
      password,
      captcha_id: captchaId.value,
      captcha_code: code,
    });
    persistAuthSession(loggedIn);
    await loadAuthenticatedUser("home");
  } catch (error) {
    authError.value = error instanceof Error ? error.message : "认证失败，请检查用户名、密码和验证码。";
    captchaCode.value = "";
    await refreshCaptcha();
  } finally {
    isAuthenticating.value = false;
  }
}

async function ensureBackendSession() {
  if (!accessToken.value || !currentUserId.value) {
    currentScreen.value = "auth";
    throw new Error("请先登录或注册后再开始对话。");
  }

  if (!activeThreadId.value) {
    const thread = await api.startThread({
      mode: "companion",
      title: "我想倾诉",
    });
    activeThreadId.value = thread.thread_id;
    localStorage.setItem("counseling_thread_id", thread.thread_id);
  }
}

function goToTab(tab: MainTab) {
  activeTab.value = tab;
  lastMainTab.value = tab;
  currentScreen.value = tab;
}

function goToOnboarding() {
  if (!selectedAge.value) {
    return;
  }

  currentScreen.value = "onboarding";
}

async function finishOnboarding(skip = false) {
  if (!skip && !canEnterHome.value) {
    return;
  }

  try {
    apiError.value = "";
    await ensureBackendSession();
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "API connection failed";
  }

  goToTab("home");
}

function openSafety() {
  safetyAction.value = null;
  lastMainTab.value = activeTab.value;
  currentScreen.value = "safety";
}

function closeSafety() {
  safetyAction.value = null;
  currentScreen.value = lastMainTab.value;
}

async function resetExperience() {
  const tokenToRevoke = refreshToken.value;
  if (tokenToRevoke) {
    try {
      await api.logout({ refresh_token: tokenToRevoke });
    } catch {
      // Local session cleanup still wins if the server session is already expired.
    }
  }

  selectedAge.value = null;
  selectedStyle.value = null;
  selectedGoal.value = null;
  composerText.value = "";
  safetyAction.value = null;
  currentScreen.value = "auth";
  activeTab.value = "home";
  lastMainTab.value = "home";
  messages.value = [...initialMessages];
  messageSeed.value = initialMessages.length + 1;
  quickActions.value = [...defaultQuickActions];
  apiError.value = "";
  authUsername.value = "";
  authPassword.value = "";
  captchaCode.value = "";
  clearAuthSession();
  await refreshCaptcha();
}

function addMessage(role: ChatRole, text: string, streaming = false) {
  const id = messageSeed.value;
  messages.value = [...messages.value, { id, role, text, streaming }];
  messageSeed.value += 1;
  return id;
}

function updateMessage(id: number, patch: Partial<Pick<ChatMessage, "text" | "streaming">>) {
  messages.value = messages.value.map((message) => (message.id === id ? { ...message, ...patch } : message));
}

function appendMessageText(id: number, text: string) {
  if (!text) {
    return;
  }

  messages.value = messages.value.map((message) =>
    message.id === id ? { ...message, text: `${message.text}${text}` } : message,
  );
}

function buildAssistantReply(message: string): string {
  if (message.includes("睡") || message.includes("失眠")) {
    return "睡不好的时候，很多情绪都会被放大。我们先不急着一次解决全部，只先分开看看：是入睡难、半夜醒，还是醒来后很累？";
  }

  if (message.includes("难受") || message.includes("倾诉")) {
    return "我在听。你不用一下子说得很完整，只要把现在最压着你的那一小块感受说出来就可以。";
  }

  if (message.includes("梳理")) {
    return "可以，我们先把事情拆成三块：发生了什么、你当时最强烈的感受、以及现在最需要被支持的部分。";
  }

  if (message.includes("建议") || message.includes("怎么办")) {
    return "我可以陪你一起想下一步。不过在建议之前，我想先帮你找稳一点的落点：现在最需要的是情绪缓下来，还是事情先变清楚？";
  }

  if (message.includes("呼吸")) {
    return "现在先把注意力放回身体。吸气四拍，停一拍，呼气六拍，我们先做三轮，不用追求做得标准。";
  }

  return "谢谢你愿意继续说。我先把这句话接住，再和你一起看接下来更需要的是安抚、梳理，还是现实支持。";
}

function normalizeSuggestedActions(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const seen = new Set<string>();
  const actions: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") {
      continue;
    }

    const action = item.trim().replace(/\s+/g, " ").slice(0, 18);
    if (!action || seen.has(action)) {
      continue;
    }

    seen.add(action);
    actions.push(action);
    if (actions.length >= 4) {
      break;
    }
  }

  return actions;
}

function inferQuickActions(message: string, riskLevel: RiskLevel | null): string[] {
  if (riskLevel === "L2" || riskLevel === "L3") {
    return ["打开 SOS", "联系可信的人", "陪我撑过10分钟", "先远离危险物"];
  }

  if (message.includes("睡") || message.includes("失眠") || message.includes("醒")) {
    return ["帮我找睡不着原因", "做睡前放松", "明天怎么恢复精力", "继续聊睡眠"];
  }

  if (message.includes("焦虑") || message.includes("慌") || message.includes("呼吸") || message.includes("紧张")) {
    return ["带我稳定60秒", "帮我找触发点", "给我一个小步骤", "继续陪我待一会"];
  }

  if (message.includes("关系") || message.includes("朋友") || message.includes("家人") || message.includes("同学")) {
    return ["帮我理清关系", "先听我说完", "给我一句怎么开口", "看看我在意什么"];
  }

  if (message.includes("建议") || message.includes("怎么办") || message.includes("选择")) {
    return ["给我一个小步骤", "帮我拆成选项", "先判断最急的事", "继续分析利弊"];
  }

  if (message.includes("难受") || message.includes("卡住") || message.includes("压力")) {
    return ["继续说最卡的点", "帮我梳理压力源", "先稳定一下", "给我一点支持"];
  }

  return [...defaultQuickActions];
}

function updateQuickActions(value: unknown, message: string, riskLevel: RiskLevel | null) {
  const suggestedActions = normalizeSuggestedActions(value);
  quickActions.value = suggestedActions.length > 0 ? suggestedActions : inferQuickActions(message, riskLevel);
}

function readRiskLevel(value: unknown): RiskLevel | null {
  if (value === "L0" || value === "L1" || value === "L2" || value === "L3") {
    return value;
  }

  return null;
}

async function submitMessage(text = composerText.value) {
  const nextMessage = text.trim();

  if (!nextMessage || isSending.value) {
    return;
  }

  composerText.value = "";

  if (currentScreen.value !== "chat") {
    goToTab("chat");
  }

  addMessage("user", nextMessage);
  quickActions.value = inferQuickActions(nextMessage, null);
  let assistantMessageId: number | null = null;
  let streamedText = "";
  let finalRiskLevel: RiskLevel | null = null;

  try {
    apiError.value = "";
    isSending.value = true;
    await ensureBackendSession();
    assistantMessageId = addMessage("assistant", "", true);
    const streamingMessageId = assistantMessageId;
    await api.streamMessage(
      activeThreadId.value,
      {
        user_id: currentUserId.value,
        content: nextMessage,
        input_type: "text",
        user_mode: selectedUserMode(),
      },
      (event, data) => {
        if (event === "token") {
          const chunk = typeof data.text === "string" ? data.text : "";
          streamedText += chunk;
          appendMessageText(streamingMessageId, chunk);
          return;
        }

        if (event === "final") {
          finalRiskLevel = readRiskLevel(data.risk_level);
          updateQuickActions(data.suggested_actions, nextMessage, finalRiskLevel);
          const finalText = typeof data.assistant_text === "string" ? data.assistant_text : "";
          if (!streamedText && finalText) {
            streamedText = finalText;
            updateMessage(streamingMessageId, { text: finalText });
          }
        }
      },
    );

    if (!streamedText) {
      updateMessage(streamingMessageId, { text: buildAssistantReply(nextMessage) });
    }

    if (finalRiskLevel === "L2" || finalRiskLevel === "L3") {
      openSafety();
    }
  } catch (error) {
    apiError.value = error instanceof Error ? error.message : "API connection failed";
    quickActions.value = inferQuickActions(nextMessage, finalRiskLevel);
    if (assistantMessageId === null) {
      addMessage("assistant", buildAssistantReply(nextMessage));
    } else if (!streamedText) {
      updateMessage(assistantMessageId, { text: buildAssistantReply(nextMessage) });
    }
  } finally {
    if (assistantMessageId !== null) {
      updateMessage(assistantMessageId, { streaming: false });
    }
    isSending.value = false;
  }
}

function startQuickCheckIn() {
  const starter = "我现在有点难受，想倾诉";
  const latestUserMessage = [...messages.value].reverse().find((message) => message.role === "user")?.text;

  goToTab("chat");

  if (latestUserMessage !== starter) {
    submitMessage(starter);
  }
}
</script>

<template>
  <main class="app-shell">
    <section class="device-frame">
      <div class="device-inner">
        <div class="status-strip">
          <span>9:41</span>
          <div class="status-icons">
            <span class="status-dot"></span>
            <span class="status-dot status-dot--wide"></span>
            <span class="status-battery"></span>
          </div>
        </div>

        <section v-if="currentScreen === 'auth'" class="screen-panel screen-panel--auth">
          <div class="screen-content screen-content--centered auth-content">
            <div class="intro-block">
              <span class="eyebrow">欢迎回来</span>
              <h1 class="screen-title">先确认是你，再慢慢开始。</h1>
              <p class="screen-description">
                你的对话会保存在自己的账户里。登录后可以继续上次的陪伴，也可以重新开始。
              </p>
            </div>

            <section class="auth-card">
              <div class="auth-tabs">
                <button
                  :class="['auth-tab', { 'auth-tab--active': authMode === 'login' }]"
                  type="button"
                  @click="setAuthMode('login')"
                >
                  登录
                </button>
                <button
                  :class="['auth-tab', { 'auth-tab--active': authMode === 'register' }]"
                  type="button"
                  @click="setAuthMode('register')"
                >
                  注册
                </button>
              </div>

              <form class="auth-form" @submit.prevent="submitAuth">
                <label class="auth-field">
                  <span>用户名</span>
                  <input
                    v-model="authUsername"
                    class="auth-input"
                    type="text"
                    autocomplete="username"
                    placeholder="3-24 位字母、数字或下划线"
                  />
                </label>

                <label class="auth-field">
                  <span>密码</span>
                  <input
                    v-model="authPassword"
                    class="auth-input"
                    type="password"
                    autocomplete="current-password"
                    placeholder="至少 6 位"
                  />
                </label>

                <div class="auth-field">
                  <span>图形验证码</span>
                  <div class="captcha-row">
                    <button class="captcha-image" type="button" :disabled="isCaptchaLoading" @click="refreshCaptcha">
                      <img v-if="captchaImageDataUrl" :src="captchaImageDataUrl" alt="图形验证码" />
                      <span v-else>{{ isCaptchaLoading ? "加载中..." : "点击刷新" }}</span>
                    </button>
                    <input
                      v-model="captchaCode"
                      class="auth-input captcha-input"
                      type="text"
                      inputmode="text"
                      autocomplete="off"
                      placeholder="输入验证码"
                    />
                  </div>
                </div>

                <div v-if="authMode === 'register'" class="auth-field">
                  <span>年龄段</span>
                  <div class="auth-age-grid">
                    <button
                      v-for="option in ageOptions"
                      :key="option.id"
                      :class="['soft-chip soft-chip--button', { 'soft-chip--active': authSelectedAge === option.id }]"
                      type="button"
                      @click="authSelectedAge = option.id"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                </div>

                <p v-if="authError" class="auth-error">{{ authError }}</p>

                <button
                  class="primary-button"
                  type="submit"
                  :disabled="
                    isAuthenticating || !authUsername.trim() || authPassword.length < 6 || !captchaId || !captchaCode.trim()
                  "
                >
                  {{ isAuthenticating ? "请稍等..." : authMode === "login" ? "登录并继续" : "创建账户" }}
                </button>
              </form>
            </section>

            <p class="auth-note">我们只用这些信息来保护你的会话和安全分流，不会把它展示给其他人。</p>
          </div>
        </section>

        <section v-else-if="currentScreen === 'ageGate'" class="screen-panel">
          <div class="screen-content screen-content--centered">
            <div class="intro-block">
              <span class="eyebrow">心理陪伴</span>
              <h1 class="screen-title">欢迎，请问你的年龄段是？</h1>
              <p class="screen-description">
                我们会根据你的年龄自动调整陪伴方式和安全提醒，让体验更合适。
              </p>
            </div>

            <div class="option-stack">
              <button
                v-for="option in ageOptions"
                :key="option.id"
                :class="['pill-option', { 'pill-option--active': selectedAge === option.id }]"
                type="button"
                @click="selectedAge = option.id"
              >
                <span>{{ option.label }}</span>
              </button>
            </div>

            <p class="micro-copy">13-17 岁将自动进入青少年保护模式</p>
          </div>

          <div class="footer-panel footer-panel--single">
            <button class="primary-button" :disabled="!selectedAge" type="button" @click="goToOnboarding">
              下一步
            </button>
          </div>
        </section>

        <section v-else-if="currentScreen === 'onboarding'" class="screen-panel">
          <div class="screen-header">
            <span class="step-pill">Step 2 of 3</span>
            <h1 class="screen-title">你希望我主要怎么陪你？</h1>
            <p class="screen-description">先选一种陪伴风格，再选一个这段时间你更需要的方向。</p>
          </div>

          <div class="screen-content screen-content--scroll">
            <section class="section-block">
              <div class="section-copy">
                <h2 class="section-title">陪伴风格</h2>
                <p class="section-description">不做死板表单，先挑一个你更舒服的交流方式。</p>
              </div>

              <div class="selection-grid selection-grid--two">
                <button
                  v-for="option in styleOptions"
                  :key="option.id"
                  :class="['choice-card', { 'choice-card--active': selectedStyle === option.id }]"
                  type="button"
                  @click="selectedStyle = option.id"
                >
                  <strong>{{ option.label }}</strong>
                  <span>{{ option.description }}</span>
                </button>
              </div>
            </section>

            <section class="section-block">
              <div class="section-copy">
                <h2 class="section-title">使用目的</h2>
                <p class="section-description">告诉我你现在更希望得到哪一类支持。</p>
              </div>

              <div class="selection-grid">
                <button
                  v-for="option in goalOptions"
                  :key="option.id"
                  :class="['choice-card', { 'choice-card--active': selectedGoal === option.id }]"
                  type="button"
                  @click="selectedGoal = option.id"
                >
                  <strong>{{ option.label }}</strong>
                  <span>{{ option.description }}</span>
                </button>
              </div>
            </section>
          </div>

          <div class="footer-panel">
            <button class="primary-button" :disabled="!canEnterHome" type="button" @click="finishOnboarding()">
              继续
            </button>
            <button class="text-button" type="button" @click="finishOnboarding(true)">以后再选</button>
          </div>
        </section>

        <section v-else-if="currentScreen === 'home'" class="screen-panel screen-panel--main">
          <header class="top-bar">
            <div class="title-group">
              <p class="eyebrow eyebrow--compact">今天也在这里陪你</p>
              <h1 class="screen-title screen-title--compact">{{ greeting }}，{{ userName }}</h1>
              <span class="mode-badge">{{ modeLabel }}</span>
            </div>

            <button class="sos-button" type="button" @click="openSafety">SOS</button>
          </header>

          <div class="screen-content screen-content--scroll screen-content--main">
            <button class="hero-card" type="button" @click="startQuickCheckIn">
              <div class="hero-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M12 4.75c.9 2.37 2.77 4.24 5.14 5.14C14.77 10.8 12.9 12.67 12 15.04c-.9-2.37-2.77-4.24-5.14-5.15C9.23 8.99 11.1 7.12 12 4.75Z"
                    fill="currentColor"
                  />
                  <path d="M18.25 4.75 19 6.5l1.75.75L19 8l-.75 1.75L17.5 8l-1.75-.75 1.75-.75.75-1.75Z" fill="currentColor" />
                </svg>
              </div>

              <div class="hero-copy">
                <span class="card-kicker">快捷入口</span>
                <h2>我现在有点难受，想倾诉</h2>
                <p>点一下就开始对话。我会先陪你把情绪放下来，再慢慢整理发生了什么。</p>
              </div>

              <span class="hero-arrow">→</span>
            </button>

            <section class="surface-card">
              <div class="card-header">
                <div>
                  <span class="card-kicker">继续上次对话</span>
                  <h2 class="card-title">上次你提到最近睡眠不太稳定...</h2>
                </div>

                <button class="icon-button" type="button" @click="goToTab('chat')">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M13 6.5 18.5 12 13 17.5M5.5 12h12.5"
                      fill="none"
                      stroke="currentColor"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="1.8"
                    />
                  </svg>
                </button>
              </div>

              <p class="surface-copy">{{ latestUserSummary }}</p>
            </section>

            <section class="surface-card">
              <span class="card-kicker">当前设定</span>
              <div v-if="currentPreferenceChips.length" class="chip-row">
                <span v-for="chip in currentPreferenceChips" :key="chip" class="soft-chip">{{ chip }}</span>
              </div>
              <p v-else class="surface-copy">还没有设置偏好，我会先用温和、少打断的方式陪你。</p>
            </section>
          </div>

          <nav class="bottom-nav">
            <button
              :class="['nav-button', { 'nav-button--active': activeTab === 'home' }]"
              type="button"
              @click="goToTab('home')"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4.75 10.5 12 4.75l7.25 5.75V18a1.75 1.75 0 0 1-1.75 1.75H6.5A1.75 1.75 0 0 1 4.75 18v-7.5Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>首页</span>
            </button>

            <button
              :class="['nav-button', { 'nav-button--active': activeTab === 'chat' }]"
              type="button"
              @click="goToTab('chat')"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M6.5 7.25h11A1.75 1.75 0 0 1 19.25 9v6A1.75 1.75 0 0 1 17.5 16.75h-6l-3.75 3v-3H6.5A1.75 1.75 0 0 1 4.75 15V9A1.75 1.75 0 0 1 6.5 7.25Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>对话</span>
            </button>

            <button
              :class="['nav-button', { 'nav-button--active': activeTab === 'profile' }]"
              type="button"
              @click="goToTab('profile')"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 12.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM6.75 18.25a5.25 5.25 0 0 1 10.5 0"
                  fill="none"
                  stroke="currentColor"
                  stroke-linecap="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>我的</span>
            </button>
          </nav>
        </section>

        <section v-else-if="currentScreen === 'chat'" class="screen-panel screen-panel--main screen-panel--chat">
          <header class="chat-header">
            <button class="icon-button" type="button" @click="goToTab('home')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M14.5 6.5 9 12l5.5 5.5"
                  fill="none"
                  stroke="currentColor"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
            </button>

            <div class="chat-title">
              <h1>宁语</h1>
              <p>你可以慢慢说，我会先听你说完。</p>
            </div>

            <button class="sos-button" type="button" @click="openSafety">SOS</button>
          </header>

          <div ref="messageListRef" class="message-list">
            <article
              v-for="message in messages"
              :key="message.id"
              :class="[
                'message-bubble',
                message.role === 'assistant' ? 'message-bubble--assistant' : 'message-bubble--user',
              ]"
            >
              <span>{{ message.text }}</span>
              <span v-if="message.streaming" class="stream-cursor" aria-hidden="true"></span>
            </article>
          </div>

          <div class="quick-action-row">
            <button
              v-for="action in quickActions"
              :key="action"
              class="quick-pill"
              type="button"
              @click="submitMessage(action)"
            >
              {{ action }}
            </button>
          </div>

          <form class="composer" @submit.prevent="submitMessage()">
            <input v-model="composerText" type="text" placeholder="把此刻最难受的感受写下来..." />
            <button class="composer-send" type="submit" :disabled="!composerText.trim() || isSending">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M5 12 19 5l-3 14-4.5-5-6.5-2Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
            </button>
          </form>

          <nav class="bottom-nav">
            <button class="nav-button" type="button" @click="goToTab('home')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4.75 10.5 12 4.75l7.25 5.75V18a1.75 1.75 0 0 1-1.75 1.75H6.5A1.75 1.75 0 0 1 4.75 18v-7.5Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>首页</span>
            </button>

            <button class="nav-button nav-button--active" type="button" @click="goToTab('chat')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M6.5 7.25h11A1.75 1.75 0 0 1 19.25 9v6A1.75 1.75 0 0 1 17.5 16.75h-6l-3.75 3v-3H6.5A1.75 1.75 0 0 1 4.75 15V9A1.75 1.75 0 0 1 6.5 7.25Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>对话</span>
            </button>

            <button class="nav-button" type="button" @click="goToTab('profile')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 12.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM6.75 18.25a5.25 5.25 0 0 1 10.5 0"
                  fill="none"
                  stroke="currentColor"
                  stroke-linecap="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>我的</span>
            </button>
          </nav>
        </section>

        <section v-else-if="currentScreen === 'profile'" class="screen-panel screen-panel--main">
          <header class="top-bar">
            <div class="title-group">
              <p class="eyebrow eyebrow--compact">个人设置</p>
              <h1 class="screen-title screen-title--compact">我的偏好</h1>
              <span class="mode-badge">{{ modeLabel }}</span>
            </div>

            <button class="sos-button" type="button" @click="openSafety">SOS</button>
          </header>

          <div class="screen-content screen-content--scroll screen-content--main">
            <section class="surface-card">
              <span class="card-kicker">当前资料</span>

              <div class="profile-row">
                <span>年龄段</span>
                <strong>{{ selectedAgeLabel }}</strong>
              </div>

              <div class="profile-row">
                <span>陪伴风格</span>
                <strong>{{ selectedStyleLabel }}</strong>
              </div>

              <div class="profile-row">
                <span>当前目标</span>
                <strong>{{ selectedGoalLabel }}</strong>
              </div>
            </section>

            <section class="surface-card">
              <span class="card-kicker">保护说明</span>
              <p class="surface-copy">
                13-17 岁用户会自动启用更积极的风险提醒和现实求助建议，以保证体验更安全。
              </p>
              <button class="secondary-button" type="button" @click="resetExperience">退出登录</button>
            </section>
          </div>

          <nav class="bottom-nav">
            <button class="nav-button" type="button" @click="goToTab('home')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4.75 10.5 12 4.75l7.25 5.75V18a1.75 1.75 0 0 1-1.75 1.75H6.5A1.75 1.75 0 0 1 4.75 18v-7.5Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>首页</span>
            </button>

            <button class="nav-button" type="button" @click="goToTab('chat')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M6.5 7.25h11A1.75 1.75 0 0 1 19.25 9v6A1.75 1.75 0 0 1 17.5 16.75h-6l-3.75 3v-3H6.5A1.75 1.75 0 0 1 4.75 15V9A1.75 1.75 0 0 1 6.5 7.25Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-linejoin="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>对话</span>
            </button>

            <button class="nav-button nav-button--active" type="button" @click="goToTab('profile')">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 12.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM6.75 18.25a5.25 5.25 0 0 1 10.5 0"
                  fill="none"
                  stroke="currentColor"
                  stroke-linecap="round"
                  stroke-width="1.8"
                />
              </svg>
              <span>我的</span>
            </button>
          </nav>
        </section>

        <section v-else class="screen-panel screen-panel--safety">
          <header class="safety-header">
            <button class="ghost-button" type="button" @click="closeSafety">返回</button>
          </header>

          <div class="screen-content screen-content--centered safety-content">
            <div class="intro-block intro-block--tight">
              <span class="eyebrow eyebrow--warning">安全支持</span>
              <h1 class="screen-title">如果你现在觉得不安全，请不要一个人扛着。</h1>
              <p class="screen-description">
                先优先联系现实中的人。你不需要独自撑住这一刻，我会把选择放在你面前。
              </p>
            </div>

            <div class="action-stack">
              <button class="amber-button" type="button" @click="safetyAction = 'trusted'">
                联系现实中的可信任的大人
              </button>
              <button class="warm-button" type="button" @click="safetyAction = 'resources'">查看本地求助资源</button>
              <button class="outline-button outline-button--amber" type="button" @click="safetyAction = 'breathing'">
                做 60 秒稳定呼吸练习
              </button>
            </div>

            <div v-if="safetyAction" class="safety-card">
              <template v-if="safetyAction === 'trusted'">
                <h2>现在可以直接发出这句话</h2>
                <p>“我现在状态不太好，能不能陪我一下？我想现在就联系你。”</p>
              </template>

              <template v-else-if="safetyAction === 'resources'">
                <h2>优先考虑这些现实支持</h2>
                <p>家人或其他可信任的大人、学校心理老师/辅导员、以及当地急救或心理援助热线。</p>
              </template>

              <template v-else>
                <h2>60 秒呼吸节奏</h2>
                <p>吸气 4 秒，停 1 秒，呼气 6 秒。重复 3 次，先把身体从绷紧里拉回来一点。</p>
              </template>
            </div>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<style>
.app-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.device-frame {
  width: min(100%, 430px);
  min-height: min(880px, calc(100vh - 48px));
  border-radius: 36px;
  background: #dbe4ea;
  padding: 14px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.16);
}

.device-inner {
  min-height: 100%;
  border-radius: 28px;
  overflow: hidden;
  background: var(--app-background);
  display: flex;
  flex-direction: column;
}

.status-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 8px;
  color: var(--text-secondary);
  font-size: 12px;
  letter-spacing: 0.03em;
}

.status-icons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.8);
}

.status-dot--wide {
  width: 14px;
}

.status-battery {
  width: 18px;
  height: 10px;
  border-radius: 4px;
  border: 1.5px solid rgba(100, 116, 139, 0.8);
  position: relative;
}

.status-battery::after {
  content: "";
  position: absolute;
  right: -4px;
  top: 2px;
  width: 2px;
  height: 4px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.8);
}

.screen-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  animation: screen-enter 0.28s ease;
}

.screen-panel--main {
  background: var(--app-background);
}

.screen-panel--chat {
  background: #f8fafc;
}

.screen-panel--safety {
  background: var(--amber-background);
}

.screen-panel--auth {
  background:
    radial-gradient(circle at 16% 12%, rgba(20, 184, 166, 0.14), transparent 34%),
    linear-gradient(180deg, #fffaf2 0%, #f0fdfa 100%);
}

.screen-header,
.top-bar,
.chat-header,
.safety-header {
  padding: 12px 24px 0;
}

.screen-content {
  padding: 24px;
}

.screen-content--centered {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 28px;
}

.screen-content--scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.screen-content--main {
  padding-top: 8px;
}

.intro-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.intro-block--tight {
  gap: 14px;
}

.auth-content {
  justify-content: flex-start;
  padding-top: 42px;
}

.auth-card {
  border: 1px solid rgba(20, 184, 166, 0.14);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.82);
  padding: 18px;
  box-shadow: 0 22px 48px rgba(15, 23, 42, 0.1);
  backdrop-filter: blur(18px);
}

.auth-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 6px;
  border-radius: 999px;
  background: #f8fafc;
}

.auth-tab {
  border-radius: 999px;
  padding: 11px 14px;
  background: transparent;
  color: var(--text-secondary);
  font-weight: 800;
}

.auth-tab--active {
  background: #ffffff;
  color: var(--accent-strong);
  box-shadow: var(--soft-shadow);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 18px;
}

.auth-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 800;
}

.auth-input {
  width: 100%;
  border: 1px solid var(--border-soft);
  border-radius: 20px;
  background: #ffffff;
  padding: 14px 16px;
  color: var(--text-primary);
  box-shadow: var(--soft-shadow);
}

.auth-age-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.captcha-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.captcha-image {
  width: 150px;
  height: 52px;
  overflow: hidden;
  border-radius: 18px;
  border: 1px solid rgba(20, 184, 166, 0.18);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 13px;
  font-weight: 800;
  box-shadow: var(--soft-shadow);
}

.captcha-image img {
  display: block;
  width: 100%;
  height: 100%;
}

.captcha-input {
  text-transform: uppercase;
}

.auth-error {
  margin: 0;
  border-radius: 18px;
  background: #fff7ed;
  padding: 12px 14px;
  color: var(--amber-text-strong);
  font-size: 13px;
  line-height: 1.5;
}

.auth-note {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.7;
  text-align: center;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.eyebrow--compact {
  padding: 0;
  background: transparent;
  color: var(--text-tertiary);
}

.eyebrow--warning {
  background: #fff7ed;
  color: var(--amber-text-strong);
}

.screen-title {
  margin: 0;
  font-size: 30px;
  line-height: 1.2;
  letter-spacing: -0.03em;
}

.screen-title--compact {
  font-size: 28px;
}

.screen-description {
  margin: 0;
  color: var(--text-secondary);
  font-size: 15px;
  line-height: 1.7;
}

.option-stack,
.action-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pill-option {
  width: 100%;
  border: 1px solid var(--border-soft);
  background: var(--surface);
  color: var(--text-primary);
  padding: 18px 20px;
  border-radius: 999px;
  text-align: center;
  font-size: 17px;
  font-weight: 700;
  transition: transform 0.2s ease, border-color 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.pill-option--active {
  border-color: var(--accent-strong);
  background: var(--accent);
  color: #ffffff;
}

.micro-copy {
  margin: 0;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

.footer-panel {
  padding: 16px 24px calc(24px + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: linear-gradient(to top, rgba(250, 249, 246, 0.96), rgba(250, 249, 246, 0));
}

.footer-panel--single {
  gap: 0;
}

.primary-button,
.secondary-button,
.amber-button,
.warm-button,
.outline-button,
.ghost-button,
.text-button,
.sos-button,
.icon-button,
.nav-button,
.quick-pill,
.composer-send,
.hero-card,
.choice-card {
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease, color 0.2s ease,
    border-color 0.2s ease;
}

.primary-button,
.secondary-button,
.amber-button,
.warm-button,
.outline-button,
.ghost-button {
  width: 100%;
  border-radius: 999px;
  padding: 16px 18px;
  font-size: 16px;
  font-weight: 700;
}

.primary-button {
  background: var(--accent);
  color: #ffffff;
  box-shadow: 0 12px 24px rgba(13, 148, 136, 0.2);
}

.primary-button:disabled,
.composer-send:disabled {
  background: #cbd5e1;
  color: #f8fafc;
  box-shadow: none;
}

.text-button {
  width: auto;
  align-self: center;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 600;
}

.step-pill {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  padding: 8px 12px;
  border-radius: 999px;
  background: #ffffff;
  box-shadow: var(--soft-shadow);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.section-block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-block + .section-block {
  margin-top: 28px;
}

.section-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-title {
  margin: 0;
  font-size: 18px;
}

.section-description {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
}

.selection-grid {
  display: grid;
  gap: 12px;
}

.selection-grid--two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.choice-card {
  border: 1px solid var(--border-soft);
  background: var(--surface);
  border-radius: 24px;
  padding: 18px 16px;
  text-align: left;
  box-shadow: var(--soft-shadow);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.choice-card strong {
  font-size: 15px;
}

.choice-card span {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.choice-card--active {
  border-color: #14b8a6;
  background: var(--accent-soft);
  box-shadow: 0 16px 30px rgba(20, 184, 166, 0.14);
}

.top-bar,
.chat-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.title-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mode-badge {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  padding: 8px 12px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 700;
}

.sos-button {
  width: auto;
  border-radius: 999px;
  padding: 10px 14px;
  background: #fff7ed;
  border: 1px solid #fcd9a8;
  color: var(--amber-text-strong);
  font-size: 13px;
  font-weight: 800;
}

.hero-card {
  width: 100%;
  border-radius: 28px;
  border: 1px solid rgba(15, 118, 110, 0.08);
  background: linear-gradient(90deg, #f0fdfa 0%, #ecfdf5 100%);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 18px 38px rgba(15, 118, 110, 0.1);
}

.hero-icon {
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.88);
  color: var(--accent-strong);
}

.hero-icon svg {
  width: 26px;
  height: 26px;
}

.hero-copy {
  flex: 1;
  text-align: left;
}

.hero-copy h2,
.card-title {
  margin: 6px 0 8px;
  font-size: 20px;
  line-height: 1.35;
}

.hero-copy p,
.surface-copy {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.hero-arrow {
  color: var(--accent-strong);
  font-size: 24px;
}

.surface-card {
  background: var(--surface);
  border-radius: 24px;
  padding: 20px;
  box-shadow: var(--card-shadow);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.card-kicker {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.03em;
}

.icon-button {
  width: 40px;
  height: 40px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #f8fafc;
  color: var(--text-primary);
}

.icon-button svg,
.nav-button svg,
.composer-send svg {
  width: 20px;
  height: 20px;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.soft-chip {
  display: inline-flex;
  align-items: center;
  padding: 10px 14px;
  border-radius: 999px;
  background: #f8fafc;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.soft-chip--button {
  border: 1px solid transparent;
}

.soft-chip--active {
  border-color: rgba(13, 148, 136, 0.24);
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.bottom-nav {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 14px 18px calc(16px + env(safe-area-inset-bottom));
  border-top: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(16px);
}

.nav-button {
  border-radius: 20px;
  padding: 10px 8px;
  background: transparent;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
}

.nav-button--active {
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.chat-title {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 4px;
  padding-top: 4px;
}

.chat-title h1 {
  margin: 0;
  font-size: 18px;
}

.chat-title p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message-bubble {
  max-width: 80%;
  padding: 14px 16px;
  border-radius: 24px;
  font-size: 15px;
  line-height: 1.7;
}

.stream-cursor {
  display: inline-block;
  width: 0.45em;
  height: 1.1em;
  margin-left: 3px;
  border-radius: 999px;
  vertical-align: -0.16em;
  background: var(--accent);
  animation: stream-cursor-blink 0.9s ease-in-out infinite;
}

.message-bubble--assistant {
  align-self: flex-start;
  background: #ffffff;
  border: 1px solid #edf2f7;
  color: var(--text-primary);
  border-top-left-radius: 10px;
  box-shadow: var(--soft-shadow);
}

.message-bubble--user {
  align-self: flex-end;
  background: var(--accent);
  color: #ffffff;
  border-top-right-radius: 10px;
}

.message-bubble--user .stream-cursor {
  background: #ffffff;
}

.quick-action-row {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding: 0 20px 14px;
}

.quick-action-row::-webkit-scrollbar,
.message-list::-webkit-scrollbar,
.screen-content--scroll::-webkit-scrollbar {
  display: none;
}

.quick-pill {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 10px 14px;
  background: #ffffff;
  border: 1px solid #dbe7ea;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.composer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px 14px;
}

.composer input {
  flex: 1;
  height: 52px;
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: #ffffff;
  padding: 0 18px;
  color: var(--text-primary);
  font-size: 15px;
  box-shadow: var(--soft-shadow);
}

.composer input::placeholder {
  color: var(--text-tertiary);
}

.composer-send {
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  border-radius: 999px;
  background: var(--accent);
  color: #ffffff;
  display: grid;
  place-items: center;
  box-shadow: 0 12px 24px rgba(13, 148, 136, 0.22);
}

.profile-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  font-size: 14px;
  color: var(--text-secondary);
}

.profile-row strong {
  color: var(--text-primary);
  font-size: 15px;
}

.secondary-button {
  background: #f8fafc;
  color: var(--text-primary);
  border: 1px solid var(--border-soft);
}

.safety-header {
  display: flex;
  justify-content: flex-start;
}

.ghost-button {
  width: auto;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.72);
  color: var(--amber-text-strong);
}

.safety-content {
  gap: 22px;
}

.amber-button {
  background: #f59e0b;
  color: #ffffff;
  box-shadow: 0 14px 28px rgba(245, 158, 11, 0.24);
}

.warm-button {
  background: #ffffff;
  color: var(--amber-text-strong);
  border: 1px solid #fcd9a8;
}

.outline-button {
  background: transparent;
  border: 1px solid var(--border-soft);
  color: var(--text-primary);
}

.outline-button--amber {
  border-color: #f3c77f;
  color: var(--amber-text-strong);
}

.safety-card {
  width: 100%;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.85);
  padding: 20px;
  box-shadow: 0 18px 34px rgba(180, 83, 9, 0.12);
}

.safety-card h2 {
  margin: 0 0 10px;
  font-size: 18px;
}

.safety-card p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 15px;
  line-height: 1.7;
}

.pill-option:hover,
.primary-button:not(:disabled):hover,
.secondary-button:hover,
.amber-button:hover,
.warm-button:hover,
.outline-button:hover,
.ghost-button:hover,
.text-button:hover,
.sos-button:hover,
.icon-button:hover,
.quick-pill:hover,
.composer-send:not(:disabled):hover,
.hero-card:hover,
.choice-card:hover,
.nav-button:hover {
  transform: translateY(-1px);
}

@keyframes screen-enter {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes stream-cursor-blink {
  0%,
  100% {
    opacity: 0.18;
  }

  50% {
    opacity: 1;
  }
}

@media (max-width: 640px) {
  .app-shell {
    padding: 0;
  }

  .device-frame {
    width: 100%;
    min-height: 100vh;
    border-radius: 0;
    padding: 0;
    box-shadow: none;
    background: transparent;
  }

  .device-inner {
    border-radius: 0;
  }
}

@media (max-width: 360px) {
  .screen-title {
    font-size: 28px;
  }

  .selection-grid--two {
    grid-template-columns: 1fr;
  }

  .hero-card {
    flex-direction: column;
    align-items: flex-start;
  }

  .captcha-row {
    grid-template-columns: 1fr;
  }

  .hero-arrow {
    display: none;
  }
}
</style>
