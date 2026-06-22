export interface GameCandidate {
  appid: number;
  name: string;
  type?: string | null;
  confidence: number;
  source: string;
  source_url: string;
}

export interface GameRead {
  id: number;
  appid: number;
  name: string;
  type?: string | null;
  header_image?: string | null;
  last_resolved_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GameAliasCreate {
  appid: number;
  canonical_name: string;
  alias: string;
  locale?: string;
  alias_type?: string;
  source?: string;
  confidence?: number;
  notes?: string | null;
}

export interface GameAliasRead {
  id: number;
  appid: number;
  canonical_name: string;
  alias: string;
  normalized_alias: string;
  locale: string;
  alias_type: string;
  source: string;
  confidence: number;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocumentCreate {
  title: string;
  content: string;
  source_type?: string;
  source_uri?: string | null;
  appid?: number | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
  chunk_size_tokens?: number;
  chunk_overlap_tokens?: number;
}

export interface KnowledgeDocumentRead {
  id: number;
  title: string;
  source_type: string;
  source_uri?: string | null;
  appid?: number | null;
  tags: string[];
  metadata: Record<string, unknown>;
  content_hash: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeChunkHit {
  chunk_id: number;
  document_id: number;
  title: string;
  source_type: string;
  source_uri?: string | null;
  appid?: number | null;
  ordinal: number;
  heading?: string | null;
  content: string;
  score: number;
  keyword_score: number;
  vector_score: number;
  rerank_score: number;
}

export interface KnowledgeSearchResponse {
  query: string;
  hits: KnowledgeChunkHit[];
  debug: Record<string, unknown>;
}

export interface KnowledgeIndexStats {
  documents: number;
  chunks: number;
  fts_enabled: boolean;
  sqlite_vec_enabled: boolean;
  embedding_dim: number;
  embedding_provider: string;
  semantic_capability: boolean;
  chunking_policy: string;
}

export interface WebSourceRead {
  id: number;
  game_key: string;
  appid?: number | null;
  source_type: string;
  source_url: string;
  title?: string | null;
  author?: string | null;
  published_at?: string | null;
  fetched_at: string;
  excerpt: string;
  content_hash: string;
  metadata: Record<string, unknown>;
}

export interface SourceClaimRead {
  id: number;
  source_id: number;
  event_id?: number | null;
  claim_type: string;
  claim_text: string;
  stance: string;
  confidence: number;
  created_at: string;
}

export interface SentimentEventRead {
  id: number;
  game_key: string;
  appid?: number | null;
  event_date?: string | null;
  event_type: string;
  summary: string;
  sentiment: string;
  severity: string;
  evidence_count: number;
  confidence: number;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface WebSentimentReport {
  game_key: string;
  appid?: number | null;
  query: string;
  event_date?: string | null;
  summary: string;
  sentiment: string;
  severity: string;
  confidence: number;
  sources: WebSourceRead[];
  claims: SourceClaimRead[];
  event?: SentimentEventRead | null;
  search_queries: string[];
  source_backend: string;
  uncertainties: string[];
  recommended_next_steps: string[];
}

export interface PriceInfo {
  is_free?: boolean | null;
  currency?: string | null;
  initial_price?: number | null;
  final_price?: number | null;
  discount_percent?: number | null;
  formatted_initial_price?: string | null;
  formatted_final_price?: string | null;
  cc: string;
  language: string;
}

export interface NewsItem {
  title: string;
  url?: string | null;
  published_at?: string | null;
  summary?: string | null;
}

export interface GameDetail {
  appid: number;
  name: string;
  type?: string | null;
  header_image?: string | null;
  is_free?: boolean | null;
  release_date?: string | null;
  developers: string[];
  publishers: string[];
  genres: string[];
  categories: string[];
  recommendations_total?: number | null;
  price?: PriceInfo | null;
  source_url: string;
  collected_at: string;
}

export interface SnapshotRead {
  id: number;
  game_id: number;
  appid: number;
  collected_at: string;
  source: string;
  cc: string;
  language: string;
  player_count?: number | null;
  is_free?: boolean | null;
  currency?: string | null;
  initial_price?: number | null;
  final_price?: number | null;
  discount_percent?: number | null;
  recommendations_total?: number | null;
  labels: string[];
  source_urls: Record<string, string>;
  news: NewsItem[];
}

export interface SnapshotCreateRequest {
  cc?: string | null;
  language?: string | null;
  labels?: string[];
}

export interface SnapshotLabelCreate {
  label: string;
}

export interface ComparisonMetric {
  field: string;
  left: string | number | boolean | null;
  right: string | number | boolean | null;
  delta?: number | null;
  comparable: boolean;
  note?: string | null;
}

export interface ComparisonResult {
  left_snapshot_id: number;
  right_snapshot_id: number;
  left_appid: number;
  right_appid: number;
  left_collected_at: string;
  right_collected_at: string;
  comparable_region: boolean;
  comparable_currency: boolean;
  summary: string;
  metrics: ComparisonMetric[];
  uncertainties: string[];
}

export type RiskLevel = "L0" | "L1" | "L2" | "L3" | "L4";

export interface AgentGameRef {
  appid: number;
  name?: string | null;
}

export interface AgentEvidence {
  source: string;
  url?: string | null;
  collected_at: string;
  summary: string;
}

export type AgentStepKind = "thinking" | "plan" | "route" | "tool_call" | "observation" | "result" | "synthesize" | "validate";
export type AgentStepStatus = "pending" | "running" | "success" | "failed" | "retry" | "skipped" | "blocked" | "warning";

export interface AgentToolStep {
  kind: AgentStepKind;
  summary: string;
  tool_name?: string | null;
  status: AgentStepStatus;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ClarificationOption {
  label: string;
  description: string;
  action_query: string;
}

export interface AgentAnalysisResult {
  task_type: string;
  classification_reason?: string | null;
  risk_level: RiskLevel;
  answer: string;
  games: AgentGameRef[];
  evidence: AgentEvidence[];
  agent_steps: AgentToolStep[];
  assumptions: string[];
  uncertainties: string[];
  recommended_next_steps: string[];
  requires_human_confirmation: boolean;
  memory_used: boolean;
  candidates: ClarificationOption[];
}

export interface ChatRequest {
  query: string;
  conversation_id?: number | null;
  auto_collect?: boolean;
  confirmed_write?: boolean;
  user_key?: string | null;
}

export interface ChatResponse {
  conversation_id: number;
  report_id?: number | null;
  result: AgentAnalysisResult;
}

export interface ChatStreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface ReviewItem {
  review_id: string;
  author?: string | null;
  voted_up: boolean;
  review_text: string;
  playtime_forever: number;
  language: string;
  timestamp_created: string;
}

export interface SentimentAnalysisResult {
  appid: number;
  total_reviews: number;
  positive_ratio: number;
  top_praise_keywords: string[];
  top_complaint_keywords: string[];
  summary: string;
  source_url?: string | null;
  analyzed_at: string;
  reviews: ReviewItem[];
}

export interface TrendPriceChange {
  snapshot_id: number;
  collected_at: string;
  previous_price: number;
  current_price: number;
  currency?: string | null;
}

export interface TrendAnalysis {
  appid: number;
  days: number;
  snapshot_count: number;
  player_count_trend: string;
  player_count_peak?: number | null;
  player_count_avg?: number | null;
  price_changes: TrendPriceChange[];
  summary: string;
  recommendation?: string | null;
  snapshots: SnapshotRead[];
}

export interface MonitorTask {
  id: number;
  appid: number;
  interval_minutes: number;
  enabled: boolean;
  last_run_at?: string | null;
  created_at: string;
}

export interface MonitorTaskCreate {
  appid: number;
  interval_minutes?: number;
  enabled?: boolean;
}

export interface MonitorAlert {
  id: number;
  appid: number;
  snapshot_id: number;
  alert_type: string;
  summary: string;
  severity: string;
  created_at: string;
}

export interface ReportRead {
  id: number;
  query: string;
  answer_markdown: string;
  created_at: string;
  snapshot_ids: number[];
  model?: string | null;
  prompt_version?: string | null;
  tool_versions?: Record<string, string> | null;
}

export interface AppSettingsRead {
  default_cc: string;
  default_language: string;
  default_currency: string;
  deepseek_model: string;
  allow_model_fallback: boolean;
  collection_interval_minutes: number;
  deepseek_api_key: boolean;
  steam_api_key: boolean;
  firecrawl_api_key: boolean;
}

export interface AppSettingsUpdate {
  default_cc?: string | null;
  default_language?: string | null;
  default_currency?: string | null;
  deepseek_model?: string | null;
  allow_model_fallback?: boolean | null;
  collection_interval_minutes?: number | null;
}

export interface TaskRead {
  id: number;
  task_type: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress_pct: number;
  progress_message?: string | null;
  input_data: Record<string, unknown>;
  result_data: Record<string, unknown>;
  error_message?: string | null;
  error_code?: string | null;
  trace_id?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  cancelled_at?: string | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  version?: string;
  database?: string;
  vector_index?: string;
}

export interface ComponentStatus {
  status: "ok" | "degraded" | "unavailable" | string;
  detail?: string | null;
}

export interface RuntimeStatus {
  service: string;
  version: string;
  environment: string;
  database: ComponentStatus;
  vector_index: ComponentStatus;
  llm: ComponentStatus;
  embedding: ComponentStatus;
  steam_api: ComponentStatus;
  firecrawl: ComponentStatus;
  scheduler: ComponentStatus;
  task_worker: ComponentStatus;
}
