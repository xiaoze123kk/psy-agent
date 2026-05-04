export type UserMode = "teen" | "adult";
export type InputType = "text" | "voice" | "test" | "system";
export type AgeRange = "13_15" | "16_17" | "18_plus";
export type RiskLevel = "L0" | "L1" | "L2" | "L3";
export type MemoryMode = "off" | "summary_only" | "long_term";
export type ChatStreamEventName = "token" | "graph_update" | "final";

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
  memory_mode: MemoryMode;
  companion_style: string;
  voice_enabled: boolean;
  save_voice_audio: boolean;
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
  risk_level: RiskLevel;
  intent: string;
  suggested_actions: string[];
  session_summary: string;
  should_write_memory: boolean;
  referenced_memories: MemoryReference[];
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
  risk_level: RiskLevel | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface MessageListResponse {
  items: MessageItem[];
}

export interface ChatStreamTokenEvent {
  text: string;
}

export interface ChatStreamGraphUpdateEvent {
  node: string;
  risk_level?: RiskLevel;
}

export interface ChatStreamFinalEvent {
  thread_id: string;
  message_id: string;
  assistant_message_id: string;
  assistant_text: string;
  risk_level: RiskLevel;
  intent: string;
  suggested_actions: string[];
  session_summary: string;
  should_write_memory: boolean;
  referenced_memories: MemoryReference[];
  risk_reasons?: string[];
  memory_candidates?: unknown[];
}

export type ChatStreamEventData = ChatStreamTokenEvent | ChatStreamGraphUpdateEvent | ChatStreamFinalEvent;

export interface MemoryItem {
  memory_id: string;
  memory_type: string;
  content: string;
  created_at?: string;
  updated_at?: string;
}

export interface MemoryReference {
  memory_id: string;
  memory_type: string;
  content: string;
}

export interface ListMemoriesResponse {
  items: MemoryItem[];
}

export interface UpdateMemoryRequest {
  content: string;
}

export interface MemoryMutationResponse {
  memory_id?: string;
  content?: string | null;
  status: string;
}

export interface StatusResponse {
  status: string;
}

export interface UserSettingsUpdateRequest {
  memory_mode?: MemoryMode;
  companion_style?: string;
  voice_enabled?: boolean;
  save_voice_audio?: boolean;
}

export interface UserSettingsResponse {
  memory_mode: MemoryMode;
  companion_style: string;
  voice_enabled: boolean;
  save_voice_audio: boolean;
}

export interface MoodLogRequest {
  mood_score: number;
  anxiety_score?: number | null;
  energy_score?: number | null;
  sleep_quality?: number | null;
  mood_tags?: string[];
  note?: string | null;
}

export interface MoodLogResponse {
  log_id: string;
  created_at: string;
  mood_score: number;
}

export interface DailyMoodPoint {
  date: string;
  mood_score: number;
  tags: string[];
}

export interface MoodTrendResponse {
  range: "7d" | "30d";
  avg_mood_score: number;
  top_tags: string[];
  daily: DailyMoodPoint[];
  summary: string;
}

export interface KnowledgeSearchItem {
  article_id: string;
  slug: string;
  title: string;
  category: string;
  audience: string;
  summary_30s: string;
  tags: string[];
}

export interface KnowledgeSearchResponse {
  items: KnowledgeSearchItem[];
}

export interface KnowledgeArticleResponse {
  article_id: string;
  slug: string;
  title: string;
  category: string;
  audience: string;
  summary_30s: string;
  explanation_3min: string;
  advanced_text: string | null;
  common_misunderstandings: string[];
  actions: string[];
  seek_help_when: string[];
  source_refs: Array<Record<string, unknown>>;
  tags: string[];
  updated_at: string;
}

export interface AskKnowledgeRequest {
  question: string;
  use_my_context?: boolean;
  thread_id?: string | null;
}

export interface KnowledgeAnswer {
  summary_30s: string;
  explanation_3min: string;
  actions: string[];
  seek_help_when: string[];
}

export interface KnowledgeSourceRef {
  source_name: string;
  source_url: string | null;
  license: string | null;
  article_id: string;
  article_title: string;
  chunk_id?: string | null;
  chunk_index?: number | null;
  score?: number | null;
}

export interface KnowledgeQuestionSuggestion {
  original_question: string;
  guessed_question: string;
  confidence: "high" | "medium";
  matched_term: string;
}

