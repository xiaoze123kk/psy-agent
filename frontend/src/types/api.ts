export type UserMode = "teen" | "adult";
export type InputType = "text" | "voice" | "test" | "system";

export interface StartThreadRequest {
  mode?: "companion" | "knowledge" | "test" | "crisis";
  title?: string;
}

export interface StartThreadResponse {
  thread_id: string;
  langgraph_thread_id: string;
  mode: string;
  title: string;
}

export interface SendMessageRequest {
  user_id: string;
  content: string;
  input_type?: InputType;
  user_mode?: UserMode;
}

export interface AssistantMessage {
  assistant_text: string;
  risk_level: "L0" | "L1" | "L2" | "L3";
  intent: string;
  suggested_actions: string[];
  session_summary: string;
  should_write_memory: boolean;
}

export interface SendMessageResponse {
  thread_id: string;
  assistant_message: AssistantMessage;
}

export interface MemoryItem {
  memory_id: string;
  memory_type: string;
  content: string;
}

export interface ListMemoriesResponse {
  items: MemoryItem[];
}

export interface MoodTrendResponse {
  range: string;
  avg_mood_score: number;
  top_tags: string[];
  daily: Array<Record<string, unknown>>;
  summary: string;
}
