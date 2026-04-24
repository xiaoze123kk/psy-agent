import { ApiClient } from "./client";
import type {
  ListMemoriesResponse,
  MoodTrendResponse,
  SendMessageRequest,
  SendMessageResponse,
  StartThreadRequest,
  StartThreadResponse,
} from "../types/api";

export class CounselingApi {
  constructor(private readonly client: ApiClient) {}

  startThread(payload: StartThreadRequest): Promise<StartThreadResponse> {
    return this.client.post<StartThreadResponse, StartThreadRequest>("/api/v1/chat/threads", payload);
  }

  sendMessage(threadId: string, payload: SendMessageRequest): Promise<SendMessageResponse> {
    return this.client.post<SendMessageResponse, SendMessageRequest>(
      `/api/v1/chat/threads/${threadId}/messages`,
      payload,
    );
  }

  listMemories(): Promise<ListMemoriesResponse> {
    return this.client.get<ListMemoriesResponse>("/api/v1/memories");
  }

  getMoodTrend(range: "7d" | "30d"): Promise<MoodTrendResponse> {
    return this.client.get<MoodTrendResponse>(`/api/v1/moods/trends?range=${range}`);
  }
}
