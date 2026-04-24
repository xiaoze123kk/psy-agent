export type UserMode = "teen" | "adult";
export type InputType = "text" | "voice" | "test" | "system";
export type AgeRange = "13_15" | "16_17" | "18_plus";

export interface CaptchaResponse {
  captcha_id: string;
  image_data_url: string;
  expires_in: number;
}

export interface RegisterRequest {
  username: string;
  password: string;
  age_range: AgeRange;
  captcha_id: string;
  captcha_code: string;
}

export interface RegisterResponse {
  user_id: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  access_expires_in: number;
  refresh_expires_in: number;
  user_mode: UserMode;
  onboarding_completed: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
  captcha_id: string;
  captcha_code: string;
}

export interface LoginResponse {
  user_id: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  access_expires_in: number;
  refresh_expires_in: number;
  user_mode: UserMode;
  onboarding_completed: boolean;
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface RefreshTokenResponse {
  user_id: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  access_expires_in: number;
  refresh_expires_in: number;
}

export interface LogoutRequest {
  refresh_token: string;
}

export interface CurrentUserResponse {
  user_id: string;
  username: string;
  email: string | null;
  nickname: string;
  age_range: AgeRange;
  user_mode: UserMode;
  usage_goals: string[];
  onboarding_completed: boolean;
  memory_mode: string;
  companion_style: string;
  voice_enabled: boolean;
}

export interface StartThreadRequest {
  mode?: "companion" | "knowledge" | "test" | "crisis";
  title?: string;
}

export interface StartThreadResponse {
  thread_id: string;
  langgraph_thread_id: string;
  mode: string;
  title: string;
  updated_at: string;
}

export interface ThreadListItem {
  thread_id: string;
  title: string;
  mode: string;
  last_summary: string | null;
  last_risk_level: "L0" | "L1" | "L2" | "L3";
  updated_at: string;
}

export interface ThreadListResponse {
  items: ThreadListItem[];
}

export interface SendMessageRequest {
  user_id?: string;
  content: string;
  input_type?: InputType;
  user_mode?: UserMode;
}

export interface AssistantMessage {
  id: string;
  role: string;
  content: string;
  assistant_text: string;
  risk_level: "L0" | "L1" | "L2" | "L3";
  intent: string;
  suggested_actions: string[];
  session_summary: string;
  should_write_memory: boolean;
  created_at: string;
}

export interface SendMessageResponse {
  thread_id: string;
  message_id: string;
  assistant_message_id: string;
  assistant_message: AssistantMessage;
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  input_type: string;
  risk_level: "L0" | "L1" | "L2" | "L3" | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface MessageListResponse {
  items: MessageItem[];
}

export interface MemoryItem {
  memory_id: string;
  memory_type: string;
  content: string;
  created_at?: string;
  updated_at?: string;
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
