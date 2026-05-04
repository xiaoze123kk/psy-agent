import { ApiClient, type SseEventHandler } from "./client";
import type {
  AskKnowledgeRequest,
  AskKnowledgeResponse,
  CaptchaResponse,
  CompleteAttemptResponse,
  CurrentUserResponse,
  KnowledgeArticleResponse,
  KnowledgeSearchResponse,
  ListMemoriesResponse,
  LoginRequest,
  LoginResponse,
  LogoutRequest,
  MessageListResponse,
  MoodTrendResponse,
  RefreshTokenRequest,
  RefreshTokenResponse,
  RegisterRequest,
  RegisterResponse,
  SendMessageRequest,
  SendMessageResponse,
  StartAttemptResponse,
  StartThreadRequest,
  StartThreadResponse,
  SubmitAnswerRequest,
  TestDetailResponse,
  TestHistoryResponse,
  TestListItem,
  TestListResponse,
  ThreadListResponse,
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

  listMemories(): Promise<ListMemoriesResponse> {
    return this.client.get<ListMemoriesResponse>("/api/v1/memories");
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
}
