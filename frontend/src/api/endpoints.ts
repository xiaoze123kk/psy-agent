import { ApiClient, type SseEventHandler } from "./client";
import type {
  CurrentUserResponse,
  ListMemoriesResponse,
  LoginRequest,
  LoginResponse,
  MessageListResponse,
  MoodTrendResponse,
  RegisterRequest,
  RegisterResponse,
  SendMessageRequest,
  SendMessageResponse,
  StartThreadRequest,
  StartThreadResponse,
  ThreadListResponse,
} from "../types/api";

export class CounselingApi {
  constructor(private readonly client: ApiClient) {}

  register(payload: RegisterRequest): Promise<RegisterResponse> {
    return this.client.post<RegisterResponse, RegisterRequest>("/api/v1/auth/register", payload);
  }

  login(payload: LoginRequest): Promise<LoginResponse> {
    return this.client.post<LoginResponse, LoginRequest>("/api/v1/auth/login", payload);
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

  getMoodTrend(range: "7d" | "30d"): Promise<MoodTrendResponse> {
    return this.client.get<MoodTrendResponse>(`/api/v1/moods/trends?range=${range}`);
  }
}
