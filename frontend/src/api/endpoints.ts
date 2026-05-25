import { ApiClient, type SseEventHandler } from "./client";
import type {
  AskKnowledgeRequest,
  AskKnowledgeResponse,
  CaptchaResponse,
  CompleteAttemptResponse,
  ConversationFeedbackRequest,
  CurrentUserResponse,
  FeedbackCreateRequest,
  FeedbackResponse,
  KnowledgeArticleResponse,
  KnowledgeGapListResponse,
  KnowledgeGapMutationResponse,
  KnowledgeQuizBankStatsResponse,
  KnowledgeQuizResultResponse,
  KnowledgeQuizSessionResponse,
  KnowledgeSearchResponse,
  CrisisEventRequest,
  CrisisEventResponse,
  ListMemoriesResponse,
  LoginRequest,
  LoginResponse,
  LogoutRequest,
  MemoryMutationResponse,
  MessageListResponse,
  MoodLogRequest,
  MoodLogResponse,
  MoodTrendResponse,
  AccountDeleteRequest,
  DataDeleteRequest,
  PersonalDataExport,
  PrivacyMutationResponse,
  PrivacySummaryResponse,
  RefreshTokenRequest,
  RefreshTokenResponse,
  RegisterRequest,
  RegisterResponse,
  ResolveKnowledgeGapRequest,
  SendMessageRequest,
  SendMessageResponse,
  StartAttemptResponse,
  StartKnowledgeQuizRequest,
  StartThreadRequest,
  StartThreadResponse,
  SubmitAnswerRequest,
  SubmitKnowledgeQuizRequest,
  TestDetailResponse,
  TestHistoryResponse,
  TestListItem,
  TestListResponse,
  ThreadListResponse,
  UpdateMemoryRequest,
  UserSettingsResponse,
  UserSettingsUpdateRequest,
  WeeklySummaryResponse,
} from "../types/api";

export class CounselingApi {
  constructor(private readonly client: ApiClient) {}

  getCaptcha(): Promise<CaptchaResponse> {
    return this.client.get<CaptchaResponse>("/api/v1/auth/captcha");
  }

  register(payload: RegisterRequest): Promise<RegisterResponse> {
    return this.client.post<RegisterResponse, RegisterRequest>("/api/v1/auth/register", payload);
  }

  login(payload: LoginRequest): Promise<LoginResponse> {
    return this.client.post<LoginResponse, LoginRequest>("/api/v1/auth/login", payload);
  }

  refreshToken(payload: RefreshTokenRequest): Promise<RefreshTokenResponse> {
    return this.client.post<RefreshTokenResponse, RefreshTokenRequest>("/api/v1/auth/refresh", payload);
  }

  logout(payload: LogoutRequest): Promise<void> {
    return this.client.post<void, LogoutRequest>("/api/v1/auth/logout", payload);
  }

  getCurrentUser(): Promise<CurrentUserResponse> {
    return this.client.get<CurrentUserResponse>("/api/v1/auth/me");
  }

  startThread(payload: StartThreadRequest): Promise<StartThreadResponse> {
    return this.client.post<StartThreadResponse, StartThreadRequest>("/api/v1/chat/threads", payload);
  }

  listThreads(): Promise<ThreadListResponse> {
    return this.client.get<ThreadListResponse>("/api/v1/chat/threads");
  }

  listMessages(threadId: string): Promise<MessageListResponse> {
    return this.client.get<MessageListResponse>(`/api/v1/chat/threads/${threadId}/messages`);
  }

  sendMessage(threadId: string, payload: SendMessageRequest): Promise<SendMessageResponse> {
    return this.client.post<SendMessageResponse, SendMessageRequest>(
      `/api/v1/chat/threads/${threadId}/messages`,
      payload,
    );
  }

  streamMessage(threadId: string, payload: SendMessageRequest, onEvent: SseEventHandler): Promise<void> {
    return this.client.streamPost<SendMessageRequest>(`/api/v1/chat/threads/${threadId}/stream`, payload, onEvent);
  }

  createCrisisEvent(payload: CrisisEventRequest): Promise<CrisisEventResponse> {
    return this.client.post<CrisisEventResponse, CrisisEventRequest>("/api/v1/safety/crisis-events", payload);
  }

  listMemories(): Promise<ListMemoriesResponse> {
    return this.client.get<ListMemoriesResponse>("/api/v1/memories");
  }

  getMemoryDocument(download = false): Promise<string> {
    const params = new URLSearchParams();
    if (download) params.set("download", "true");
    const query = params.toString();
    const path = `/api/v1/memories/document${query ? `?${query}` : ""}`;
    return this.client.getText(path);
  }

  updateMemory(memoryId: string, payload: UpdateMemoryRequest): Promise<MemoryMutationResponse> {
    return this.client.patch<MemoryMutationResponse, UpdateMemoryRequest>(`/api/v1/memories/${memoryId}`, payload);
  }

  deleteMemory(memoryId: string): Promise<MemoryMutationResponse> {
    return this.client.delete<MemoryMutationResponse>(`/api/v1/memories/${memoryId}`);
  }

  clearMemories(): Promise<{ status: string }> {
    return this.client.delete<{ status: string }>("/api/v1/memories");
  }

  getPrivacySummary(): Promise<PrivacySummaryResponse> {
    return this.client.get<PrivacySummaryResponse>("/api/v1/me/privacy-summary");
  }

  exportPersonalData(): Promise<PersonalDataExport> {
    return this.client.get<PersonalDataExport>("/api/v1/me/data-export?format=json");
  }