export interface AskKnowledgeResponse {
  answer: KnowledgeAnswer;
  related_articles: KnowledgeSearchItem[];
  coverage_status: "sufficient" | "partial" | "insufficient" | "not_applicable";
  scope_status: "in_scope" | "out_of_scope";
  confidence: "high" | "medium" | "low";
  source_refs: KnowledgeSourceRef[];
  question_suggestion: KnowledgeQuestionSuggestion | null;
  gap_id: string | null;
  continue_chat_payload: {
    mode: string;
    context_type: string;
    article_id?: string | null;
    thread_id?: string | null;
  };
  risk_level: "L0" | "L1" | "L2" | "L3";
}

export interface TestListItem {
  test_id: string;
  code: string;
  title: string;
  test_type: "state" | "personality" | "anime";
  estimated_minutes: number;
  audience: string;
  status: string;
}

export interface TestListResponse {
  items: TestListItem[];
}

export interface TestOption {
  id: string;
  text: string;
  score: number;
}

export interface TestQuestion {
  index: number;
  text: string;
  options: TestOption[];
}

export interface TestDetailResponse {
  test_id: string;
  code: string;
  title: string;
  questions: TestQuestion[];
}

export interface StartAttemptResponse {
  attempt_id: string;
  test_id: string;
  questions: TestQuestion[];
}

export interface SubmitAnswerRequest {
  question_index: number;
  option_id: string;
}

export interface TestResultProfile {
  sixteen_type_code?: string;
  sixteen_type_label?: string;
  traits: string[];
  strengths: string[];
  blind_spots: string[];
  companion_style: string;
}

export interface ContinueChatContext {
  mode: string;
  context_type: string;
}

export interface CompleteAttemptResponse {
  attempt_id: string;
  test_code: string;
  test_type?: string;
  result_code: string;
  result_title: string;
  summary: string;
  strengths: string[];
  blind_spots: string[];
  suggested_actions: string[];
  continue_chat_context: ContinueChatContext;
  profile: TestResultProfile;
}

export interface TestHistoryItem {
  attempt_id: string;
  test_id: string;
  test_title: string;
  result_code: string;
  result_label: string;
  completed_at: string;
}

export interface TestHistoryResponse {
  items: TestHistoryItem[];
}

export interface KnowledgeGapItem {
  gap_id: string;
  question: string;
  category: string | null;
  audience: string | null;
  coverage_status: string;
  confidence: string;
  top_score: number;
  status: string;
  hit_count: number;
  source_refs: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
}

export interface KnowledgeGapListResponse {
  items: KnowledgeGapItem[];
}

export interface ResolveKnowledgeGapRequest {
  article_id?: string | null;
  reviewer_note?: string | null;
}

export interface KnowledgeGapMutationResponse {
  gap_id: string;
  status: string;
}

export type KnowledgeQuizMode = "10" | "50" | "100";
export type KnowledgeQuizQuestionType = "single_choice" | "true_false" | "image";

export interface KnowledgeQuizOption {
  key: string;
  text: string;
}

export interface KnowledgeQuizVisual {
  kind: string;
  title: string;
  lines: string[];
}

export interface KnowledgeQuizQuestion {
  question_id: string;
  type: KnowledgeQuizQuestionType;
  topic: string;
  difficulty: number;
  stem: string;
  options: KnowledgeQuizOption[];
  visual: KnowledgeQuizVisual | null;
  source_title: string;
  source_url: string;
}

export interface StartKnowledgeQuizRequest {
  mode: KnowledgeQuizMode;
}

export interface KnowledgeQuizSessionResponse {
  session_id: string;
  mode: KnowledgeQuizMode;
  total: number;
  questions: KnowledgeQuizQuestion[];
}

export interface SubmitKnowledgeQuizAnswer {
  question_id: string;
  answer: string;
}

export interface SubmitKnowledgeQuizRequest {
  session_id: string;
  answers: SubmitKnowledgeQuizAnswer[];
}

export interface KnowledgeQuizReviewItem {
  question_id: string;
  question: KnowledgeQuizQuestion;
  is_correct: boolean;
  user_answer: string | null;
  correct_answer: string;
  explanation: string;
  source_title: string;
  source_url: string;
}

export interface KnowledgeQuizResultResponse {
  session_id: string;
  mode: KnowledgeQuizMode;
  total: number;
  correct: number;
  accuracy: number;
  title: string;
  title_description: string;
  review: KnowledgeQuizReviewItem[];
}

export interface KnowledgeQuizBankStatsResponse {
  total: number;
  by_type: Record<string, number>;
  by_topic: Record<string, number>;
}