  deletePersonalData(payload: DataDeleteRequest): Promise<PrivacyMutationResponse> {
    return this.client.delete<PrivacyMutationResponse, DataDeleteRequest>("/api/v1/me/data", payload);
  }

  deleteAccount(payload: AccountDeleteRequest): Promise<PrivacyMutationResponse> {
    return this.client.delete<PrivacyMutationResponse, AccountDeleteRequest>("/api/v1/me/account", payload);
  }

  updateSettings(payload: UserSettingsUpdateRequest): Promise<UserSettingsResponse> {
    return this.client.patch<UserSettingsResponse, UserSettingsUpdateRequest>("/api/v1/me/settings", payload);
  }

  searchKnowledge(query: string, options: { category?: string; audience?: string } = {}): Promise<KnowledgeSearchResponse> {
    const params = new URLSearchParams({ q: query });
    if (options.category) params.set("category", options.category);
    if (options.audience) params.set("audience", options.audience);
    return this.client.get<KnowledgeSearchResponse>(`/api/v1/knowledge/search?${params.toString()}`);
  }

  getKnowledgeArticle(articleId: string): Promise<KnowledgeArticleResponse> {
    return this.client.get<KnowledgeArticleResponse>(`/api/v1/knowledge/articles/${articleId}`);
  }

  askKnowledge(payload: AskKnowledgeRequest): Promise<AskKnowledgeResponse> {
    return this.client.post<AskKnowledgeResponse, AskKnowledgeRequest>("/api/v1/knowledge/ask", payload);
  }

  listKnowledgeGaps(status = "open", limit = 50): Promise<KnowledgeGapListResponse> {
    const params = new URLSearchParams({ status, limit: String(limit) });
    return this.client.get<KnowledgeGapListResponse>(`/api/v1/knowledge/gaps?${params.toString()}`);
  }

  resolveKnowledgeGap(gapId: string, payload: ResolveKnowledgeGapRequest): Promise<KnowledgeGapMutationResponse> {
    return this.client.post<KnowledgeGapMutationResponse, ResolveKnowledgeGapRequest>(
      `/api/v1/knowledge/gaps/${gapId}/resolve`,
      payload,
    );
  }

  getKnowledgeQuizStats(): Promise<KnowledgeQuizBankStatsResponse> {
    return this.client.get<KnowledgeQuizBankStatsResponse>("/api/v1/knowledge/quiz/stats");
  }

  startKnowledgeQuiz(payload: StartKnowledgeQuizRequest): Promise<KnowledgeQuizSessionResponse> {
    return this.client.post<KnowledgeQuizSessionResponse, StartKnowledgeQuizRequest>("/api/v1/knowledge/quiz/start", payload);
  }

  submitKnowledgeQuiz(payload: SubmitKnowledgeQuizRequest): Promise<KnowledgeQuizResultResponse> {
    return this.client.post<KnowledgeQuizResultResponse, SubmitKnowledgeQuizRequest>("/api/v1/knowledge/quiz/submit", payload);
  }

  createMoodLog(payload: MoodLogRequest): Promise<MoodLogResponse> {
    return this.client.post<MoodLogResponse, MoodLogRequest>("/api/v1/moods", payload);
  }

  getMoodTrend(range: "7d" | "30d"): Promise<MoodTrendResponse> {
    return this.client.get<MoodTrendResponse>(`/api/v1/moods/trends?range=${range}`);
  }

  listTests(): Promise<TestListResponse> {
    return this.client.get<TestListResponse>("/api/v1/tests");
  }

  getTest(testId: string): Promise<TestDetailResponse> {
    return this.client.get<TestDetailResponse>(`/api/v1/tests/${testId}`);
  }

  startAttempt(testId: string): Promise<StartAttemptResponse> {
    return this.client.post<StartAttemptResponse, Record<string, never>>(`/api/v1/tests/${testId}/attempts`);
  }

  submitAnswer(attemptId: string, payload: SubmitAnswerRequest): Promise<void> {
    return this.client.post<void, SubmitAnswerRequest>(`/api/v1/tests/attempts/${attemptId}/answers`, payload);
  }

  completeAttempt(attemptId: string): Promise<CompleteAttemptResponse> {
    return this.client.post<CompleteAttemptResponse, Record<string, never>>(`/api/v1/tests/attempts/${attemptId}/complete`);
  }

  getTestHistory(): Promise<TestHistoryResponse> {
    return this.client.get<TestHistoryResponse>("/api/v1/tests/history");
  }

  getAttemptResult(attemptId: string): Promise<CompleteAttemptResponse> {
    return this.client.get<CompleteAttemptResponse>(`/api/v1/tests/attempts/${attemptId}/result`);
  }

  // --- Sprint 3: Feedback ---

  submitFeedback(payload: FeedbackCreateRequest): Promise<FeedbackResponse> {
    return this.client.post<FeedbackResponse, FeedbackCreateRequest>("/api/v1/feedback", payload);
  }

  submitConversationQualityFeedback(payload: ConversationFeedbackRequest): Promise<FeedbackResponse> {
    return this.client.post<FeedbackResponse, ConversationFeedbackRequest>("/api/v1/feedback", payload);
  }

  // --- Sprint 3: Weekly Summary ---

  getWeeklySummary(): Promise<WeeklySummaryResponse> {
    return this.client.get<WeeklySummaryResponse>("/api/v1/moods/weekly-summary");
  }
}
